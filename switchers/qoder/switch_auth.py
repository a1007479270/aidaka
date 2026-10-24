#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qoder 登录态备份 / 恢复 / 查看 / 取号 一体脚本（aidaka 项目 · Windows 一键版，纯标准库）

一个脚本搞定:
  - 备份当前桌面端登录态（Qoder 的 auth.v1.dat 是 DPAPI 加密的，同机同用户才能还原）
  - 查看/输出当前 QODER 签到信息 (ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON)
  - 用当前登录态立即签到一次（等价于本地跑 platforms/qoder.py）
  - 选择之前的某个备份来恢复

设计要点:
  - 脚本目录跟随自身 (BASE_DIR = 本文件所在目录)，移动到任意目录/电脑都能用。
  - 冷启动友好: 即使 qoder_auth_backup/ 为空或不存在，也能运行；先选 [1] 生成第一个备份。
  - token 只解密到内存，日志一律脱敏；只有 [2]/show 会打印完整凭据行（这是复制去青龙用的）。
  - 设备标识取自 Qoder 自带 runtime-info.exe 的缓存(~/.qoder-cn/umid-cache.json)，
    缺失时自动调用 runtime-info.exe 重新生成；活动接口必须带这套 Cosy-* 设备头才会下发活动。

交互菜单(双击 switch_qoder_auth.bat 即进入):
  [1] 备份当前登录态（仅备份，不还原）
  [2] 输出当前 QODER 信息 (ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON)
  [3] 用当前登录态立即签到一次
  [4] 还原 xxx (昵称)   <- 有备份时才出现
  [0] 取消
  还原时会先自动备份"当前登录态"，防止丢号。

命令行:
  python switch_auth.py            # 交互式菜单
  python switch_auth.py list       # 仅列出所有备份 (无备份时给提示, 不报错)
  python switch_auth.py backup     # 仅备份当前登录态(带时间戳)
  python switch_auth.py show       # 仅输出当前 QODER 信息(复制到青龙环境变量)
  python switch_auth.py signin     # 用当前登录态立即签到(不写青龙)
"""

import ctypes
import ctypes.wintypes as wt
import base64
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import datetime
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "qoder_auth_backup")
BACKUP_PREFIX = "qoder-auth."
# 需要一起备份的文件：登录态 + 机器标识 + DPAPI 密钥所在的 Local State
STATE_FILES = ("auth.v1.dat", "auth.machine-id", "Local State")


def log(msg):
    print(msg, flush=True)


def fail(msg):
    log("[错误] %s" % msg)
    sys.exit(1)


# ---------- 定位客户端数据目录 ----------
def find_app_dir():
    env = os.environ.get("QODER_AUTH_DIR", "").strip()
    roots = [env] if env else []
    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        roots += glob.glob(os.path.join(appdata, "com.qodercn.app.*"))
        roots += glob.glob(os.path.join(appdata, "com.qoder.app.*"))
    for path in roots:
        if os.path.isfile(os.path.join(path, "auth.v1.dat")) and os.path.isfile(os.path.join(path, "Local State")):
            return path
    return ""


def read_client_version():
    """Cosy-Version 要和客户端实际版本一致；优先读安装目录 build-manifest.json。"""
    env = os.environ.get("QODER_VERSION", "").strip()
    if env:
        return env
    seeds = []
    for var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(var)
        if base:
            seeds += glob.glob(os.path.join(base, "Programs", "Qoder*")) + glob.glob(os.path.join(base, "Qoder*"))
    # 客户端也可能装在其他盘（D:\Users\<u>\AppData\Local\Programs\Qoder CN）
    for drive in "CDEFGH":
        seeds += glob.glob(os.path.join(drive + ":\\Users", "*", "AppData", "Local", "Programs", "Qoder*"))
    for install in seeds:
        for pattern in (os.path.join("resources", "build-manifest.json"),
                        os.path.join("resources", "*", "build-manifest.json")):
            for manifest in glob.glob(os.path.join(install, pattern)):
                try:
                    with open(manifest, "r", encoding="utf-8") as f:
                        version = json.load(f).get("productVersion")
                    if version:
                        return str(version)
                except (OSError, json.JSONDecodeError):
                    continue
    for local in (os.environ.get("LOCALAPPDATA") or "",):
        ini = os.path.join(local, "Qoder CN", "Qoder CN Launcher", "state.ini")
        try:
            with open(ini, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip().startswith("targetVersion="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            pass
    return "0.0.0"


# ---------- Windows 凭据解密（DPAPI + CNG AES-GCM，零依赖） ----------
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.c_void_p)]


class _ACMI(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong), ("dwInfoVersion", wt.DWORD),
        ("pbNonce", ctypes.c_void_p), ("cbNonce", wt.DWORD),
        ("pbAuthData", ctypes.c_void_p), ("cbAuthData", wt.DWORD),
        ("pbTag", ctypes.c_void_p), ("cbTag", wt.DWORD),
        ("pbMacContext", ctypes.c_void_p), ("cbMacContext", wt.DWORD),
        ("cbAAD", wt.DWORD), ("cbData", ctypes.c_ulonglong), ("dwFlags", wt.DWORD),
    ]


def _dpapi(data):
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.restype = wt.BOOL
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(data, len(data))
    inp = _BLOB()
    inp.cbData = len(data)
    inp.pbData = ctypes.cast(buf, ctypes.c_void_p)
    out = _BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        fail("DPAPI 解密失败(gle=%d)，请用登录 Qoder 的那个 Windows 用户运行" % ctypes.GetLastError())
    plain = ctypes.string_at(out.pbData, out.cbData)
    kernel32.LocalFree(out.pbData)
    return plain


def _aesgcm(key, nonce, ciphertext, tag_len=16):
    bc = ctypes.windll.bcrypt
    halg = ctypes.c_void_p()
    if bc.BCryptOpenAlgorithmProvider(ctypes.byref(halg), "AES", None, 0) != 0:
        fail("bcrypt 打开 AES 算法失败")
    try:
        mode = ctypes.create_unicode_buffer("ChainingModeGCM")
        if bc.BCryptSetProperty(halg, "ChainingMode", mode, ctypes.sizeof(mode), 0) != 0:
            fail("bcrypt 设置 GCM 模式失败")
        hkey = ctypes.c_void_p()
        if bc.BCryptGenerateSymmetricKey(halg, ctypes.byref(hkey), None, 0, key, len(key), 0) != 0:
            fail("bcrypt 生成密钥失败")
        try:
            info = _ACMI()
            info.cbSize = ctypes.sizeof(info)
            info.dwInfoVersion = 1
            nb = ctypes.create_string_buffer(nonce, len(nonce))
            info.pbNonce = ctypes.cast(nb, ctypes.c_void_p)
            info.cbNonce = len(nonce)
            body, tag = ciphertext[:-tag_len], ciphertext[-tag_len:]
            tb = ctypes.create_string_buffer(tag, len(tag))
            info.pbTag = ctypes.cast(tb, ctypes.c_void_p)
            info.cbTag = len(tag)
            ib = ctypes.create_string_buffer(body, len(body)) if body else None
            out = (ctypes.c_ubyte * (len(body) + 32))()
            got = wt.DWORD(0)
            rc = bc.BCryptDecrypt(hkey, ib, len(body), ctypes.byref(info), None, 0,
                                  out, len(out), ctypes.byref(got), 0)
            if rc != 0:
                fail("auth.v1.dat 解密失败(0x%x)，可能是文件被改动或换了 Windows 用户" % rc)
            return bytes(bytearray(out[:got.value]))
        finally:
            bc.BCryptDestroyKey(hkey)
    finally:
        bc.BCryptCloseAlgorithmProvider(halg, 0)


# ---------- 设备标识 ----------
def read_device(app_dir):
    home = os.environ.get("QODER_HOME") or os.path.join(os.path.expanduser("~"), ".qoder-cn")
    umid = {}
    cache = os.path.join(home, "umid-cache.json")
    if os.path.isfile(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                umid = json.load(f).get("info") or {}
        except (OSError, json.JSONDecodeError):
            umid = {}
    if not umid.get("machineToken"):
        exes = glob.glob(os.path.join(home, ".bin", "umid-*", "runtime-info.exe"))
        if exes:
            try:
                proc = subprocess.run([exes[0]], capture_output=True, timeout=60, text=True)
                start = (proc.stdout or "").find("{")
                if start >= 0:
                    umid = json.loads(proc.stdout[start:])
                    log("已调用 runtime-info.exe 生成设备标识")
            except Exception as e:
                log("[提示] runtime-info.exe 调用失败(%s)，设备标识可能不完整" % type(e).__name__)
    machine_id = ""
    path = os.path.join(app_dir, "auth.machine-id")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            machine_id = f.read().strip()
    return {
        "machineToken": umid.get("machineToken", ""),
        "machineType": umid.get("machineType", ""),
        "machineCode": umid.get("machineCode", ""),
        "machineId": machine_id,
        "machineHostname": socket.gethostname(),
        "machineOS": "Windows",
        "version": read_client_version(),
        "clientType": os.environ.get("QD_CLIENT_TYPE", "10"),
    }


# ---------- 读取当前登录态 ----------
def load_current():
    if os.name != "nt":
        fail("取号只能在装有 Qoder 桌面端的 Windows 上运行")
    app_dir = find_app_dir()
    if not app_dir:
        fail("没找到 auth.v1.dat，请设 QODER_AUTH_DIR 指向客户端数据目录(%%APPDATA%%\\com.qodercn.app.stable)")
    try:
        with open(os.path.join(app_dir, "Local State"), "r", encoding="utf-8") as f:
            enc_key = base64.b64decode(json.load(f)["os_crypt"]["encrypted_key"])[5:]
        key = _dpapi(enc_key)
        with open(os.path.join(app_dir, "auth.v1.dat"), "rb") as f:
            blob = f.read()
        if not blob.startswith(b"v10"):
            fail("auth.v1.dat 前缀不是 v10，客户端加密方案可能已变更")
        auth = json.loads(_aesgcm(key, blob[3:15], blob[15:]).decode("utf-8"))
    except KeyError:
        fail("Local State 里没有 os_crypt.encrypted_key，客户端版本可能已变更")
    user = auth.get("user") or {}
    return {
        "token": auth.get("token", ""),
        "refreshToken": auth.get("refreshToken", ""),
        "uid": user.get("id", ""),
        "remark": user.get("name") or user.get("email") or "qoder",
        "expiresAt": auth.get("expiresAt", ""),
        "refreshTokenExpiresAt": auth.get("refreshTokenExpiresAt", ""),
        "device": read_device(app_dir),
        "base": os.environ.get("QODER_BASE", "https://openapi.qoder.com.cn"),
        "_appDir": app_dir,
    }


def qoder_line(acc):
    """青龙 QODER 环境变量的一行: ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON"""
    device = json.dumps(acc["device"], ensure_ascii=False, separators=(",", ":"))
    return "#".join([acc["token"], acc["refreshToken"], acc["uid"], acc["remark"], device])


def mask(value, keep=4):
    if not value:
        return "<空>"
    return value if len(value) <= keep * 2 else "%s…%s" % (value[:keep], value[-keep:])


# ---------- 备份 / 还原 ----------
def list_backups():
    """返回备份快照目录列表(可能为空)，不在此处报错退出。"""
    return sorted(d for d in glob.glob(os.path.join(BACKUP_DIR, BACKUP_PREFIX + "*"))
                  if os.path.isdir(d) and os.path.isfile(os.path.join(d, "auth.v1.dat")))


def backup_current():
    app_dir = find_app_dir()
    if not app_dir:
        fail("未找到客户端数据目录，无法备份")
    missing = [f for f in STATE_FILES if not os.path.isfile(os.path.join(app_dir, f))]
    if "auth.v1.dat" in missing:
        fail("当前登录文件不存在: %s" % os.path.join(app_dir, "auth.v1.dat"))
    nick = "unknown"
    try:
        nick = load_current()["remark"]
    except SystemExit:
        pass
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(nick))
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = os.path.join(BACKUP_DIR, "%s%s.%s" % (BACKUP_PREFIX, safe, ts))
    os.makedirs(dest_dir, exist_ok=True)
    saved = []
    for name in STATE_FILES:
        src = os.path.join(app_dir, name)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(dest_dir, name))
            saved.append(name)
    with open(os.path.join(dest_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"remark": nick, "appDir": app_dir, "files": saved,
                   "at": datetime.datetime.now().isoformat(timespec="seconds")}, f, ensure_ascii=False, indent=2)
    log("已备份当前登录态 -> %s (%s)" % (os.path.relpath(dest_dir, BASE_DIR), ", ".join(saved)))
    return dest_dir


def restore_backup(dest):
    app_dir = find_app_dir()
    if not app_dir:
        fail("未找到客户端数据目录，无法还原")
    if os.path.isfile(os.path.join(app_dir, "auth.v1.dat")):
        backup_current()
    restored = []
    for name in STATE_FILES:
        src = os.path.join(dest, name)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(app_dir, name))
            restored.append(name)
    if "auth.v1.dat" not in restored:
        fail("备份 %s 中没有 auth.v1.dat" % os.path.basename(dest))
    log("")
    log("=== 已还原: %s -> 桌面端 ===" % os.path.basename(dest))
    acc = load_current()
    log("还原后 uid=%s  昵称=%s  token 过期时间=%s" % (acc["uid"], acc["remark"], acc["expiresAt"]))
    log("设备标识=%s" % (", ".join("%s=%s" % (k, mask(v)) for k, v in acc["device"].items())))
    log("")
    log("=== 该账号的 QODER 签到信息 (复制到青龙环境变量) ===")
    log(qoder_line(acc))
    log("")
    log("⚠️  请重启 Qoder 桌面端确认账号已切换(若提示重新登录属正常)。")
    log("   备份含 DPAPI 加密凭据，只能在同一台机器、同一个 Windows 用户下还原。")


# ---------- 签到 ----------
def run_signin(acc):
    """把当前登录态交给仓库 platforms/qoder.py，复用同一套签到逻辑。"""
    root = os.environ.get("DAILY_CHECKIN_ROOT") or os.path.dirname(os.path.dirname(BASE_DIR))
    script = os.environ.get("QODER_CHECKIN_SCRIPT") or os.path.join(root, "platforms", "qoder.py")
    if not os.path.isfile(script):
        fail("找不到签到脚本: %s" % script)
    env = dict(os.environ)
    env["QODER"] = qoder_line(acc)
    py = sys.executable or "python"
    log("=== 用当前登录态立即签到 ===")
    proc = subprocess.run([py, script], env=env, cwd=BASE_DIR)
    return proc.returncode


def show_current():
    log("=== 当前桌面端登录态 ===")
    app_dir = find_app_dir()
    if not app_dir:
        log("  (未找到客户端数据目录，请设 QODER_AUTH_DIR)")
        log("")
        return None
    acc = load_current()
    log("  uid=%s  昵称=%s" % (acc["uid"], acc["remark"]))
    log("  token 过期=%s  refreshToken 过期=%s" % (acc["expiresAt"], acc["refreshTokenExpiresAt"]))
    log("  数据目录=%s" % app_dir)
    log("")
    return acc


def main():
    init_console()
    # 只在管道/重定向时把编码固定成 UTF-8；控制台流交给 init_console，
    # 这里再 reconfigure 会把已经接管好的控制台流改坏（中文变「褰撳墠」）。
    if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "interactive"

    if mode == "show":
        acc = load_current()
        log("=== 当前 QODER 信息 (复制到青龙环境变量 QODER) ===")
        log(qoder_line(acc))
        log("")
        log("青龙: 系统设置 -> 环境变量 -> 新建 QODER，把上面整行粘贴进去；多账号换行追加。")
        log("token 约 30 天过期(脚本会自动刷新)，刷新失效时回本机重跑本命令更新即可。")
        return 0

    if mode == "backup":
        backup_current()
        return 0

    if mode == "signin":
        return run_signin(load_current())

    if mode == "list":
        acc = show_current()
        files = list_backups()
        if not files:
            log("[提示] 备份目录中还没有任何 %s* 备份文件夹。" % BACKUP_PREFIX)
            log("        可运行本脚本选 [1] 备份当前登录态来生成第一个备份;")
            log("        或把其他账号的 qoder_auth_backup/ 文件夹复制到本目录以带来旧账号。")
        else:
            for i, d in enumerate(files, 1):
                meta = {}
                try:
                    with open(os.path.join(d, "meta.json"), "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except (OSError, json.JSONDecodeError):
                    pass
                log("  [%d] %-46s  昵称=%s  备份于=%s" % (
                    i, os.path.basename(d), meta.get("remark", "?"), meta.get("at", "?")))
        if acc:
            log("")
            log("当前账号 QODER 行: %s" % qoder_line(acc))
        return 0

    # 交互式菜单: 备份当前 + 查看 QODER 信息 + 立即签到 + 选旧备份还原
    # 即使没有任何备份也能运行(冷启动友好)
    acc = show_current()
    files = list_backups()
    log("请选择操作:")
    log("  [1] 备份当前登录态（仅备份，不还原）")
    log("  [2] 输出当前 QODER 信息 (ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON)")
    log("  [3] 用当前登录态立即签到一次")
    for i, d in enumerate(files, 4):
        meta = {}
        try:
            with open(os.path.join(d, "meta.json"), "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        log("  [%d] 还原 %-46s (昵称=%s)" % (i, os.path.basename(d), meta.get("remark", "?")))
    if not files:
        log("  （暂无备份，可先选 [1] 备份当前登录态；")
        log("   若想带旧账号，把其他机器同用户的 qoder_auth_backup/ 文件夹复制到此目录即可）")
    log("  [0] 取消")
    log("")
    try:
        choice = input("输入编号: ").strip()
    except EOFError:
        log("")
        choice = "0"
    if not choice or choice == "0":
        log("已取消。")
        return 0
    if not choice.isdigit():
        fail("请输入数字编号")
    idx = int(choice)
    if idx == 1:
        backup_current()
        return 0
    if idx == 2:
        if acc:
            log(qoder_line(acc))
        else:
            log(qoder_line(load_current()))
        return 0
    if idx == 3:
        return run_signin(load_current())
    if files and 4 <= idx <= 3 + len(files):
        restore_backup(files[idx - 4])
        return 0
    fail("无效编号: %s" % choice)


def init_console() -> None:
    """保证中文在 Windows 控制台正确显示（本机运行时才有意义）。

    正常情况 Python 3 在 Windows 控制台走 WriteConsoleW 写宽字符，与 chcp
    无关。但外部一旦设了 PYTHONIOENCODING（WorkBuddy / VS Code / 某些终端
    会注入 PYTHONIOENCODING=utf-8），Python 就改把 UTF-8 字节直接写进控制台，
    而控制台仍按自己的 chcp（中文系统 936=GBK）解释这些字节，于是「小天-售后」
    显示成「灏忓ぉ-鍞悗」，菜单和账号名全花掉。

    这里重新接管 stdout/stderr，强制回到 Unicode 控制台写入路径，与
    PYTHONIOENCODING、chcp 彻底解耦。管道/重定向（青龙、> file）不动，
    两个流各自判断，避免 stdout 重定向时 stderr 的提示仍乱码。
    """
    if os.name != "nt":
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            if stream is None or not stream.isatty():
                continue
            raw = io._WindowsConsoleIO(stream.fileno(), "w", closefd=False)
            setattr(sys, name, io.TextIOWrapper(
                raw, encoding="utf-8", errors="replace",
                line_buffering=True, write_through=True))
        except Exception:
            continue   # 拿不到控制台就保持原样，绝不能因此中断

if __name__ == "__main__":
    sys.exit(main() or 0)

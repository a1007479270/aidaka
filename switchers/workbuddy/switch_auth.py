#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 登录态备份 / 恢复 / 查看 一体脚本（aidaka 项目 · Windows 一键版，纯标准库）

一个脚本搞定:
  - 备份当前桌面端登录态
  - 查看当前 WORKBUDDY 信息 (ACCESS_TOKEN#UID#账号名)
  - 选择之前的某个备份来恢复

设计要点:
  - 脚本目录跟随自身 (BASE_DIR = 本文件所在目录), 移动到任意目录/电脑都能用。
  - 冷启动友好: 即使 workbuddy_auth_backup/ 为空或不存在, 也能运行;
    先选 [1] 备份当前登录态即可生成第一个备份, 之后才出现还原选项。
  - 还原/读取实时登录态依赖 %LOCALAPPDATA%, 自动适配目标 Windows 用户。

关于新版客户端的加密（5.6.2 起）
  accessToken / refreshToken / nickname / phoneNumber 被换成
  {"$wbEncrypted": 1, "envelope": "..."} 信封：AES-256-GCM，
  key = SHA256(atRestSecretKey 字符串)，keyId = SHA256(key).hex[:16]。
  密钥不落盘，但客户端自己随时能取——用 ELECTRON_RUN_AS_NODE=1 把
  WorkBuddy.exe 当普通 Node 跑，调它注册的原生绑定:
      process._linkedBinding('electron_browser_workbuddy_storage').loggerGet()
  本脚本据此在本机解密（不需要管理员权限，也不需要客户端开着窗口）。

  取 token 的顺序：
      1) 当前登录文件（明文直接用；信封则现场解密）
      2) 同目录下的历史明文快照 *.info
      3) 本目录 accounts.txt 缓存（上次成功取到的值）
  解不开时打印诊断（缺客户端 / 缺密钥 / keyId 不匹配）与下一步该怎么做。

交互菜单(双击 switch_auth.bat 即进入):
  [1] 备份当前登录态（仅备份，不还原）
  [2] 输出当前 WORKBUDDY 信息 (ACCESS_TOKEN#UID#账号名)
  [3] 还原 xxx  (昵称 / uid)   <- 有备份时才出现
  [0] 取消
  还原时会先自动备份"当前登录态"，防止丢号。

命令行:
  python switch_auth.py            # 交互式菜单
  python switch_auth.py list       # 仅列出所有备份 (无备份时给提示, 不报错)
  python switch_auth.py backup     # 仅备份当前登录态(带时间戳)
  python switch_auth.py show       # 仅输出当前 WORKBUDDY 信息
  python switch_auth.py show --save  # 同上，并把结果缓存到 accounts.txt
  python switch_auth.py diag       # 自检：客户端路径 / 密钥 / keyId
  python switch_auth.py selftest   # AES-256-GCM 已知答案自测（CI 可跑）

环境变量:
  WORKBUDDY_ATREST_KEY    直接给 44 字符密钥（客户端找不到时的唯一出路）
  WORKBUDDY_CLIENT_EXE    指定 WorkBuddy.exe 路径（自定义安装目录）
  WORKBUDDY_ELECTRON_BIN  同上，兼容其他工具的命名
"""
import os
import sys
import io
import json
import glob
import time
import base64
import shutil
import datetime
import re
import subprocess

# 脚本目录跟随自身: 只要 switch_auth.py 与 workbuddy_auth_backup/ 放在一起,
# 移动到任意目录 / 电脑都能运行 (不再硬编码具体路径)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local"),
    "CodeBuddyExtension", "Data", "Public", "auth", "workbuddy-desktop.info"
)
AUTH_DIR = os.path.dirname(AUTH_FILE)
BACKUP_DIR = os.path.join(BASE_DIR, "workbuddy_auth_backup")
# 上次取到的账号行缓存（明文 token，已被 .gitignore 挡住）
CACHE_FILE = os.path.join(BASE_DIR, "accounts.txt")


# ======================================================================
# 控制台中文输出（Windows）
# ======================================================================
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


# ======================================================================
# AES-256-GCM（纯标准库，无第三方依赖）
# ======================================================================
SBOX = [
0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16]
RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36,0x6c,0xd8,0xab,0x4d]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1b) & 0xff
    return a


def _expand_key(key):
    w = [list(key[i * 4:(i + 1) * 4]) for i in range(8)]
    for i in range(8, 60):
        t = list(w[i - 1])
        if i % 8 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i // 8 - 1]
        elif i % 8 == 4:
            t = [SBOX[b] for b in t]
        w.append([w[i - 8][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(15)]


def _aes_block(rk, block):
    s = [block[i] ^ rk[0][i] for i in range(16)]
    for rnd in range(1, 14):
        s = [SBOX[b] for b in s]
        s = [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
             s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]
        ns = []
        for c in range(4):
            a = s[c * 4:c * 4 + 4]
            ns += [_xtime(a[0]) ^ _xtime(a[1]) ^ a[1] ^ a[2] ^ a[3],
                   a[0] ^ _xtime(a[1]) ^ _xtime(a[2]) ^ a[2] ^ a[3],
                   a[0] ^ a[1] ^ _xtime(a[2]) ^ _xtime(a[3]) ^ a[3],
                   _xtime(a[0]) ^ a[0] ^ a[1] ^ a[2] ^ _xtime(a[3])]
        s = ns
        s = [s[i] ^ rk[rnd][i] for i in range(16)]
    s = [SBOX[b] for b in s]
    s = [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
         s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]
    return bytes(s[i] ^ rk[14][i] for i in range(16))


def _gf_mult(x, y):
    r = 0xE1 << 120
    z, v = 0, x
    for i in range(127, -1, -1):
        if (y >> i) & 1:
            z ^= v
        if v & 1:
            v = (v >> 1) ^ r
        else:
            v >>= 1
    return z


def _gcm_ctx(key, iv):
    """返回 (h, j0, inc32, gctr)"""
    if len(key) != 32:
        raise ValueError("key 必须 32 字节")
    if len(iv) != 12:
        raise ValueError("nonce 必须 12 字节")
    rk = _expand_key(key)
    h = int.from_bytes(_aes_block(rk, b"\x00" * 16), "big")
    j0 = iv + b"\x00\x00\x00\x01"

    def inc32(b):
        return b[:12] + ((int.from_bytes(b[12:], "big") + 1) % 2 ** 32).to_bytes(4, "big")

    def gctr(icb, data):
        out = b""
        cb = icb
        for i in range(0, len(data), 16):
            ks = _aes_block(rk, cb)
            out += bytes(a ^ b for a, b in zip(data[i:i + 16], ks))
            cb = inc32(cb)
        return out

    return h, j0, inc32, gctr


def _gcm_tag(h, j0, inc32, gctr, aad, ct):
    buf = aad + b"\x00" * ((-len(aad)) % 16) + ct + b"\x00" * ((-len(ct)) % 16)
    buf += (len(aad) * 8).to_bytes(8, "big") + (len(ct) * 8).to_bytes(8, "big")
    y = 0
    for i in range(0, len(buf), 16):
        y = _gf_mult(y ^ int.from_bytes(buf[i:i + 16], "big"), h)
    return gctr(j0, y.to_bytes(16, "big"))


def aes_gcm_decrypt(key, iv, ct, aad, tag):
    """AES-256-GCM 解密；tag 不匹配抛 ValueError（说明密钥或 AAD 不对）"""
    h, j0, inc32, gctr = _gcm_ctx(key, iv)
    pt = gctr(inc32(j0), ct)
    if _gcm_tag(h, j0, inc32, gctr, aad, ct) != tag:
        raise ValueError("GCM 认证失败")
    return pt


# ----------------------------------------------------------------------
# 信封：派生密钥、AAD、解开 {$wbEncrypted:1, envelope}
# ----------------------------------------------------------------------
def _u32(n):
    return n.to_bytes(4, "big")


def field_aad(key_id):
    """字段信封的 AAD，54 字节。任何一处不对都会 GCM 认证失败。"""
    return (b"WB-AAD\x00" + b"\x01" + _u32(5) + b"WBEV1" + _u32(6) + b"sym-v1"
            + _u32(1) + _u32(16) + key_id.encode("ascii") + b"\x02" + b"\x00" + b"\x00")


def derive_key(secret_b64):
    """atRestSecretKey(44 字符 base64) -> (32 字节 AES key, keyId)

    注意：是对「base64 字符串本身」做 SHA-256，不是先 b64decode。
    """
    import hashlib
    key = hashlib.sha256(secret_b64.encode("utf-8")).digest()
    return key, hashlib.sha256(key).hexdigest()[:16]


def is_encrypted(v):
    """新版客户端把字段塞进 {$wbEncrypted:1, envelope:...}"""
    return isinstance(v, dict) and v.get("$wbEncrypted") == 1 and "envelope" in v


def envelope_keyid(wrapper):
    """取出信封声明的 keyId（诊断用，解不开时能说清是哪把钥匙）"""
    try:
        env = json.loads(base64.b64decode(wrapper["envelope"]))
        return env.get("keyId") or ""
    except Exception:
        return ""


def open_envelope(key, key_id, wrapper):
    """解开一个信封字段，返回明文 str；密钥不对返回 None"""
    try:
        env = json.loads(base64.b64decode(wrapper["envelope"]))
        if env.get("keyId") != key_id:
            return None
        pt = aes_gcm_decrypt(
            key,
            base64.b64decode(env["nonce"]),
            base64.b64decode(env["ciphertext"]),
            field_aad(key_id),
            base64.b64decode(env["authTag"]),
        )
        return pt.decode("utf-8", "replace")
    except Exception:
        return None


def decrypt_value(v, keys):
    """字段值 -> 明文 str；明文原样返回；解不开返回 None"""
    if isinstance(v, str):
        return v
    if not is_encrypted(v):
        return None
    for key, key_id in keys or []:
        got = open_envelope(key, key_id, v)
        if got is not None:
            return got
    return None


# ----------------------------------------------------------------------
# 取密钥：让客户端自己交出来
# ----------------------------------------------------------------------
_STORAGE_JS = ("const m=process._linkedBinding('electron_browser_workbuddy_storage');"
               "const p=JSON.parse(m.loggerGet());"
               "process.stdout.write(String(p.atRestSecretKey||''));")

_SECRET_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")

_KEY_STATE = {"keys": None, "note": "", "client": None}


def find_client_exe():
    """定位客户端可执行文件：环境变量 → 常见路径 → 卸载注册表项"""
    for var in ("WORKBUDDY_CLIENT_EXE", "WORKBUDDY_ELECTRON_BIN"):
        p = (os.environ.get(var) or "").strip().strip('"')
        if p and os.path.isfile(p):
            return p

    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    cands = [os.path.join(local, "Programs", "WorkBuddy", "WorkBuddy.exe")]
    for drive in "CDEFGHI":
        cands.append(os.path.join(drive + ":" + os.sep, "Program Files", "WorkBuddy", "WorkBuddy.exe"))
    if sys.platform == "darwin":
        cands.append("/Applications/WorkBuddy.app/Contents/MacOS/Electron")
    for c in cands:
        if os.path.isfile(c):
            return c

    if os.name == "nt":
        try:
            import winreg
            roots = [
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            ]
            for root, path in roots:
                try:
                    parent = winreg.OpenKey(root, path)
                except OSError:
                    continue
                with parent:
                    for i in range(winreg.QueryInfoKey(parent)[0]):
                        try:
                            sub = winreg.OpenKey(parent, winreg.EnumKey(parent, i))
                        except OSError:
                            continue
                        with sub:
                            try:
                                name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                            except OSError:
                                continue
                            if "workbuddy" not in name.lower():
                                continue
                            for field in ("InstallLocation", "DisplayIcon"):
                                try:
                                    val = str(winreg.QueryValueEx(sub, field)[0])
                                except OSError:
                                    continue
                                val = val.strip('"').split(",")[0]
                                exe = val if val.lower().endswith(".exe") else os.path.join(val, "WorkBuddy.exe")
                                if os.path.isfile(exe):
                                    return exe
        except Exception:
            pass
    return None


def key_from_client(exe=None, timeout=20):
    """让客户端的原生绑定交出 atRestSecretKey；失败返回 None"""
    exe = exe or find_client_exe()
    if not exe or not os.path.isfile(exe):
        return None
    env = dict(os.environ)
    env["ELECTRON_RUN_AS_NODE"] = "1"
    flags = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW：不弹黑框
    try:
        proc = subprocess.run([exe, "-e", _STORAGE_JS], capture_output=True,
                              timeout=timeout, env=env, creationflags=flags,
                              stdin=subprocess.DEVNULL)
    except Exception:
        return None
    out = (proc.stdout or b"").decode("ascii", "replace").strip()
    return out if _SECRET_RE.match(out) else None


def resolve_keys(no_decrypt=False):
    """返回 ([(key, keyId), ...], 说明文字)"""
    if no_decrypt:
        return [], "已用 --no-decrypt 关闭解密"
    if _KEY_STATE["keys"] is not None:
        return _KEY_STATE["keys"], _KEY_STATE["note"]

    keys, note = [], ""
    env_key = (os.environ.get("WORKBUDDY_ATREST_KEY") or "").strip()
    if env_key:
        sources, note = [env_key], "环境变量 WORKBUDDY_ATREST_KEY"
    else:
        exe = find_client_exe()
        _KEY_STATE["client"] = exe
        secret = key_from_client(exe) if exe else None
        if secret:
            sources, note = [secret], "客户端原生绑定（%s）" % os.path.basename(exe)
        else:
            sources = []
            note = ("未找到 WorkBuddy 客户端（可用 WORKBUDDY_CLIENT_EXE 指定路径）"
                    if not exe else "客户端在，但取不到密钥（版本可能已变）")

    for s in sources:
        try:
            keys.append(derive_key(s))
        except Exception:
            pass
    _KEY_STATE["keys"], _KEY_STATE["note"] = keys, note
    return keys, note


# ======================================================================
# 登录态文件读取
# ======================================================================
def load_info(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def acc(info, key, keys=None):
    """取账号字段；加密字段就地解密，解不开时给占位文案"""
    v = (info.get("account", {}) or {}).get(key, "?") if info else "?"
    if isinstance(v, dict):
        got = decrypt_value(v, keys or [])
        if got:
            return got
        return "WorkBuddy账号"
    return v or "WorkBuddy账号"


def uid_of(info, keys=None):
    """uid 必须是纯字符串（拼环境变量用）"""
    v = (info.get("account", {}) or {}).get("uid") if info else None
    if isinstance(v, dict):
        v = decrypt_value(v, keys or [])
    return v if isinstance(v, str) and v else ""


def jwt_exp(tok):
    """从 JWT 里取 exp（秒）；失败返回 0"""
    try:
        seg = tok.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return int(json.loads(base64.urlsafe_b64decode(seg)).get("exp") or 0)
    except Exception:
        return 0


def show_current(keys):
    print("=== 当前桌面端登录态 ===")
    info = load_info(AUTH_FILE)
    if not info:
        print("  (登录文件不存在: %s)" % AUTH_FILE)
        print()
        return
    tok = (info.get("auth", {}) or {}).get("accessToken")
    nick = acc(info, "nickname", keys)
    uid = uid_of(info, keys) or "?"
    if is_encrypted(tok):
        state = "已加密（新版客户端）"
        if decrypt_value(tok, keys):
            state += "，本地可解"
        else:
            kid = envelope_keyid(tok) or "?"
            state += "，当前解不开（keyId=%s）" % kid
    else:
        state = "明文"
    print("  uid=%s  昵称=%s  token=%s" % (uid, nick, state))
    print()


def list_backups():
    """返回备份文件列表(可能为空), 不在此处报错退出。"""
    return sorted(glob.glob(os.path.join(BACKUP_DIR, "workbuddy-desktop.info.*")))


def backup_current(keys=None):
    if not os.path.isfile(AUTH_FILE):
        print("[错误] 当前登录文件不存在: %s" % AUTH_FILE)
        sys.exit(1)
    nick = acc(load_info(AUTH_FILE), "nickname", keys)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in nick)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, "workbuddy-desktop.info.%s_%s.bak" % (safe, ts))
    shutil.copyfile(AUTH_FILE, dest)
    print("已备份当前登录态 -> %s" % os.path.basename(dest))


def token_line_of(path, keys=None):
    """从某个登录态文件解析出 WORKBUDDY 行: ACCESS_TOKEN#UID#账号名

    明文直接用；加密信封就地解密（需要本机密钥）。
    """
    info = load_info(path)
    if not info:
        return None
    tok = (info.get("auth", {}) or {}).get("accessToken")
    tok = decrypt_value(tok, keys or [])
    if not isinstance(tok, str) or not tok.startswith("eyJ"):
        return None
    uid = uid_of(info, keys)
    if not uid:
        return None
    return "%s#%s#%s" % (tok, uid, acc(info, "nickname", keys))


def scan_accounts(keys):
    """扫描 auth 目录下所有 .info（含历史快照），返回可用的账号行。

    返回 [dict(exp, line, file, current, encrypted)]，按过期时间倒序。
    """
    rows, seen = [], set()
    try:
        files = glob.glob(os.path.join(AUTH_DIR, "*.info"))
    except Exception:
        files = []
    current_norm = os.path.normcase(os.path.abspath(AUTH_FILE))
    for f in files:
        line = token_line_of(f, keys)
        if not line:
            continue
        tok = line.split("#")[0]
        if tok in seen:           # 同一 token 可能被多个快照引用
            continue
        seen.add(tok)
        info = load_info(f) or {}
        rows.append({
            "exp": jwt_exp(tok),
            "line": line,
            "file": os.path.basename(f),
            "current": os.path.normcase(os.path.abspath(f)) == current_norm,
            "encrypted": is_encrypted((info.get("auth", {}) or {}).get("accessToken")),
        })
    rows.sort(key=lambda r: r["exp"], reverse=True)
    return rows


def cache_read():
    if not os.path.isfile(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as fp:
            for ln in fp:
                ln = ln.strip()
                if ln and "#" in ln:
                    return ln
    except Exception:
        pass
    return None


def cache_write(line):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as fp:
            fp.write(line + "\n")
        return True
    except Exception:
        return False


def fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "未知"


def print_no_token_help(rows, keys, note):
    """拿不到有效 token 时的诊断与出路"""
    print("[错误] 取不到可用的 accessToken。")
    print()
    print("诊断:")
    info = load_info(AUTH_FILE)
    if info is None:
        print("  · 登录文件不存在（%s）——客户端没登录过，或装的是别的账号目录" % AUTH_FILE)
    else:
        tok = (info.get("auth", {}) or {}).get("accessToken")
        if is_encrypted(tok):
            kid = envelope_keyid(tok) or "?"
            print("  · 当前登录文件是加密信封，keyId=%s" % kid)
            print("  · 本机密钥状态: %s" % (note or "无"))
            if keys:
                print("  · 已取到密钥 keyId=%s —— 与文件里的不一致，说明客户端升级换过钥匙"
                      % keys[0][1])
        else:
            print("  · 登录文件里没有可用的 accessToken 字段")
    if rows:
        print("  · 找到 %d 份可用记录，但都已过期（最晚 %s）" % (len(rows), fmt_ts(rows[0]["exp"])))
    elif os.path.isdir(AUTH_DIR):
        print("  · 同目录下没有可解出 token 的 .info（%s）" % AUTH_DIR)
    if cache_read():
        print("  · accounts.txt 有缓存，但同样可能已过期")
    print()
    print("接下来可以这样做（任一）:")
    print("  1) 装/保留 WorkBuddy 桌面端并登录一次 → 直接重跑，脚本会现场解密")
    print("  2) 客户端装在非默认目录 → 设 WORKBUDDY_CLIENT_EXE=<...>\\WorkBuddy.exe")
    print("  3) 没有客户端（青龙/CI/新机器）→ 在已登录的机器上取一次 44 字符密钥，设")
    print("     WORKBUDDY_ATREST_KEY=<密钥>，或从可用环境把账号行抄进 accounts.txt")
    print("  4) 抓一次桌面端的 Authorization: Bearer 头，手工填 accounts.txt")
    print()
    print("提示: accounts.txt 一行一个账号，格式 ACCESS_TOKEN#UID#备注，明文保存，勿外传。")


def show_current_token_line(save=False, keys=None, note=""):
    rows = scan_accounts(keys)
    now = time.time()
    live = [r for r in rows if r["exp"] > now]

    if live:
        # 优先当前登录文件（客户端可能刚刷新过），否则取到期最晚的
        pick = next((r for r in live if r["current"]), live[0])
        print("=== 当前 WORKBUDDY 信息 (复制到青龙环境变量) ===")
        print(pick["line"])
        print()
        src = pick["file"] + ("" if pick["current"] else "（历史快照）")
        if pick["current"] and pick["encrypted"]:
            src += "（本地解密）"
        print("来源    : %s" % src)
        print("有效期至: %s" % fmt_ts(pick["exp"]))
        days = int((pick["exp"] - now) // 86400)
        if days <= 7:
            print("⚠️  只剩 %d 天，建议尽快换新 token" % max(days, 0))
        if save:
            print()
            print("已缓存到 %s（下次取不到时自动兜底）" % CACHE_FILE if cache_write(pick["line"])
                  else "[警告] 缓存写入失败: %s" % CACHE_FILE)
        return 0

    # 没有有效明文 → 看缓存
    cached = cache_read()
    if cached:
        exp = jwt_exp(cached.split("#")[0])
        if exp > now:
            print("=== WORKBUDDY 信息 (来自 accounts.txt 缓存) ===")
            print(cached)
            print()
            print("有效期至: %s" % fmt_ts(exp))
            return 0
        print("[提示] accounts.txt 缓存已过期（%s）" % fmt_ts(exp))
        print()

    print_no_token_help(rows, keys, note)
    return 2


def restore_and_show(sel, keys):
    # 切换前先自动备份当前状态（防丢号）
    if os.path.isfile(AUTH_FILE):
        backup_current(keys)
    shutil.copyfile(sel, AUTH_FILE)
    print()
    print("=== 已还原: %s -> 桌面端 ===" % os.path.basename(sel))
    info = load_info(AUTH_FILE)
    if info:
        print("还原后 uid=%s  昵称=%s" % (uid_of(info, keys) or "?", acc(info, "nickname", keys)))
        print()
        print("=== 该账号的 WORKBUDDY 签到 token 行 (复制到青龙环境变量) ===")
        line = token_line_of(AUTH_FILE, keys)
        print(line if line else "(该备份里的 token 既不是明文，也无法用本机密钥解开)")
    print()
    print("⚠️  请重启/刷新 WorkBuddy 桌面端确认账号已切换(若提示重新登录属正常)。")


def diag():
    """自检：环境、客户端、密钥、keyId、当前文件状态"""
    keys, note = resolve_keys()
    exe = _KEY_STATE.get("client") or find_client_exe()
    print("=== 环境自检 ===")
    print("  登录文件 : %s %s" % (AUTH_FILE, "(存在)" if os.path.isfile(AUTH_FILE) else "(不存在)"))
    print("  客户端   : %s" % (exe or "(未找到)"))
    print("  密钥来源 : %s" % (note or "-"))
    print("  本机keyId: %s" % (", ".join(k[1] for k in keys) if keys else "(无)"))
    info = load_info(AUTH_FILE)
    if info:
        tok = (info.get("auth", {}) or {}).get("accessToken")
        print("  文件格式 : %s" % ("加密信封" if is_encrypted(tok) else "明文"))
        if is_encrypted(tok):
            print("  文件keyId: %s" % (envelope_keyid(tok) or "?"))
        line = token_line_of(AUTH_FILE, keys)
        print("  能否取号 : %s" % ("能" if line else "不能"))
        if line:
            print("  账号     : %s" % line.split("#")[2])
            print("  有效期至 : %s" % fmt_ts(jwt_exp(line.split("#")[0])))
    print()
    return 0 if keys else 1


def selftest():
    """AES-256-GCM 已知答案测试（NIST GCM spec 附录 B，AES-256 用例）"""
    key = bytes.fromhex("feffe9928665731c6d6a8f9467308308feffe9928665731c6d6a8f9467308308")
    iv = bytes.fromhex("cafebabefacedbaddecaf888")
    pt = bytes.fromhex(
        "d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
        "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39"
        "1aafd255")
    ct = bytes.fromhex(
        "522dc1f099567d07f47f37a32a84427d643a8cdcbfe5c0c97598a2bd2555d1aa"
        "8cb08e48590dbb3da7b08b1056828838c5f61e6393ba7a0abcc9f662898015ad")
    tag = bytes.fromhex("b094dac5d93471bdec1a502270e3cc6c")

    ok = True
    try:
        ok = aes_gcm_decrypt(key, iv, ct, b"", tag) == pt
    except Exception:
        ok = False
    print("GCM 已知答案测试: %s" % ("通过" if ok else "失败"))

    # 篡改一位必须失败
    bad = bytearray(tag)
    bad[0] ^= 0x01
    try:
        aes_gcm_decrypt(key, iv, ct, b"", bytes(bad))
        tamper = False
    except ValueError:
        tamper = True
    print("篡改检测: %s" % ("通过" if tamper else "失败"))

    # AAD 长度自检
    aad_ok = len(field_aad("0123456789abcdef")) == 54
    print("AAD 长度: %s (%d 字节)" % ("通过" if aad_ok else "失败", len(field_aad("0" * 16))))
    return 0 if (ok and tamper and aad_ok) else 1


def main():
    init_console()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    argv = [a for a in sys.argv[1:]]
    save = "--save" in argv
    no_decrypt = "--no-decrypt" in argv
    argv = [a for a in argv if a not in ("--save", "--no-decrypt")]

    # --key <44 字符密钥>：临时指定，优先级高于环境变量与客户端
    for i, a in enumerate(list(argv)):
        if a == "--key" and i + 1 < len(argv):
            os.environ["WORKBUDDY_ATREST_KEY"] = argv[i + 1]
            del argv[i:i + 2]
            break

    mode = argv[0] if argv else "interactive"

    if mode == "selftest":
        return selftest()

    keys, note = resolve_keys(no_decrypt)

    if mode == "diag":
        return diag()

    if mode == "list":
        show_current(keys)
        files = list_backups()
        if not files:
            print("[提示] 备份目录中还没有任何 workbuddy-desktop.info.* 备份。")
            print("        可运行本脚本选 [1] 备份当前登录态来生成第一个备份;")
            print("        或把其他机器上的 workbuddy_auth_backup/ 文件夹复制到本目录以带来旧账号。")
        else:
            for i, f in enumerate(files, 1):
                info = load_info(f)
                print("  [%d] %-42s  uid=%s  昵称=%s" % (
                    i, os.path.basename(f), uid_of(info, keys) or "?", acc(info, "nickname", keys)))
        print()
        return 0

    if mode == "backup":
        backup_current(keys)
        return 0

    if mode == "show":
        return show_current_token_line(save=save, keys=keys, note=note)

    # 交互式菜单: 备份当前 + 查看当前 WORKBUDDY + 选旧备份还原
    # 即使没有任何备份也能运行(冷启动友好)
    show_current(keys)
    files = list_backups()
    print("请选择操作:")
    print("  [1] 备份当前登录态（仅备份，不还原）")
    print("  [2] 输出当前 WORKBUDDY 信息 (ACCESS_TOKEN#UID#账号名)")
    if files:
        for i, f in enumerate(files, 3):
            info = load_info(f)
            print("  [%d] 还原 %-42s  (uid=%s  昵称=%s)" % (
                i, os.path.basename(f), uid_of(info, keys) or "?", acc(info, "nickname", keys)))
    else:
        print("  （暂无备份，可先选 [1] 备份当前登录态；")
        print("   若想带旧账号，把其他机器的 workbuddy_auth_backup/ 文件夹复制到此目录即可）")
    print("  [0] 取消")
    print()
    try:
        choice = input("输入编号: ").strip()
    except EOFError:
        print()
        choice = "0"
    if not choice or choice == "0":
        print("已取消。")
        return 0
    try:
        idx = int(choice)
    except ValueError:
        print("[错误] 请输入数字编号")
        return 1
    if idx == 1:
        backup_current(keys)
        return 0
    if idx == 2:
        return show_current_token_line(save=True, keys=keys, note=note)
    if files:
        ridx = idx - 3
        if 0 <= ridx < len(files):
            restore_and_show(files[ridx], keys)
            return 0
    print("[错误] 无效编号: %s" % choice)
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aidaka 统一签到入口
==========================
一条命令跑完所有已配置平台的每日签到，也可只跑指定平台。

用法:
    python checkin.py                  # 跑全部平台
    python checkin.py ima qoder        # 只跑指定平台（可多选）
    python checkin.py --list           # 列出所有平台及环境变量
    python checkin.py --dry-run        # 只探测不实际领取（所有平台）
    python checkin.py --debug          # 打印接口原始响应
    python checkin.py --save-local-cred  # 把本机取到的账号存成 switchers/<平台>/accounts.txt
    python checkin.py --no-local-cred    # 只用环境变量，不从本机取号（青龙/CI 用）

凭证来源（每个平台独立，环境变量为空时才往下找）:
    环境变量 → switchers/<平台>/accounts.txt → switchers/<平台>/switch_auth.py show（本机登录态）
    取到的凭证只在本次进程内生效，不写入系统环境变量。

环境变量（每个平台独立配置，多账号用换行分隔，详见 docs/）:
    ima         ima_uid#uid_type#ima_guid#refresh_token#备注
    workbuddy   ACCESS_TOKEN#UID#备注
    qoder       ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON
    traework    ACCESS_TOKEN#UID#备注#设备ID

青龙部署不需要本文件——把 platforms/ 下对应的单文件上传到青龙即可
（每个平台脚本都是自包含的，详见 docs/qinglong.md）。
"""

import argparse
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PLATFORMS_DIR = os.path.join(ROOT, "platforms")
SWITCHERS_DIR = os.path.join(ROOT, "switchers")

# 平台顺序即此列表；新增平台只需在 platforms/ 放一个同名单文件并加进来
PLATFORM_ORDER = ["ima", "workbuddy", "qoder", "traework"]

# 本地回退用的账号文件（一行一个账号，格式与环境变量相同）；已被 .gitignore 挡住
LOCAL_ACCOUNT_FILE = "accounts.txt"

CRED_SOURCE = {
    "env": "环境变量",
    "file": "本地 %s" % LOCAL_ACCOUNT_FILE,
    "show": "本机登录态（switchers 现取）",
    "encrypted": "登录态已被客户端加密，无法自动获取",
    "none": "未找到本地凭证",
}


def _py_candidates():
    """列出可能装有 cryptography 的解释器——qoder / traework 取号需要它。"""
    cands = [[sys.executable]]
    if os.name == "nt":
        py = shutil.which("py")
        if py:
            for ver in ("-3.10", "-3.11", "-3.12"):
                cands.append([py, ver])
    for exe in ("python3.11", "python3.10", "python3", "python"):
        path = shutil.which(exe)
        if path:
            cands.append([path])

    # 常见安装路径：Windows 上 python.exe 往往不叫 python3.10，按名字找不到
    patterns = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            patterns.append(os.path.join(local, "Programs", "Python", "Python3*", "python.exe"))
        patterns.append(r"C:\Python3*\python.exe")
        patterns.append(os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                                     "Python3*", "python.exe"))
    else:
        patterns += ["/usr/bin/python3.*", "/usr/local/bin/python3.*"]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            if os.path.isfile(path):
                cands.append([path])

    out, seen = [], set()
    for cand in cands:
        key = tuple(cand)
        if key not in seen:
            seen.add(key)
            out.append(cand)
    return out


def _looks_like_account(key, line):
    """判断一行是不是该平台的账号行（# 分隔）；顺带挡掉占位符与密文信封。"""
    if not line or line.startswith("#") or "$wbEncrypted" in line or "YOUR_" in line:
        return False
    parts = line.split("#")
    if key == "ima":
        return len(parts) >= 4 and bool(parts[3].strip())
    if key == "qoder":
        if len(parts) < 5:
            return False
        try:
            device = json.loads(parts[4].strip())
        except ValueError:
            return False
        return isinstance(device, dict) and bool(device.get("machineToken"))
    if key in ("workbuddy", "traework"):
        return parts[0].strip().startswith("eyJ") and len(parts) >= 2
    return False


def _pick_account_line(key, text):
    """从 switcher 的输出（或本地文件）里挑出第一行合法账号。"""
    for raw in (text or "").splitlines():
        line = re.sub(r"^[-*>\s]+", "", raw.strip())
        if _looks_like_account(key, line):
            return line
    return ""


def _run_switcher_show(key):
    """跑 switchers/<平台>/switch_auth.py show，返回输出；密文信封返回 ENCRYPTED。"""
    script = os.path.join(SWITCHERS_DIR, key, "switch_auth.py")
    if not os.path.isfile(script):
        return ""
    for cmd in _py_candidates():
        try:
            proc = subprocess.run(
                cmd + [script, "show"], cwd=os.path.dirname(script),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=90)
        except (OSError, subprocess.SubprocessError):
            continue
        blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if "$wbEncrypted" in blob:
            return "ENCRYPTED"
        if _pick_account_line(key, blob):
            return blob
    return ""


def _save_local_account(key, line):
    """把取到的账号行存成本地文件，下次就不用再跑 switcher。"""
    folder = os.path.join(SWITCHERS_DIR, key)
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, LOCAL_ACCOUNT_FILE), "w", encoding="utf-8") as fp:
            fp.write(line + "\n")
    except OSError as exc:
        print("  [警告] 写入本地账号文件失败: %s" % exc)
        return False
    print("  [保存] 已写入 switchers/%s/%s（含明文 token，已在 .gitignore 中）"
          % (key, LOCAL_ACCOUNT_FILE))
    return True


def local_credential(key, meta, save=False):
    """环境变量为空时，从本项目已有的凭证补上。

    顺序：环境变量 → switchers/<平台>/accounts.txt → switchers 现跑 show（本机登录态）。
    只在本次进程内写 os.environ，不改动任何系统环境变量。
    """
    env_name = meta.get("env") or key.upper()
    if os.environ.get(env_name, "").strip():
        return "env"

    path = os.path.join(SWITCHERS_DIR, key, LOCAL_ACCOUNT_FILE)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                line = _pick_account_line(key, fp.read())
        except OSError:
            line = ""
        if line:
            os.environ[env_name] = line
            return "file"

    print("  [取号] %s 未配置，正在从本机登录态读取…" % env_name)
    blob = _run_switcher_show(key)
    if blob == "ENCRYPTED":
        return "encrypted"

    line = _pick_account_line(key, blob)
    if not line:
        return "none"

    os.environ[env_name] = line
    if save:
        _save_local_account(key, line)
    return "show"


def load_platform(key):
    """按文件路径加载 platforms/<key>.py，返回模块对象（失败返回 None）。"""
    path = os.path.join(PLATFORMS_DIR, key + ".py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("aidaka_platform_%s" % key, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def platform_meta(key):
    mod = load_platform(key)
    meta = dict(getattr(mod, "PLATFORM", None) or {})
    meta.setdefault("key", key)
    meta.setdefault("title", key)
    meta.setdefault("env", key.upper())
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="checkin.py",
        description="aidaka 统一签到入口（ima / WorkBuddy / Qoder / TraeWork）",
    )
    parser.add_argument("platforms", nargs="*",
                        help="要签到的平台，缺省为全部；可用: %s" % " ".join(PLATFORM_ORDER))
    parser.add_argument("--list", action="store_true", help="列出所有平台及环境变量")
    parser.add_argument("--dry-run", action="store_true", help="只探测不实际领取")
    parser.add_argument("--debug", action="store_true", help="打印接口原始响应")
    parser.add_argument("--no-local-cred", action="store_true",
                        help="环境变量为空时不再从本机登录态取号，只用环境变量")
    parser.add_argument("--save-local-cred", action="store_true",
                        help="把从本机取到的账号行存成 switchers/<平台>/accounts.txt，下次直接用")
    args = parser.parse_args(argv)

    if args.list:
        print("可用平台:")
        for key in PLATFORM_ORDER:
            meta = platform_meta(key)
            print("  %-10s %-26s 环境变量 %-11s 格式 %s" % (
                meta["key"], meta["title"], meta["env"],
                meta.get("env_format", "-")))
        return 0

    keys = args.platforms or list(PLATFORM_ORDER)
    unknown = [k for k in keys if k not in PLATFORM_ORDER]
    if unknown:
        parser.error("未知平台: %s（可用: %s）" % (", ".join(unknown), ", ".join(PLATFORM_ORDER)))

    print("=== aidaka 开始: %s ===" % ", ".join(keys))
    results = {}
    for key in keys:
        mod = load_platform(key)
        meta = getattr(mod, "PLATFORM", None) or {}
        print("\n----- [%s] %s -----" % (key, meta.get("title", key)))

        if not args.no_local_cred:
            source = local_credential(key, meta, save=args.save_local_cred)
            print("[凭据] %s" % CRED_SOURCE.get(source, source))

        if mod is None or not hasattr(mod, "run"):
            print("[错误] 平台模块加载失败: platforms/%s.py" % key)
            results[key] = 1
            continue
        try:
            rc = mod.run(dry_run=args.dry_run, debug=args.debug)
        except Exception as exc:  # 单平台异常不影响其他平台
            print("[错误] %s 签到抛出异常: %s" % (key, exc))
            rc = 1
        results[key] = int(rc or 0)
        time.sleep(1)

    print("\n=== aidaka 汇总 ===")
    for key in keys:
        mark = "OK" if results.get(key, 1) == 0 else "失败"
        print("  %-10s %s" % (key, mark))
    failed = [k for k, rc in results.items() if rc != 0]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

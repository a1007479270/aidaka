#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ima 登录凭证(多账号) 提取/备份/查看/还原 一体脚本 (daily-checkin 项目 · ima 平台)
备份/查看/还原为纯标准库；仅 [e] 提取功能需要 Windows + cryptography 库。

原理:
    ima 签到凭证存在脚本同目录的 credentials.json 中(由本脚本
    [e] 提取，或命令 extract 生成)。备份/恢复这个文件，
    即可实现 ima 多账号并存与切换，主号不丢失。

用法:
    python switch_auth.py            # 交互式菜单
    python switch_auth.py list       # 仅列出所有凭证备份
    python switch_auth.py backup     # 仅备份当前凭证(带时间戳)
    python switch_auth.py show       # 查看当前凭证账号信息 + 青龙环境变量行
    python switch_auth.py restore <备份名或序号>   # 还原指定凭证
    python switch_auth.py extract    # 从 ima 客户端提取凭证(Windows)

说明:
    备份目录 ima_cred_backup/ 跟随脚本自身存放，拷到任意目录都能用。
    还原前会自动先备份当前凭证，防止丢失。
    [c] 立即签到会调用仓库 platforms/ima.py（可用 IMA_CHECKIN_SCRIPT 覆盖路径）。
    凭证 refresh_token 失效时，完全退出 ima 后运行 extract 重新提取。
    提取功能需要: pip install cryptography -i https://mirrors.aliyun.com/pypi/simple/
"""

import base64
import ctypes
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

try:
    import ctypes.wintypes  # noqa: F401
except ImportError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# 仓库根目录 = switchers/ima/ 的上两级（可用环境变量覆盖，兼容拷贝到别处使用）
ROOT = os.environ.get("DAILY_CHECKIN_ROOT") or os.path.dirname(os.path.dirname(HERE))
CRED_FILE = os.path.join(HERE, "credentials.json")
BACKUP_DIR = os.path.join(HERE, "ima_cred_backup")

# 签到脚本位于仓库 platforms/ 下（单文件自包含，青龙也可直接上传该文件）
CHECKIN_SCRIPT = os.environ.get("IMA_CHECKIN_SCRIPT") or os.path.join(ROOT, "platforms", "ima.py")

WANTED = ("IMA-UID", "UID-TYPE", "IMA-GUID", "IMA-TOKEN", "IMA-REFRESH-TOKEN")


def _read_cred():
    if not os.path.exists(CRED_FILE):
        return None
    try:
        with open(CRED_FILE, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        print("[错误] 读取 credentials.json 失败: %s" % exc)
        return None


def _mask(s, keep=6):
    s = s or ""
    return s[:keep] + "***" if len(s) > keep else (s + "***" if s else "-")


def _label(cred):
    """账号短标识: uid 前缀。"""
    return (cred.get("ima_uid") or "unknown")[:10]


# ---- 提取凭证(Windows 专用, 需要 cryptography) ----

def _dpapi_decrypt(data):
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("DPAPI 解密失败 (CryptUnprotectData)")
    out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return out


def _load_aes_key(user_data_dir):
    local_state_path = os.path.join(user_data_dir, "Local State")
    if not os.path.exists(local_state_path):
        raise FileNotFoundError("找不到 %s" % local_state_path)
    with open(local_state_path, "r", encoding="utf-8") as fp:
        state = json.load(fp)
    enc_key = base64.b64decode(state["os_crypt"]["encrypted_key"])
    if enc_key[:5] != b"DPAPI":
        raise ValueError("未知的密钥格式, 无法解密。")
    return _dpapi_decrypt(enc_key[5:])


def _read_cookies(db_path, aes_key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not os.path.exists(db_path):
        return {}
    tmp = os.path.join(tempfile.mkdtemp(prefix="ima_cred_"), "Cookies")
    try:
        shutil.copy2(db_path, tmp)
    except OSError:
        raise OSError("无法读取 %s，请先【完全退出 ima 客户端】(含托盘图标)。" % db_path)
    result = {}
    con = sqlite3.connect(tmp)
    try:
        for name, enc in con.execute("SELECT name, encrypted_value FROM cookies"):
            if name not in WANTED or enc is None:
                continue
            if isinstance(enc, str):
                enc = enc.encode("latin-1")
            prefix = enc[:3]
            if prefix in (b"v10", b"v11"):
                plain = AESGCM(aes_key).decrypt(enc[3:15], enc[15:], None)
                value = plain[32:] if len(plain) > 32 else plain
                try:
                    value = value.decode("utf-8")
                except UnicodeDecodeError:
                    value = plain.decode("utf-8", "replace")
                result[name] = value
            elif prefix == b"v20":
                raise ValueError("Cookie 使用了 v20(应用绑定)加密, 暂不支持。")
    finally:
        con.close()
        shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
    return result


def do_extract(profile_dir=None):
    """从 ima 客户端提取凭证并写入 credentials.json。"""
    if sys.platform != "win32":
        print("[错误] 提取功能仅支持 Windows(需要 DPAPI 解密)。")
        return False
    user_data = profile_dir or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "ima.copilot", "User Data")
    if not os.path.isdir(user_data):
        print("[错误] ima 数据目录不存在: %s" % user_data)
        return False
    try:
        import cryptography  # noqa: F401  懒加载, 仅提取时需要
    except ImportError:
        print("[错误] 缺少 cryptography 库, 请先安装:")
        print("    pip install cryptography -i https://mirrors.aliyun.com/pypi/simple/")
        return False

    try:
        print("[1/3] 读取加密密钥 (Local State + DPAPI)...")
        aes_key = _load_aes_key(user_data)
        print("[2/3] 解密 Cookie 库...")
        cookies = {}
        for rel in ("Default/Extension Cookies", "Default/Network/Cookies", "Default/Cookies"):
            found = _read_cookies(os.path.join(user_data, rel), aes_key)
            if found:
                cookies.update(found)
                print("      %s -> 找到 %d 个字段" % (rel, len(found)))
    except (OSError, ValueError, FileNotFoundError) as exc:
        print("[错误] %s" % exc)
        return False

    missing = [n for n in WANTED if n not in cookies]
    if "IMA-TOKEN" in missing and "IMA-REFRESH-TOKEN" in missing:
        print("[错误] 未找到登录凭证。请确认:")
        print("  1) ima 客户端已在本机登录;")
        print("  2) 提取时已【完全退出】ima;")
        print("  3) 若因凭证失效而重新提取, 请先打开 ima 确认登录正常(必要时重新扫码)。")
        return False

    print("[3/3] 写入 credentials.json ...")
    cred = {
        "ima_uid": cookies.get("IMA-UID", ""),
        "uid_type": cookies.get("UID-TYPE", ""),
        "ima_guid": cookies.get("IMA-GUID", ""),
        "refresh_token": cookies.get("IMA-REFRESH-TOKEN", ""),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if not cred["refresh_token"]:
        print("[错误] 缺少 IMA-REFRESH-TOKEN, 无法长期签到。")
        return False
    with open(CRED_FILE, "w", encoding="utf-8") as fp:
        json.dump(cred, fp, ensure_ascii=False, indent=2)
    print("[完成] 凭证已写入: %s" % CRED_FILE)
    print("(该文件等同账号钥匙, 请勿上传或分享)")
    return True


def do_backup(tag=None, quiet=False):
    if not os.path.exists(CRED_FILE):
        print("[错误] 当前目录没有 credentials.json，请先运行 extract 提取（python switch_auth.py extract）。")
        return None
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    cred = _read_cred() or {}
    name = "%s_%s.json" % (tag or _label(cred), ts)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, name)
    shutil.copy2(CRED_FILE, dest)
    if not quiet:
        print("[完成] 已备份当前凭证 -> %s" % dest)
    return name


def do_list():
    if not os.path.isdir(BACKUP_DIR):
        print("备份目录为空(尚无凭证备份)。")
        return []
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".json"))
    if not files:
        print("备份目录为空(尚无凭证备份)。")
        return []
    print("现有凭证备份:")
    for i, f in enumerate(files, 1):
        path = os.path.join(BACKUP_DIR, f)
        try:
            with open(path, "r", encoding="utf-8") as fp:
                cred = json.load(fp)
            extra = "uid:%s, 提取于:%s" % (_mask(cred.get("ima_uid")), cred.get("saved_at", "?"))
        except (OSError, json.JSONDecodeError):
            extra = "(文件损坏)"
        print("  [%d] %s  (%s)" % (i, f, extra))
    return files


def do_show():
    cred = _read_cred()
    if not cred:
        print("[错误] 未找到 credentials.json: %s" % CRED_FILE)
        return
    print("当前 ima 凭证信息:")
    print("  ima_uid       : %s" % _mask(cred.get("ima_uid")))
    print("  uid_type      : %s" % (cred.get("uid_type") or "-"))
    print("  ima_guid      : %s" % _mask(cred.get("ima_guid"), 8))
    print("  refresh_token : %s" % _mask(cred.get("refresh_token")))
    print("  提取时间      : %s" % cred.get("saved_at", "-"))
    print("  凭证文件      : %s" % CRED_FILE)
    print("青龙环境变量一行(多账号用换行分隔):")
    print("  %s#%s#%s#%s#备注" % (
        cred.get("ima_uid", ""), cred.get("uid_type", ""),
        cred.get("ima_guid", ""), cred.get("refresh_token", "")))


def do_restore(name):
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".json")) \
        if os.path.isdir(BACKUP_DIR) else []
    if not files:
        print("[错误] 没有任何凭证备份可还原。")
        return
    target = None
    if name.isdigit() and 1 <= int(name) <= len(files):
        target = files[int(name) - 1]
    else:
        hits = [f for f in files if name in f]
        if len(hits) == 1:
            target = hits[0]
        elif len(hits) > 1:
            print("[错误] 匹配到多个备份，请用更精确的名称: %s" % ", ".join(hits))
            return
    if not target:
        print("[错误] 找不到备份: %s" % name)
        return
    src = os.path.join(BACKUP_DIR, target)
    print("即将还原: %s" % target)
    if os.path.exists(CRED_FILE):
        keep = do_backup(tag="restore前自动备份", quiet=True)
        print("(已自动备份当前凭证: %s)" % keep)
    shutil.copy2(src, CRED_FILE)
    print("[完成] 已还原。可运行签到脚本验证: python ima_checkin.py")


def menu():
    while True:
        files = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".json")) \
            if os.path.isdir(BACKUP_DIR) else []
        print("\n===== ima 登录凭证管理 =====")
        print("[1] 备份当前凭证（仅备份，不还原）")
        print("[2] 查看当前凭证账号信息 + 青龙环境变量行")
        if files:
            for i, f in enumerate(files, 1):
                print("[%d] 还原 %s" % (i + 2, f))
        print("[e] 提取/更新凭证 (需先完全退出 ima)")
        print("[c] 立即执行一次签到")
        print("[0] 取消")
        choice = input("请选择: ").strip().lower()
        if choice == "1":
            do_backup()
        elif choice == "2":
            do_show()
        elif choice == "e":
            print("提示: 请先【完全退出 ima 客户端】(含托盘图标) 再提取。")
            input("确认已退出后按回车继续...")
            do_extract()
        elif choice == "c":
            os.system('"%s" "%s"' % (sys.executable or "python", CHECKIN_SCRIPT))
        elif choice == "0" or choice == "":
            return
        elif choice.isdigit() and 3 <= int(choice) <= 2 + len(files):
            do_restore(files[int(choice) - 3])
        else:
            print("无效选择。")


def main():
    args = sys.argv[1:]
    if not args:
        menu()
    elif args[0] == "list":
        do_list()
    elif args[0] == "backup":
        do_backup()
    elif args[0] == "show":
        do_show()
    elif args[0] == "restore" and len(args) > 1:
        do_restore(args[1])
    elif args[0] == "extract":
        do_extract(args[1] if len(args) > 1 else None)
    elif args[0] in ("-h", "--help", "help"):
        print(__doc__)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

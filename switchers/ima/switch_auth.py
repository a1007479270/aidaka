#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ima 登录凭证(多账号) 提取/备份/查看/还原 一体脚本 (aidaka 项目 · ima 平台)
全部功能纯标准库；仅 [e] 提取功能需要 Windows(DPAPI 解出 Cookie 库主密钥)。

原理:
    ima 是基于 Electron/Chromium 的客户端，登录态存在
        %LOCALAPPDATA%\ima.copilot\User Data\Default\{Extension Cookies, Network\Cookies}
    的 cookies 表里，值为 Chromium v10 方案(AES-256-GCM)加密；
    主密钥在 User Data\Local State 里由 Windows DPAPI 保护。
    解出 IMA-UID / UID-TYPE / IMA-GUID / IMA-REFRESH-TOKEN 后写入脚本同目录的
    credentials.json。备份/恢复这个文件，即可实现 ima 多账号并存与切换，主号不丢失。
    ima 运行中也能提取(共享读)，不必完全退出。

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
    凭证 refresh_token 失效时，运行 extract 重新提取即可(ima 开着也行)。
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
import io

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


# ---- 提取凭证(Windows 专用, 纯标准库) ----

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


# ---- AES-256-GCM(纯标准库, 免 pip 装 cryptography) ----

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
    """AES-256-GCM 解密；tag 不匹配抛 ValueError"""
    h, j0, inc32, gctr = _gcm_ctx(key, iv)
    pt = gctr(inc32(j0), ct)
    if _gcm_tag(h, j0, inc32, gctr, aad, ct) != tag:
        raise ValueError("GCM 认证失败")
    return pt


# ---- 共享读取(ima 运行中也能读, 不必完全退出) ----

GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE = ctypes.c_void_p(-1).value


def _read_file_shared(path):
    """用 FILE_SHARE_READ|WRITE|DELETE 打开并读全量。

    浏览器/Electron 进程会给 Cookie 库加锁, shutil.copy2 会报 WinError 32;
    但锁本身通常允许共享读, 用 CreateFileW 显式声明共享模式即可绕开。
    完全共享也被拒时退回普通读取。
    """
    if os.name != "nt":
        with open(path, "rb") as fp:
            return fp.read()
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_void_p]
    k32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                             ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.CreateFileW(path, GENERIC_READ, FILE_SHARE_ALL, None,
                        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if not h or h == INVALID_HANDLE:
        with open(path, "rb") as fp:      # 共享失败就直读(可能仍会抛错)
            return fp.read()
    try:
        chunks, buf, got = [], ctypes.create_string_buffer(1 << 20), ctypes.c_uint32(0)
        while True:
            if not k32.ReadFile(h, buf, len(buf), ctypes.byref(got), None):
                raise OSError(ctypes.get_last_error(), "ReadFile 失败: %s" % path)
            if got.value == 0:
                break
            chunks.append(buf.raw[:got.value])
        return b"".join(chunks)
    finally:
        k32.CloseHandle(h)


def _decode_cookie_value(plain):
    """Chromium 130+ 会在明文前拼 32 字节 SHA256(host_key)，需要剥掉。

    不能只看长度：老版本没有前缀。两个候选都试，挑能干净 UTF-8 解码的那个。
    """
    cands = [plain[32:], plain] if len(plain) > 32 else [plain]
    for raw in cands:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if text and all(32 <= ord(ch) or ch in "\t" for ch in text):
            return text
    return plain[32:].decode("utf-8", "replace") if len(plain) > 32 \
        else plain.decode("utf-8", "replace")


def _read_cookies(db_path, aes_key):
    """读取单个 Cookie 库中 ima 相关字段。

    返回 (found, skipped)。skipped=True 表示文件存在但被占用/读不了，
    调用方应继续尝试其它库，而不是整体失败。
    """
    if not os.path.exists(db_path):
        return {}, False
    tmp_dir = tempfile.mkdtemp(prefix="ima_cred_")
    tmp = os.path.join(tmp_dir, "Cookies")
    try:
        try:
            data = _read_file_shared(db_path)
        except OSError:
            return {}, True
        with open(tmp, "wb") as fp:
            fp.write(data)
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
                    plain = aes_gcm_decrypt(aes_key, enc[3:15], enc[15:-16], b"", enc[-16:])
                    result[name] = _decode_cookie_value(plain)
                elif prefix == b"v20":
                    print("      [警告] %s 使用 v20(应用绑定)加密, 无法解密, 请换回默认浏览器加密方式。" % name)
        finally:
            con.close()
        return result, False
    except (sqlite3.DatabaseError, ValueError) as exc:
        print("      [警告] 解析 %s 失败: %s" % (os.path.basename(db_path), exc))
        return {}, True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
        print("[1/3] 读取加密密钥 (Local State + DPAPI)...")
        aes_key = _load_aes_key(user_data)
        print("[2/3] 解密 Cookie 库...")
        cookies, locked = {}, []
        # Extension Cookies 先试: ima 的登录态优先落在这里, 且它不被浏览器进程锁
        for rel in ("Default/Extension Cookies", "Default/Network/Cookies", "Default/Cookies"):
            found, skipped = _read_cookies(os.path.join(user_data, *rel.split("/")), aes_key)
            if found:
                cookies.update(found)
                print("      %s -> 找到 %d 个字段" % (rel, len(found)))
            elif skipped:
                locked.append(rel)
    except (OSError, ValueError, FileNotFoundError) as exc:
        print("[错误] %s" % exc)
        return False

    missing = [n for n in WANTED if n not in cookies]
    if "IMA-TOKEN" in missing and "IMA-REFRESH-TOKEN" in missing:
        print("[错误] 未找到登录凭证。请确认:")
        print("  1) ima 客户端已在本机登录;")
        print("  2) 若刚登录过, 打开 ima 首页刷新一下再试;")
        print("  3) 若因凭证失效而重新提取, 请先打开 ima 确认登录正常(必要时重新扫码)。")
        if locked:
            print("  (以下库被占用读不了, 可完全退出 ima 后重试: %s)" % ", ".join(locked))
        return False
    if missing:
        print("[提示] 缺少字段: %s (不影响签到)" % ", ".join(missing))

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
    print("  %s#%s#%s#%s#%s" % (
        cred.get("ima_uid", ""), cred.get("uid_type", ""),
        cred.get("ima_guid", ""), cred.get("refresh_token", ""),
        "ima-" + (cred.get("ima_uid") or "unknown")[:8]))


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
        print("[e] 提取/更新凭证 (ima 开着也能提取)")
        print("[c] 立即执行一次签到")
        print("[0] 取消")
        choice = input("请选择: ").strip().lower()
        if choice == "1":
            do_backup()
        elif choice == "2":
            do_show()
        elif choice == "e":
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
    init_console()
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
    main()

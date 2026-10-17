#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TraeWork 登录态备份 / 恢复 / 查看 一体脚本（daily-checkin 项目 · Windows 一键版）

一个脚本搞定:
  - 备份当前桌面端登录态（多账号逐个登录、逐个备份，即实现多账号切换）
  - 查看当前 TRAEWORK 信息 (ACCESS_TOKEN#UID#账号名#设备ID，复制到青龙环境变量)
  - 选择之前的某个备份来还原（切换账号）

与参考脚本 switch_auth.py 一致的交互菜单(双击 switch_auth.bat 即进入):
  [1] 备份当前登录态（仅备份，不还原）
  [2] 输出当前 TRAEWORK 信息 (ACCESS_TOKEN#UID#账号名#设备ID)
  [3] 还原 xxx  (uid / 昵称)   <- 有备份时才出现，每个备份占一个菜单项
  [0] 取消
  还原前会先自动备份"当前登录态"，防止丢号。

设计要点:
  - 脚本目录跟随自身 (BASE_DIR = 本文件所在目录)，备份存到旁边的
    traework_auth_backup/，移动到任意目录/电脑都能用。
  - 冷启动友好: 备份目录为空/不存在也能运行，先选 [1] 生成第一个备份，
    之后才出现还原选项。
  - TraeWork 登录态加密存放在 storage.json 里（AES-128-CBC），
    因此本脚本需要 cryptography（pip install cryptography；switch_auth.bat
    缺失时会自动安装）。这是它和纯明文读取的青龙脚本唯一的区别。

命令行:
  python switch_auth.py            # 交互式菜单
  python switch_auth.py list       # 仅列出所有备份 (无备份时给提示, 不报错)
  python switch_auth.py backup     # 仅备份当前登录态(带时间戳)
  python switch_auth.py show       # 仅输出当前 TRAEWORK 信息
"""

import os
import sys
import glob
import json
import base64
import hashlib
import datetime
import subprocess

# 脚本目录跟随自身: 只要 switch_auth.py 与 traework_auth_backup/ 放在一起,
# 移动到任意目录 / 电脑都能运行 (不硬编码具体路径)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "traework_auth_backup")

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    sys.exit(
        "缺少依赖 cryptography。请先执行：\n"
        "    python -m pip install cryptography\n"
        "（或直接双击 switch_auth.bat，会自动安装）"
    )

# ================================================================
# 登录态定位与解密（TraeWork 桌面端：AES-128-CBC）
# ================================================================

# 新版叫 TRAE SOLO CN，旧版叫 Trae CN / Trae，依次探测
APP_DIR_NAMES = ("TRAE SOLO CN", "Trae CN", "Trae")

AUTH_KEY = "iCubeAuthInfo://icube.cloudide"      # 登录态（加密）
USERTAG_KEY = "iCubeAuthInfo://usertag"          # 账号 -> 区域 映射（加密）
SERVER_DATA_KEY = "iCubeServerData://icube.cloudide"  # 服务端数据缓存（明文）

# 与账号绑定、还原时需要整体替换的三个键
PROFILE_KEYS = (AUTH_KEY, USERTAG_KEY, SERVER_DATA_KEY)

HEADER_LEN, SALT_LEN, DIGEST_LEN = 6, 32, 64
AES_KEY_LEN = AES_IV_LEN = 16

# 两份 64 字节常量，异或后参与密钥派生（与客户端实现一致）
_URE = bytes([
    82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
    124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
    84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
    8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37,
])
_DRE = bytes([
    31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
    96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
    160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
    23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125,
])
_XOR_MASK = bytes(a ^ b for a, b in zip(_URE, _DRE))


def _unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if 1 <= pad <= 16 and data[-pad:] == bytes([pad]) * pad:
        return data[:-pad]
    return data


def decrypt_blob(blob_b64: str) -> bytes:
    """解密 storage.json 中的密文，返回去掉 64 字节校验区后的明文。"""
    raw = base64.b64decode(blob_b64)
    if len(raw) <= HEADER_LEN + SALT_LEN:
        raise ValueError("登录态数据长度异常，无法解密")
    salt = raw[HEADER_LEN:HEADER_LEN + SALT_LEN]
    # 先对 salt 做一次 SHA-512，再与掩码拼接后做第二次 SHA-512
    digest = hashlib.sha512(
        hashlib.sha512(salt).digest() + _XOR_MASK
    ).digest()
    key, iv = digest[:AES_KEY_LEN], digest[AES_KEY_LEN:AES_KEY_LEN + AES_IV_LEN]
    ciphertext = raw[HEADER_LEN + SALT_LEN:]
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = _unpad(dec.update(ciphertext) + dec.finalize())
    if len(plain) < DIGEST_LEN:
        raise ValueError("解密结果长度异常")
    return plain[DIGEST_LEN:]


def decrypt_json(blob_b64: str) -> dict:
    return json.loads(decrypt_blob(blob_b64).decode("utf-8"))


def _appdata() -> str:
    return os.environ.get(
        "APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    )


def storage_candidates() -> list:
    """所有存在的 storage.json，按修改时间倒序（最新在前）。"""
    root = _appdata()
    found = [
        os.path.join(root, name, "User", "globalStorage", "storage.json")
        for name in APP_DIR_NAMES
    ]
    existing = [p for p in found if os.path.isfile(p)]
    existing.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return existing


def load_storage(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _decryptable(path: str) -> bool:
    """机器上可能并存新旧多个客户端，旧版登录态格式不同、解不开；实测一次。"""
    try:
        blob = load_storage(path).get(AUTH_KEY)
        return isinstance(blob, str) and isinstance(decrypt_json(blob), dict)
    except Exception:
        return False


def find_storage_path() -> str:
    candidates = storage_candidates()
    if not candidates:
        raise FileNotFoundError(
            "找不到 TraeWork 的 storage.json，请确认桌面端已安装并至少登录过一次。"
        )
    for path in candidates:
        if _decryptable(path):
            return path
    return candidates[0]


def app_name_of(storage_path: str) -> str:
    # <APPDATA>/<APP>/User/globalStorage/storage.json -> <APP>
    parts = os.path.normpath(storage_path).split(os.sep)
    try:
        return parts[-4]
    except IndexError:
        return ""


def read_auth(storage_path: str) -> dict:
    """读取并解密当前登录账号，返回关键字段 dict。"""
    storage = load_storage(storage_path)
    blob = storage.get(AUTH_KEY)
    if not blob:
        raise ValueError(f"{storage_path} 中没有登录态，请先在桌面端登录账号。")
    payload = decrypt_json(blob)
    account = payload.get("account") or {}
    region_info = payload.get("userRegion") or {}
    return {
        "token": payload.get("token", "") or "",
        "uid": str(payload.get("userId", "") or ""),
        "name": str(account.get("username", "") or "")
                or (str(payload.get("userId", "")) and "user-%s" % payload.get("userId"))
                or "unknown",
        "region": region_info.get("region", "CN") or "CN",
        "expired_at": payload.get("expiredAt", "") or "",
        "raw_keys": {k: storage[k] for k in PROFILE_KEYS if k in storage},
    }


# ---- 设备 ID（签到请求头 x-device-id 需要，缺了服务端可能返回 9004）----

TINY_STORAGE_REL = os.path.join("aha", "TinyStorage")
DEVICE_ID_KEY = "aha.device.device_id"


def read_device_id(storage_path: str) -> str:
    root = _appdata()
    names = []
    try:
        names.append(app_name_of(storage_path))
    except Exception:
        pass
    names.extend(APP_DIR_NAMES)
    for name in dict.fromkeys(names):
        path = os.path.join(root, name, TINY_STORAGE_REL)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            blob = (data.get("tiny_storage_data") or {}).get(DEVICE_ID_KEY)
            if not blob:
                continue
            payload = json.loads(decrypt_blob(blob).decode("utf-8"))
            device_id = str(payload.get("device_id_str") or "")
            if device_id:
                return device_id
        except Exception:
            continue
    return ""


# ================================================================
# 备份 / 还原（备份文件是不透明的登录态快照，与参考脚本同构）
# ================================================================


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name))


def list_backups() -> list:
    """返回备份文件列表(可能为空)，按时间倒序（新的在前）。"""
    return sorted(
        glob.glob(os.path.join(BACKUP_DIR, "traework-storage.*.json")),
        reverse=True,
    )


def backup_meta(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return {"uid": data.get("uid", "?"), "name": data.get("name", "?"),
                "createdAt": data.get("createdAt", "")}
    except Exception:
        return {"uid": "?", "name": "?", "createdAt": ""}


def backup_current(label: str = "") -> str:
    """备份当前登录态 -> traework_auth_backup/traework-storage.<名>_<uid>_<时间>.json"""
    storage_path = find_storage_path()
    auth = read_auth(storage_path)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = ("_%s" % safe_name(label)) if label else ""
    fname = "traework-storage.%s_%s_%s%s.json" % (
        safe_name(auth["name"]), safe_name(auth["uid"]), ts, suffix,
    )
    dest = os.path.join(BACKUP_DIR, fname)
    envelope = {
        "version": 1,
        "createdAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "app": app_name_of(storage_path),
        "source": storage_path,
        "uid": auth["uid"],
        "name": auth["name"],
        "region": auth["region"],
        "deviceId": read_device_id(storage_path),
        "keys": auth["raw_keys"],
    }
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)
    return dest


def token_line_of(storage_path: str) -> str:
    """从当前登录态拼出 TRAEWORK 行: ACCESS_TOKEN#UID#账号名#设备ID"""
    auth = read_auth(storage_path)
    if not auth["token"]:
        return ""
    fields = [auth["token"], auth["uid"], auth["name"]]
    device_id = read_device_id(storage_path)
    if device_id:
        fields.append(device_id)
    return "#".join(fields)


def app_running(app_name: str) -> bool:
    target = (app_name or "").strip().lower()
    if not target:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return False
    for row in out.splitlines():
        proc = row.split('","')[0].strip().strip('"').lower()
        if proc.endswith(".exe"):
            proc = proc[:-4]
        if proc == target or proc.startswith(target):
            return True
    return False


def restore_and_show(sel: str) -> None:
    storage_path = find_storage_path()
    app_name = app_name_of(storage_path)

    # 客户端运行时还原会被其退出时的内存态覆盖，必须先完全退出
    if app_running(app_name):
        print("[错误] 检测到 %s 正在运行，请先完全退出客户端（含托盘）后再还原。"
              % app_name)
        return

    with open(sel, "r", encoding="utf-8-sig") as f:
        envelope = json.load(f)
    keys = envelope.get("keys") or {}
    if not keys.get(AUTH_KEY):
        print("[错误] 备份文件缺少登录态数据：%s" % os.path.basename(sel))
        return

    # 切换前先自动备份当前状态（防丢号）
    auto = backup_current(label="before-restore")
    storage = load_storage(storage_path)
    for key in PROFILE_KEYS:
        if key in keys:
            storage[key] = keys[key]
        else:
            storage.pop(key, None)
    tmp = storage_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(storage, f, ensure_ascii=False, indent=4)
    os.replace(tmp, storage_path)

    print()
    print("=== 已还原: %s -> 桌面端 ===" % os.path.basename(sel))
    auth = read_auth(storage_path)
    print("还原后 uid=%s  昵称=%s  区域=%s" % (auth["uid"], auth["name"], auth["region"]))
    print("切换前状态已自动备份: %s" % os.path.basename(auto))
    print()
    print("=== 该账号的 TRAEWORK 签到 token 行 (复制到青龙环境变量) ===")
    line = token_line_of(storage_path)
    print(line or "(无法解析 accessToken，请重新登录该账号后再备份)")
    print()
    print("⚠️  请重启 TraeWork 桌面端确认账号已切换(若提示重新登录属正常)。")


# ================================================================
# 展示与入口（与参考脚本一致的扁平菜单）
# ================================================================


def show_current():
    print("=== 当前桌面端登录态 ===")
    try:
        path = find_storage_path()
        auth = read_auth(path)
        device_id = read_device_id(path)
        print("  uid=%s  昵称=%s  区域=%s" % (auth["uid"], auth["name"], auth["region"]))
        print("  设备ID=%s" % (device_id or "(未读取到)"))
        print("  token过期=%s" % (auth["expired_at"] or "未知"))
    except (FileNotFoundError, ValueError) as e:
        print("  (读取失败: %s)" % e)
    print()


def show_current_token_line():
    try:
        line = token_line_of(find_storage_path())
    except (FileNotFoundError, ValueError) as e:
        print("[错误] %s" % e)
        return
    if not line:
        print("[错误] 无法从当前登录态解析 accessToken，请先在桌面端登录。")
        return
    if sys.stdout.isatty():
        print("=== 当前 TRAEWORK 信息 (复制到青龙环境变量 TRAEWORK) ===")
        print("格式: ACCESS_TOKEN#UID#账号名#设备ID")
        print(line)
        print("-" * 60)
        print("青龙 -> 系统设置 -> 环境变量 -> 新建，名称填 TRAEWORK；")
        print("定时任务命令: task traework.py，规则 0 9,21 * * *")
    else:
        # 重定向/管道时只输出干净的一行，方便 python switch_auth.py show > ql.txt
        print(line)


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "interactive"

    if mode == "list":
        show_current()
        files = list_backups()
        if not files:
            print("[提示] 备份目录中还没有任何 traework-storage.*.json 备份。")
            print("        可运行本脚本选 [1] 备份当前登录态来生成第一个备份；")
            print("        或把其他机器上的 traework_auth_backup/ 文件夹复制到本目录以带来旧账号。")
        else:
            for i, f in enumerate(files, 1):
                m = backup_meta(f)
                print("  [%d] %-46s  uid=%s  昵称=%s" % (
                    i, os.path.basename(f), m["uid"], m["name"]))
        print()
        return

    if mode == "backup":
        dest = backup_current()
        print("已备份当前登录态 -> %s" % os.path.basename(dest))
        return

    if mode == "show":
        show_current_token_line()
        return

    # 交互式菜单: 备份当前 + 查看当前 TRAEWORK + 选旧备份还原
    # 即使没有任何备份也能运行(冷启动友好)
    show_current()
    files = list_backups()
    print("请选择操作:")
    print("  [1] 备份当前登录态（仅备份，不还原）")
    print("  [2] 输出当前 TRAEWORK 信息 (ACCESS_TOKEN#UID#账号名#设备ID)")
    if files:
        for i, f in enumerate(files, 3):
            m = backup_meta(f)
            print("  [%d] 还原 %-46s  (uid=%s  昵称=%s)" % (
                i, os.path.basename(f), m["uid"], m["name"]))
    else:
        print("  （暂无备份，可先选 [1] 备份当前登录态；")
        print("   若想带旧账号，把其他机器的 traework_auth_backup/ 文件夹复制到此目录即可）")
    print("  [0] 取消")
    print()
    print("提示: 还原前会先自动备份当前登录态；还原后请重启 TraeWork 客户端。")
    print()
    try:
        choice = input("输入编号: ").strip()
    except EOFError:
        print()
        choice = "0"
    if not choice or choice == "0":
        print("已取消。")
        return
    try:
        idx = int(choice)
    except ValueError:
        print("[错误] 请输入数字编号")
        return
    if idx == 1:
        dest = backup_current()
        print("已备份当前登录态 -> %s" % os.path.basename(dest))
        return
    if idx == 2:
        show_current_token_line()
        return
    if files:
        ridx = idx - 3
        if 0 <= ridx < len(files):
            restore_and_show(files[ridx])
            return
    print("[错误] 无效编号: %s" % choice)


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as e:
        print("[错误] %s" % e)
        sys.exit(1)

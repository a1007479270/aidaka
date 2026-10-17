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

⚠️ 关于新版客户端的加密
  WorkBuddy 新版把登录文件里的 accessToken / refreshToken / nickname 加密成
  {"$wbEncrypted": 1, "envelope": "..."} 信封，密钥由客户端构建时注入
  （atRestSecretKey → SHA256 → AES-256-GCM），本地无法解开。
  因此取 token 的顺序是：
      1) 当前登录文件（旧版客户端仍然是明文）
      2) 同目录下的历史明文备份 *.info（新版加密前的快照）
      3) 本目录 accounts.txt 缓存（上次成功取到的值）
  都拿不到时打印诊断与下一步该怎么做，而不是只说"失败"。

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
"""
import os
import sys
import json
import glob
import time
import base64
import shutil
import datetime

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


def load_info(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def acc(info, key):
    v = (info.get("account", {}) or {}).get(key, "?") if info else "?"
    if isinstance(v, dict):          # 加密信封，读不出真实昵称
        return "WorkBuddy账号"
    return v or "WorkBuddy账号"


def is_encrypted(v):
    """新版客户端把字段塞进 {$wbEncrypted:1, envelope:...}"""
    return isinstance(v, dict) and v.get("$wbEncrypted") == 1


def jwt_exp(tok):
    """从 JWT 里取 exp（秒）；失败返回 0"""
    try:
        seg = tok.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return int(json.loads(base64.urlsafe_b64decode(seg)).get("exp") or 0)
    except Exception:
        return 0


def show_current():
    print("=== 当前桌面端登录态 ===")
    info = load_info(AUTH_FILE)
    if info:
        tok = (info.get("auth", {}) or {}).get("accessToken")
        state = "已加密（新版客户端）" if is_encrypted(tok) else "明文"
        print("  uid=%s  昵称=%s  token=%s" % (
            acc(info, "uid"), acc(info, "nickname"), state))
    else:
        print("  (登录文件不存在: %s)" % AUTH_FILE)
    print()


def list_backups():
    """返回备份文件列表(可能为空), 不在此处报错退出。"""
    return sorted(glob.glob(os.path.join(BACKUP_DIR, "workbuddy-desktop.info.*")))


def backup_current():
    if not os.path.isfile(AUTH_FILE):
        print("[错误] 当前登录文件不存在: %s" % AUTH_FILE)
        sys.exit(1)
    nick = acc(load_info(AUTH_FILE), "nickname")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in nick)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, "workbuddy-desktop.info.%s_%s.bak" % (safe, ts))
    shutil.copyfile(AUTH_FILE, dest)
    print("已备份当前登录态 -> %s" % os.path.basename(dest))


def token_line_of(path):
    """从某个登录态文件解析出 WORKBUDDY 行: ACCESS_TOKEN#UID#账号名

    只认明文 accessToken；加密信封返回 None（无法解开）。
    """
    info = load_info(path)
    if not info:
        return None
    tok = (info.get("auth", {}) or {}).get("accessToken")
    if not isinstance(tok, str) or not tok:
        return None
    uid = acc(info, "uid")
    if not uid or uid == "?":
        return None
    return "%s#%s#%s" % (tok, uid, acc(info, "nickname"))


def scan_plaintext_accounts():
    """扫描 auth 目录下所有 .info（含历史快照），返回明文可用的账号行。

    返回 [(exp, line, 文件名, 是否当前登录文件)]，按过期时间倒序。
    """
    rows, seen = [], set()
    try:
        files = glob.glob(os.path.join(AUTH_DIR, "*.info"))
    except Exception:
        files = []
    for f in files:
        line = token_line_of(f)
        if not line:
            continue
        tok = line.split("#")[0]
        if tok in seen:           # 同一 token 可能被多个快照引用
            continue
        seen.add(tok)
        rows.append((jwt_exp(tok), line, os.path.basename(f),
                     os.path.normcase(os.path.abspath(f)) == os.path.normcase(os.path.abspath(AUTH_FILE))))
    rows.sort(key=lambda r: r[0], reverse=True)
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


def print_no_token_help(rows):
    """拿不到有效明文时的诊断与出路"""
    print("[错误] 取不到可用的 accessToken。")
    print()
    print("诊断:")
    info = load_info(AUTH_FILE)
    if info is None:
        print("  · 登录文件不存在（%s）——客户端没登录过，或装的是别的账号目录" % AUTH_FILE)
    elif is_encrypted((info.get("auth", {}) or {}).get("accessToken")):
        print("  · 当前登录文件已加密（新版客户端），token 在 {\"$wbEncrypted\":1} 信封里，本地解不开")
    else:
        print("  · 登录文件里没有 accessToken 字段")
    if rows:
        print("  · 找到 %d 份明文快照，但都已过期（最晚 %s）" % (len(rows), fmt_ts(rows[0][0])))
    else:
        print("  · 同目录下没有明文快照（%s/*.info）" % AUTH_DIR)
    if cache_read():
        print("  · accounts.txt 里有缓存，但同样需要检查是否过期")
    print()
    print("接下来可以这样做（任一）:")
    print("  1) 旧版客户端还在用 → 直接运行 [2]，它会读到明文")
    print("  2) 换机器/旧版跑一次 show，把账号行抄进 accounts.txt（本目录），之后 [2] 会读缓存")
    print("  3) 装回旧版客户端登录一次，生成本地明文快照后再升级（快照会留在 auth 目录）")
    print("  4) 在浏览器 DevTools 里抓桌面端的 Authorization: Bearer 头，手工填进 accounts.txt")
    print()
    print("提示: accounts.txt 一行一个账号，格式 ACCESS_TOKEN#UID#备注，明文保存，勿外传。")


def show_current_token_line(save=False):
    rows = scan_plaintext_accounts()
    now = time.time()
    live = [r for r in rows if r[0] > now]

    if live:
        exp, line, fname, is_current = live[0]
        print("=== 当前 WORKBUDDY 信息 (复制到青龙环境变量) ===")
        print(line)
        print()
        print("来源    : %s%s" % (fname, "" if is_current else "（历史明文快照）"))
        print("有效期至: %s" % fmt_ts(exp))
        days = int((exp - now) // 86400)
        if days <= 7:
            print("⚠️  只剩 %d 天，建议尽快换新 token" % max(days, 0))
        if not is_current:
            print()
            print("说明: 当前登录文件已被新版客户端加密（无法本地解开），这里用的是同目录下")
            print("      仍然有效的明文快照。客户端刷新 token 后这个快照不会跟着更新。")
        if save:
            print()
            print("已缓存到 %s（下次取不到时自动兜底）" % CACHE_FILE if cache_write(line)
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

    print_no_token_help(rows)
    return 2


def restore_and_show(sel):
    # 切换前先自动备份当前状态（防丢号）
    if os.path.isfile(AUTH_FILE):
        backup_current()
    shutil.copyfile(sel, AUTH_FILE)
    print()
    print("=== 已还原: %s -> 桌面端 ===" % os.path.basename(sel))
    info = load_info(AUTH_FILE)
    if info:
        print("还原后 uid=%s  昵称=%s" % (acc(info, "uid"), acc(info, "nickname")))
        print()
        print("=== 该账号的 WORKBUDDY 签到 token 行 (复制到青龙环境变量) ===")
        line = token_line_of(AUTH_FILE)
        print(line if line else "(无法从该备份解析 accessToken/uid)")
    print()
    print("⚠️  请重启/刷新 WorkBuddy 桌面端确认账号已切换(若提示重新登录属正常)。")


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    argv = [a for a in sys.argv[1:]]
    save = "--save" in argv
    argv = [a for a in argv if a != "--save"]
    mode = argv[0] if argv else "interactive"

    if mode == "list":
        show_current()
        files = list_backups()
        if not files:
            print("[提示] 备份目录中还没有任何 workbuddy-desktop.info.* 备份。")
            print("        可运行本脚本选 [1] 备份当前登录态来生成第一个备份;")
            print("        或把其他机器上的 workbuddy_auth_backup/ 文件夹复制到本目录以带来旧账号。")
        else:
            for i, f in enumerate(files, 1):
                info = load_info(f)
                print("  [%d] %-42s  uid=%s  昵称=%s" % (
                    i, os.path.basename(f), acc(info, "uid"), acc(info, "nickname")))
        print()
        return 0

    if mode == "backup":
        backup_current()
        return 0

    if mode == "show":
        return show_current_token_line(save=save)

    # 交互式菜单: 备份当前 + 查看当前 WORKBUDDY + 选旧备份还原
    # 即使没有任何备份也能运行(冷启动友好)
    show_current()
    files = list_backups()
    print("请选择操作:")
    print("  [1] 备份当前登录态（仅备份，不还原）")
    print("  [2] 输出当前 WORKBUDDY 信息 (ACCESS_TOKEN#UID#账号名)")
    if files:
        for i, f in enumerate(files, 3):
            info = load_info(f)
            print("  [%d] 还原 %-42s  (uid=%s  昵称=%s)" % (
                i, os.path.basename(f), acc(info, "uid"), acc(info, "nickname")))
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
        backup_current()
        return 0
    if idx == 2:
        return show_current_token_line(save=True)
    if files:
        ridx = idx - 3
        if 0 <= ridx < len(files):
            restore_and_show(files[ridx])
            return 0
    print("[错误] 无效编号: %s" % choice)
    return 1


if __name__ == "__main__":
    sys.exit(main())

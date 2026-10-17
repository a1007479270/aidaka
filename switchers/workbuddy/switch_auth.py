#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 登录态备份 / 恢复 / 查看 一体脚本（daily-checkin 项目 · Windows 一键版，纯标准库）

一个脚本搞定:
  - 备份当前桌面端登录态
  - 查看当前 WORKBUDDY 信息 (ACCESS_TOKEN#UID#账号名)
  - 选择之前的某个备份来恢复

设计要点:
  - 脚本目录跟随自身 (BASE_DIR = 本文件所在目录), 移动到任意目录/电脑都能用。
  - 冷启动友好: 即使 workbuddy_auth_backup/ 为空或不存在, 也能运行;
    先选 [1] 备份当前登录态即可生成第一个备份, 之后才出现还原选项。
  - 还原/读取实时登录态依赖 %LOCALAPPDATA%, 自动适配目标 Windows 用户。

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
"""
import os
import sys
import json
import shutil
import glob
import datetime

# 脚本目录跟随自身: 只要 switch_auth.py 与 workbuddy_auth_backup/ 放在一起,
# 移动到任意目录 / 电脑都能运行 (不再硬编码具体路径)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local"),
    "CodeBuddyExtension", "Data", "Public", "auth", "workbuddy-desktop.info"
)
BACKUP_DIR = os.path.join(BASE_DIR, "workbuddy_auth_backup")


def load_info(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def acc(info, key):
    return (info.get("account", {}) or {}).get(key, "?") if info else "?"


def show_current():
    print("=== 当前桌面端登录态 ===")
    info = load_info(AUTH_FILE)
    if info:
        print("  uid=%s  昵称=%s" % (acc(info, "uid"), acc(info, "nickname")))
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
    """从某个登录态文件解析出 WORKBUDDY 行: ACCESS_TOKEN#UID#账号名"""
    info = load_info(path)
    if not info:
        return None
    tok = (info.get("auth", {}) or {}).get("accessToken", "")
    uid = acc(info, "uid")
    nick = acc(info, "nickname")
    if tok and uid:
        return "%s#%s#%s" % (tok, uid, nick)
    return None


def show_current_token_line():
    line = token_line_of(AUTH_FILE)
    if line:
        print("=== 当前 WORKBUDDY 信息 (复制到青龙环境变量) ===")
        print(line)
    else:
        print("[错误] 无法从当前登录态解析 accessToken/uid (文件: %s)" % AUTH_FILE)


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
    mode = sys.argv[1] if len(sys.argv) > 1 else "interactive"

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
        return

    if mode == "backup":
        backup_current()
        return

    if mode == "show":
        show_current_token_line()
        return

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
        return
    try:
        idx = int(choice)
    except ValueError:
        print("[错误] 请输入数字编号")
        return
    if idx == 1:
        backup_current()
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
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 switchers 的账号行转成金山文档表格 B 列需要的 JSON。

【为什么需要它】
  switchers/<平台>/switch_auth.py show 打印的是「青龙环境变量」格式（# 分隔的一行），
  但 wps-airscript 版签到脚本要求表格 B 列放的是 JSON 对象。两者字段一一对应，
  这个脚本负责转换，省得手抄 token 抄错。

【用法】
  python to_wps.py qoder                  # 自动跑本机 switcher，直接输出可粘贴的 JSON
  python to_wps.py qoder --clip           # 顺带复制到剪贴板
  python to_wps.py ima --stdin            # 从标准输入粘贴账号行（可多行、多账号）
  python to_wps.py traework "token#uid#备注#设备ID"
  python to_wps.py all                    # 四个平台一起，一行一个 JSON
  python to_wps.py all --tsv              # 输出「平台<TAB>JSON」，在表格 A2 粘贴一次填满所有行
  python to_wps.py all --tsv --clip       # 同上并复制，粘一次搞定整张表

【输出说明】
  默认只输出 JSON（一行一个账号），方便直接复制；
  人类可读的提示都走 stderr，所以 `> out.txt` 拿到的还是干净 JSON。
  --tsv 时每行是「平台 + TAB + JSON」，粘贴到表格 A 列会自动分列分行。
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PLATFORMS = ("ima", "workbuddy", "qoder", "traework")

# 备注列里常见的占位符，视为「没填」
PLACEHOLDER_NAMES = {"", "-", "备注", "未命名", "remark", "name", "账号"}

# 每个平台在 B 列需要的字段（顺序即输出顺序）
FIELD_HINT = {
    "ima": "ima_uid / uid_type / ima_guid / refresh_token / name",
    "workbuddy": "token / uid / name",
    "qoder": "name / refreshToken / accessToken / uid / device{...}",
    "traework": "token / uid / device_id / name",
}


def eprint(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------- 解析账号行
def looks_like_account_line(platform, line):
    """判断一行是不是本平台的账号行（# 分隔）。"""
    if "#" not in line:
        return False
    if line.startswith(("#", "//", "===")):
        return False
    if "$wbEncrypted" in line:
        return False
    parts = line.split("#")
    head = parts[0].strip()
    if not head:
        return False
    if platform == "ima":
        # ima_uid#uid_type#ima_guid#refresh_token[#备注]
        return len(parts) >= 4 and bool(parts[3].strip())
    if platform == "qoder":
        # ACCESS#REFRESH#UID#备注#设备JSON
        if len(parts) < 5:
            return False
        try:
            dev = json.loads(parts[4].strip())
        except (ValueError, IndexError):
            return False
        return isinstance(dev, dict) and bool(dev.get("machineToken"))
    if platform == "traework":
        # ACCESS[#UID][#备注][#设备ID]，ACCESS 是 JWT
        return len(head) >= 40 and head.count(".") == 2
    if platform == "workbuddy":
        # ACCESS[#UID][#备注]，ACCESS 是 JWT
        return len(head) >= 40 and head.count(".") == 2
    return False


def extract_account_lines(platform, text):
    """从 switcher 的整段输出里挑出账号行（去掉标题、提示、空行）。"""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 去掉 markdown 列表符号 / 箭头等前缀
        line = re.sub(r"^[-*>]\s*", "", line)
        if looks_like_account_line(platform, line):
            out.append(line)
    return out


# ---------------------------------------------------------------- 各平台转换
def _name(value, default):
    """备注留空或只是占位符时，给一个能看懂的默认名。"""
    v = (value or "").strip()
    return default if v in PLACEHOLDER_NAMES or not v else v


def to_ima(line):
    p = line.split("#")
    return {
        "ima_uid": p[0].strip(),
        "uid_type": (p[1].strip() if len(p) > 1 else "") or "1",
        "ima_guid": p[2].strip() if len(p) > 2 else "",
        "refresh_token": p[3].strip() if len(p) > 3 else "",
        "name": _name(p[4] if len(p) > 4 else "", "ima账号"),
    }


def to_workbuddy(line):
    p = line.split("#")
    return {
        "token": p[0].strip(),
        "uid": p[1].strip() if len(p) > 1 else "",
        "name": _name(p[2] if len(p) > 2 else "", "WorkBuddy账号"),
    }


def to_qoder(line):
    p = line.split("#", 4)
    device = {}
    if len(p) > 4 and p[4].strip():
        try:
            device = json.loads(p[4].strip())
        except ValueError:
            device = {}
    uid = p[2].strip() if len(p) > 2 else ""
    return {
        "name": _name(p[3] if len(p) > 3 else "", uid or "Qoder账号"),
        "refreshToken": p[1].strip() if len(p) > 1 else "",
        "accessToken": p[0].strip(),
        "uid": uid,
        "device": device,
    }


def to_traework(line):
    p = line.split("#")
    return {
        "token": p[0].strip(),
        "uid": p[1].strip() if len(p) > 1 else "",
        "device_id": p[3].strip() if len(p) > 3 else "",
        "name": _name(p[2] if len(p) > 2 else "", "TraeWork账号"),
    }


CONVERTERS = {
    "ima": to_ima,
    "workbuddy": to_workbuddy,
    "qoder": to_qoder,
    "traework": to_traework,
}


# ---------------------------------------------------------------- 跑 switcher
def _python_candidates():
    """列出可能装有 cryptography 的解释器，按优先级尝试。"""
    cands = [[sys.executable]]

    def add(cmd):
        if cmd and cmd not in cands:
            cands.append(cmd)

    # py 启动器指定版本（Windows 常见多版本并存）
    if os.name == "nt":
        py = shutil.which("py")
        if py:
            for ver in ("-3.10", "-3.11", "-3.12", "-3.9"):
                add([py, ver])

    for exe in ("python3.11", "python3.10", "python3.12", "python3", "python"):
        path = shutil.which(exe)
        if path:
            add([path])

    # 常见安装路径（PATH 里没配的也算上）
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
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            if os.path.isfile(p):
                add([p])

    return cands


def _has_module(py_cmd, module):
    try:
        r = subprocess.run(py_cmd + ["-c", "import " + module],
                           capture_output=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run_switcher(platform):
    """执行 switchers/<平台>/switch_auth.py show，返回 (stdout, stderr)。"""
    script = os.path.join(HERE, platform, "switch_auth.py")
    if not os.path.isfile(script):
        raise RuntimeError("找不到 switcher: %s" % script)

    attempts = _python_candidates()
    last = ("", "")
    for py_cmd in attempts:
        try:
            r = subprocess.run(py_cmd + [script, "show"], cwd=os.path.dirname(script),
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            last = ("", str(exc))
            continue
        out, err = r.stdout or "", r.stderr or ""
        blob = out + err
        # 缺依赖就换一个装了的解释器重试
        if "cryptography" in blob and ("缺少依赖" in blob or "ModuleNotFoundError" in blob):
            for alt in attempts:
                if alt == py_cmd or not _has_module(alt, "cryptography"):
                    continue
                try:
                    r2 = subprocess.run(alt + [script, "show"], cwd=os.path.dirname(script),
                                        capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", timeout=120)
                    return r2.stdout or "", r2.stderr or ""
                except (OSError, subprocess.SubprocessError):
                    continue
        if blob.strip():
            return out, err
        last = (out, err)
    return last


# ---------------------------------------------------------------- 剪贴板
def copy_text(text):
    """尽力复制到剪贴板；失败返回 False。"""
    try:
        import tkinter  # noqa: F401
        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16le"), check=True, timeout=10)
            return True
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=10)
            return True
        for exe in ("wl-copy", "xclip"):
            if shutil.which(exe):
                cmd = [exe] if exe == "wl-copy" else [exe, "-selection", "clipboard"]
                subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=10)
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------- 主流程
def convert(platform, lines, compact=True):
    conv = CONVERTERS[platform]
    out = []
    for line in lines:
        obj = conv(line)
        if compact:
            out.append(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        else:
            out.append(json.dumps(obj, ensure_ascii=False, indent=2))
    return out


def handle_platform(platform, raw_arg, from_stdin, quiet, compact=True):
    """返回该平台转换后的 JSON 字符串列表。"""
    if raw_arg:
        lines = [l.strip() for l in raw_arg.splitlines() if l.strip() and "#" in l]
    elif from_stdin:
        data = sys.stdin.read()
        lines = extract_account_lines(platform, data)
        if not lines:
            # 用户可能直接粘了一行没有 # 的 token
            eprint("[错误] 从标准输入没找到 %s 的账号行（应为 # 分隔的一行）" % platform)
            eprint("       需要的字段: %s" % FIELD_HINT[platform])
            return []
    else:
        out, err = run_switcher(platform)
        if "$wbEncrypted" in out:
            eprint("[错误] WorkBuddy 登录态已被新版客户端加密，switcher 读到的只是密文信封，不是 token。")
            eprint("       可行的取 token 方式：")
            eprint("         1) 用旧版备份的明文登录态：switchers/workbuddy/ 里 restore 一份旧备份，再跑 show")
            eprint("         2) 从客户端请求头抄 Authorization: Bearer <token>，然后：")
            eprint('            python to_wps.py workbuddy "<token>#<uid>#备注"')
            return []
        lines = extract_account_lines(platform, out)
        if not lines:
            eprint("[错误] %s 的 switcher 没有输出可识别的账号行。" % platform)
            detail = (out or err).strip()
            if detail:
                eprint("       switcher 输出如下（前 500 字）：")
                eprint(detail[:500])
            eprint("       若本机没登录过该平台，请先在客户端登录，或用 --stdin 粘贴账号行。")
            return []

    if not quiet:
        eprint("[%s] 识别到 %d 个账号（B 列字段: %s）" % (platform, len(lines), FIELD_HINT[platform]))
    return convert(platform, lines, compact=compact)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把 switchers 的青龙格式账号行转成金山文档表格 B 列的 JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python to_wps.py qoder\n"
               "  python to_wps.py all --tsv --clip\n"
               "  echo 'uid#2#guid#rt#备注' | python to_wps.py ima --stdin\n")
    ap.add_argument("platform", help="ima / workbuddy / qoder / traework，或 all")
    ap.add_argument("account", nargs="?", help="直接给账号行（# 分隔）；不给则自动跑 switcher")
    ap.add_argument("--stdin", action="store_true", help="从标准输入读账号行")
    ap.add_argument("--tsv", action="store_true", help="输出「平台<TAB>JSON」，便于整表粘贴")
    ap.add_argument("--clip", action="store_true", help="结果复制到剪贴板")
    ap.add_argument("--pretty", action="store_true", help="JSON 带缩进（更好看但更长）")
    ap.add_argument("--quiet", action="store_true", help="不打印提示")
    args = ap.parse_args(argv)

    key = args.platform.strip().lower()
    targets = list(PLATFORMS) if key == "all" else [key]
    for p in targets:
        if p not in PLATFORMS:
            eprint("[错误] 未知平台: %s（可选: %s / all）" % (p, " ".join(PLATFORMS)))
            return 2

    if len(targets) > 1 and (args.account or args.stdin):
        eprint("[错误] --stdin / 直接给账号行只能配合单个平台使用")
        return 2

    if args.pretty and args.tsv:
        eprint("[提示] --pretty 会让 JSON 变成多行，--tsv 的整表粘贴就失效了；建议二选一。")

    rows = []          # (platform, json_text)
    for p in targets:
        jsons = handle_platform(p, args.account, args.stdin, args.quiet,
                                compact=not args.pretty)
        for j in jsons:
            rows.append((p, j))

    if not rows:
        eprint("没有可输出的内容。")
        return 1

    if args.tsv:
        text = "\n".join("%s\t%s" % (p, j) for p, j in rows)
    else:
        text = "\n".join(j for _, j in rows)

    print(text)

    if args.clip:
        if copy_text(text):
            eprint("已复制到剪贴板。" + ("（TSV 格式，粘到表格 A 列一格即可填满多行）" if args.tsv else ""))
        else:
            eprint("复制到剪贴板失败，请手动复制上面的输出。")

    if args.tsv and not args.quiet:
        eprint("粘贴方法: 在表格里点 A 列第一个空行（如 A6），Ctrl+V，平台与 JSON 会自动分到 A/B 两列。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

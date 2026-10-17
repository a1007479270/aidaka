#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ima (ima.copilot 腾讯AI工作台) 「每日登录福利」自动签到 - daily-checkin 项目平台模块
纯标准库实现，零第三方依赖。

两种用法:
  1) 青龙面板: 把本文件单独上传到青龙即可运行(单文件自包含, 无跨文件依赖)
  2) 统一入口: 在仓库根目录运行  python checkin.py ima [--dry-run] [--debug]

【环境变量】
  IMA  格式: ima_uid#uid_type#ima_guid#refresh_token#备注
       多账号用换行(\n)隔开，例如:
         10001#1#GUID-AAA#rt_xxx#主号
         10002#1#GUID-BBB#rt_yyy#小号

  也可用 IMA_CRED_FILE 指定一个 credentials.json（单账号本地模式），
  格式同 ima-qiandao 项目的 {"ima_uid","uid_type","ima_guid","refresh_token"}。

【定时规则建议】
  一天 1~2 次即可，例如:  0 9,21 * * *

【取凭证】
  凭证藏在 ima 客户端本地加密存储里，Windows 上用本项目配套的
  switchers/ima/switch_auth.py 提取（先完全退出 ima 再运行）：
      python switchers/ima/switch_auth.py extract
  产物 credentials.json 内容即为 ima_uid/uid_type/ima_guid/refresh_token。

【说明】
  - access_token 仅 2 小时有效，脚本每次先用 refresh_token 换新，无需手动维护。
  - refresh_token 失效（接口报未登录）时需重新扫码登录 ima 并重新提取。
  - 满签奖励（连签 7 天）会自动顺带领取。
  - 接口与签名算法参考自公开项目 LeapYa/ima-qiandao，已实测可用。
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime

# ---- 配置 ----
BASE_URL = "https://ima.qq.com"
REFRESH_URL = BASE_URL + "/cgi-bin/auth_login/refresh"
ACTIVITY_INFO_URL = BASE_URL + "/cgi-bin/daily_login_activity/get_activity_info"
CHECK_IN_URL = BASE_URL + "/cgi-bin/daily_login_activity/check_in"

# 与 ima 内置浏览器一致的固定请求头（服务端不严格校验具体值）
FROM_BROWSER_IMA = "1"
EXTENSION_VERSION = "5.17.2"

CHECKIN_TYPE_DAILY = 1
CHECKIN_TYPE_WEEKLY_BONUS = 2

STATUS_CLAIMED = 2      # 已领取
STATUS_AVAILABLE = 3    # 可领取
STATUS_TEXT = {0: "未知", 1: "已过期", 2: "已领取", 3: "可领取", 4: "未解锁"}

PLATFORM = {
    "key": "ima",
    "title": "ima (腾讯 AI 工作台)",
    "env": "IMA",
    "env_format": "ima_uid#uid_type#ima_guid#refresh_token#备注",
    "switcher": "switchers/ima/switch_auth.py",
}


# ---- 签名 ----
def _to_int32(value):
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def bkn(token):
    """复刻 ima 页面 JS 的 djb2 签名算法，输出 x-ima-bkn 头。"""
    result = 5381
    for ch in token:
        result += _to_int32(_to_int32(result) << 5) + ord(ch)
    return _to_int32(result) & 0x7FFFFFFF


# ---- HTTP ----
def http_post_json(url, body, headers, timeout=20):
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            raise RuntimeError("HTTP %s: %s" % (exc.code, raw[:200])) from None
    except urllib.error.URLError as exc:
        raise RuntimeError("网络错误: %s" % exc.reason) from None


def build_cookie(acc, token):
    parts = [
        "IMA-UID=%s" % acc["ima_uid"],
        "IMA-TOKEN=%s" % token,
        "IMA-REFRESH-TOKEN=%s" % acc["refresh_token"],
        "UID-TYPE=%s" % acc["uid_type"],
        "IMA-GUID=%s" % acc["ima_guid"],
        "PLATFORM=H5",
    ]
    return "; ".join(parts)


def auth_headers(acc, token=None):
    headers = {
        "Content-Type": "application/json",
        "from_browser_ima": FROM_BROWSER_IMA,
        "extension_version": EXTENSION_VERSION,
        "x-ima-cookie": build_cookie(acc, token or acc["refresh_token"]),
    }
    if token:
        headers["x-ima-bkn"] = str(bkn(token))
    return headers


# ---- 业务 ----
def refresh_access_token(acc):
    """用长期 refresh_token 换 2 小时有效的 access token。"""
    device_cookie = "IMA-GUID=%s; PLATFORM=H5" % acc["ima_guid"]
    body = {
        "userId": acc["ima_uid"],
        "refreshToken": acc["refresh_token"],
        "tokenType": -1,
    }
    headers = {
        "Content-Type": "application/json",
        "from_browser_ima": FROM_BROWSER_IMA,
        "extension_version": EXTENSION_VERSION,
        "x-ima-cookie": device_cookie,
    }
    data = http_post_json(REFRESH_URL, body, headers)
    token = data.get("token")
    if data.get("code") != 0 or not token:
        raise RuntimeError(
            "刷新登录失败 code=%s msg=%s (refresh_token 可能已失效，"
            "需重新扫码登录 ima 并重新提取凭证)"
            % (data.get("code"), data.get("msg"))
        )
    return token


def get_activity_info(acc, token):
    return http_post_json(ACTIVITY_INFO_URL, {}, auth_headers(acc, token))


def check_in(acc, token, checkin_type):
    return http_post_json(
        CHECK_IN_URL, {"type": checkin_type}, auth_headers(acc, token)
    )


def find_item(info, top):
    for item in info.get("infos") or []:
        if item.get("top") == top:
            return item
    return None


def week_summary(info):
    cells = []
    for item in info.get("infos") or []:
        top = item.get("top") or "?"
        status = item.get("status")
        mark = STATUS_TEXT.get(status, "?")
        cells.append("%s:%s" % (top, mark))
    return "  ".join(cells)


def parse_accounts(raw):
    """解析 IMA 环境变量为多账号列表。
    每一行: ima_uid#uid_type#ima_guid#refresh_token#备注
    """
    accounts = []
    if not raw:
        return accounts
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("#")
        if len(parts) < 4:
            print("[跳过] 环境变量行格式不对(需至少4段): %s..." % line[:40])
            continue
        accounts.append({
            "ima_uid": parts[0].strip(),
            "uid_type": parts[1].strip() or "1",
            "ima_guid": parts[2].strip(),
            "refresh_token": parts[3].strip(),
            "remark": (parts[4].strip() if len(parts) > 4 else "") or "账号%d" % (len(accounts) + 1),
        })
    return accounts


def load_file_account():
    """单账号本地模式：从 credentials.json 读取。"""
    path = os.environ.get("IMA_CRED_FILE") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "credentials.json"
    )
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fp:
            cred = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        print("[警告] 读取 %s 失败: %s" % (path, exc))
        return None
    if not cred.get("refresh_token"):
        return None
    cred.setdefault("ima_uid", "")
    cred.setdefault("uid_type", "1")
    cred.setdefault("ima_guid", "")
    cred["remark"] = "credentials.json"
    return cred


def checkin_one(acc, dry_run=False, debug=False):
    """对单个账号执行签到，返回结果 dict。dry_run=True 时只探测不领取。"""
    remark = acc["remark"]
    result = {"remark": remark, "ima_uid": acc["ima_uid"], "status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    try:
        token = refresh_access_token(acc)
    except RuntimeError as exc:
        result.update(status="error", action="refresh_failed", msg=str(exc))
        return result

    try:
        info = get_activity_info(acc, token)
        if debug:
            print("[DEBUG][%s] activity_info: %s" % (remark, json.dumps(info, ensure_ascii=False)[:500]))
    except RuntimeError as exc:
        result.update(status="error", action="query_failed", msg=str(exc))
        return result

    if info.get("code") != 0:
        result.update(status="error", action="query_failed",
                      msg="查询活动失败 code=%s msg=%s" % (info.get("code"), info.get("msg")))
        return result

    today = find_item(info, "今日")
    if today is None:
        result.update(status="error", action="structure_changed",
                      msg="未找到今日条目，活动可能已改版。原始响应: %s" % json.dumps(info, ensure_ascii=False)[:300])
        return result

    result["checkin_days"] = info.get("checkin_days")
    result["total_reward_points"] = info.get("total_reward_points")

    status = today.get("status")
    if status == STATUS_AVAILABLE:
        if dry_run:
            result.update(action="dry_run", msg="今天可签到 (dry-run, 未执行)")
        else:
            resp = check_in(acc, token, CHECKIN_TYPE_DAILY)
            if resp.get("code") == 0:
                result.update(action="clicked",
                              points=resp.get("rewardReceived") or today.get("reward"),
                              msg="签到成功")
            else:
                text = json.dumps(resp, ensure_ascii=False)
                if "已签到" in text or "请明天" in text:
                    result.update(action="skip_already_signed", msg="今天已签到")
                else:
                    result.update(status="error", action="checkin_failed",
                                  msg="code=%s msg=%s" % (resp.get("code"), resp.get("msg")))
    elif status == STATUS_CLAIMED:
        result.update(action="skip_already_signed", msg="今天已签到")
    else:
        result.update(action="not_available", msg="今天不可签到 (status=%s %s)" % (status, STATUS_TEXT.get(status)))

    # 满签奖励：连签 7 天时可领，自动顺带领取
    bonus = find_item(info, "满签奖励")
    if (bonus is not None and bonus.get("status") == STATUS_AVAILABLE and not dry_run):
        resp = check_in(acc, token, CHECKIN_TYPE_WEEKLY_BONUS)
        result["weekly_bonus_claimed"] = resp.get("code") == 0
        if result["weekly_bonus_claimed"]:
            result["msg"] = (result.get("msg") or "") + "；满签奖励已领取"

    # 签到后刷新一次累计数据
    if result.get("action") == "clicked":
        try:
            info = get_activity_info(acc, token)
            result["total_reward_points"] = info.get("total_reward_points")
            result["checkin_days"] = info.get("checkin_days")
        except RuntimeError:
            pass

    return result


def run(dry_run=False, debug=False):
    """对 IMA 环境变量（或 credentials.json）中的所有账号执行签到。

    返回退出码：全部正常 0，存在失败 1。dry_run=True 时只探测不实际领取。
    """
    accounts = parse_accounts(os.environ.get("IMA", ""))
    if not accounts:
        acc = load_file_account()
        if acc:
            accounts = [acc]
    if not accounts:
        print(
            "[错误] 未配置账号。\n"
            "青龙: 环境变量 IMA, 每行格式 ima_uid#uid_type#ima_guid#refresh_token#备注\n"
            "本地: 用 switchers/ima/switch_auth.py extract 生成 credentials.json"
        )
        return 1

    results = []
    for acc in accounts:
        res = checkin_one(acc, dry_run=dry_run, debug=debug)
        results.append(res)
        print(json.dumps(res, ensure_ascii=False))

    # 汇总
    ok = [r for r in results if r.get("status") == "ok"]
    err = [r for r in results if r.get("status") == "error"]
    print("[汇总] 共 %d 账号: 成功/跳过 %d, 失败 %d" % (len(results), len(ok), len(err)))
    return 1 if err else 0


def main(argv=None):
    """命令行入口: python ima.py [--dry-run] [--debug]"""
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in args
    debug = "--debug" in args or os.environ.get("IMA_DEBUG") == "1"
    return run(dry_run=dry_run, debug=debug)


if __name__ == "__main__":
    sys.exit(main())

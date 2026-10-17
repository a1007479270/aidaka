#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy (腾讯 codebuddy) 每日积分签到 - daily-checkin 项目平台模块
纯标准库实现，零第三方依赖。

两种用法:
  1) 青龙面板: 把本文件单独上传到青龙即可运行(单文件自包含, 无跨文件依赖)
  2) 统一入口: 在仓库根目录运行  python checkin.py workbuddy [--dry-run] [--debug]

【环境变量】
  WORKBUDDY  格式: ACCESS_TOKEN#UID#备注
             多账号用换行(\n)隔开，例如:
               tok1#uid1#账号A
               tok2#uid2#账号B

【定时规则建议】
  一天 1~2 次即可，例如:  0 9,21 * * *

【说明】
  - ACCESS_TOKEN / UID 取自本机文件(登录后明文):
      Windows: %LOCALAPPDATA%/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info
      里面的 auth.accessToken 与 account.uid
  - token 约 60 天过期，过期需重新取新值更新环境变量
  - 签到接口域名必须用 www.codebuddy.cn (带 /v2/)，copilot.tencent.com 会 404
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error

# ---- 配置 ----
BASE = "https://www.codebuddy.cn"
CHECKIN_STATUS_URL = BASE + "/v2/billing/meter/checkin-status"
DAILY_CHECKIN_URL = BASE + "/v2/billing/meter/daily-checkin"

PLATFORM = {
    "key": "workbuddy",
    "title": "WorkBuddy (腾讯 CodeBuddy)",
    "env": "WORKBUDDY",
    "env_format": "ACCESS_TOKEN#UID#备注",
    "switcher": "switchers/workbuddy/switch_auth.py",
}

# 请求头：带 token 与基础 UA。WorkBuddy 桌面端签到接口依赖登录态，
# 这里用 Bearer token + 常规头；若后端要求 cookie，可改下方 build_headers。
def build_headers(token: str) -> dict:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WorkBuddyCheckin/1.0",
        "Accept": "application/json, text/plain, */*",
        "Origin": BASE,
        "Referer": BASE + "/",
    }


def http_post(url: str, token: str, payload: dict = None) -> dict:
    """发送 POST 请求，返回解析后的 JSON；失败抛出异常。"""
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=build_headers(token), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code}: {body[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def parse_accounts(raw: str) -> list:
    """解析 WORKBUDDY 环境变量为多账号列表。
    每一行: ACCESS_TOKEN#UID#备注
    """
    accounts = []
    if not raw:
        return accounts
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("#")
        token = parts[0].strip()
        uid = parts[1].strip() if len(parts) > 1 else ""
        remark = parts[2].strip() if len(parts) > 2 else (uid or "未命名")
        if not token:
            continue
        accounts.append({"token": token, "uid": uid, "remark": remark})
    return accounts


def checkin_one(acc: dict, dry_run: bool = False, debug: bool = False) -> dict:
    """对单个账号执行签到，返回结果 dict。dry_run=True 时只查询状态不签到。"""
    remark = acc["remark"]
    token = acc["token"]
    result = {"remark": remark, "uid": acc["uid"], "status": "ok"}

    if "YOUR_ACCESS_TOKEN" in token:
        result.update(status="error", action="no_account",
                      msg="仍是脱敏占位值，请设 WORKBUDDY 环境变量"
                          "（本机可跑 switchers/workbuddy/switch_auth.py show 取 token 行）")
        return result

    # 说明：状态查询接口(checkin-status)的 today_checked_in 字段在实测中
    # 并不可靠(活动 active=false 时恒为 false，但实际当日已签)，因此
    # 不依赖它做"跳过"决策，改为【直接调签到接口 + 用响应判定】，更稳。
    # 下面仍可选地拉一次状态接口仅作 DEBUG 参考。
    if debug or os.environ.get("WB_DEBUG") == "1":
        try:
            status_resp = http_post(CHECKIN_STATUS_URL, token)
            print(f"[DEBUG][{remark}] checkin-status 原始响应: "
                  f"{json.dumps(status_resp, ensure_ascii=False)}")
        except RuntimeError as e:
            print(f"[DEBUG][{remark}] checkin-status 查询失败(忽略): {e}")

    if dry_run:
        result.update(status="ok", action="dry_run", msg="dry-run 模式，未执行签到")
        return result

    # 直接执行签到
    try:
        ck_resp = http_post(DAILY_CHECKIN_URL, token)
    except RuntimeError as e:
        em = str(e)
        # 业务正常的"今天已签到"走 400，但不算异常
        if "已签到" in em or "请明天" in em or "already" in em.lower() \
                or "明天再来" in em:
            result.update(status="ok", action="skip_already_signed",
                          msg="今天已签到")
        else:
            result.update(status="error", action="checkin_failed", msg=em)
        return result

    if isinstance(ck_resp, dict):
        # 兼容后端结构: {"code":0,"msg":"OK","data":{"credit":100,"streak_days":4,...}}
        code = ck_resp.get("code")
        data = ck_resp.get("data") or {}
        text = json.dumps(ck_resp, ensure_ascii=False)
        msg = ck_resp.get("msg") or ""

        # 已是今日已签 (接口通常返回 code!=0 或文案含"已签到/明天再来")
        if ("已签到" in text or "明天再来" in text or
                "already" in text.lower() or "请明天" in text):
            result.update(action="skip_already_signed", msg=msg or "今天已签到")
        elif code == 0 or msg.upper() in ("OK", "SUCCESS") or "成功" in msg:
            # 领取成功：优先从 data.credit / points 取积分
            points = (data.get("credit") if isinstance(data, dict) else None) \
                or ck_resp.get("points") or ck_resp.get("point") or ck_resp.get("reward")
            streak = data.get("streak_days") if isinstance(data, dict) else None
            result.update(action="clicked",
                          points=points,
                          streak_days=streak,
                          msg=msg or "领取成功")
        else:
            # 其它情况：如实记录原始响应
            result.update(action="unknown", msg=text[:300])
    else:
        result.update(action="unknown", msg=str(ck_resp)[:300])

    return result


# 占位默认账号：未配置 WORKBUDDY 环境变量时回退到此值并报错提示。
# 请用 switchers/workbuddy/switch_auth.py show 生成真实 token 行写入环境变量
# （切勿把真实 token 提交到公开仓库）。格式: ACCESS_TOKEN#UID#备注
DEFAULT_ACCOUNT = "YOUR_ACCESS_TOKEN_HERE#YOUR_UID_HERE#主号(本机)"


def run(dry_run: bool = False, debug: bool = False) -> int:
    """执行签到，返回退出码。dry_run=True 时只查询状态不实际签到。"""
    raw = os.environ.get("WORKBUDDY", "").strip()
    if not raw:
        # 青龙未配置环境变量时，回退到占位默认账号（会触发 no_account 提示）
        raw = DEFAULT_ACCOUNT
    accounts = parse_accounts(raw)

    if not accounts:
        print(json.dumps({
            "status": "error",
            "action": "no_account",
            "msg": "未读取到 WORKBUDDY 环境变量，请按 ACCESS_TOKEN#UID#备注 格式配置（多账号换行）"
        }, ensure_ascii=False))
        return 1

    print(f"=== WorkBuddy 签到开始，共 {len(accounts)} 个账号 ===")
    results = []
    for acc in accounts:
        try:
            r = checkin_one(acc, dry_run=dry_run, debug=debug)
        except Exception as e:  # 单个账号异常不影响其他账号
            r = {"remark": acc["remark"], "uid": acc["uid"],
                 "status": "error", "action": "exception", "msg": str(e)}
        results.append(r)
        # 输出单行 JSON，方便青龙日志查看与通知解析
        print(json.dumps(r, ensure_ascii=False))
        time.sleep(1.5)  # 账号间稍作间隔，降低风控

    # 汇总
    ok = sum(1 for r in results if r.get("status") == "ok")
    err = sum(1 for r in results if r.get("status") == "error")
    print(f"=== 完成: 成功/已签 {ok} 个, 异常 {err} 个 ===")
    return 1 if err else 0


def main(argv=None) -> int:
    """命令行入口: python workbuddy.py [--dry-run] [--debug]"""
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in args
    debug = "--debug" in args or os.environ.get("WB_DEBUG") == "1"
    return run(dry_run=dry_run, debug=debug)


if __name__ == "__main__":
    sys.exit(main())

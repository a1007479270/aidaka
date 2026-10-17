#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 成长计划 - 额外奖励自动领取 (aidaka 附属脚本, 青龙 / 本地通用)
========================================================================
背景:
  桌面端"成长计划"会跳转到网页版 www.workbuddy.cn/profile/plans-usage,
  页面里有很多可领取奖励(连续签到奖励、任务积分、成长礼包等)。
  本脚本复用同一账号的登录态(桌面端 accessToken 或 网页 session Cookie),
  拉取可领奖励并自动领取。

登录态来源(二选一, 优先级: 环境变量 > 内置默认):
  1) WORKBUDDY  (桌面端)  格式: ACCESS_TOKEN#UID#备注   (Bearer 鉴权)
  2) WORKBUDDY_COOKIE (网页端) 格式: session=xxx; session_2=yyy   (Cookie 鉴权)

重要:
  - 网页端和桌面端是同一账号体系(workbuddy.cn / codebuddy.cn 同号),
    所以两种登录态都能领同一个号的奖励。
  - 领取接口需要你从浏览器"点领取"时抓到的真实请求补全 REWARDS 列表,
    脚本已预留位置, 未配置时只做"探测"(列出可领奖励)不误领。

环境变量:
  WORKBUDDY          桌面端 token, 多账号换行 (ACCESS_TOKEN#UID#备注)
  WORKBUDDY_COOKIE   网页端 session Cookie (单账号/同号)
  WB_DRYRUN         设为 1 时只探测可领奖励、不实际领取(默认开启安全)
  WB_DEBUG          设为 1 时打印原始请求/响应
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from urllib.parse import urljoin

BASE = "https://www.workbuddy.cn"
API_BASE = "https://www.codebuddy.cn"

# 成长计划相关接口 (部分来自实测, 领取接口需按浏览器真实请求补全)
PLANS_PAGE_URL = BASE + "/profile/plans-usage"
# 常见的奖励/签到查询与领取接口(路径按实测调整)
REWARD_STATUS_URL = API_BASE + "/v2/billing/meter/checkin-activity-status"
# TODO: 领取接口 —— 把下面的占位替换成你从浏览器"点领取"抓到的真实请求
# 每条奖励: { "name": 名称, "url": 领取POST地址, "payload": 请求体(dict) }
REWARDS = [
    # 示例(请替换):
    # {
    #     "name": "连续签到7天奖励",
    #     "url": API_BASE + "/v2/billing/meter/claim-reward",
    #     "payload": {"rewardId": "streak_7", "type": "checkin"},
    # },
]


# ---------- HTTP ----------
def build_headers(token=None, cookie=None) -> dict:
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": BASE,
        "Referer": BASE + "/",
    }
    if token:
        h["Authorization"] = "Bearer " + token
        h["Content-Type"] = "application/json"
    elif cookie:
        h["Cookie"] = cookie
        h["Content-Type"] = "application/json"
    return h


def http_post(url: str, token=None, cookie=None, payload: dict = None) -> dict:
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers=build_headers(token, cookie), method="POST")
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


def http_get(url: str, token=None, cookie=None) -> dict:
    req = urllib.request.Request(url, headers=build_headers(token, cookie), method="GET")
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
        return {"raw": body[:500]}


# ---------- 账号解析 ----------
def load_account() -> dict:
    """返回 {'token':.., 'cookie':.., 'remark':..} 优先 WORKBUDDY(Bearer)"""
    raw = os.environ.get("WORKBUDDY", "").strip()
    if raw:
        line = raw.splitlines()[0].strip()
        parts = line.split("#")
        return {"token": parts[0].strip(),
                "cookie": None,
                "remark": parts[2].strip() if len(parts) > 2 else (parts[1].strip() if len(parts) > 1 else "主号")}
    cookie = os.environ.get("WORKBUDDY_COOKIE", "").strip()
    if cookie:
        return {"token": None, "cookie": cookie, "remark": "主号(网页Cookie)"}
    # 开源版不内置任何凭据：未配置登录态时返回 None，由 main() 负责提示
    return None
    return {"token": default_token, "cookie": None, "remark": "主号(内置默认)"}


# ---------- 核心 ----------
def probe_rewards(acc: dict) -> list:
    """探测成长计划可领奖励。先尝试状态接口, 失败则回退抓页面。"""
    out = []
    try:
        resp = http_post(REWARD_STATUS_URL, acc["token"], acc["cookie"])
        if os.environ.get("WB_DEBUG") == "1":
            print(f"[DEBUG] 状态接口响应: {json.dumps(resp, ensure_ascii=False)[:600]}")
        # 尝试从 data 里找可领奖励字段(各版本不同, 兼容常见命名)
        data = resp.get("data") if isinstance(resp, dict) else None
        if isinstance(data, dict):
            for key in ("rewards", "tasks", "claimable", "activities"):
                v = data.get(key)
                if isinstance(v, list) and v:
                    out.append({"source": "status_api", "items": v})
    except RuntimeError as e:
        print(f"[探测] 状态接口失败(忽略): {e}")
    return out


def claim_one(acc: dict, reward: dict) -> dict:
    dry = os.environ.get("WB_DRYRUN", "1") == "1"
    name = reward.get("name", "未命名奖励")
    if dry:
        return {"name": name, "action": "dryrun", "msg": "探测模式, 未实际领取"}
    try:
        resp = http_post(reward["url"], acc["token"], acc["cookie"], reward.get("payload"))
    except RuntimeError as e:
        return {"name": name, "action": "claim_failed", "msg": str(e)}
    text = json.dumps(resp, ensure_ascii=False)
    if "成功" in text or resp.get("code") == 0 or "ok" in text.lower():
        return {"name": name, "action": "claimed", "msg": resp.get("msg") or "领取成功",
                "raw": text[:200]}
    if "已领取" in text or "已经" in text or "明天" in text:
        return {"name": name, "action": "already_claimed", "msg": "已领取"}
    return {"name": name, "action": "unknown", "msg": text[:200]}


def main() -> int:
    acc = load_account()
    if not acc:
        print("[错误] 未配置登录态。请设置环境变量：")
        print("  WORKBUDDY=ACCESS_TOKEN#UID#备注   （桌面端 token，switchers/workbuddy/switch_auth.py show 可取）")
        print("  或 WORKBUDDY_COOKIE=session=xxx   （网页端 Cookie）")
        return 1
    print(f"=== 成长计划奖励领取 开始 [{acc['remark']}] ===")
    print(f"鉴权方式: {'Bearer token' if acc['token'] else 'Cookie'}")
    dry = os.environ.get("WB_DRYRUN", "1") == "1"
    print(f"模式: {'探测(不领取)' if dry else '实际领取'}")

    # 1) 探测可领奖励
    probed = probe_rewards(acc)
    if probed:
        for p in probed:
            print(f"[探测] 来源={p['source']} 奖励数={len(p['items'])}")
            for it in p["items"][:10]:
                print("  -", json.dumps(it, ensure_ascii=False)[:200])
    else:
        print("[探测] 状态接口未返回可解析的奖励列表(可能需直接抓页面/配置 REWARDS)")

    # 2) 领取(仅当 REWARDS 已配置且非 dry 模式)
    if not REWARDS:
        print("[提示] REWARDS 列表为空 -> 请在脚本中按浏览器真实'领取'请求补全后, "
              "设 WB_DRYRUN=0 才会实际领取。")
    else:
        for r in REWARDS:
            res = claim_one(acc, r)
            print(json.dumps(res, ensure_ascii=False))
            time.sleep(1.2)

    print("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

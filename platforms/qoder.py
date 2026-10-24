#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qoder (Qoder CN) 每日领取 Credits - aidaka 项目平台模块
纯标准库实现，零第三方依赖；青龙上传单文件即可跑，本机也能直接跑。
统一入口: 在仓库根目录运行  python checkin.py qoder [--dry-run] [--debug]

【环境变量】
  QODER  格式: ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON
         第 3~5 段可省略（省略时备注=uid，设备段必须提供，否则服务端不下发活动）
         多账号用换行(\n)隔开，例如:
           dt-xxxx#drt-xxxx#019f...#主号#{"machineToken":"P1gA...","machineType":"92...","machineCode":"04fd...","machineId":"a50a...","machineHostname":"AMD","machineOS":"Windows","version":"0.4.8","clientType":"10"}
           dt-yyyy#drt-yyyy#小号
  设备JSON 与整行 JSON 都可以由本机 `python switch_qoder_auth.py show` 直接生成，复制即用。

  QODER_ACCOUNTS_FILE  也可指向 JSON 文件（{"accounts":[{...}]}），优先级低于 QODER
  QODER_BASE           接口域名，默认 CN: https://openapi.qoder.com.cn；国际版 https://openapi.qoder.sh
  QD_DRYRUN            设为 1 时只列出活动，不实际领取
  QD_DEBUG             设为 1 时打印活动接口原始响应
  QD_STATE_FILE        设为可写路径时，token 轮换结果写回该文件，减少重新取号次数

【取 token（每个账号做一次，在登录过 Qoder 桌面端的 Windows 上）】
  python switch_qoder_auth.py show     # 直接输出上面格式的 QODER 行

【定时规则建议】
  新一轮每天 10:00(UTC+8) 开放，窗口 10:00~次日 10:00，错过不补；
  一天 1~2 次即可，例如:  5 10,21 * * *

【说明】
  - 活动接口必须带 Cosy-* 设备头，不带时返回 200 但 campaigns 为空数组，看起来像"没有活动"。
  - 领取接口幂等：已领过再调返回 status=CLAIMED, replayed=true，不会重复发奖，因此可放心一天多次跑。
  - token 约 30 天过期、refreshToken 约 1 年；脚本会自动刷新，若刷新也失败(401)则需回 Windows 重新取号。
"""

import os
import sys
import json
import time
import ssl
import calendar
import random
import urllib.request
import urllib.error
import io

BASE = os.environ.get("QODER_BASE", "https://openapi.qoder.com.cn").rstrip("/")
CAMPAIGNS_PATH = "/sash/api/v1/me/campaigns"
CLAIM_PATH = "/sash/api/v1/me/campaigns/%s/claim"
REFRESH_PATH = "/api/v1/deviceToken/refresh"
UA = os.environ.get("QD_UA", "Qoder/claim")
TIMEOUT = int(os.environ.get("QD_TIMEOUT", "25"))

# 判定「待领取」的状态；CLAIMED 一律跳过（接口本身也幂等）
UNCLAIMED = {"UNCLAIMED", "NOT_CLAIMED", "PENDING", "AVAILABLE", "CLAIMABLE"}
COSY = {
    "clientType": "Cosy-ClientType",
    "machineOS": "Cosy-MachineOS",
    "machineHostname": "Cosy-MachineHostname",
    "machineId": "Cosy-MachineId",
    "machineToken": "Cosy-MachineToken",
    "machineCode": "Cosy-MachineCode",
    "machineType": "Cosy-MachineType",
    "version": "Cosy-Version",
}

# 本机默认账号（本地一键验证用）。青龙部署时请设 QODER 环境变量覆盖，
# 脚本优先使用环境变量，环境变量为空才依次回退到 QODER_ACCOUNTS_FILE / 此处默认值。
# 凭据已脱敏，请由 `python switchers/qoder/switch_auth.py show` 生成后填入，切勿提交真实 token 到仓库。
DEFAULT_ACCOUNT = "YOUR_ACCESS_TOKEN_HERE#YOUR_REFRESH_TOKEN_HERE#YOUR_UID#主号(本机)#"

PLATFORM = {
    "key": "qoder",
    "title": "Qoder (CN 个人版)",
    "env": "QODER",
    "env_format": "ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON",
    "switcher": "switchers/qoder/switch_auth.py",
}


def log(msg):
    print(msg, flush=True)


# ---------- HTTP ----------
def build_headers(acc, token=None):
    """Qoder 活动接口鉴权用 Bearer，设备标识用 Cosy-* 头，二者缺一不可。"""
    h = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA,
    }
    device = acc.get("device") or {}
    for key, header in COSY.items():
        value = device.get(key)
        if value not in (None, ""):
            h[header] = str(value)
    h.setdefault("Cosy-ClientType", str(os.environ.get("QD_CLIENT_TYPE", "10")))
    if token:
        h["Authorization"] = "Bearer " + token
    return h


def http(method, url, headers, payload=None, retries=3):
    """返回 (status, dict)。5xx/429 自动重试，网络异常不抛出，单个账号失败不影响其他账号。"""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    ctx = ssl.create_default_context()
    last = (0, {"error": "未发起请求"})
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                body = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(body) if body.strip() else {})
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body) if body.strip() else {"raw": body[:300]}
            except json.JSONDecodeError:
                parsed = {"raw": body[:300]}
            last = (e.code, parsed)
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return last
        except Exception as e:
            last = (0, {"error": "%s: %s" % (type(e).__name__, e)})
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1) + random.random())
    return last


# ---------- 账号解析 ----------
def normalize(acc):
    """补齐字段，返回统一结构；设备段缺失时保留空 dict 由调用方判定。"""
    device = acc.get("device") or {}
    if isinstance(device, str):
        try:
            device = json.loads(device)
        except json.JSONDecodeError:
            device = {}
    out = {
        "token": acc.get("token") or acc.get("accessToken") or "",
        "refreshToken": acc.get("refreshToken") or acc.get("refresh_token") or "",
        "uid": acc.get("uid") or "",
        "remark": acc.get("remark") or acc.get("name") or "",
        "device": device,
        "base": (acc.get("base") or BASE).rstrip("/"),
        "expiresAt": acc.get("expiresAt") or "",
    }
    if not out["remark"]:
        out["remark"] = out["uid"] or "未命名"
    if not out["uid"] and out["token"]:
        out["uid"] = out["remark"]
    return out


def parse_accounts(raw):
    """解析 QODER 环境变量。每行 ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON。
    也接受整行 JSON（switch_qoder_auth.py 导出文件格式），便于两种写法混用。
    """
    accounts = []
    for line in (raw or "").splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            try:
                accounts.append(normalize(json.loads(line)))
            except json.JSONDecodeError:
                log("[警告] 跳过无法解析的 JSON 行: %s…" % line[:40])
            continue
        parts = line.split("#", 4)
        device = {}
        if len(parts) >= 5 and parts[4].strip():
            try:
                device = json.loads(parts[4].strip())
            except json.JSONDecodeError:
                log("[警告] 第 %s 段的设备JSON 不合法，该行仍会尝试但可能查不到活动" % parts[3])
        if not parts[0].strip():
            continue
        accounts.append(normalize({
            "token": parts[0].strip(),
            "refreshToken": parts[1].strip() if len(parts) > 1 else "",
            "uid": parts[2].strip() if len(parts) > 2 else "",
            "remark": parts[3].strip() if len(parts) > 3 else "",
            "device": device,
        }))
    return accounts


def load_accounts():
    raw = os.environ.get("QODER", "").strip()
    if not raw:
        path = os.environ.get("QODER_ACCOUNTS_FILE", "").strip()
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data.get("accounts") if isinstance(data, dict) else data
                return [normalize(a) for a in (items or []) if isinstance(a, dict)], "file"
            except (OSError, json.JSONDecodeError) as e:
                log("[警告] 读取 QODER_ACCOUNTS_FILE 失败: %s" % e)
        raw = DEFAULT_ACCOUNT
    return parse_accounts(raw), "env"


def line_of(acc):
    """把账号还原成 QODER 单行格式，方便复制进青龙环境变量。"""
    device = acc.get("device") or {}
    device_str = json.dumps(device, ensure_ascii=False, separators=(",", ":")) if device else ""
    return "#".join([acc.get("token", ""), acc.get("refreshToken", ""),
                    acc.get("uid", ""), acc.get("remark", ""), device_str])


# ---------- 核心 ----------
def refresh(acc):
    status, data = http("POST", acc["base"] + REFRESH_PATH, build_headers(acc),
                        {"refresh_token": acc.get("refreshToken", "")})
    if status != 200:
        if status == 401:
            return None, "refreshToken 失效(401)，需回 Windows 重新取号"
        return None, "刷新失败 HTTP %s: %s" % (status, json.dumps(data, ensure_ascii=False)[:200])
    token = data.get("token") or data.get("accessToken") or data.get("access_token") or ""
    renewed = data.get("refreshToken") or data.get("refresh_token") or ""
    if not token:
        return None, "刷新响应里没有 token"
    acc["token"] = token
    if renewed:
        acc["refreshToken"] = renewed
    for field in ("expiresAt", "refreshTokenExpiresAt"):
        if data.get(field):
            acc[field] = data[field]
    if debug or os.environ.get("QD_DEBUG") == "1":
        log("[DEBUG] 刷新成功，新 token 前缀 %s…，refreshToken %s" % (token[:8], "已轮换" if renewed else "未变"))
    return token, ""


def near_expiry(acc):
    """expiresAt 是 UTC ISO 字符串，距过期不足 10 分钟就先刷新，避免签到中途失效。"""
    value = acc.get("expiresAt") or ""
    if not value:
        return False
    try:
        return calendar.timegm(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")) - time.time() < 600
    except (ValueError, OverflowError):
        return False


def checkin_one(acc, dry_run=False, debug=False):
    remark = acc["remark"]
    result = {"remark": remark, "uid": acc["uid"], "status": "ok"}

    if "YOUR_ACCESS_TOKEN" in (acc.get("token") or ""):
        result.update(status="error", action="no_account",
                      msg="仍是脱敏默认值，请设 QODER 环境变量（本机可跑 switch_qoder_auth.py show 取）")
        return result
    if not acc.get("device", {}).get("machineToken"):
        result.update(status="error", action="no_device",
                      msg="缺少设备标识(Cosy-MachineToken)，活动接口不会下发活动，请用 switch_qoder_auth.py 重新生成完整行")
        return result

    token = acc["token"]
    if not token or near_expiry(acc):
        token, err = refresh(acc)
        if not token:
            result.update(status="error", action="token_expired", msg=err)
            return result

    dry = dry_run or os.environ.get("QD_DRYRUN") == "1"
    status, data = http("GET", acc["base"] + CAMPAIGNS_PATH, build_headers(acc, token))
    if status == 401:
        token, err = refresh(acc)
        if not token:
            result.update(status="error", action="token_expired", msg=err)
            return result
        status, data = http("GET", acc["base"] + CAMPAIGNS_PATH, build_headers(acc, token))
    if status != 200:
        result.update(status="error", action="campaign_failed",
                      msg="HTTP %s: %s" % (status, json.dumps(data, ensure_ascii=False)[:300]))
        return result
    if debug or os.environ.get("QD_DEBUG") == "1":
        log("[DEBUG][%s] campaigns 原始响应: %s" % (remark, json.dumps(data, ensure_ascii=False)[:600]))

    campaigns = data.get("campaigns") or []
    if not campaigns:
        result.update(action="no_campaign",
                      msg="活动列表为空(showCampaign=%s claimable=%s)：可能未到 10:00 窗口、活动已下线，或设备头与客户端版本不符"
                          % (data.get("showCampaign"), data.get("claimable")))
        return result

    now = time.time()
    pending = []
    for c in campaigns:
        cid = c.get("campaignId") or ""
        if not cid:
            continue
        st = str(c.get("claimStatus") or "").upper()
        if st == "CLAIMED":
            continue
        start, end = c.get("startAt") or 0, c.get("endAt") or 0
        in_window = (not start or now >= start) and (not end or now <= end)
        if st in UNCLAIMED or (in_window and not st):
            pending.append(c)

    if not pending:
        result.update(action="skip_already_claimed",
                      msg="本轮已领: %s" % ", ".join("%s=%s" % (c.get("campaignKey"), c.get("claimStatus")) for c in campaigns))
        return result

    if dry:
        result.update(status="ok", action="dryrun",
                      msg="待领 %d 项: %s" % (len(pending), ", ".join(
                          "%s(%s Credits)" % (c.get("campaignKey"), (c.get("benefit") or {}).get("amount")) for c in pending)))
        return result

    gained, failed, skipped = 0.0, [], []
    for c in pending:
        cid = c["campaignId"]
        key = c.get("campaignKey")
        expect = ((c.get("benefit") or {}).get("amount")) or 0
        st2, d2 = http("POST", (acc["base"] + CLAIM_PATH) % cid, build_headers(acc, token), {})
        if st2 == 401:
            token, _ = refresh(acc)
            if not token:
                failed.append("%s:token失效" % key)
                break
            st2, d2 = http("POST", (acc["base"] + CLAIM_PATH) % cid, build_headers(acc, token), {})
        claim_status = str(d2.get("status") or "").upper()
        if st2 == 200 and claim_status in ("CLAIMED", "REPLAYED", "SUCCESS"):
            if d2.get("replayed"):
                # 服务端认为本轮已领（多机同账号并发时会遇到），属业务正常，不算异常
                skipped.append(key)
                continue
            gained += float(((d2.get("benefit") or {}).get("amount")) or expect or 0)
        else:
            failed.append("%s:HTTP%s%s" % (key, st2, json.dumps(d2, ensure_ascii=False)[:120]))

    if failed:
        result.update(status="error" if not gained else "ok", action="claim_failed",
                      msg="; ".join(failed) + ("（已领 %d Credits）" % gained if gained else ""))
    elif skipped:
        result.update(action="skip_already_claimed", msg="本轮已领: %s" % ", ".join(skipped))
    else:
        result.update(action="clicked", credits=int(gained), msg="领取成功")
    return result


def run(dry_run: bool = False, debug: bool = False) -> int:
    """执行签到，返回退出码。dry_run=True 时只列出活动不领取。"""
    # 只给管道/重定向固定 UTF-8；控制台流由 init_console 接管，
    # 再 reconfigure 会把它改坏（中文变「褰撳墠」）。
    if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    accounts, source = load_accounts()
    if not accounts:
        log(json.dumps({"status": "error", "action": "no_account",
                        "msg": "未读取到 QODER 环境变量，请按 ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON 格式配置（多账号换行）"},
                       ensure_ascii=False))
        return 1

    log("=== Qoder 签到开始，共 %d 个账号（来源:%s 模式:%s）===" % (
        len(accounts), source, "探测不领取" if dry_run else "实际领取"))
    results = []
    for acc in accounts:
        try:
            r = checkin_one(acc, dry_run=dry_run, debug=debug)
        except Exception as e:  # 单个账号异常不影响其他账号
            r = {"remark": acc.get("remark", "未命名"), "uid": acc.get("uid", ""),
                 "status": "error", "action": "exception", "msg": str(e)}
        results.append((acc, r))
        log(json.dumps(r, ensure_ascii=False))
        time.sleep(1.5)

    ok = sum(1 for _, r in results if r.get("status") == "ok")
    err = len(results) - ok
    credits = sum(r.get("credits", 0) for _, r in results)
    log("=== 完成: 正常 %d 个, 异常 %d 个, 本次领取 %d Credits ===" % (ok, err, credits))

    # token 轮换后写回成 QODER 单行格式，复制即可更新青龙环境变量
    state = os.environ.get("QD_STATE_FILE", "").strip()
    if state:
        try:
            tmp = state + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(line_of(a) for a, _ in results) + "\n")
            os.replace(tmp, state)
            try:
                os.chmod(state, 0o600)
            except OSError:
                pass
            log("最新 token 已写入 %s（内容为 QODER 变量格式，含凭据勿外传）" % state)
        except OSError as e:
            log("[警告] 写回 QD_STATE_FILE 失败: %s" % e)
    return 0 if err == 0 else 1


def main(argv=None) -> int:
    """命令行入口: python qoder.py [--dry-run] [--debug]"""
    init_console()
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in args or os.environ.get("QD_DRYRUN") == "1"
    debug = "--debug" in args or os.environ.get("QD_DEBUG") == "1"
    return run(dry_run=dry_run, debug=debug)


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
    sys.exit(main())

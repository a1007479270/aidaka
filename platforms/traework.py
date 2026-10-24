#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TraeWork 每日积分签到 - aidaka 项目平台模块
纯标准库实现，零第三方依赖。

两种用法:
  1) 青龙面板: 把本文件单独上传到青龙即可运行(单文件自包含, 无跨文件依赖)
  2) 统一入口: 在仓库根目录运行  python checkin.py traework [--dry-run] [--debug]

【环境变量】
  TRAEWORK  格式: ACCESS_TOKEN#UID#备注#设备ID
             只有 ACCESS_TOKEN 必填，后三段可省略；多账号换行，例如:
               eyJhbG...#1124000000000001#主号#3000000000000001
               eyJhbG...#1124000000000002#小号

【定时规则建议】
  一天 1~2 次即可，例如:  0 9,21 * * *
  脚本幂等：先查状态，今日已签到会自动跳过，不会重复领取。

【说明】
  - ACCESS_TOKEN / UID / 设备ID 在已登录 TraeWork 的 Windows 电脑上一键获取：
      双击 switchers/traework/switch_auth.bat 选 [2]（或 python switchers/traework/switch_auth.py show）
  - 设备ID 建议带上：缺失时脚本会按 token 派生固定值兜底，
    但服务端可能返回 9004。
  - token 会过期（约两周），过期后重新在桌面端登录、重新取新值更新环境变量。
  - 接口与客户端实现一致：
      POST https://api.trae.cn/trae/api/v2/ug/checkin_credits/status
      POST https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim
      请求体 {"req_source": 2}        # 2 = TraeWork(lite)，TraeCode IDE 为 1
      请求头 Authorization: Cloud-IDE-JWT <token>; x-device-id: <设备ID>
  - 服务端繁忙返回 9074 时自动重试（默认 3 次，间隔 5 秒）。
"""

import os
import sys
import json
import time
import hashlib
import argparse
import urllib.request
import urllib.error
import io

# ---- 配置 ----
BASE = "https://api.trae.cn"
CHECKIN_STATUS_URL = BASE + "/trae/api/v2/ug/checkin_credits/status"
DAILY_CHECKIN_URL = BASE + "/trae/api/v2/ug/checkin_credits/claim"

REQ_SOURCE = 2            # 2 = TraeWork(lite)，1 = TraeCode IDE
RETRYABLE_CODES = {9074}  # 服务端繁忙，稍后重试即可
DEVICE_REQUIRED_CODE = 9004

ENV_NAME = "TRAEWORK"

PLATFORM = {
    "key": "traework",
    "title": "TraeWork (国内个人版)",
    "env": "TRAEWORK",
    "env_format": "ACCESS_TOKEN#UID#备注#设备ID",
    "switcher": "switchers/traework/switch_auth.py",
}


def build_headers(token: str, device_id: str) -> dict:
    return {
        "Authorization": "Cloud-IDE-JWT " + token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TraeWorkCheckin/1.0",
        "X-User-Region": "CN",
        "x-device-id": device_id,
    }


def http_post(url: str, token: str, device_id: str, payload: dict = None,
              timeout: int = 20) -> tuple:
    """发送 POST 请求，返回 (HTTP状态码, 解析后的JSON)。"""
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers=build_headers(token, device_id), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            code = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        code = e.code
    except urllib.error.URLError as e:
        return 0, {"message": f"网络错误: {e.reason}"}
    try:
        return code, json.loads(body)
    except json.JSONDecodeError:
        return code, {"message": body[:300]}


def derive_device_id(token: str) -> str:
    """没有真实设备 ID 时，按 token 派生一个稳定的 16 位数字 ID。"""
    digest = hashlib.sha256(("traework-device:" + token).encode("utf-8")).hexdigest()
    return str(int(digest[:15], 16) % 10**16).zfill(16)


def parse_accounts(raw: str) -> list:
    """解析 TRAEWORK 环境变量为多账号列表。
    每一行: ACCESS_TOKEN#UID#备注#设备ID（后三段可省略）。
    """
    accounts = []
    if not raw:
        return accounts
    for line in raw.replace("&", "\n").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("#")]
        token = parts[0]
        if not token:
            continue
        uid = parts[1] if len(parts) > 1 else ""
        remark = parts[2] if len(parts) > 2 and parts[2] else (uid or "未命名")
        device_id = parts[3] if len(parts) > 3 else ""
        accounts.append({
            "token": token,
            "uid": uid,
            "remark": remark,
            "device_id": device_id or derive_device_id(token),
        })
    return accounts


def checkin_one(acc: dict, debug: bool = False, dry_run: bool = False) -> dict:
    """对单个账号执行签到，返回结果 dict。"""
    remark, token, uid, device_id = (
        acc["remark"], acc["token"], acc["uid"], acc["device_id"]
    )
    result = {"remark": remark, "uid": uid, "status": "error",
              "action": "error", "credits": None, "msg": ""}

    # 1) 先查状态：今日已签直接跳过（脚本因此幂等）
    code, status = http_post(CHECKIN_STATUS_URL, token, device_id,
                             {"req_source": REQ_SOURCE})
    if debug:
        print(f"[DEBUG][{remark}] status <- HTTP {code} "
              f"{json.dumps(status, ensure_ascii=False)}", file=sys.stderr)
    if code != 200 or "checked_in" not in status:
        result["msg"] = (f"查询签到状态失败（HTTP {code}）："
                         f"{status.get('message') or status}")
        return result

    result["credits"] = status.get("credits")
    if status.get("checked_in"):
        result.update(status="ok", action="skip_already_signed", msg="今天已签到")
        return result
    if not status.get("enable", True):
        result.update(status="ok", action="disabled", msg="该账号未开启签到功能")
        return result

    if dry_run:
        result.update(status="ok", action="dry_run", msg="今天可签到 (dry-run, 未执行)")
        return result

    # 2) 领取积分（9074 服务端繁忙自动重试）
    for attempt in range(4):
        code, resp = http_post(DAILY_CHECKIN_URL, token, device_id,
                               {"req_source": REQ_SOURCE})
        if debug:
            print(f"[DEBUG][{remark}] claim <- HTTP {code} "
                  f"{json.dumps(resp, ensure_ascii=False)}", file=sys.stderr)
        if code == 200 and resp.get("code") == 0:
            data = resp.get("data") or {}
            result.update(
                status="ok", action="clicked",
                credits=data.get("credits", result["credits"]),
                msg=resp.get("message") or "签到成功",
            )
            return result
        biz_code = resp.get("code")
        msg = resp.get("message") or json.dumps(resp, ensure_ascii=False)
        if biz_code in RETRYABLE_CODES and attempt < 3:
            time.sleep(5)
            continue
        result["msg"] = f"签到失败（HTTP {code}）：{msg}"
        if biz_code in RETRYABLE_CODES:
            result["msg"] += "（服务端繁忙，已重试多次）"
        if biz_code == DEVICE_REQUIRED_CODE:
            result["msg"] += "；请用 switch_auth.bat 的 [2] 重新获取带设备ID的环境变量"
        return result

    return result


def run(dry_run: bool = False, debug: bool = False) -> int:
    """执行签到，返回退出码。dry_run=True 时只查询状态不实际领取。"""
    raw = os.environ.get(ENV_NAME, "").strip()
    accounts = parse_accounts(raw)

    if not accounts:
        print(json.dumps({
            "status": "error",
            "action": "no_account",
            "msg": ("未读取到 TRAEWORK 环境变量，请按 "
                    "ACCESS_TOKEN#UID#备注#设备ID 格式配置（多账号换行）；"
                    "token 行可用 switchers/traework/switch_auth.py show 一键获取"),
        }, ensure_ascii=False))
        return 1

    print(f"=== TraeWork 签到开始，共 {len(accounts)} 个账号 ===")
    results = []
    for acc in accounts:
        try:
            r = checkin_one(acc, debug=debug, dry_run=dry_run)
        except Exception as e:  # 单个账号异常不影响其他账号
            r = {"remark": acc["remark"], "uid": acc["uid"],
                 "status": "error", "action": "exception",
                 "credits": None, "msg": str(e)}
        results.append(r)
        # 输出单行 JSON，方便青龙日志查看与通知解析
        print(json.dumps(r, ensure_ascii=False))
        time.sleep(1.5)  # 账号间稍作间隔，降低风控

    # 汇总
    ok = sum(1 for r in results if r.get("status") == "ok")
    err = len(results) - ok
    clicked = sum(1 for r in results if r.get("action") == "clicked")
    signed = sum(1 for r in results if r.get("action") == "skip_already_signed")
    print(f"=== 完成: 成功/已签 {ok} 个（本次领取 {clicked}，今日已签 {signed}），"
          f"异常 {err} 个 ===")
    return 0 if err == 0 else 1


def main(argv=None) -> int:
    """命令行入口: python traework.py [--dry-run] [--debug]"""
    init_console()
    parser = argparse.ArgumentParser(description="TraeWork 每日积分签到（aidaka 平台模块）")
    parser.add_argument("--debug", action="store_true",
                        help="打印接口原始响应（也可用环境变量 TRAEWORK_DEBUG=1）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只查询签到状态，不实际领取")
    args = parser.parse_args(argv)
    debug = args.debug or os.environ.get("TRAEWORK_DEBUG") == "1"
    return run(dry_run=args.dry_run, debug=debug)


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

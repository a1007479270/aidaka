#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily-checkin 统一签到入口
==========================
一条命令跑完所有已配置平台的每日签到，也可只跑指定平台。

用法:
    python checkin.py                  # 跑全部平台
    python checkin.py ima qoder        # 只跑指定平台（可多选）
    python checkin.py --list           # 列出所有平台及环境变量
    python checkin.py --dry-run        # 只探测不实际领取（所有平台）
    python checkin.py --debug          # 打印接口原始响应

环境变量（每个平台独立配置，多账号用换行分隔，详见 docs/）:
    ima         ima_uid#uid_type#ima_guid#refresh_token#备注
    workbuddy   ACCESS_TOKEN#UID#备注
    qoder       ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON
    traework    ACCESS_TOKEN#UID#备注#设备ID

青龙部署不需要本文件——把 platforms/ 下对应的单文件上传到青龙即可
（每个平台脚本都是自包含的，详见 docs/qinglong.md）。
"""

import argparse
import importlib.util
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PLATFORMS_DIR = os.path.join(ROOT, "platforms")

# 平台顺序即此列表；新增平台只需在 platforms/ 放一个同名单文件并加进来
PLATFORM_ORDER = ["ima", "workbuddy", "qoder", "traework"]


def load_platform(key):
    """按文件路径加载 platforms/<key>.py，返回模块对象（失败返回 None）。"""
    path = os.path.join(PLATFORMS_DIR, key + ".py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("daily_checkin_platform_%s" % key, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def platform_meta(key):
    mod = load_platform(key)
    meta = dict(getattr(mod, "PLATFORM", None) or {})
    meta.setdefault("key", key)
    meta.setdefault("title", key)
    meta.setdefault("env", key.upper())
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="checkin.py",
        description="daily-checkin 统一签到入口（ima / WorkBuddy / Qoder / TraeWork）",
    )
    parser.add_argument("platforms", nargs="*",
                        help="要签到的平台，缺省为全部；可用: %s" % " ".join(PLATFORM_ORDER))
    parser.add_argument("--list", action="store_true", help="列出所有平台及环境变量")
    parser.add_argument("--dry-run", action="store_true", help="只探测不实际领取")
    parser.add_argument("--debug", action="store_true", help="打印接口原始响应")
    args = parser.parse_args(argv)

    if args.list:
        print("可用平台:")
        for key in PLATFORM_ORDER:
            meta = platform_meta(key)
            print("  %-10s %-26s 环境变量 %-11s 格式 %s" % (
                meta["key"], meta["title"], meta["env"],
                meta.get("env_format", "-")))
        return 0

    keys = args.platforms or list(PLATFORM_ORDER)
    unknown = [k for k in keys if k not in PLATFORM_ORDER]
    if unknown:
        parser.error("未知平台: %s（可用: %s）" % (", ".join(unknown), ", ".join(PLATFORM_ORDER)))

    print("=== daily-checkin 开始: %s ===" % ", ".join(keys))
    results = {}
    for key in keys:
        mod = load_platform(key)
        meta = getattr(mod, "PLATFORM", None) or {}
        print("\n----- [%s] %s -----" % (key, meta.get("title", key)))
        if mod is None or not hasattr(mod, "run"):
            print("[错误] 平台模块加载失败: platforms/%s.py" % key)
            results[key] = 1
            continue
        try:
            rc = mod.run(dry_run=args.dry_run, debug=args.debug)
        except Exception as exc:  # 单平台异常不影响其他平台
            print("[错误] %s 签到抛出异常: %s" % (key, exc))
            rc = 1
        results[key] = int(rc or 0)
        time.sleep(1)

    print("\n=== daily-checkin 汇总 ===")
    for key in keys:
        mark = "OK" if results.get(key, 1) == 0 else "失败"
        print("  %-10s %s" % (key, mark))
    failed = [k for k, rc in results.items() if rc != 0]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

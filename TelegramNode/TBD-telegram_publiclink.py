# -*- coding: utf-8 -*-
"""
文件名: Telegram.Node_xc
脚本说明:
本脚本实现从指定 Telegram 频道自动爬取订阅链接；
下载并解析各种代理订阅节点（包括 vmess, vless, ssr, ss, trojan, hysteria及hysteria2等协议），
支持节点去重、地区识别与重命名，并使用 Clash 核心程序进行节点测速（延迟测试）；
最终生成可用于 Clash 使用的 YAML 配置文件。
主要功能:
1. 从 Telegram 指定频道抓取带有订阅链接的消息，支持时间窗口过滤新消息。
2. 支持多种常见代理协议的节点解析，以及识别节点所在区域。
3. 采用命令行模式调用 clash 核心程序进行节点延迟测试，筛选有效节点。
4. 根据节点地区与延迟自动排序和归类，生成最终配置文件。
5. 环境变量配置灵活，方便集成自动化流程。
"""
import os
import re
import sys
import base64
import json
import yaml
import time
import socket
import hashlib
import asyncio
import shutil
import subprocess
import concurrent.futures
import tempfile
import requests
import socket
from concurrent.futures import as_completed
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# --- 环境变量读取 ---
API_ID = int(os.environ.get('TELEGRAM_API_ID') or 0)
API_HASH = os.environ.get('TELEGRAM_API_HASH')
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS', '')
TIME_WINDOW_HOURS = 4  # 抓取多长时间的消息，单位为小时。
MIN_EXPIRE_HOURS = 2   # 订阅地址剩余时间最小过期，单位为小时。
OUTPUT_FILE = 'flclashyaml/Tg-node1.yaml'  # 输出文件路径，用于保存生成的配置或结果.



# === 新增：测速策略开关（推荐保留这几个选项）===
# 测速模式：
ENABLE_SPEED_TEST = True  # 是否启用整体速度测试功能，True表示启用。测试顺序如下



# 主函数
async def main():
    print("=" * 60)
    print("Telegram.Node_Clash-Speedtest测试版 V1")
    print(datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    preprocess_regex_rules()

    print("[1/5] 加载原有节点和抓取状态")
    existing_proxies, last_message_ids = load_existing_proxies_and_state()
    print(f"已有节点数: {len(existing_proxies)}")

    print("[2/5] 抓取 Telegram 新订阅链接")
    urls, last_message_ids = await scrape_telegram_links(last_message_ids)
    new_proxies = []
    if urls:
        print(f"抓取到 {len(urls)} 个订阅链接，开始下载解析...")
        for url in urls:
            proxies = download_and_parse(url)
            if proxies:
                new_proxies.extend(proxies)
    print(f"新增节点数: {len(new_proxies)}")

    all_proxies_map = {
        get_proxy_key(p): p for p in existing_proxies if is_valid_proxy(p)
    }
    added_count = 0
    for p in new_proxies:
        key = get_proxy_key(p)
        if key not in all_proxies_map:
            all_proxies_map[key] = p
            added_count += 1
    print(f"合并去重后总节点数: {len(all_proxies_map)}，新增有效节点: {added_count}")

    all_nodes = list(all_proxies_map.values())
    if not all_nodes:
        sys.exit("❌ 无任何节点可用，程序退出")
        

    # [3/5] 开始节点测速（支持多种模式）
    print("[3/5] 开始节点测速（模式: %s）" % SPEEDTEST_MODE)
    clash_path = 'clash_core/clash'
    need_clash = 'clash' in SPEEDTEST_MODE
    if need_clash and not (os.path.isfile(clash_path) and os.access(clash_path, os.X_OK)):
        sys.exit(f"clash 核心缺失或不可执行: {clash_path}")

    final_tested_nodes = all_nodes.copy()
    clash_path = './xcspeedtest'  # 你的 speedtest-clash 二进制的路径

    if SPEEDTEST_MODE == "tcp_only":
        print("使用【纯 TCP 测速】模式")
        final_tested_nodes = batch_tcp_test(all_nodes)
    elif SPEEDTEST_MODE == "clash_only":
        print("使用【纯 speedtest-clash 测速】模式")
        final_tested_nodes = batch_test_proxies_speedtest(
            clash_path,
            all_nodes,
            max_workers=MAX_TEST_WORKERS,
            debug=ENABLE_SPEEDTEST_LOG
        )
    elif SPEEDTEST_MODE == "tcp_first":
        print("使用【TCP 粗筛 → speedtest-clash 精测】两阶段模式")
        print("阶段1：TCP 超高并发粗筛...")
        tcp_passed = batch_tcp_test(all_nodes)
        print(f"TCP 粗筛完成：{len(all_nodes)} → {len(tcp_passed)}")
        if not tcp_passed:
            print("TCP 全死，降级使用纯 speedtest-clash 模式")
            final_tested_nodes = batch_test_proxies_speedtest(
                clash_path,
                all_nodes,
                max_workers=MAX_TEST_WORKERS,
                debug=ENABLE_SPEEDTEST_LOG
            )
        else:
            print("阶段2：对 TCP 存活节点进行 speedtest-clash 精准测速...")
            final_tested_nodes = batch_test_proxies_speedtest(
                clash_path,
                tcp_passed,
                max_workers=MAX_TEST_WORKERS,
                debug=ENABLE_SPEEDTEST_LOG
            )
    elif SPEEDTEST_MODE == "clash_first":
        print("使用【speedtest-clash 先测 → TCP 后验】模式")
        clash_passed = batch_test_proxies_speedtest(
            clash_path,
            all_nodes,
            max_workers=MAX_TEST_WORKERS,
            debug=ENABLE_SPEEDTEST_LOG
        )
        final_tested_nodes = [p for p in clash_passed if tcp_ping(p) is not None]
    else:
        print("未知模式，使用默认 tcp_first")
        tcp_passed = batch_tcp_test(all_nodes)
        if not tcp_passed:
            final_tested_nodes = batch_test_proxies_speedtest(
                clash_path,
                all_nodes,
                max_workers=MAX_TEST_WORKERS,
                debug=ENABLE_SPEEDTEST_LOG
            )
        else:
            final_tested_nodes = batch_test_proxies_speedtest(
                clash_path,
                tcp_passed,
                max_workers=MAX_TEST_WORKERS,
                debug=ENABLE_SPEEDTEST_LOG
            )

    # 测速结果统计
    success_count = len(final_tested_nodes)
    print(f"测速完成，最终存活优质节点：{success_count} 个")

    # 保底回退机制
    if success_count == 0:
        print("测速全死，启动保底回退策略（热门地区未测速保留）")
        fallback_regions = [
            '香港', '台湾', '日本', '新加坡',
            '美国', '韩国', '德国', '英国', '加拿大'
        ]
        candidates = identify_regions_only(all_nodes)
        selected = []
        grouped = defaultdict(list)
        for p in candidates:
            region = p.get('region_info', {}).get('name')
            if region in fallback_regions:
                grouped[region].append(p)
        for r in fallback_regions:
            selected.extend(grouped[r][:30])
        final_tested_nodes = selected[:500]
        print(f"回退保留 {len(final_tested_nodes)} 个热门地区节点（未测速）")

    # [4/5] 节点名称统一规范化处理
    print("[4/5] 节点名称统一规范化处理")
    normalized_proxies = normalize_proxy_names(final_tested_nodes)
    final_proxies = limit_proxy_counts(normalized_proxies, max_total=600)
    if not final_proxies:
        sys.exit("❌ 节点重命名和限量后无有效节点，程序退出")

    # [5/5] 最终排序并生成配置文件
    print("[5/5] 最终排序并生成配置文件")
    final_proxies.sort(
        key=lambda p: (
            REGION_PRIORITY.index(p['region_info']['name']) if p.get('region_info') and p['region_info']['name'] in REGION_PRIORITY else 99,
            p.get('clash_delay', p.get('tcp_delay', 9999))
        )
    )

    total_count = len(final_proxies)
    update_time = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")

    final_config = {
        'proxies': final_proxies,
        'last_message_ids': last_message_ids,
        'update_time': update_time,
        'total_nodes': total_count,
        'note': '由 GitHub Actions 自动生成，每4小时更新一次，已按延迟排序并智能限量'
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# TG频道节点自动抓取+测延迟精选订阅\n")
            f.write(f"# 最后更新时间：{update_time} (北京时间)\n")
            f.write(f"# 本次保留节点数：{total_count} 个（延迟最优）\n")
            f.write(f"# 由 GitHub Actions 自动构建！\n\n")
            yaml.dump(final_config, f, allow_unicode=True, sort_keys=False, indent=2, width=4096)
        print(f"✅ 配置文件已成功保存至 {OUTPUT_FILE}")
        print(f"   本次共保留 {total_count} 个优质节点")
        print(f"   更新时间：{update_time}")
        print("🎉 全部任务完成！")
    except Exception as e:
        print(f"❌ 写出配置文件失败: {e}")
        sys.exit(1)

def sync_main():
    if not ENABLE_SPEED_TEST:
        print("测速功能未启用，跳过测速。")
        return

    ret = run_speedtest(enable_tcp_log=ENABLE_TCP_LOG)
    print(f"测速进程返回码：{ret}")    

if __name__ == "__main__":
    asyncio.run(main())  # 调用异步主函数

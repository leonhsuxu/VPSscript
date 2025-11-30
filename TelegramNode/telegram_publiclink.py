# 文件名: TelegramNode/telegram_publiclink.py
# -*- coding: utf-8 -*-
import os
import re
import asyncio
import yaml
import base64
import time
from datetime import datetime, timedelta, timezone
import sys
from collections import defaultdict
import socket
import concurrent.futures
import hashlib
import subprocess
import shutil
# --- Telethon ---
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaWebPage
from telethon.sessions import StringSession
# =================================================================================
# Part 1: 配置
# =================================================================================
# --- Telegram 抓取器配置 ---
API_ID = os.environ.get('TELEGRAM_API_ID')  # 从 GitHub Secrets 获取的 Telegram 应用 API ID
API_HASH = os.environ.get('TELEGRAM_API_HASH')  # 从 GitHub Secrets 获取的 Telegram 应用 API HASH
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')  # 从 GitHub Secrets 获取的 Telethon 字符串会话，用于登录
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS')  # 从 GitHub Actions 环境变量获取的频道/群组 ID 列表字符串
TIME_WINDOW_HOURS = 48  # 设置抓取消息的时间窗口，单位为小时 (例如: 48 表示只抓取最近48小时内的消息)
MIN_EXPIRE_HOURS = 7    # 设置订阅链接的最小剩余有效期，单位为小时 (例如: 7 表示过滤掉7小时内将过期的链接)
# --- Clash 配置生成器配置 ---
OUTPUT_FILE = 'flclashyaml/telegram_scraper.yaml'  # 最终生成的 Clash 配置文件的输出路径和文件名
ENABLE_SPEED_TEST = True  # 是否启用节点测速功能 (True: 启用, False: 禁用)
SOCKET_TIMEOUT = 5      # 节点测速时的 TCP 连接超时时间，单位为秒
MAX_TEST_WORKERS = 256  # 并发测速的最大线程数，可根据运行环境性能调整

# --- 地区、命名和过滤配置 (已优化) ---
# *** 修改 ***：增加了 '德国', '英国'
ALLOWED_REGIONS = {'香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国'}

# *** 修改 ***：增加了 '德国', '英国'
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国']

# *** 修改 ***：增加了德国和英国的映射
CHINESE_COUNTRY_MAP = {
    'US': '美国', 'United States': '美国', 'USA': '美国',
    'JP': '日本', 'Japan': '日本',
    'HK': '香港', 'Hong Kong': '香港',
    'SG': '狮城', 'Singapore': '狮城',
    'TW': '湾省', 'Taiwan': '湾省',
    'KR': '韩国', 'Korea': '韩国', 'KOR': '韩国',
    'DE': '德国', 'Germany': '德国',
    'GB': '英国', 'United Kingdom': '英国', 'UK': '英国',
}

# *** 修改 ***：增加了德国和英国的匹配规则
CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'香港|港|HK|Hong Kong|HKBN|HGC|PCCW|WTT'},
    '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|沪日|深日|JP|Japan'},
    '狮城': {'code': 'SG', 'pattern': r'新加坡|坡|狮城|SG|Singapore'},
    '美国': {'code': 'US', 'pattern': r'美国|美|波特兰|达拉斯|Oregon|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥'},
    '湾省': {'code': 'TW', 'pattern': r'台湾|湾省|台|新北|彰化|TW|Taiwan'},
    '韩国': {'code': 'KR', 'pattern': r'韩国|韩|首尔|KR|Korea|KOR|韓'},
    '德国': {'code': 'DE', 'pattern': r'德国|德|DE|Germany'},
    '英国': {'code': 'GB', 'pattern': r'英国|英|UK|GB|United Kingdom|England'},
}

JUNK_PATTERNS = re.compile(r"(?:专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)", re.IGNORECASE)
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')
# =================================================================================
# Part 2: 函数定义
# =================================================================================
def parse_expire_time(text):
    match = re.search(r'到期时间[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', text)
    if match:
        try: return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8)))
        except: return None
    return None
def is_expire_time_valid(expire_time):
    if expire_time is None: return True
    hours_remaining = (expire_time - datetime.now(timezone(timedelta(hours=8)))).total_seconds() / 3600
    if hours_remaining < MIN_EXPIRE_HOURS:
        print(f"  ❌ 已跳过: 链接剩余时间 ({hours_remaining:.1f} 小时) 少于最低要求 ({MIN_EXPIRE_HOURS} 小时)")
        return False
    return True
async def scrape_telegram_links():
    if not all([API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS_STR]):
        print("❌ 错误: 缺少必要的环境变量 (API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS)。")
        return []
    TARGET_CHANNELS = [line.strip() for line in TELEGRAM_CHANNEL_IDS_STR.split('\n') if line.strip() and not line.strip().startswith('#')]
    if not TARGET_CHANNELS:
        print("❌ 错误: TELEGRAM_CHANNEL_IDS 中未找到有效频道 ID。")
        return []
    print(f"▶️ 配置抓取 {len(TARGET_CHANNELS)} 个频道: {TARGET_CHANNELS}")
    try:
        client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        print(f"✅ 以 {me.first_name} (@{me.username}) 的身份成功连接")
    except Exception as e:
        print(f"❌ 错误: 连接 Telegram 时出错: {e}"); return []
    target_time = datetime.now(timezone.utc) - timedelta(hours=TIME_WINDOW_HOURS)
    all_links = set()
    for channel_id in TARGET_CHANNELS:
        print(f"\n--- 正在处理频道: {channel_id} ---")
        try:
            async for message in client.iter_messages(await client.get_entity(channel_id), limit=500):
                if message.date < target_time: break
                if message.text and is_expire_time_valid(parse_expire_time(message.text)):
                    for url in re.findall(r'订阅链接[:：]\s*[`]*\s*(https?://[^\s<>"*`]+)', message.text):
                        cleaned_url = url.strip().strip('.,*`')
                        if cleaned_url:
                            all_links.add(cleaned_url)
                            print(f"  ✅ 找到链接: {cleaned_url[:70]}...")
        except Exception as e:
            print(f"❌ 错误: 从频道 '{channel_id}' 获取消息时出错: {e}")
    await client.disconnect()
    print(f"\n✅ 抓取完成, 共找到 {len(all_links)} 个不重复的有效链接。")
    return list(all_links)
def preprocess_regex_rules():
    for region in CUSTOM_REGEX_RULES:
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(sorted(CUSTOM_REGEX_RULES[region]['pattern'].split('|'), key=len, reverse=True))
def get_country_flag_emoji(code):
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in code) if code and len(code) == 2 else "❓"
def download_subscription(url):
    print(f"  ⬇️ 正在下载: {url[:80]}...")
    if not shutil.which("wget"): print("  ✗ 错误: wget 未安装。"); return []
    try:
        content = subprocess.run(["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", url], capture_output=True, text=True, check=True).stdout
        if not content: print("  ✗ 下载内容为空。"); return []
        try: return yaml.safe_load(content).get('proxies', [])
        except yaml.YAMLError: return yaml.safe_load(base64.b64decode(content)).get('proxies', [])
    except Exception as e:
        print(f"  ✗ 下载或解析时出错: {e}"); return []
def get_proxy_key(p):
    return hashlib.md5(f"{p.get('server','')}:{p.get('port',0)}|{p.get('uuid') or p.get('password') or ''}".encode()).hexdigest()
def process_proxies(proxies):
    identified = []
    for p in proxies:
        name = JUNK_PATTERNS.sub('', FLAG_EMOJI_PATTERN.sub('', p.get('name', ''))).strip()
        for eng, chn in CHINESE_COUNTRY_MAP.items(): name = re.sub(r'\b' + re.escape(eng) + r'\b', chn, name, flags=re.IGNORECASE)
        for r_name, rules in CUSTOM_REGEX_RULES.items():
            if re.search(rules['pattern'], name, re.IGNORECASE) and r_name in ALLOWED_REGIONS:
                p['region_info'] = {'name': r_name, 'code': rules['code']}; identified.append(p); break
    print(f"  - 节点过滤: 原始 {len(proxies)} -> 识别并保留 {len(identified)}")
    final, counters = [], defaultdict(lambda: defaultdict(int))
    master_pattern = re.compile('|'.join(sorted([p for r in CUSTOM_REGEX_RULES.values() for p in r['pattern'].split('|')], key=len, reverse=True)), re.IGNORECASE)
    for p in identified:
        info = p['region_info']
        match = FLAG_EMOJI_PATTERN.search(p['name'])
        if match:
            flag = match.group(0)
        else:
            flag = get_country_flag_emoji(info['code'])
        feature = re.sub(r'\s+', ' ', master_pattern.sub(' ', FLAG_EMOJI_PATTERN.sub('', p['name'], 1)).replace('-', ' ')).strip() or f"{sum(1 for fp in final if fp['region_info']['name'] == info['name']) + 1:02d}"
        new_name = f"{flag} {info['name']} {feature}".strip()
        counters[info['name']][new_name] += 1
        if counters[info['name']][new_name] > 1: new_name += f" {counters[info['name']][new_name]}"
        p['name'] = new_name; final.append(p)
    return final
def test_single_proxy(proxy):
    try:
        start = time.time()
        socket.create_connection((proxy['server'], proxy['port']), timeout=SOCKET_TIMEOUT).close()
        proxy['delay'] = int((time.time() - start) * 1000)
        return proxy
    except: return None
def generate_config(proxies):
    if not proxies: return None
    names = [p['name'] for p in proxies]
    clean = [{k: v for k, v in p.items() if k not in ['region_info', 'delay']} for p in proxies]
    groups = [{'name': n, 'type': t, 'proxies': (['♻️ 自动选择', '🔯 故障转移', 'DIRECT'] if t == 'select' else []) + names, 'url': 'http://www.gstatic.com/generate_204', 'interval': 300}
              for n, t in [('🚀 节点选择', 'select'), ('♻️ 自动选择', 'url-test'), ('🔯 故障转移', 'fallback')]]
    return {'mixed-port':

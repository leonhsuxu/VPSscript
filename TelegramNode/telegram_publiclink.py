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
API_ID = os.environ.get('TELEGRAM_API_ID')
API_HASH = os.environ.get('TELEGRAM_API_HASH')
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS')
TIME_WINDOW_HOURS = 48
MIN_EXPIRE_HOURS = 7

# --- Clash 配置生成器配置 ---
OUTPUT_FILE = 'flclashyaml/telegram_scraper.yaml'
ENABLE_SPEED_TEST = True
SOCKET_TIMEOUT = 5
MAX_TEST_WORKERS = 256

# --- 地区、命名和过滤配置 (已优化) ---
ALLOWED_REGIONS = {'香港', '日本', '狮城', '美国', '湾省', '韩国'}
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国']

CHINESE_COUNTRY_MAP = {
    'US': '美国', 'United States': '美国', 'USA': '美国',
    'JP': '日本', 'Japan': '日本',
    'HK': '香港', 'Hong Kong': '香港',
    'SG': '狮城', 'Singapore': '狮城',
    'TW': '湾省', 'Taiwan': '湾省',
    'KR': '韩国', 'Korea': '韩国', 'KOR': '韩国',
}

CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'香港|港|HK|Hong Kong|HKBN|HGC|PCCW|WTT'},
    '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|沪日|深日|JP|Japan'},
    '狮城': {'code': 'SG', 'pattern': r'新加坡|坡|狮城|SG|Singapore'},
    '美国': {'code': 'US', 'pattern': r'美国|美|波特兰|达拉斯|Oregon|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥'},
    '湾省': {'code': 'TW', 'pattern': r'台湾|湾省|台|新北|彰化|TW|Taiwan'},
    '韩国': {'code': 'KR', 'pattern': r'韩国|韩|首尔|KR|Korea|KOR|韓'},
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
                    for url in re.findall(r'订阅链接[:：]\s*[\`]*\s*(https?://[^\s<>"*`]+)', message.text):
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
        
        #
        # === 代码修正处 ===
        #
        # 将原来复杂易错的单行代码，替换为下面清晰的 if/else 逻辑
        #
        match = FLAG_EMOJI_PATTERN.search(p['name'])
        if match:
            flag = match.group(0)
        else:
            flag = get_country_flag_emoji(info['code'])
        #
        # === 修正结束 ===
        #
        
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
    return {'mixed-port': 7890, 'allow-lan': True, 'mode': 'rule', 'log-level': 'info', 'external-controller': '127.0.0.1:9090',
            'dns': {'enable': True, 'listen': '0.0.0.0:53', 'enhanced-mode': 'fake-ip', 'fake-ip-range': '198.18.0.1/16',
                    'nameserver': ['223.5.5.5', '119.29.29.29'], 'fallback': ['https://dns.google/dns-query', 'https://1.1.1.1/dns-query']},
            'proxies': clean, 'proxy-groups': groups, 'rules': ['GEOIP,CN,DIRECT', 'MATCH,🚀 节点选择']}

async def main():
    print("=" * 60 + f"\nClash 订阅自动生成脚本 @ {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S %Z')}\n" + "=" * 60)
    preprocess_regex_rules()
    
    print("\n[1/4] 从 Telegram 抓取、下载并合并节点...")
    urls = await scrape_telegram_links()
    if not urls: sys.exit("\n❌ 未找到任何有效订阅链接，脚本终止。")
    proxies = {get_proxy_key(p): p for url in urls for p in download_subscription(url) if p}
    if not proxies: sys.exit("\n❌ 下载和解析后，无有效节点，脚本终止。")
    print(f"✅ 合并去重后共 {len(proxies)} 个节点。")

    print("\n[2/4] 过滤与重命名节点...")
    processed = process_proxies(list(proxies.values()))
    if not processed: sys.exit("\n❌ 过滤后无任何可用节点，脚本终止。")

    print("\n[3/4] 测速与最终排序...")
    final = processed
    if ENABLE_SPEED_TEST:
        with concurrent.futures.ThreadPoolExecutor(MAX_TEST_WORKERS) as executor:
            tested = list(executor.map(test_single_proxy, processed))
        final = [p for p in tested if p]
        print(f"  - 测速完成, {len(final)} / {len(processed)} 个节点可用。")
        if not final: print("\n  ⚠️ 警告: 测速后无可用节点，将使用所有过滤后的节点。"); final = processed
    
    final.sort(key=lambda p: (REGION_PRIORITY.index(p['region_info']['name']), p.get('delay', 9999)))
    print(f"✅ 最终处理完成 {len(final)} 个节点。")

    print("\n[4/4] 生成最终配置文件...")
    config = generate_config(final)
    if not config: sys.exit("\n❌ 无法生成配置文件。")
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2)
    print(f"✅ 配置文件已成功保存至: {OUTPUT_FILE}\n\n🎉 任务全部完成！")

if __name__ == '__main__':
    asyncio.run(main())

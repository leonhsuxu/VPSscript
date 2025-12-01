# 文件名: TelegramNode/telegram_publiclink.py
# -*- coding: utf-8 -*-
# ============================================================================
# Clash 订阅自动生成脚本 V1.R5 (最终修复版)
#
# 版本历史:
# V1.R5 (20251201) - 终极修复
#   - 引入对 UUID 格式的严格正则校验，彻底杜绝因 uuid 格式错误导致的异常。
#   - 优化节点名称清理逻辑，移除更多无用符号。
# V1.R4 (20251201) - 健壮性修复
#   - 新增全面的节点验证与净化函数，处理数据类型和字段缺失问题。
# V1.R3 (20251201) - 健壮性修复 & 逻辑优化
#   - 强化 REALITY 节点验证，修正旗帜 Emoji 与地区不匹配问题。
# V1.R2 (20251201) - 修复 & 优化
#   - 增加对 REALITY 节点的验证。
# V1.R1 (20251130) - 初始版本
# ============================================================================
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
from telethon.sessions import StringSession

# =================================================================================
# Part 1: 配置
# =================================================================================
# --- Telegram 抓取器配置 ---
API_ID = os.environ.get('TELEGRAM_API_ID')
API_HASH = os.environ.get('TELEGRAM_API_HASH')
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS')
TIME_WINDOW_HOURS = 72
MIN_EXPIRE_HOURS = 7

# --- Clash 配置生成器配置 ---
OUTPUT_FILE = 'flclashyaml/telegram_scraper.yaml'
ENABLE_SPEED_TEST = True
SOCKET_TIMEOUT = 8
MAX_TEST_WORKERS = 128

# --- 测速配置（FlClash 兼容）---
TEST_URL = 'http://www.gstatic.com/generate_204'
TEST_INTERVAL = 300

# --- 地区、命名和过滤配置 ---
ALLOWED_REGIONS = {'香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国', '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大', '法国', '英国', '德国', '俄罗斯', '意大利', '巴西', '阿根廷', '土耳其', '澳大利亚'}
REGION_PRIORITY = ['香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国', '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大', '法国', '英国', '德国', '俄罗斯', '意大利', '巴西', '阿根廷', '土耳其', '澳大利亚']

CHINESE_COUNTRY_MAP = {
    'HK': '香港', 'Hong Kong': '香港', 'HongKong': '香港',
    'TW': '台湾', 'Taiwan': '台湾', 'TWN': '台湾', 'Taipei': '台湾',
    'JP': '日本', 'Japan': '日本', 'Tokyo': '日本', 'Osaka': '日本',
    'SG': '新加坡', 'Singapore': '新加坡', 'SGP': '新加坡',
    'KR': '韩国', 'Korea': '韩国', 'KOR': '韩国', 'Seoul': '韩国', 'South Korea': '韩国',
    'MY': '马来西亚', 'Malaysia': '马来西亚',
    'TH': '泰国', 'Thailand': '泰国',
    'IN': '印度', 'India': '印度',
    'PH': '菲律宾', 'Philippines': '菲律宾',
    'ID': '印度尼西亚', 'Indonesia': '印度尼西亚',
    'VN': '越南', 'Vietnam': '越南',
    'US': '美国', 'United States': '美国', 'USA': '美国', 'America': '美国',
    'CA': '加拿大', 'Canada': '加拿大',
    'FR': '法国', 'France': '法国',
    'GB': '英国', 'United Kingdom': '英国', 'UK': '英国', 'England': '英国', 'London': '英国',
    'DE': '德国', 'Germany': '德国', 'Frankfurt': '德国', 'Munich': '德国', 'Berlin': '德国',
    'RU': '俄罗斯', 'Russia': '俄罗斯',
    'IT': '意大利', 'Italy': '意大利',
    'BR': '巴西', 'Brazil': '巴西',
    'AR': '阿根廷', 'Argentina': '阿根廷',
    'TR': '土耳其', 'Turkey': '土耳其',
    'AU': '澳大利亚', 'Australia': '澳大利亚'
}

COUNTRY_NAME_TO_CODE_MAP = {
    "香港": "HK", "台湾": "TW", "日本": "JP", "新加坡": "SG", "韩国": "KR",
    "马来西亚": "MY", "泰国": "TH", "印度": "IN", "菲律宾": "PH", "印度尼西亚": "ID", "越南": "VN",
    "美国": "US", "加拿大": "CA", "法国": "FR", "英国": "GB", "德国": "DE", "俄罗斯": "RU", "意大利": "IT",
    "巴西": "BR", "阿根廷": "AR", "土耳其": "TR", "澳大利亚": "AU"
}

CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'香港|港|HK|Hong\s*Kong|HongKong|HKBN|HGC|PCCW|WTT|HKT|九龙|沙田|屯门|荃湾|深水埗|油尖旺'},
    '台湾': {'code': 'TW', 'pattern': r'台湾|湾省|台|TW|Taiwan|TWN|台北|Taipei|台中|Taichung|高雄|Kaohsiung|新北|彰化|Hinet|中华电信'},
    '日本': {'code': 'JP', 'pattern': r'日本|日|川日|东京|大阪|泉日|沪日|深日|京日|广日|JP|Japan|Tokyo|Osaka|Saitama|埼玉|名古屋|Nagoya|福冈|Fukuoka|横滨|Yokohama|NTT|IIJ|GMO|Linode'},
    '新加坡': {'code': 'SG', 'pattern': r'新加坡|坡|狮城|狮|新|SG|Singapore|SG\d+|SGP|星|狮子城'},
    '韩国': {'code': 'KR', 'pattern': r'韩国|韩|南朝鲜|首尔|釜山|仁川|KR|Korea|KOR|韓|Seoul|Busan|KT|SK|LG|South\s*Korea'},
    '马来西亚': {'code': 'MY', 'pattern': r'马来西亚|马来|MY|Malaysia|吉隆坡|Kuala\s*Lumpur'},
    '泰国': {'code': 'TH', 'pattern': r'泰国|泰|TH|Thailand|曼谷|Bangkok'},
    '印度': {'code': 'IN', 'pattern': r'印度|IN|India|孟买|Mumbai|新德里|Delhi'},
    '菲律宾': {'code': 'PH', 'pattern': r'菲律宾|菲|PH|Philippines|马尼拉|Manila'},
    '印度尼西亚': {'code': 'ID', 'pattern': r'印度尼西亚|印尼|ID|Indonesia|雅加达|Jakarta'},
    '越南': {'code': 'VN', 'pattern': r'越南|越|VN|Vietnam|胡志明|Ho\s*Chi\s*Minh|河内|Hanoi'},
    '美国': {'code': 'US', 'pattern': r'美国|美|波特兰|达拉斯|Oregon|俄勒冈|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥|纽约|迈阿密|亚特兰大|US|USA|United\s*States|America|LA|NYC|SF|San\s*Francisco|Washington|华盛顿|Kansas|堪萨斯|Denver|丹佛|Phoenix|Seattle|Chicago|Boston|波士顿|Atlanta|Miami|Las\s*Vegas'},
    '加拿大': {'code': 'CA', 'pattern': r'加拿大|加|CA|Canada|多伦多|Toronto|温哥华|Vancouver'},
    '法国': {'code': 'FR', 'pattern': r'法国|法|FR|France|巴黎|Paris'},
    '英国': {'code': 'GB', 'pattern': r'英国|英|伦敦|曼彻斯特|UK|GB|United\s*Kingdom|Britain|England|London|Manchester'},
    '德国': {'code': 'DE', 'pattern': r'德国|德|法兰克福|慕尼黑|柏林|DE|Germany|Frankfurt|Munich|Berlin|Hetzner'},
    '俄罗斯': {'code': 'RU', 'pattern': r'俄罗斯|俄|RU|Russia|莫斯科|Moscow|圣彼得堡|Petersburg'},
    '意大利': {'code': 'IT', 'pattern': r'意大利|意|IT|Italy|罗马|Rome|米兰|Milan'},
    '巴西': {'code': 'BR', 'pattern': r'巴西|BR|Brazil|圣保罗|Sao\s*Paulo|里约|Rio'},
    '阿根廷': {'code': 'AR', 'pattern': r'阿根廷|AR|Argentina|布宜诺斯艾利斯|Buenos\s*Aires'},
    '土耳其': {'code': 'TR', 'pattern': r'土耳其|土|TR|Turkey|伊斯坦布尔|Istanbul'},
    '澳大利亚': {'code': 'AU', 'pattern': r'澳大利亚|澳洲|澳|AU|Australia|悉尼|Sydney|墨尔本|Melbourne'},
}

JUNK_PATTERNS = re.compile(r"(?:专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)", re.IGNORECASE)
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')
UUID_PATTERN = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', re.IGNORECASE)

# =================================================================================
# Part 2: 函数定义
# =================================================================================
def parse_expire_time(text):
    """解析消息中的到期时间"""
    match = re.search(r'到期时间[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', text)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8)))
        except: return None
    return None

def is_expire_time_valid(expire_time):
    """检查订阅链接是否在有效期内"""
    if expire_time is None: return True
    now_utc8 = datetime.now(timezone(timedelta(hours=8)))
    hours_remaining = (expire_time - now_utc8).total_seconds() / 3600
    if hours_remaining < MIN_EXPIRE_HOURS:
        print(f"  ❌ 已跳过: 链接剩余时间 ({hours_remaining:.1f} 小时) 少于最低要求 ({MIN_EXPIRE_HOURS} 小时)")
        return False
    return True

async def scrape_telegram_links():
    """从 Telegram 频道抓取订阅链接"""
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
        print(f"❌ 错误: 连接 Telegram 时出错: {e}")
        return []

    target_time = datetime.now(timezone.utc) - timedelta(hours=TIME_WINDOW_HOURS)
    all_links = set()
    for channel_id in TARGET_CHANNELS:
        print(f"\n--- 正在处理频道: {channel_id} ---")
        try:
            entity = await client.get_entity(channel_id)
            async for message in client.iter_messages(entity, limit=500):
                if message.date < target_time: break
                if message.text and is_expire_time_valid(parse_expire_time(message.text)):
                    for url in re.findall(r'订阅链接[:：]?\s*`?\s*(https?://[^\s<>"*`]+)', message.text):
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
    """预处理正则规则：按长度排序以优化匹配效率"""
    for region in CUSTOM_REGEX_RULES:
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(sorted(CUSTOM_REGEX_RULES[region]['pattern'].split('|'), key=len, reverse=True))

def get_country_flag_emoji(code):
    """根据国家代码生成旗帜 Emoji"""
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in code) if code and len(code) == 2 else "❓"

def download_subscription(url):
    """下载并解析订阅链接"""
    print(f"  ⬇️ 正在下载: {url[:80]}...")
    if not shutil.which("wget"):
        print("  ✗ 错误: wget 未安装。")
        return []
    try:
        content = subprocess.run(
            ["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", url],
            capture_output=True, text=True, check=True
        ).stdout
        if not content:
            print("  ✗ 下载内容为空。")
            return []
        try:
            return yaml.safe_load(content).get('proxies', [])
        except yaml.YAMLError:
            return yaml.safe_load(base64.b64decode(content)).get('proxies', [])
    except Exception as e:
        print(f"  ✗ 下载或解析时出错: {e}")
        return []

def get_proxy_key(p

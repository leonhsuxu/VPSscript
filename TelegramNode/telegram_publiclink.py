# -*- coding: utf-8 -*-
# =====================================================================
# Clash 订阅自动生成脚本 V4 - 20251204 Clash测速版
#
# 功能：
# 1. 从 Telegram 频道动态抓取订阅链接
# 2. 支持两种下载方式（wget优先，requests备用）
# 3. 订阅内容自动判断并解析：
#    - YAML 格式直接提取 proxies 字段
#    - 明文协议链接（vmess、vless、ssr、ss、trojan、hysteria等）逐行解析
#    - Base64 编码的混合协议节点解析
# 4. 解析过程中统计各协议成功和失败节点数量，统一打印
# 5. 支持节点去重、地区识别（含emoji国旗）、Clash核心测速与排序、旧节点测速去重
# 6. 生成Clash兼容配置文件，里边包含爬取消息截止id
# =====================================================================
import os
import re
import asyncio
import yaml
import base64
import json
import time
import requests
from datetime import datetime, timedelta, timezone
import sys
from collections import defaultdict
import socket
import concurrent.futures
import hashlib
import subprocess
import shutil
from urllib.parse import urlparse, parse_qs, unquote
import tempfile # For creating temporary directories
import platform # To detect OS for Clash core executable name
# --- Telethon ---
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
# ========================== Telegram 个人资料配置 ==========================
API_ID = os.environ.get('TELEGRAM_API_ID')  # 获取 Telegram API ID
API_HASH = os.environ.get('TELEGRAM_API_HASH')  # 获取 Telegram API HASH
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')  # 获取 Telegram 会话字符串
# ========================== 配置区 =========================================
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS')  # Telegram频道ID，多行字符串，从yml引入
TIME_WINDOW_HOURS = 8  # 抓取时间窗口，单位小时
MIN_EXPIRE_HOURS = 2  # 订阅链接最低剩余有效期，单位小时
OUTPUT_FILE = 'flclashyaml/telegram_scraper.yaml'  # 输出YAML路径
# ========================== 测速参数 =========================================
ENABLE_SPEED_TEST = True  # 是否启用测速  True开启，False关闭
# SOCKET_TIMEOUT = 3  # TCP测速超时时间(秒) - 已移除，因为不再进行 TCP 直接测速
MAX_TEST_WORKERS = 5  # 并发测速线程数 (注意: 使用Clash核心测速时，过高的并发数会显著增加资源消耗)
HTTP_TIMEOUT = 5          # HTTP 请求超时时间（秒），用于Clash核心测速时的请求
HTTP_TEST_URL = 'http://www.gstatic.com/generate_204'  # 轻量无内容响应URL，用于HTTP测速
# Clash 核心测速相关配置
# 请根据您的操作系统和Clash核心的实际位置进行修改
# 示例: Linux 为 './clash_core/clash', Windows 为 'C:\\clash_core\\clash.exe'
# 或者如果您已将Clash核心添加到系统PATH中，可以直接写 'clash'
CLASH_CORE_PATH = './clash_core/clash'
CLASH_CONFIG_PORT_HTTP = 7890  # Clash 核心监听的 HTTP 代理端口
CLASH_CONFIG_PORT_SOCKS = 7891 # Clash 核心监听的 SOCKS5 代理端口
CLASH_SECRET = "your_clash_secret" # Clash API 的可选密码，如果不需要可以留空或删除
# ========== 地区过滤配置 ==========
ALLOWED_REGIONS = {'香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国',
                   '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大', '法国',
                   '英国', '德国', '俄罗斯', '意大利', '巴西', '阿根廷', '土耳其', '澳大利亚'}
# ========== 排序优先级配置 ==========
REGION_PRIORITY = ['香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国', '印度', '菲律宾',
                   '印度尼西亚', '越南', '美国', '加拿大', '法国', '英国', '德国', '俄罗斯', '意大利',
                   '巴西', '阿根廷', '土耳其', '澳大利亚']
# ========== 国家/地区映射表 ==========
CHINESE_COUNTRY_MAP = {
    'HK': '香港', 'TW': '台湾', 'JP': '日本', 'SG': '新加坡', 'KR': '韩国', 'MY': '马来西亚',
    'TH': '泰国', 'IN': '印度', 'PH': '菲律宾', 'ID': '印度尼西亚', 'VN': '越南', 'US': '美国',
    'CA': '加拿大', 'FR': '法国', 'GB': '英国', 'DE': '德国', 'RU': '俄罗斯', 'IT': '意大利',
    'BR': '巴西', 'AR': '阿根廷', 'TR': '土耳其', 'AU': '澳大利亚'
}
# ========== 地区识别正则规则 ==========
CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'香港|港|HK|Hong\s*Kong'},
    '台湾': {'code': 'TW', 'pattern': r'台湾|台|TW|Taiwan'},
    '日本': {'code': 'JP', 'pattern': r'日本|日|JP|Japan'},
    '新加坡': {'code': 'SG', 'pattern': r'新加坡|SG|Singapore'},
    '韩国': {'code': 'KR', 'pattern': r'韩国|南朝鲜|KR|Korea'},
    '马来西亚': {'code': 'MY', 'pattern': r'马来西亚|MY|Malaysia'},
    '泰国': {'code': 'TH', 'pattern': r'泰国|TH|Thailand'},
    '印度': {'code': 'IN', 'pattern': r'印度|IN|India'},
    '菲律宾': {'code': 'PH', 'pattern': r'菲律宾|PH|Philippines'},
    '印度尼西亚': {'code': 'ID', 'pattern': r'印度尼西亚|印尼|ID|Indonesia'},
    '越南': {'code': 'VN', 'pattern': r'越南|VN|Vietnam'},
    '美国': {'code': 'US', 'pattern': r'美国|US|USA|United States'},
    '加拿大': {'code': 'CA', 'pattern': r'加拿大|CA|Canada'},
    '法国': {'code': 'FR', 'pattern': r'法国|FR|France'},
    '英国': {'code': 'GB', 'pattern': r'英国|GB|UK|United Kingdom'},
    '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'},
    '俄罗斯': {'code': 'RU', 'pattern': r'俄罗斯|RU|Russia'},
    '意大利': {'code': 'IT', 'pattern': r'意大利|IT|Italy'},
    '巴西': {'code': 'BR', 'pattern': r'巴西|BR|Brazil'},
    '阿根廷': {'code': 'AR', 'pattern': r'阿根廷|AR|Argentina'},
    '土耳其': {'code': 'TR', 'pattern': r'土耳其|TR|Turkey'},
    '澳大利亚': {'code': 'AU', 'pattern': r'澳大利亚|AU|Australia'},
}
JUNK_PATTERNS = re.compile(r"(?:专线|IPLC|体验|官网|倍率|x\d[\.\d]*|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)", re.IGNORECASE)
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')
BJ_TZ = timezone(timedelta(hours=8))
# =================================================================================
# Part 2: 函数定义
# =================================================================================
def process_proxies(proxies):
    """
    过滤节点，仅保留地区在 ALLOWED_REGIONS 的节点，
    并添加 region_info，最后重命名节点。
    """
    identified = []
    for p in proxies:
        matched_region = None
        for region_name, info in CUSTOM_REGEX_RULES.items():
            pattern = info['pattern']
            if re.search(pattern, p.get('name', ''), re.IGNORECASE):
                matched_region = {'name': region_name, 'code': info['code']}
                break
        if matched_region is None:
            continue
        if matched_region['name'] not in ALLOWED_REGIONS:
            continue
        p['region_info'] = matched_region
        identified.append(p)
    print(f"  - 节点过滤: 总数 {len(proxies)} -> 有效地区识别后 {len(identified)}")
    counters = defaultdict(lambda: defaultdict(int))
    master_pattern = re.compile(
        '|'.join(sorted([p for r in CUSTOM_REGEX_RULES.values() for p in r['pattern'].split('|')], key=len, reverse=True)),
        re.IGNORECASE
    )
    final = []
    for p in identified:
        info = p['region_info']
        match = FLAG_EMOJI_PATTERN.search(p['name'])
        flag = match.group(0) if match else get_country_flag_emoji(info['code'])
        clean_name = master_pattern.sub('', FLAG_EMOJI_PATTERN.sub('', p['name'], 1)).strip()
        clean_name = re.sub(r'^\W+|\W+$', '', clean_name)
        feature = re.sub(r'\s+', ' ', clean_name).strip()
        if not feature:
            count = sum(1 for fp in final if fp['region_info']['name'] == info['name']) + 1
            feature = f"{info['code']}{count:02d}"
        base_name = f"{flag} {info['name']} {feature}".strip()
        counters[info['name']][base_name] += 1
        count_ = counters[info['name']][base_name]
        if count_ > 1:
            new_name = f"{base_name} {count_}"
        else:
            new_name = base_name
        p['name'] = new_name
        final.append(p)
    return final

# --- 读取本地已有节点及抓取状态 ---
def load_existing_proxies_and_state():
    existing_proxies = []
    last_message_ids = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                loaded_yaml = yaml.safe_load(f)
                if isinstance(loaded_yaml, dict):
                    existing_proxies = loaded_yaml.get('proxies', [])
                    if not isinstance(existing_proxies, list):
                        existing_proxies = []
                    last_message_ids = loaded_yaml.get('last_message_ids', {})
                    if not isinstance(last_message_ids, dict):
                        last_message_ids = {}
                elif isinstance(loaded_yaml, list):
                    existing_proxies = [p for p in loaded_yaml if isinstance(p, dict)]
        except Exception as e:
            print(f"  - 读取或解析 {OUTPUT_FILE} 失败: {e}")
    return existing_proxies, last_message_ids

def extract_valid_subscribe_links(text):
    """
    从单条消息文本中提取有效订阅链接，
    忽略机场名链接，根据到期时间过滤剩余时间<2小时的链接。
    """
    MIN_HOURS_LEFT = MIN_EXPIRE_HOURS
    BJ_TZ = timezone(timedelta(hours=8))
    link_pattern = re.compile(
        r'(?:订阅链接|订阅地址|订阅)[\s:：]*?[^hH]*?(https?://[^\s<>"*`]+)'
    )
    links = link_pattern.findall(text)
    expire_time = None
    expire_patterns = [
        r'到期时间[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{2}:\d{2}:\d{2})',
        r'过期时间[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{2}:\d{2}:\d{2})',
        r'该订阅将于(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{2}:\d{2}:\d{2})(?:\s*\+\d{4}\s*[A-Za-z]{3})?过期',
        r'过期[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        r'到期[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        r'该订阅将于未知过期',
        r'过期时间[:：]\s*长期有效',
        r'过期[:：]\s*未知/无限',
    ]
    text_single_line = text.replace('\n', ' ')
    for patt in expire_patterns:
        match = re.search(patt, text_single_line)
        if match:
            if '未知' in match.group(0) or '长期有效' in match.group(0) or '无限' in match.group(0):
                expire_time = None
                break
            if match.lastindex:
                dt_str = match.group(1)
                fmt_candidates = ['%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d']
                for fmt in fmt_candidates:
                    try:
                        dt = datetime.strptime(dt_str, fmt)
                        if fmt in ('%Y-%m-%d', '%Y/%m/%d'):
                            dt = dt.replace(hour=23, minute=59, second=59)
                        expire_time = dt.replace(tzinfo=BJ_TZ)
                        break
                    except:
                        continue
            break
    now = datetime.now(BJ_TZ)
    valid_links = []
    for url in links:
        if expire_time is not None:
            hours_left = (expire_time - now).total_seconds() / 3600
            if hours_left < MIN_HOURS_LEFT:
                continue
        valid_links.append(url)
    return valid_links

async def scrape_telegram_links(last_message_ids=None):
    if last_message_ids is None:
        last_message_ids = {}
    if not all([API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS_STR]):
        print("❌ 错误: 缺少必要的环境变量 (API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS)。")
        return [], last_message_ids
    TARGET_CHANNELS = [line.strip() for line in TELEGRAM_CHANNEL_IDS_STR.split('\n')
                       if line.strip() and not line.strip().startswith('#')]
    if not TARGET_CHANNELS:
        print("❌ 错误: TELEGRAM_CHANNEL_IDS 中未找到有效频道 ID。")
        return [], last_message_ids
    print(f"▶️ 配置抓取 {len(TARGET_CHANNELS)} 个频道: {TARGET_CHANNELS}")
    try:
        client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        print(f"✅ 以 {me.first_name} (@{me.username}) 的身份成功连接")
    except Exception as e:
        print(f"❌ 错误: 连接 Telegram 时出错: {e}")
        return [], last_message_ids
    bj_now = datetime.now(BJ_TZ)
    bj_prior_time = bj_now - timedelta(hours=TIME_WINDOW_HOURS)
    target_time = bj_prior_time.astimezone(timezone.utc)
    all_links = set()
    for channel_id in TARGET_CHANNELS:
        print(f"\n📢  正在处理频道: {channel_id} ...")
        try:
            entity = await client.get_entity(channel_id)
        except Exception as e:
            print(f"❌ 错误: 无法获取频道实体 {channel_id}: {e}")
            continue
        last_id = last_message_ids.get(channel_id, 0)
        max_id_found = last_id
        try:
            async for message in client.iter_messages(entity, min_id=last_id + 1, reverse=False):
                if message.date < target_time:
                    break
                if message.text:
                    links = extract_valid_subscribe_links(message.text)
                    for link in links:
                        all_links.add(link)
                        print(f"  ✅ 找到链接: {link[:70]}...")
                if message.id > max_id_found:
                    max_id_found = message.id
            last_message_ids[channel_id] = max_id_found
        except Exception as e:
            print(f"❌ 错误: 从频道 '{channel_id}' 获取消息时出错: {e}")
    await client.disconnect()
    print(f"\n✅ 抓取完成, 共找到 {len(all_links)} 个不重复的有效链接。")
    return list(all_links), last_message_ids

def preprocess_regex_rules():
    """预处理正则规则：按长度排序以优化匹配效率"""
    for region in CUSTOM_REGEX_RULES:
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(
            sorted(CUSTOM_REGEX_RULES[region]['pattern'].split('|'), key=len, reverse=True)
        )

def get_country_flag_emoji(code):
    """根据国家代码生成旗帜 Emoji"""
    if not code or len(code) != 2:
        return "❓"
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in code)

def attempt_download_using_wget(url):
    """使用 wget 下载订阅链接"""
    print(f"  ⬇️ 正在使用 wget 下载: {url[:80]}...")
    if not shutil.which("wget"):
        print("  ✗ 错误: wget 未安装，无法执行下载。")
        return None
    try:
        # 使用 --no-check-certificate 避免证书问题
        content = subprocess.run(
            ["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", "--no-check-certificate", url],
            capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore'
        ).stdout
        return content if content else None
    except subprocess.CalledProcessError as e:
        print(f"  ✗ wget 下载失败: {e.stderr}")
        return None

def attempt_download_using_requests(url):
    """使用 requests 下载订阅链接"""
    print(f"  ⬇️ 正在使用 requests 下载: {url[:80]}...")
    try:
        headers = {'User-Agent': 'Clash'}
        response = requests.get(url, headers=headers, timeout=30, verify=False) # verify=False 忽略SSL证书错误
        response.raise_for_status()
        response.encoding = response.apparent_encoding or 'utf-8'
        return response.text
    except requests.RequestException as e:
        print(f"  ✗ requests 下载失败: {e}")
        return None

def parse_proxies_from_content(content):
    """从下载的内容中解析代理节点"""
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            proxies = data.get('proxies', [])
            if isinstance(proxies, list):
                return proxies
        elif isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def is_base64(text):
    """检查字符串是否是有效的 Base64 编码"""
    try:
        s = ''.join(text.split())
        if not s or len(s) % 4 != 0:
            return False
        # Relaxed check for URL-safe base64, common in some subs
        if not re.match(r'^[A-Za-z0-9+/=\-_]+$', s): # Added - and _
            return False
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False

# ---------------- 协议节点解析 ----------------
def parse_vmess_node(line):
    try:
        content_b64 = line[8:]
        decoded = base64.b64decode(content_b64 + '=' * (-len(content_b64) % 4)).decode('utf-8', errors='ignore')
        info = json.loads(decoded)
        node = {
            'name': info.get('ps', 'vmess_node'),
            'type': 'vmess',
            'server': info.get('add') or info.get('host'),
            'port': int(info.get('port', 0)),
            'uuid': info.get('id') or info.get('uuid'),
            'alterId': int(info.get('aid', info.get('alterId', 0))) if str(info.get('aid', '')).isdigit() else 0,
            'cipher': info.get('scy', 'auto'),
            'network': info.get('net', 'tcp'),
            'tls': True if info.get('tls', '').lower() == 'tls' else False,
            'skip-cert-verify': info.get('allowInsecure', False),
            'ws-opts': {},
        }
        if node['network'] == 'ws':
            ws_opts = {
                'path': info.get('path', ''),
                'headers': {'Host': info.get('host', '')} if info.get('host') else {},
            }
            node['ws-opts'] = ws_opts
        return node
    except Exception:
        return None

def parse_vless_node(line):
    try:
        parsed = urlparse(line.strip())
        if parsed.scheme != 'vless':
            return None
        params = parse_qs(parsed.query)
        node = {
            'name': unquote(parsed.fragment) if parsed.fragment else f"vless_{parsed.hostname}",
            'type': 'vless',
            'server': parsed.hostname,
            'port': int(parsed.port or 0),
            'uuid': parsed.username,
            'encryption': 'none',
            'flow': params.get('flow', [''])[0],
            'tls': (parsed.query.lower().find('tls') != -1) or ('tls' in params),
            'skip-cert-verify': params.get('allowInsecure', ['false'])[0].lower() == 'true',
            'network': params.get('type', ['tcp'])[0],
            'host': params.get('host', [''])[0],
            'path': params.get('path', [''])[0],
            'sni': params.get('sni', [''])[0],
        }
        if node['network'] == 'ws':
            node['ws-opts'] = {'path': node['path'], 'headers': {'Host': node['host']} if node['host'] else {}}
        return node
    except Exception:
        return None

def parse_ssr_node(line):
    try:
        ssr_b64 = line[6:]
        ssr_decoded = base64.urlsafe_b64decode(ssr_b64 + '=' * (-len(ssr_b64) % 4)).decode('utf-8', errors='ignore')
        parts = ssr_decoded.split('/?')
        main = parts[0]
        params_str = parts[1] if len(parts) > 1 else ''
        server, port, protocol, method, obfs, password_b64 = main.split(':', 5)
        password = base64.urlsafe_b64decode(password_b64 + '=' * (-len(password_b64) % 4)).decode('utf-8', errors='ignore')
        params = {}
        for param in params_str.split('&'):
            if '=' in param:
                k, v = param.split('=', 1)
                params[k] = v
        remark = unquote(params.get('remarks', ''))
        node = {
            'name': remark or f"ssr_{server}",
            'type': 'ssr',
            'server': server,
            'port': int(port),
            'cipher': method,
            'protocol': protocol,
            'obfs': obfs,
            'password': password,
            'udp': params.get('udp', 'false').lower() == 'true'
        }
        return node
    except Exception:
        return None

def parse_ss_node(line):
    try:
        line = line.strip()
        if not line.startswith('ss://'):
            return None
        content = line[5:]
        if '@' in content:
            parsed = urlparse('ss://' + content)
            user_pass = parsed.netloc.split('@')[0]
            method, password = user_pass.split(':', 1)
            server = parsed.hostname
            port = parsed.port
            name = unquote(parsed.fragment) if parsed.fragment else f"ss_{server}"
            node = {'name': name, 'type': 'ss', 'server': server, 'port': port,
                    'cipher': method, 'password': password, 'udp': True}
            return node
        else:
            ss_b64 = content.split('#')[0]
            remark = ''
            if '#' in content:
                remark = unquote(content.split('#')[1])
            decoded = base64.urlsafe_b64decode(ss_b64 + '=' * (-len(ss_b64) % 4)).decode('utf-8', errors='ignore')
            method_password, server_port = decoded.split('@')
            method, password = method_password.split(':')
            server, port = server_port.split(':')
            node = {'name': remark or f"ss_{server}", 'type': 'ss', 'server': server,
                    'port': int(port), 'cipher': method, 'password': password, 'udp': True}
            return node
    except Exception:
        return None

def parse_trojan_node(line):
    try:
        parsed = urlparse(line)
        if parsed.scheme != 'trojan':
            return None
        password = parsed.username or ''
        server = parsed.hostname or ''
        port = parsed.port or 0
        params = parse_qs(parsed.query)
        node = {
            'name': unquote(parsed.fragment) if parsed.fragment else f"trojan_{server}",
            'type': 'trojan',
            'server': server,
            'port': port,
            'password': password,
            'sni': params.get('sni', [''])[0],
            'skip-cert-verify': params.get('allowInsecure', ['false'])[0].lower() == 'true',
            'udp': True,
            'alpn': params.get('alpn', []),
            'tls': True,
        }
        return node
    except Exception:
        return None

def parse_hysteria_node(line):
    try:
        parsed = urlparse(line)
        if parsed.scheme != 'hysteria':
            return None
        params = parse_qs(parsed.query)
        node = {
            'name': unquote(parsed.fragment) or f"hysteria_{parsed.hostname}",
            'type': 'hysteria',
            'server': parsed.hostname,
            'port': int(parsed.port or 0),
            'auth': params.get('auth', [''])[0],
            'protocol': params.get('protocol', ['udp'])[0],
            'insecure': params.get('insecure', ['false'])[0].lower() == 'true',
            'obfs': params.get('obfs', [''])[0],
            'udp': True,
        }
        return node
    except Exception:
        return None

def parse_hysteria2_node(line):
    try:
        parsed = urlparse(line)
        if parsed.scheme != 'hysteria2':
            return None
        params = parse_qs(parsed.query)
        auth = parsed.username or ''
        obfs_password = params.get('obfs-password', [''])[0]
        insecure_val = params.get('insecure', ['false'])[0].lower()
        insecure = insecure_val in ('1', 'true', 'yes')
        node = {
            'name': unquote(parsed.fragment) if parsed.fragment else f"hysteria2_{parsed.hostname}",
            'type': 'hysteria2',
            'server': parsed.hostname,
            'port': int(parsed.port or 0),
            'auth': auth,
            'protocol': params.get('protocol', ['udp'])[0],
            'insecure': insecure,
            'obfs': params.get('obfs', [''])[0],
            'obfs-password': obfs_password,
            'udp': params.get('udp', ['true'])[0].lower() == 'true',
        }
        return node
    except Exception as e:
        return None

# ---------------- 订阅解析主逻辑 ----------------
def parse_plain_nodes_from_text(text):
    proxies = []
    success_count = defaultdict(int)
    failure_count = defaultdict(int)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        proxy = None
        proto = None
        if line.startswith('vmess://'):
            proto = 'vmess'
            proxy = parse_vmess_node(line)
        elif line.startswith('vless://'):
            proto = 'vless'
            proxy = parse_vless_node(line)
        elif line.startswith('ssr://'):
            proto = 'ssr'
            proxy = parse_ssr_node(line)
        elif line.startswith('ss://'):
            proto = 'ss'
            proxy = parse_ss_node(line)
        elif line.startswith('trojan://'):
            proto = 'trojan'
            proxy = parse_trojan_node(line)
        elif line.startswith('hysteria://'):
            proto = 'hysteria'
            proxy = parse_hysteria_node(line)
        elif line.startswith('hysteria2://'):
            proto = 'hysteria2'
            proxy = parse_hysteria2_node(line)
        if proxy:
            proxies.append(proxy)
            success_count[proto] += 1
        else:
            failure_count[proto] += 1
    for proto, count in success_count.items():
        print(f"  - 明文协议解析完成，{proto} 节点成功数：{count}")
    for proto, count in failure_count.items():
        print(f"  - 明文协议解析失败，{proto} 节点失败数：{count}")
    return proxies

def decode_base64_and_parse(content):
    try:
        decoded = base64.b64decode(''.join(content.split())).decode('utf-8', errors='ignore')
        proxies = []
        success_count = defaultdict(int)
        failure_count = defaultdict(int)
        for line in decoded.splitlines():
            line = line.strip()
            if not line:
                continue
            proxy = None
            proto = None
            if line.startswith('vmess://'):
                proto = 'vmess'
                proxy = parse_vmess_node(line)
            elif line.startswith('vless://'):
                proto = 'vless'
                proxy = parse_vless_node(line)
            elif line.startswith('ssr://'):
                proto = 'ssr'
                proxy = parse_ssr_node(line)
            elif line.startswith('ss://'):
                proto = 'ss'
                proxy = parse_ss_node(line)
            elif line.startswith('trojan://'):
                proto = 'trojan'
                proxy = parse_trojan_node(line)
            elif line.startswith('hysteria://'):
                proto = 'hysteria'
                proxy = parse_hysteria_node(line)
            elif line.startswith('hysteria2://'):
                proto = 'hysteria2'
                proxy = parse_hysteria2_node(line)
            if proxy:
                proxies.append(proxy)
                success_count[proto] += 1
            else:
                failure_count[proto] += 1
        for proto, count in success_count.items():
            print(f"  - Base64 解码解析完成，{proto} 节点成功数：{count}")
        for proto, count in failure_count.items():
            print(f"  - Base64 解码解析失败，{proto} 节点失败数：{count}")
        return proxies
    except Exception as e:
        print(f"  - Base64 解码解析异常: {e}")
        return []

def download_subscription(url):
    content = attempt_download_using_wget(url)
    if content is None:
        content = attempt_download_using_requests(url)
    if content is None:
        print(f"  ❌ 下载失败: {url}")
        return []
    proxies = parse_proxies_from_content(content)
    if proxies:
        print(f"  - 直接 YAML 解析获取 {len(proxies)} 个节点")
        return proxies
    proxies = parse_plain_nodes_from_text(content)
    if proxies:
        print(f"  - 明文内容解析获取 {len(proxies)} 个节点")
        return proxies
    if is_base64(content):
        print(f"  - 内容为 Base64 编码，正在解码解析...")
        proxies = decode_base64_and_parse(content)
        if proxies:
            return proxies
        else:
            print(f"  - Base64 解码无有效节点")
            return []
    print(f"  - 内容不符合已知格式，未找到有效节点")
    return []

# 移除了 test_single_proxy_tcp 函数，因为不再进行直接 TCP 测速

def generate_clash_config_for_proxy(proxy, config_path, http_port, socks_port):
    """
    Generates a minimal Clash config file for a single proxy.
    Accepts http_port and socks_port to configure Clash listener ports.
    """
    # Ensure proxy has a name for the Clash config
    if 'name' not in proxy:
        proxy['name'] = f"{proxy.get('type', 'unknown')}_{proxy.get('server', 'unknown')}_{proxy.get('port', 'unknown')}_{hashlib.md5(str(proxy).encode()).hexdigest()[:6]}"

    config_data = {
        'port': http_port, # <--- 使用动态分配的 HTTP 端口
        'socks-port': socks_port, # <--- 使用动态分配的 SOCKS 端口
        'allow-lan': False, # 通常在测速时设置为 False
        'mode': 'rule', # or 'direct'
        'log-level': 'silent', # 设置为 silent 减少日志输出，如果需要详细日志可以改为 info 或 debug
        'secret': CLASH_SECRET, # Clash API 的可选密码
        'proxies': [proxy], # 将单个代理添加到 proxies 列表中
        'proxy-groups': [
            {
                'name': 'Proxy',
                'type': 'select',
                'proxies': [proxy['name']] # 代理组引用该代理
            },
            {
                'name': 'DIRECT', # 直连策略组，虽然此处未使用，但Clash配置通常包含
                'type': 'direct'
            }
        ],
        'rules': [
            'MATCH,Proxy' # 所有流量都通过 'Proxy' 组，确保测速流量走代理
        ]
    }
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False, indent=2)
    except Exception as e:
        print(f"  ✗ Failed to write Clash config to {config_path}: {e}")
        raise # 重新抛出异常，让调用者知道配置生成失败

def wait_for_clash_startup(port, timeout=10):
    """Waits for Clash to start listening on the given port."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # Try to establish a connection to the Clash HTTP proxy port
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False

def test_single_proxy_with_clash_core(proxy):
        proxy['http_delay'] = None
        return proxy
    except Exception as e:
        # 捕获其他任何意外错误
        print(f"  ✗ An unexpected error occurred during Clash core testing for {original_proxy_name}: {e}")
        proxy['http_delay'] = None
        return proxy
    finally:
        # 恢复代理的原始名称，因为我们在函数开始时修改了它
        if 'name' in proxy and proxy['name'].endswith(f"_{unique_id}"):
            proxy['name'] = original_proxy_name

        # 终止 Clash 核心进程
        if clash_process and clash_process.poll() is None: # 检查进程是否仍在运行
            clash_process.terminate() # 尝试正常终止
            try:
                clash_process.wait(timeout=5) # 等待几秒钟让进程关闭
            except subprocess.TimeoutExpired:
                clash_process.kill() # 如果超时未关闭，则强制杀死进程
        
        # ****** 仅在 http_delay 为 None 时（即测速失败）打印 Clash 核心的日志 ******
        if proxy.get('http_delay') is None:
            print(f"  --- Clash Core Logs for {original_proxy_name} ---")
            if os.path.exists(log_file_stdout):
                with open(log_file_stdout, 'r', encoding='utf-8') as f:
                    stdout_content = f.read()
                    if stdout_content:
                        print(f"  Clash STDOUT:\n{stdout_content}")
            if os.path.exists(log_file_stderr):
                with open(log_file_stderr, 'r', encoding='utf-8') as f:
                    stderr_content = f.read()
                    if stderr_content:
                        print(f"  Clash STDERR:\n{stderr_content}")
            print(f"  --- End Clash Core Logs ---")
        # ****** 调试日志输出结束 ******

        # 清理临时目录
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"  ✗ Failed to clean up temp directory {temp_dir}: {e}")

# --- 主控流程 ---
def get_proxy_key(p):
    """生成代理节点的唯一标识"""
    # 优先使用 uuid/password，然后是 server/port 组合
    unique_part = p.get('uuid') or p.get('password') or ''
    return hashlib.md5(
        f"{p.get('server','')}:{p.get('port',0)}|{unique_part}".encode()
    ).hexdigest()

def is_valid_proxy(proxy):
    """验证代理节点的协议格式和有效性"""
    if not isinstance(proxy, dict):
        return False
    required_keys = ['name', 'server', 'port', 'type']
    if not all(key in proxy for key in required_keys):
        return False
    # 进一步检查协议类型
    allowed_types = {'http', 'socks5', 'trojan', 'vless', 'ss', 'vmess', 'ssr', 'hysteria', 'hysteria2'}
    if 'type' in proxy and proxy['type'] not in allowed_types:
        return False
    # 确保端口范围在有效范围内
    if not isinstance(proxy['port'], int) or not (1 <= proxy['port'] <= 65535):
        return False
    return True

def delete_old_yaml():
    """每周一晚上23:00删除旧的 YAML 文件"""
    now = datetime.now(timezone(timedelta(hours=8)))  # 北京时间
    # 周一(weekday()==0), 23:00-23:59
    if now.weekday() == 0 and now.hour == 23:
        if os.path.exists(OUTPUT_FILE):
            try:
                os.remove(OUTPUT_FILE)
                print(f"✅ 已根据计划删除旧的配置文件: {OUTPUT_FILE}")
            except OSError as e:
                print(f"❌ 删除旧配置文件时出错: {e}")

def generate_config(proxies):
    """根据代理节点列表生成完整的 Clash 配置字典"""
    if not proxies:
        return None
    config = {
        'proxies': proxies,
    }
    return config

async def main():
                    if p.get('region_info') and p['region_info']['name'] in fallback_regions:
                        # For fallback, if http_delay is None, use tcp_delay for sorting
                        p['http_delay'] = p.get('tcp_delay', 9999) # Assign tcp_delay if http_delay is None
                        region_grouped_fallback_nodes[p['region_info']['name']].append(p)
                
                for region in fallback_regions:
                    # Sort by http_delay (which is tcp_delay for fallback nodes)
                    sorted_region_nodes = sorted(region_grouped_fallback_nodes[region], key=lambda x: x.get('http_delay', 9999))
                    selected_fallback_nodes.extend(sorted_region_nodes[:fallback_count_per_region])
                
                print(f"  - 回退策略已选择 {len(selected_fallback_nodes)} 个节点。")
                nodes_to_process_after_speed_test = selected_fallback_nodes
            elif not http_passed_nodes and not http_failed_nodes: # This means tcp_successful_proxies_raw was empty
                print("⚠️ 无任何节点通过 TCP 测速或 HTTP 测速。")
                nodes_to_process_after_speed_test = []
            
    else: # ENABLE_SPEED_TEST is False
        nodes_to_process_after_speed_test = all_nodes
        print("测速关闭，使用全部节点继续处理")

    if not nodes_to_process_after_speed_test:
        sys.exit("❌ 无任何可用节点通过测速或回退选择，程序终止。")

    # 5. 节点地区识别及重命名 (对最终选定的节点集进行处理)
    print("[4/5] 节点地区识别及重命名")
    processed_proxies = process_proxies(nodes_to_process_after_speed_test)
    
    if not processed_proxies:
        sys.exit("❌ 识别有效节点失败，程序退出")
    
    # 6. 排序 (优先使用 http_delay 进行排序)
    processed_proxies.sort(
        key=lambda p: (
            REGION_PRIORITY.index(p['region_info']['name']) if p['region_info']['name'] in REGION_PRIORITY else 99,
            p.get('http_delay', p.get('tcp_delay', 9999)) # Use http_delay first, then tcp_delay if http_delay is missing
        )
    )
    print(f"[5/5] 排序完成，节点数量: {len(processed_proxies)}")

    # 7. 输出最终配置
    final_config = {
        'proxies': processed_proxies,
        'last_message_ids': last_message_ids,
    }
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(final_config, f, allow_unicode=True, sort_keys=False, indent=2)
        print(f"✅ 配置文件及状态已成功保存至: {OUTPUT_FILE}\n\n🎉 任务全部完成！")
    except Exception as e:
        print(f"❌ 写入最终配置文件时出错: {e}")

if __name__ == "__main__":
    asyncio.run(main())

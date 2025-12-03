# -*- coding: utf-8 -*-
# =====================================================================
# Clash 订阅自动生成脚本 V3 - 20251203
#
# 功能：
# 1. 从 Telegram 频道动态抓取订阅链接
# 2. 支持两种下载方式（wget优先，requests备用）
# 3. 订阅内容自动判断并解析：
#    - YAML 格式直接提取 proxies 字段
#    - 明文协议链接（vmess、vless、ssr、ss、trojan、hysteria等）逐行解析
#    - Base64 编码的混合协议节点解析
# 4. 解析过程中统计各协议成功和失败节点数量，统一打印
# 5. 支持节点去重、地区识别（含emoji国旗）、TCP测速与排序、旧节点测速去重
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
SOCKET_TIMEOUT = 3  # TCP测速超时时间(秒)
MAX_TEST_WORKERS = 256  # 并发测速线程数
HTTP_TIMEOUT = 5          # HTTP 请求超时时间（秒）
HTTP_TEST_URL = 'http://www.gstatic.com/generate_204'  # 轻量无内容响应URL，用于HTTP测速
# ========== 地区过滤配置 ==========
ALLOWED_REGIONS = {'香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国',
                   '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大', '法国',
                   '英国', '德国', '俄罗斯', '意大利', '巴西', '阿根廷', '土耳其', '澳大利亚'}
# ALLOWED_REGIONS = set(CUSTOM_REGEX_RULES.keys()) # 或可使用已有的 CUSTOM_REGEX_RULES 键集合
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
# =========================    for p in proxies:
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
    MIN_HOURS_LEFT = 2
    BJ_TZ = timezone(timedelta(hours=8))

    # 1. 找所有订阅链接（只匹配带订阅关键字的链接，不匹配机场链接）
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

    # 把文本统一换成空格替换换行，防止分行影响正则捕获
    text_single_line = text.replace('\n', ' ')

    for patt in expire_patterns:
        match = re.search(patt, text_single_line)
        if match:
            if '未知' in match.group(0) or '长期有效' in match.group(0) or '无限' in match.group(0):
                expire_time = None  # 无限期
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

    from datetime import timezone, timedelta
    BJ_TZ = timezone(timedelta(hours=8))
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
        content = subprocess.run(
            ["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", url],
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
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or 'utf-8'
        return response.text
    except requests.RequestException as e:
        print(f"  ✗ requests 下载失败: {e}")
        return None


def parse_proxies_from_content(content):
    """从下载的内容中解析代理节点"""
    try:
        # 尝试解析 YAML 内容
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
        if not re.match(r'^[A-Za-z0-9+/=]+$', s):
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

        # 用户ID在 netloc 的用户名部分
        auth = parsed.username or ''

        # 混淆密码
        obfs_password = params.get('obfs-password', [''])[0]

        # insecure判断，兼容 '0', 'false', '1', 'true'
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
        # 通常建议打印或记录异常以方便调试
        # print(f"Error parsing node: {e}")
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


def test_single_proxy_tcp(proxy):
        # 请求失败返回None
        return None

def combined_speed_test(proxy):
    """
    组合测速流程：
    1. 先做TCP连接测试
    2. TCP成功后做HTTP请求测试（直连，不走代理）
    3. 返回包含 tcp_delay 和 http_delay 信息的proxy字典
    4. 失败时返回None，或者http_delay设为None表示HTTP测试失败但TCP成功
    """
    p = test_single_proxy_tcp(proxy)    # TCP测试
    if not p:
        return None  # TCP失败，跳过HTTP测试
    
    p = test_single_proxy_http(p)       # HTTP测试(直连)
    if not p:
        # HTTP测试失败但TCP成功，保留TCP延迟，HTTP延迟设为None
        proxy['http_delay'] = None
        return proxy

    return p  # 两项测速都成功，返回包含两个延迟信息的节点

# ------------------ 主控流程 ------------------

# 代理节点示例列表，格式必须包含 'server' 和 'port'
all_nodes = [
    {"server": "1.1.1.1", "port": 8080},
    {"server": "2.2.2.2", "port": 3128},
    # 你自己的代理列表...
]

if ENABLE_SPEED_TEST:
    print(f"[3/5] 开始 TCP 和 HTTP 连接综合测速（超时 TCP:{SOCKET_TIMEOUT}s，HTTP:{HTTP_TIMEOUT}s，最大线程 {MAX_TEST_WORKERS}）...")

    # 使用线程池并发测速，提升测速效率
    with concurrent.futures.ThreadPoolExecutor(MAX_TEST_WORKERS) as pool:
        # 并发执行组合测速函数（TCP+HTTP）
        tested_results = list(pool.map(combined_speed_test, all_nodes))
    
    # 筛选测速成功的代理节点（非 None）
    tested_proxies = [p for p in tested_results if p]

    print(f"测速成功节点数: {len(tested_proxies)} / {len(all_nodes)}")

else:
    # 测速关闭，直接使用全部节点
    tested_proxies = all_nodes
    print("测速关闭，使用全部节点继续处理")

# 如果没有任何测速成功的节点，退回使用全部节点，保证程序后续可执行
if not tested_proxies:
    print("⚠️ 无测速成功节点，使用所有节点继续处理")
    tested_proxies = all_nodes

# 打印最终结果，方便确认
for proxy in tested_proxies:
    print(f"代理 {proxy['server']}:{proxy['port']}, TCP延迟={proxy.get('tcp_delay')}ms, HTTP延迟={proxy.get('http_delay')}")

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
    # 仅包含proxies键，使其成为一个有效的Clash代理提供者文件
    config = {
        'proxies': proxies,
    }
    return config


async def main():
    
    print("=" * 60)
    print("Clash 订阅自动生成脚本 V3 ")
    print(f"时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    preprocess_regex_rules()
    
    # delete_old_yaml()  # 取消定期删除，保留历史文件
    

    print("[1/5] 读取已有节点及抓取状态文件")
    existing_proxies, last_message_ids = load_existing_proxies_and_state()
    print(f"已有节点数量: {len(existing_proxies)}")

    # 2. 抓取 Telegram 获取新订阅链接和新节点
    print("[2/5] 抓取 Telegram 订阅链接")
    urls, last_message_ids = await scrape_telegram_links(last_message_ids)

    new_proxies_list = []
    if urls:
        print(f"共抓取 {len(urls)} 个订阅链接，开始下载解析节点...")
        for url in urls:
            proxies = download_subscription(url)
            if proxies:
                new_proxies_list.extend(proxies)

    print(f"抓取新增节点数: {len(new_proxies_list)}")

    # 3. 合并原有和新增节点，去重
    all_proxies_map = {get_proxy_key(p): p for p in existing_proxies if is_valid_proxy(p)}
    added_new = 0
    for p in new_proxies_list:
        key = get_proxy_key(p)
        if key not in all_proxies_map:
            all_proxies_map[key] = p
            added_new += 1
    print(f"合并去重后总节点数: {len(all_proxies_map)}, 新增节点: {added_new}")

    all_nodes = list(all_proxies_map.values())
    if not all_nodes:
        sys.exit("❌ 无任何可用节点, 程序终止")

    # 4. TCP 测速所有节点，保留测速成功的
    if ENABLE_SPEED_TEST:
        print(f"[3/5] 开始 TCP 连接测速（超时 {SOCKET_TIMEOUT}s，最大线程 {MAX_TEST_WORKERS}）...")
        with concurrent.futures.ThreadPoolExecutor(MAX_TEST_WORKERS) as pool:
            tested_results = list(pool.map(test_single_proxy_tcp, all_nodes))
        tested_proxies = [p for p in tested_results if p]
        print(f"测速成功节点数: {len(tested_proxies)} / {len(all_nodes)}")
    else:
        tested_proxies = all_nodes
        print("测速关闭，使用全部节点继续处理")

    if not tested_proxies:
        print("⚠️ 无测速成功节点，使用所有节点继续处理")
        tested_proxies = all_nodes

    # 5. 仅针对测速通过节点做地区识别和重命名
    print("[4/5] 节点地区识别及重命名")
    processed_proxies = process_proxies(tested_proxies)
    if not processed_proxies:
        sys.exit("❌ 识别有效节点失败，程序退出")

    # 6. 排序
    processed_proxies.sort(
        key=lambda p: (
            REGION_PRIORITY.index(p['region_info']['name']) if p['region_info']['name'] in REGION_PRIORITY else 99,
            p.get('delay', 9999)
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

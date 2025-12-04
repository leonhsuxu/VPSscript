# -*- coding: utf-8 -*-
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
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# === 环境变量读取 ===
API_ID = int(os.environ.get('TELEGRAM_API_ID') or 0)
API_HASH = os.environ.get('TELEGRAM_API_HASH')
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS', '')

TIME_WINDOW_HOURS = 8
MIN_EXPIRE_HOURS = 2
OUTPUT_FILE = 'flclashyaml/telegram_scraper.yaml'

ENABLE_SPEED_TEST = True
MAX_TEST_WORKERS = 64
SOCKET_TIMEOUT = 3
HTTP_TIMEOUT = 5

HTTP_TEST_URL = 'http://www.gstatic.com/generate_204'

ALLOWED_REGIONS = {
    '香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国',
    '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大',
    '法国', '英国', '德国', '俄罗斯', '意大利', '巴西',
    '阿根廷', '土耳其', '澳大利亚'
}

REGION_PRIORITY = [
    '香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国',
    '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大',
    '法国', '英国', '德国', '俄罗斯', '意大利', '巴西',
    '阿根廷', '土耳其', '澳大利亚'
]

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

FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')
BJ_TZ = timezone(timedelta(hours=8))


def get_country_flag_emoji(code):
    if not code or len(code) != 2:
        return "❓"
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in code)


def preprocess_regex_rules():
    for region in CUSTOM_REGEX_RULES:
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(
            sorted(CUSTOM_REGEX_RULES[region]['pattern'].split('|'), key=len, reverse=True)
        )


def load_existing_proxies_and_state():
    existing_proxies = []
    last_message_ids = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                loaded_yaml = yaml.safe_load(f)
                if isinstance(loaded_yaml, dict):
                    existing_proxies = loaded_yaml.get('proxies', [])
                    last_message_ids = loaded_yaml.get('last_message_ids', {})
                elif isinstance(loaded_yaml, list):
                    existing_proxies = [p for p in loaded_yaml if isinstance(p, dict)]
        except Exception as e:
            print(f"读取 {OUTPUT_FILE} 失败: {e}")
    return existing_proxies, last_message_ids


def extract_valid_subscribe_links(text):
    MIN_HOURS_LEFT = MIN_EXPIRE_HOURS

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
        print("❌ 缺少环境变量(API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS)")
        return [], last_message_ids
    TARGET_CHANNELS = [line.strip() for line in TELEGRAM_CHANNEL_IDS_STR.split('\n')
                       if line.strip() and not line.strip().startswith('#')]
    if not TARGET_CHANNELS:
        print("❌ TELEGRAM_CHANNEL_IDS 未找到有效频道")
        return [], last_message_ids
    print(f"准备从 {len(TARGET_CHANNELS)} 频道抓取订阅链接")
    try:
        client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        print(f"已连接 Telegram: {me.first_name} (@{me.username})")
    except Exception as e:
        print(f"连接 Telegram 出错: {e}")
        return [], last_message_ids

    bj_now = datetime.now(BJ_TZ)
    target_time = bj_now - timedelta(hours=TIME_WINDOW_HOURS)
    target_time = target_time.astimezone(timezone.utc)

    all_links = set()
    for channel_id in TARGET_CHANNELS:
        print(f"处理频道 {channel_id}")
        try:
            entity = await client.get_entity(channel_id)
        except Exception as e:
            print(f"无法获取频道 {channel_id} 实体: {e}")
            continue
        last_id = last_message_ids.get(channel_id, 0)
        max_id_found = last_id
        try:
            async for msg in client.iter_messages(entity, min_id=last_id + 1, reverse=False):
                if msg.date < target_time:
                    break
                if msg.text:
                    links = extract_valid_subscribe_links(msg.text)
                    for link in links:
                        all_links.add(link)
                        print(f"  获得链接: {link[:70]}")
                if msg.id > max_id_found:
                    max_id_found = msg.id
            last_message_ids[channel_id] = max_id_found
        except Exception as e:
            print(f"获取频道 {channel_id} 消息出错: {e}")

    await client.disconnect()
    print(f"共抓取到 {len(all_links)} 个有效不重复链接。")
    return list(all_links), last_message_ids

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
        # print(f"Error parsing node: {e}") # Debugging
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

# --------- 下载并解析订阅内容 ---------
def attempt_download(url):
    import shutil

    def try_wget():
        if shutil.which("wget"):
            try:
                result = subprocess.run(
                    ["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", url],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding='utf-8', timeout=30
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass
        return None

    def try_requests():
        import requests
        try:
            r = requests.get(url, headers={'User-Agent': 'Clash'}, timeout=30)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or 'utf-8'
            return r.text
        except Exception:
            return None

    content = try_wget()
    if content is None:
        content = try_requests()

    return content


def parse_proxies_subscribe(content):
    # 先试yaml解析
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

    # 解析明文订阅，组合用例（需要加入你的节点解析函数，parse_vmess_node等）
    # 这里只示意
    proxies = parse_plain_nodes_from_text(content)
    if proxies:
        return proxies

    # Base64解码后尝试
    if is_base64(content):
        return decode_base64_and_parse(content)

    return []


def download_and_parse(url):
    content = attempt_download(url)
    if not content:
        print(f"下载失败: {url}")
        return []

    proxies = parse_proxies_subscribe(content)
    if proxies:
        print(f"解析出节点数: {len(proxies)}")
    else:
        print(f"未找到有效节点: {url}")
    return proxies


def get_proxy_key(proxy):
    unique_part = proxy.get('uuid') or proxy.get('password') or ''
    return hashlib.md5(
        f"{proxy.get('server','')}:{proxy.get('port',0)}|{unique_part}".encode()
    ).hexdigest()


def is_valid_proxy(proxy):
    if not isinstance(proxy, dict):
        return False
    required_keys = ['name', 'server', 'port', 'type']
    if not all(key in proxy for key in required_keys):
        return False
    allowed_types = {'http', 'socks5', 'trojan', 'vless', 'ss', 'vmess', 'ssr', 'hysteria', 'hysteria2'}
    if proxy['type'] not in allowed_types:
        return False
    if not isinstance(proxy['port'], int) or not (1 <= proxy['port'] <= 65535):
        return False
    return True


def identify_regions_only(proxies):
    identified = []
    for p in proxies:
        matched_region = None
        for region_name, info in CUSTOM_REGEX_RULES.items():
            if re.search(info['pattern'], p.get('name', ''), re.IGNORECASE):
                matched_region = {'name': region_name, 'code': info['code']}
                break
        if matched_region:
            p['region_info'] = matched_region
            identified.append(p)
    return identified


def process_proxies(proxies):
    identified = []
    for p in proxies:
        matched_region = None
        for region_name, info in CUSTOM_REGEX_RULES.items():
            if re.search(info['pattern'], p.get('name', ''), re.IGNORECASE):
                matched_region = {'name': region_name, 'code': info['code']}
                break
        if matched_region is None:
            continue
        if matched_region['name'] not in ALLOWED_REGIONS:
            continue
        p['region_info'] = matched_region
        identified.append(p)

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


def generate_config(proxies, last_message_ids):
    return {
        'proxies': proxies,
        'last_message_ids': last_message_ids,
    }


def clash_test_proxy(clash_path, proxy):
    """调用 clash 执行文件测速接口，返回延迟或 None。"""
    tested_types = {'vmess', 'vless', 'trojan', 'ss', 'ssr', 'hysteria', 'hysteria2', 'http', 'socks5'}
    if proxy.get('type', '').lower() not in tested_types:
        return None

    import tempfile
    import yaml

    temp_dir = tempfile.mkdtemp()
    temp_config_path = os.path.join(temp_dir, 'config.yaml')

    test_url = "http://www.gstatic.com/generate_204"

    config = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": False,
        "mode": "Rule",
        "proxies": [proxy],
        "proxy-groups": [
            {
                "name": "TestGroup",
                "type": "select",
                "proxies": [proxy['name']]
            }
        ],
        "rules": [
            f"DOMAIN,{urlparse(test_url).netloc},TestGroup",
            "FINAL,DIRECT"
        ]
    }

    with open(temp_config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

    try:
        proc = subprocess.run(
            [clash_path, '-t', temp_config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            timeout=15
        )
        output = proc.stdout
        # 找出“节点名: 123 ms”形式的延迟
        match = re.search(rf"{re.escape(proxy['name'])}: (\d+) ms", output)
        if match:
            delay = int(match.group(1))
            return delay
    except Exception as e:
        print(f"Clash 测试异常: {e}")
        return None
    finally:
        try:
            os.remove(temp_config_path)
            os.rmdir(temp_dir)
        except Exception:
            pass

    return None


def test_proxy_with_clash(clash_path, proxy):
    delay = clash_test_proxy(clash_path, proxy)
    if delay is not None:
        proxy['clash_delay'] = delay
        return proxy
    else:
        return None


def batch_test_proxies_clash(clash_path, proxies, max_workers=32):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(test_proxy_with_clash, clash_path, p) for p in proxies]
        for future in futures:
            res = future.result()
            if res:
                results.append(res)
    return results


async def main():
    print("=" * 60)
    print("Clash 订阅自动生成脚本 - Clash 核心测速版本")
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

    all_proxies_map = {get_proxy_key(p): p for p in existing_proxies if is_valid_proxy(p)}
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

    if ENABLE_SPEED_TEST:
        print("[3/5] 使用 clash 核心测速")
        clash_path = 'clash_core/clash'
        if not (os.path.isfile(clash_path) and os.access(clash_path, os.X_OK)):
            sys.exit(f"❌ clash 核心缺失或不可执行: {clash_path}")

        tested_nodes = batch_test_proxies_clash(clash_path, all_nodes, max_workers=MAX_TEST_WORKERS)
        print(f" ✅测速成功节点数: {len(tested_nodes)}")

        if not tested_nodes:
            print("⚠️ clash测速全部失败，启用回退策略保留指定地区节点")
            fallback_regions = ['香港', '日本', '美国', '新加坡', '德国']
            fallback_count = 30
            fallback_candidates = identify_regions_only(all_nodes)

            selected = []
            grouped = defaultdict(list)
            for p in fallback_candidates:
                if p.get('region_info') and p['region_info']['name'] in fallback_regions:
                    grouped[p['region_info']['name']].append(p)

            for region in fallback_regions:
                selected.extend(grouped[region][:fallback_count])

            tested_nodes = selected

        nodes_to_process = tested_nodes

    else:
        print("测速关闭，使用所有节点")
        nodes_to_process = all_nodes

    if not nodes_to_process:
        sys.exit("❌ 找不到符合条件的节点，程序退出")

    print("[4/5] 节点地区识别和重命名")
    processed_proxies = process_proxies(nodes_to_process)
    if not processed_proxies:
        sys.exit("❌ 节点地区识别失败，程序退出")

    processed_proxies.sort(
        key=lambda p: (
            REGION_PRIORITY.index(p['region_info']['name']) if p['region_info']['name'] in REGION_PRIORITY else 99,
            p.get('clash_delay', 9999)
        )
    )

    print(f"[5/5] 排序完成，节点数: {len(processed_proxies)}")

    final_config = generate_config(processed_proxies, last_message_ids)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(final_config, f, allow_unicode=True, sort_keys=False, indent=2)
        print(f"✅ 配置文件已保存至 {OUTPUT_FILE}")
        print("🎉 任务完成！")
    except Exception as e:
        print(f"写出文件时异常: {e}")

if __name__ == "__main__":
    asyncio.run(main())

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
OUTPUT_FILE = 'flclashyaml/Tg-node1.yaml'  # 输出文件路径，用于保存生成的配置或结果。



# === 新增：测速策略开关（推荐保留这几个选项）===
# 测速模式：
ENABLE_SPEED_TEST = True  # 是否启用整体速度测试功能，True表示启用。测试顺序如下

SPEEDTEST_MODE = os.getenv('SPEEDTEST_MODE', 'tcp_first').lower()  # 默认推荐 tcp_first,下边的命令
#   "tcp_only"      → 只用 TCP 测速（最快，最严格，适合节点特别多的情况）
#   "clash_only"    → 只用 Clash -fast 测速（最准）
#   "tcp_first"     → 先 TCP 粗筛（<800ms）→ 再 Clash 精测（推荐！平衡速度与质量）
#   "clash_first"   → 先 Clash → 再 TCP（一般用不上）

# TCP 和Clash 测速专属参数
TCP_TIMEOUT = 4.0          # 单次 TCP 连接超时时间（秒），建议 3~5
TCP_MAX_WORKERS = 200      # TCP 测速最大并发（可以比 Clash 高很多，非常快）
TCP_MAX_DELAY = 1000       # TCP 延迟阈值，超过此值直接丢弃（ms）
ENABLE_TCP_LOG = False     # 默认关闭TCP日志
ENABLE_SPEEDTEST_LOG = True  # 默认关闭 speedtest 详细日志


MAX_TEST_WORKERS = 128    # 速度测试时最大并发工作线程数，控制测试的并行度。
SOCKET_TIMEOUT = 3       # 套接字连接超时时间，单位为秒
HTTP_TIMEOUT = 5         # HTTP请求超时时间，单位为秒
TEST_URLS = [
    'http://www.gstatic.com/generate_204',
    'http://www.youtube.com',
]


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
    '香港': {
        'code': 'HK',
        'pattern': r'香港|港|HK|Hong\s*Kong|HongKong|HKBN|HGC|PCCW|WTT|HKT|九龙|沙田|屯门|荃湾|深水埗|油尖旺'
    },
    '日本': {
        'code': 'JP',
        'pattern': r'日本|日|川日|东京|大阪|泉日|沪日|深日|京日|广日|JP|Japan|Tokyo|Osaka|Saitama|埼玉|名古屋|Nagoya|福冈|Fukuoka|横滨|Yokohama|NTT|IIJ|GMO|Linode'
    },
    '新加坡': {
        'code': 'SG',
        'pattern': r'新加坡|坡|狮城|狮|新|SG|Singapore|SG\d+|SGP|星|狮子城'
    },
    '美国': {
        'code': 'US',
        'pattern': r'美国|美|波特兰|达拉斯|Oregon|俄勒冈|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥|纽约|迈阿密|亚特兰大|US|USA|United\s*States|America|LA|NYC|SF|San\s*Francisco|Washington|华盛顿|Kansas|堪萨斯|Denver|丹佛|Phoenix|Seattle|Chicago|Boston|波士顿|Atlanta|Miami|Las\s*Vegas'
    },
    '台湾': {
        'code': 'TW',
        'pattern': r'台湾|湾省|台|TW|Taiwan|TWN|台北|Taipei|台中|Taichung|高雄|Kaohsiung|新北|彰化|Hinet|中华电信'
    },
    '韩国': {
        'code': 'KR',
        'pattern': r'韩国|韩|南朝鲜|首尔|釜山|仁川|KR|Korea|KOR|韓|Seoul|Busan|KT|SK|LG'
    },
    '德国': {
        'code': 'DE',
        'pattern': r'德国|德|法兰克福|慕尼黑|柏林|DE|Germany|Frankfurt|Munich|Berlin|Hetzner'
    },
    '英国': {
        'code': 'GB',
        'pattern': r'英国|英|伦敦|曼彻斯特|UK|GB|United\s*Kingdom|Britain|England|London|Manchester'
    },
    '加拿大': {'code': 'CA', 'pattern': r'加拿大|枫叶|多伦多|温哥华|蒙特利尔|CA|Canada'},
    '澳大利亚': {'code': 'AU', 'pattern': r'澳大利亚|澳洲|悉尼|AU|Australia'},
    '越南': {'code': 'VN', 'pattern': r'越南|VN|Vietnam'},
    '印度': {'code': 'IN', 'pattern': r'印度|IN|India'},
    '马来西亚': {'code': 'MY', 'pattern': r'马来西亚|马来|MY|Malaysia'},
    '法国': {'code': 'FR', 'pattern': r'法国|FR|France'},
    '泰国': {
    'code': 'TH',
    'pattern': r'泰国|TH|Thailand|曼谷|Bangkok'
},
    '菲律宾': {
    'code': 'PH',
    'pattern': r'菲律宾|PH|Philippines|马尼拉|Manila'
},
    '印度尼西亚': {
    'code': 'ID',
    'pattern': r'印度尼西亚|印尼|ID|Indonesia|雅加达|Jakarta'
},
    '俄罗斯': {
    'code': 'RU',
    'pattern': r'俄罗斯|RU|Russia|莫斯科|Moscow'
},
    '意大利': {
    'code': 'IT',
    'pattern': r'意大利|IT|Italy|罗马|Rome'
},
    '巴西': {
    'code': 'BR',
    'pattern': r'巴西|BR|Brazil|圣保罗|São\s*Paulo'
},
    '阿根廷': {
    'code': 'AR',
    'pattern': r'阿根廷|AR|Argentina|布宜诺斯艾利斯|Buenos\s*Aires'
},
    '土耳其': {
    'code': 'TR',
    'pattern': r'土耳其|TR|Turkey|伊斯坦布尔|Istanbul'
}
}
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')
BJ_TZ = timezone(timedelta(hours=8))

def do_speed_test():
    if not ENABLE_SPEED_TEST:
        print("测速功能未启用，跳过。")
        return
    # 启用测速并打印日志
    run_speedtest(enable_tcp_log=False)

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
                    if not isinstance(existing_proxies, list):
                        existing_proxies = []
                    last_message_ids = loaded_yaml.get('last_message_ids', {})
                    if not isinstance(last_message_ids, dict):
                        last_message_ids = {}
                elif isinstance(loaded_yaml, list):
                    existing_proxies = [p for p in loaded_yaml if isinstance(p, dict)]
        except Exception as e:
            print(f"读取 {OUTPUT_FILE} 失败: {e}")
    return existing_proxies, last_message_ids

def extract_valid_subscribe_links(text):
    MIN_HOURS_LEFT = MIN_EXPIRE_HOURS
    link_pattern = re.compile(
        r'(?:订阅链接|订阅地址|订阅|链接)[\s:：`]*?(https?://[A-Za-z0-9\-._~:/?#[\]@!$&\'()*+,;=%]+)'
    )
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
    expire_time = None
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
                    except Exception:
                        continue
            break
    now = datetime.now(BJ_TZ)
    valid_links = []
    links = link_pattern.findall(text)
    for url in links:
        if expire_time is not None:
            hours_left = (expire_time - now).total_seconds() / 3600
            if hours_left < MIN_HOURS_LEFT:
                continue
        valid_links.append(url)
    return valid_links

# ==========================
# 替换了 scrape_telegram_links 为 B 版本更完善的实现
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
    target_time = (bj_now - timedelta(hours=TIME_WINDOW_HOURS)).astimezone(timezone.utc)
    all_links = set()
    for channel_id in TARGET_CHANNELS:
        print(f"\n 🎯正在处理频道: {channel_id} ...")
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
                        if link not in all_links:
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

# --- B 版本的下载及解析相关函数合入 ---

def attempt_download_using_wget(url):
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
            # 标准格式: ss://method:password@server:port#remarks
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
            # base64格式 ss://base64(method:password@server:port) 或带备注
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
    except Exception:
        return None

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

def download_and_parse(url):
    # 用 B 版本的下载解析逻辑替代 A 里原 download_and_parse 体
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

# --- 下面保持原A版测速、去重、排序等逻辑 ---


def get_proxy_key(proxy):
    unique_part = proxy.get('uuid') or proxy.get('password') or ''
    return hashlib.md5(
        f"{proxy.get('server','')}:{proxy.get('port',0)}|{unique_part}".encode()
    ).hexdigest()

def is_valid_ss_cipher(cipher):
    """
    判断ss节点cipher字段是否合法，避免被错误的Base64或其它字符串污染。
    这里列举了Clash常见支持的ss加密方法，必要时你可根据实际增加或修改。

    参数:
        cipher (str): ss节点中cipher字段

    返回:
        bool: 是否有效
    """
    if not cipher:
        return False
    valid_ciphers = {
        'aes-256-gcm', 'aes-128-gcm', 'chacha20-ietf-poly1305',
        'aes-256-cfb', 'aes-128-cfb', 'chacha20-ietf', 'xchacha20',
        'aes-128-ctr', 'aes-256-ctr', 'rc4-md5'
    }
    return cipher.lower() in valid_ciphers


def is_valid_proxy(proxy):
    """
    验证代理节点基本完整性和字段有效性，增加对ss加密方法的单独验证。

    参数:
        proxy (dict): 代理节点字典

    返回:
        bool: 合法为True，否则False
    """
    if not isinstance(proxy, dict):
        return False
    required_keys = ['name', 'server', 'port', 'type']
    if not all(key in proxy for key in required_keys):
        return False

    allowed_types = {'http', 'socks5', 'trojan', 'vless', 'ss', 'vmess', 'ssr', 'hysteria', 'hysteria2'}
    if proxy['type'] not in allowed_types:
        return False

    port = proxy.get('port')
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return False

    # SS协议特有的加密方法字段检查，确保为有效cipher
    if proxy['type'] == 'ss':
        cipher = proxy.get('cipher', '')
        if not is_valid_ss_cipher(cipher):
            if cipher:
                print(f"⚠️ 无效的 ss cipher: {cipher}，节点名: {proxy.get('name')}")
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
#锚点


# 新增的国家代码 转 中文名字典，方便快速映射
COUNTRY_CODE_TO_CN = {
    v['code']: k for k, v in CUSTOM_REGEX_RULES.items()
}

def emoji_to_country_code(emoji):
    if len(emoji) != 2:
        return None
    try:
        # 两个flag emoji的unicode解码成国家代码
        return ''.join(chr(ord(c) - 0x1F1E6 + ord('A')) for c in emoji)
    except:
        return None

FLAG_EMOJI_UN_FLAG ='🇺🇳'  # 无国家用联合国，按需修改

def strip_starting_flags(s):
    """
    反复检测字符串开头是否为2个区域符号组成的国旗emoji，
    若是，则去除，直到开头无此国旗emoji。
    """
    def is_flag_emoji(substr):
        # 判断 substr 是否两个unicode字符都位于国旗unicode区域
        if len(substr) != 2:
            return False
        return all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in substr)
    
    while len(s) >= 2 and is_flag_emoji(s[:2]):
        s = s[2:]
    return s.strip()

def normalize_proxy_names(proxies):
    pattern_trailing_number = re.compile(r'\s*\d+\s*$')
    normalized = []

    for p in proxies:
        name = p.get('name', '').strip()

        # 用循环检测清理开头所有国旗emoji
        name = strip_starting_flags(name)

        # 清理尾部数字序号
        name = pattern_trailing_number.sub('', name).strip()

        p['name'] = name

        # 以下保持现有逻辑不变
        region_info = p.get('region_info', None)
        flag_match = re.search(r'[\U0001F1E6-\U0001F1FF]{2}', name)
        flag_emoji = flag_match.group(0) if flag_match else None

        country_cn = None
        if region_info and 'name' in region_info and region_info['name'] in CUSTOM_REGEX_RULES:
            country_cn = region_info['name']
        elif flag_emoji:
            code = emoji_to_country_code(flag_emoji)
            if code and code in COUNTRY_CODE_TO_CN:
                country_cn = COUNTRY_CODE_TO_CN[code]
        if not country_cn:
            for cname, info in CUSTOM_REGEX_RULES.items():
                if re.search(info['pattern'], name, re.IGNORECASE):
                    country_cn = cname
                    break
        if not country_cn:
            short_name = name[:2] if len(name) >= 2 else name
            country_cn = short_name if short_name else "未知"
            flag_emoji = FLAG_EMOJI_UN_FLAG
        if not flag_emoji:
            code = None
            for k, v in COUNTRY_CODE_TO_CN.items():
                if v == country_cn:
                    code = k
                    break
            flag_emoji = get_country_flag_emoji(code) if code else FLAG_EMOJI_UN_FLAG

        clean_name = country_cn
        p['_norm_flag'] = flag_emoji
        p['_norm_country'] = clean_name
        normalized.append(p)

    grouped = {}
    for p in normalized:
        country = p['_norm_country']
        grouped.setdefault(country, []).append(p)

    final_list = []
    for country, plist in grouped.items():
        for idx, p in enumerate(plist, 1):
            new_name = f"{p['_norm_flag']} {country} {idx}"
            p['name'] = new_name
            del p['_norm_flag']
            del p['_norm_country']
            final_list.append(p)

    return final_list

# ----


def limit_proxy_counts(proxies, max_total=600):
    """
    根据指定规则限制节点数量：
    - ['香港', '日本', '美国', '新加坡'] 每区最多60个；
    - ['德国', '台湾', '韩国'] 每区最多15个；
    - 其他地区 每区最多10个；
    其余地区数量不足照常保留。
    
    总数 <= max_total时不限制。
    先按延迟排序，延迟无值排后。
    返回限制后的节点列表。
    """
    
    if len(proxies) <= max_total:
        return proxies

    limit_60 = {'香港', '日本', '美国', '新加坡'}
    limit_15 = {'德国', '台湾', '韩国'}

    # 按延迟排序，延迟缺失按9999处理
    proxies.sort(key=lambda p: p.get('clash_delay', 9999))

    grouped = defaultdict(list)
    for p in proxies:
        rname = p.get('region_info', {}).get('name') if p.get('region_info') else None
        grouped[rname].append(p)

    selected = []

    # 先选60限制区
    for region in limit_60:
        nodes = grouped.get(region, [])
        selected.extend(nodes[:60])

    # 15限制区
    for region in limit_15:
        nodes = grouped.get(region, [])
        selected.extend(nodes[:15])

    # 其他区域
    other_regions = set(grouped.keys()) - limit_60 - limit_15 - {None}
    for region in other_regions:
        nodes = grouped.get(region, [])
        selected.extend(nodes[:10])

    # 可能有没有地区信息的节点，全部保留
    selected.extend(grouped.get(None, []))

    # 如果数量仍超限，则按延迟排序截断
    if len(selected) > max_total:
        selected.sort(key=lambda p: p.get('clash_delay', 9999))
        selected = selected[:max_total]

    return selected


def generate_config(proxies, last_message_ids):
    return {
        'proxies': proxies,
        'last_message_ids': last_message_ids,
    }


#TCP 测速,测速默认关闭
def run_speedtest(enable_tcp_log=False):
    cmd = ['./xcspeedtest', '--verbose']  # 具体参数视版本而定
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    while True:
        line = process.stdout.readline()
        if line == '' and process.poll() is not None:
            break
        if line:
            if 'TCP' in line:
                if enable_tcp_log:
                    print(line.strip())
                else:
                    # TCP日志关闭 不打印
                    pass
            else:
                print(line.strip())
                
    stderr_lines = process.stderr.read().splitlines()
    for line in stderr_lines:
        if 'TCP' in line:
            if enable_tcp_log:
                print(line.strip())
        else:
            print(line.strip())
    
    return process.poll()


def tcp_ping(proxy, timeout=TCP_TIMEOUT):
    """
    纯 TCP 连接测延迟，返回延迟（ms）或 None
    """
    server = proxy.get('server')
    port = proxy.get('port')
    if not server or not port:
        return None
    
    try:
        start = time.time()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((server, int(port)))
        delay_ms = int((time.time() - start) * 1000)
        # 过滤异常值（<1ms 基本是假的）
        if 1 < delay_ms <= 5000:
            return delay_ms
        else:
            return None
    except:
        return None
        

# 锚点

def test_proxy_with_clash(clash_path, proxy):
    delay = clash_test_proxy(clash_path, proxy)
    if delay is not None:
        proxy['clash_delay'] = delay
        return proxy
    return None



def batch_tcp_test(proxies, max_workers=TCP_MAX_WORKERS):
    """超高并发 TCP 测速"""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {executor.submit(tcp_ping, p): p for p in proxies}
        for future in as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            delay = future.result()
            if delay is not None and delay <= TCP_MAX_DELAY:
                proxy = proxy.copy()  # 避免修改原字典
                proxy['tcp_delay'] = delay
                results.append(proxy)
                print(f"TCP PASS: {delay:4d}ms → {proxy.get('name', '')[:40]}")
            else:
                if delay:
                    print(f"TCP SLOW: {delay:4d}ms → 丢弃 {proxy.get('name', '')[:40]}")
    return results

def batch_test_proxies_speedtest(speedtest_path, proxies, max_workers=32, debug=False):
    """
    使用 speedtest-clash 批量测试代理延迟。
    :param speedtest_path: speedtest-clash 二进制路径
    :param proxies: 代理节点列表
    :param max_workers: 最大并发数
    :param debug: 是否打印详细测速日志
    :return: 测速成功并带延迟字段的代理列表
    """
        
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(xcspeedtest_test_proxy, speedtest_path, proxy, debug): proxy
            for proxy in proxies
        }
        for future in concurrent.futures.as_completed(futures):
            proxy = futures[future]
            try:
                delay = future.result()
            except Exception as e:
                if debug:
                    print(f"[speedtest-clash] 测速异常: 节点 {proxy.get('name')} 错误: {e}")
                delay = None
            if delay is not None:
                pcopy = proxy.copy()
                pcopy['clash_delay'] = delay
                if debug:
                    print(f"[speedtest-clash] 节点 {proxy.get('name')} 测速延迟: {delay} ms")
                results.append(pcopy)
            else:
                if debug:
                    print(f"[speedtest-clash] 节点 {proxy.get('name')} 测速失败或超时")
    return results


# clash 测速

def xcspeedtest_test_proxy(speedtest_path, proxy, debug=True):
    """
    使用 speedtest-clash 二进制以 -fast 参数测试代理延迟，成功返回延迟(ms)，失败返回None。
    debug=True 时打印测速日志和延迟信息。
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'config.yaml')
            config = {
                "port": 7890,
                "socks-port": 7891,
                "allow-lan": False,
                "mode": "Rule",
                "log-level": "silent",
                "proxies": [proxy],
                "proxy-groups": [{"name": "TESTGROUP", "type": "select", "proxies": [proxy["name"]]}],
                "rules": ["MATCH,DIRECT"]
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, sort_keys=False)

            cmd = [speedtest_path, '-c', config_path, '-fast']
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=25, text=True)
            output = result.stdout + result.stderr

            if debug:
                print(f"[speedtest-clash 日志] 输出:\n{output}")

            import re
            m = re.search(r"delay[:\s]*([0-9\.]+)\s*ms", output, re.I)
            if m:
                delay = int(float(m.group(1)))
                if debug:
                    print(f"[speedtest-clash 日志] 代理 {proxy.get('name')} 延迟: {delay} ms")
                if 1 < delay < 800:
                    return delay

            # 如果没捕获到 delay 关键字，则尝试抓取所有合理数字最小的作为备用
            delays = re.findall(r'(\d+)', output)
            delays = [int(d) for d in delays if 1 < int(d) < 800]
            if delays:
                delay = min(delays)
                if debug:
                    print(f"[speedtest-clash 日志] 代理 {proxy.get('name')} 替代延迟: {delay} ms")
                return delay

    except Exception as e:
        if debug:
            print(f"[speedtest-clash 日志] 测速异常: {e}")
    return None



def clash_test_proxy(clash_path, proxy, debug=False):
    temp_dir = tempfile.mkdtemp()
    config_path = os.path.join(temp_dir, 'config.yaml')
    try:
        for test_url in TEST_URLS:
            config = {
                "port": 7890,
                "socks-port": 7891,
                "allow-lan": False,
                "mode": "Rule",
                "log-level": "silent",
                "proxies": [proxy],
                "proxy-groups": [{"name": "TESTGROUP", "type": "select", "proxies": [proxy["name"]]}],
                "rules": [f"DOMAIN,{urlparse(test_url).netloc},TESTGROUP", "MATCH,DIRECT"]
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, sort_keys=False)
            cmd = [clash_path, '-c', config_path, '-fast']
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=22,
                text=True
            )
            output = (result.stdout + result.stderr).replace('\x00', '')
            if debug:
                print(f"\n=== [-fast] 测试 URL: {test_url} [{proxy['name']}] ===\n{output}\n{'='*60}")
            # 解析延迟，逻辑同之前
            match = re.search(r'\b(\d+)ms\b(?=\s*$)', output, re.MULTILINE)
            if match:
                delay = int(match.group(1))
                if 1 < delay < 800:
                    if debug:
                        print(f"成功抓到延迟: {delay}ms → 保留")
                    return delay
            delays = re.findall(r'\b([2-9]\d{1,3})\b', output)
            if delays:
                delay = min(int(x) for x in delays if int(x) < 800)
                if delay > 1:
                    return delay
            if re.search(r'\b(0\s*ms|1\s*ms|NA)\b', output, re.I):
                if debug:
                    print("检测到 0ms/1ms/NA → 丢弃")
                return None
        # 所有测速地址都无结果时返回 None
        if debug:
            print(f"所有测速地址均未通过 → 丢弃: {proxy['name']}")
    except subprocess.TimeoutExpired:
        if debug:
            print(f"[-fast] 测速超时 → 丢弃: {proxy['name']}")
    except Exception as e:
        if debug:
            print(f"[-fast] 异常: {proxy['name']} → {e}")
    finally:
        try:
            shutil.rmtree(temp_dir)
        except:
            pass
    return None




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

def main():
    if not ENABLE_SPEED_TEST:
        print("测速功能未启用，跳过测速。")
        return
    
    ret = run_speedtest(enable_tcp_log=ENABLE_TCP_LOG)
    print(f"测速进程返回码：{ret}")   

if __name__ == "__main__":
    asyncio.run(main())

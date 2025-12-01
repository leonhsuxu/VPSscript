# 文件名: TelegramNode/telegram_publiclink.py
# -*- coding: utf-8 -*-
# ============================================================================
# Clash 订阅自动生成脚本 V1.R5 - 20251201
#
# 版本历史:
# 2种下载方式，优先使用 wget
# 支持解析Base64编码，增加对 Trojan、Hysteria 和 Hysteria2 协议的支持
# 对节点进行标准化处理，滤除广告、识别地区，并重命名为 [旗帜] [地区] [特征] 的统一格式
# 持续增量写入 telegram_scraper.yaml 文件，写入后节点去重，并进行TCP测速
# ============================================================================
import os
import re
import asyncio
import yaml
import base64
import json
import time
import requests  # 引入 requests 库
from datetime import datetime, timedelta, timezone
import sys
from collections import defaultdict
import socket
import concurrent.futures
import hashlib
import subprocess
import shutil
import calendar  # 引入 calendar 用于获取当前星期几
# --- Telethon ---
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaWebPage
from telethon.sessions import StringSession

# ========================== 配置区 ==========================
API_ID = os.environ.get('TELEGRAM_API_ID')  # 获取 Telegram API ID
API_HASH = os.environ.get('TELEGRAM_API_HASH')  # 获取 Telegram API HASH
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')  # 获取 Telegram 会话字符串
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS')  # 获取 Telegram 频道 ID
TIME_WINDOW_HOURS = 72  # 抓取消息的时间窗口，单位为小时
MIN_EXPIRE_HOURS = 7  # 订阅链接的最小剩余有效期，单位为小时
OUTPUT_FILE = 'flclashyaml/telegram_scraper.yaml'  # 输出的 YAML 配置文件路径
ENABLE_SPEED_TEST = True  # 是否启用节点测速功能
SOCKET_TIMEOUT = 8  # 节点测速的 TCP 连接超时时间，单位为秒
MAX_TEST_WORKERS = 128  # 最大并发测速线程数
TEST_URL = 'http://www.gstatic.com/generate_204'  # 测速的 URL
TEST_INTERVAL = 300  # 测速间隔，单位为秒

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

# 正则用于过滤含有一些无用信息的模式
JUNK_PATTERNS = re.compile(r"(?:专线|IPLC|体验|官网|倍率|x\d[\.\d]*|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)", re.IGNORECASE)
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')

# =================================================================================
# Part 2: 函数定义
# =================================================================================

def parse_expire_time(text):
    """解析消息中的到期时间"""
    match = re.search(r'到期时间[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', text)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            return None
    return None

def is_expire_time_valid(expire_time):
    """检查订阅链接是否在有效期内"""
    if expire_time is None:
        return True
    hours_remaining = (expire_time - datetime.now(timezone(timedelta(hours=8)))).total_seconds() / 3600
    if hours_remaining < MIN_EXPIRE_HOURS:
        print(f"  ❌ 已跳过: 链接剩余时间 ({hours_remaining:.1f} 小时) 少于最低要求 ({MIN_EXPIRE_HOURS} 小时)")
        return False
    return True

async def scrape_telegram_links():
    """从 Telegram 频道抓取订阅链接"""
    if not all([API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS_STR]):
        print("❌ 错误: 缺少必要的环境变量 (API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS)。")
        return []

    # 处理频道 ID 列表
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
            async for message in client.iter_messages(await client.get_entity(channel_id), limit=500):
                if message.date < target_time:
                    break
                if message.text and is_expire_time_valid(parse_expire_time(message.text)):
                    for url in re.findall(r'订阅链接[:：]`]*\s*(https?://[^\s<>"*`]+)', message.text):
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
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(
            sorted(CUSTOM_REGEX_RULES[region]['pattern'].split('|'), key=len, reverse=True)
        )

def get_country_flag_emoji(code):
    """根据国家代码生成旗帜 Emoji"""
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in code) if code and len(code) == 2 else "❓"

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
            return proxies if isinstance(proxies, list) else []
        elif isinstance(data, list):
            return data  # 如果 content 是一个直接的代理列表
        else:
            print(f"  - 警告: 解析的内容不是有效的 proxies 格式: {str(content)[:100]}")
            return []
    except (yaml.YAMLError, AttributeError) as e:
        print(f"  - YAML 解析错误: {e}")
        return []
    except Exception as e:
        print(f"  - 解析内容时其他错误: {e}")
        return []


def is_base64(string):
    """检查字符串是否是有效的 Base64 编码"""
    try:
        # 移除所有空白字符
        s = ''.join(string.split())
        if not s or len(s) % 4 != 0:
            return False
        # 检查是否只包含Base64字符
        if not re.match(r'^[A-Za-z0-9+/=]+$', s):
            return False
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False


def decode_base64_and_parse(base64_str):
    """解码 Base64 并解析为 Clash 格式的节点"""
    try:
        # 移除所有空白字符后再解码
        decoded_content = base64.b64decode(''.join(base64_str.split())).decode('utf-8', errors='ignore')
        proxies = []
        for line in decoded_content.splitlines():
            line = line.strip()
            proxy = None
            if line.startswith('vless://'):
                proxy = parse_vless_node(line)
            elif line.startswith('vmess://'):
                proxy = parse_vmess_node(line)
            elif line.startswith('ssr://'):
                proxy = parse_ssr_node(line)
            elif line.startswith('ss://'):
                proxy = parse_ss_node(line)
            elif line.startswith('trojan://'):
                proxy = parse_trojan_node(line)
            elif line.startswith('hysteria://'):
                proxy = parse_hysteria_node(line)
            elif line.startswith('hysteria2://'):
                proxy = parse_hysteria2_node(line)
            
            if proxy:
                proxies.append(proxy)
        return [p for p in proxies if p]
    except Exception as e:
        print(f"  - 解码 Base64 并解析时出错: {e}")
        return []

def parse_vless_node(node_str):
    # 此函数在原代码中缺失，此处补充一个基本实现
    try:
        from urllib.parse import urlparse, parse_qs
        uri = urlparse(node_str)
        params = parse_qs(uri.query)
        
        proxy = {
            "name": uri.fragment or f"VLESS {uri.hostname}:{uri.port}",
            "type": "vless",
            "server": uri.hostname,
            "port": int(uri.port),
            "uuid": uri.username,
            "tls": params.get('security', ['none'])[0] == 'tls',
            "network": params.get('type', ['tcp'])[0],
            "servername": params.get('sni', [uri.hostname])[0],
        }
        return proxy
    except Exception as e:
        print(f"  - 解析 VLESS 节点时发生错误: {e}")
        return {}

def parse_ssr_node(node_str):
    """解析 SSR 节点字符串并转换为 Clash 格式"""
    try:
        # SSR链接需要特殊处理，因为它的base64不是标准格式
        node_str = node_str[6:]
        missing_padding = len(node_str) % 4
        if missing_padding:
            node_str += '=' * (4 - missing_padding)
        decoded = base64.urlsafe_b64decode(node_str).decode('utf-8')
        
        parts = decoded.split('/?')
        main_part, params_part = parts[0], parts[1] if len(parts) > 1 else ''
        
        main_params = main_part.split(':')
        server = main_params[0]
        port = main_params[1]
        protocol = main_params[2]
        method = main_params[3]
        obfs = main_params[4]
        password_encoded = main_params[5]
        
        password = base64.urlsafe_b64decode(password_encoded + '=' * (-len(password_encoded) % 4)).decode('utf-8')

        proxy = {
            "name": f"SSR {server}:{port}",
            "type": "ssr",
            "server": server,
            "port": int(port),
            "password": password,
            "cipher": method,
            "obfs": obfs,
            "protocol": protocol,
        }
        return proxy
    except Exception as e:
        print(f"  - 解析 SSR 节点时发生错误: {e}")
        return {}

def parse_vmess_node(node_str):
    """解析 Vmess 节点字符串并转换为 Clash 格式"""
    try:
        # Vmess链接的base64部分可能没有padding
        base64_str = node_str[8:]
        decoded_str = base64.urlsafe_b64decode(base64_str + '=' * (-len(base64_str) % 4)).decode('utf-8')
        json_data = json.loads(decoded_str)

        proxy = {
            "name": json_data.get('ps', f"Vmess {json_data.get('add')}:{json_data.get('port')}"),
            "type": "vmess",
            "server": json_data.get('add'),
            "port": int(json_data.get('port')),
            "uuid": json_data.get('id'),
            "alterId": int(json_data.get('aid')),
            "cipher": json_data.get('scy', "auto"),
            "tls": json_data.get('tls') == "tls",
            "network": json_data.get('net'),
            "ws-opts": {"path": json_data.get('path'), "headers": {"Host": json_data.get('host')}} if json_data.get('net') == 'ws' else None,
            "servername": json_data.get('sni', json_data.get('host')),
        }
        # 清理None值
        if proxy["ws-opts"]:
            proxy["ws-opts"] = {k: v for k, v in proxy["ws-opts"].items() if v}
        proxy = {k: v for k, v in proxy.items() if v is not None}
        return proxy
    except Exception as e:
        print(f"  - 解析 Vmess 节点时发生错误: {e}")
        return {}


def parse_ss_node(node_str):
    """解析 SS 节点字符串并转换为 Clash 格式"""
    try:
        from urllib.parse import urlparse, unquote
        uri = urlparse(node_str)
        
        # Base64部分在userinfo
        userinfo_decoded = base64.urlsafe_b64decode(uri.userinfo + '=' * (-len(uri.userinfo) % 4)).decode('utf-8')
        cipher, password = userinfo_decoded.split(':', 1)

        proxy = {
            "name": unquote(uri.fragment) if uri.fragment else f"SS {uri.hostname}:{uri.port}",
            "type": "ss",
            "server": uri.hostname,
            "port": int(uri.port),
            "password": password,
            "cipher": cipher
        }
        return proxy
    except Exception as e:
        # 尝试旧版解析
        try:
            # ss://method:password@server:port#name
            parts = node_str[5:].split('#')
            main_part = parts[0]
            name = unquote(parts[1]) if len(parts) > 1 else None

            at_parts = main_part.split('@')
            cred, server_info = at_parts[0], at_parts[1]
            
            cred_decoded = base64.urlsafe_b64decode(cred + '=' * (-len(cred) % 4)).decode('utf-8')
            cipher, password = cred_decoded.split(':', 1)
            
            server, port = server_info.split(':')
            
            proxy = {
                "name": name or f"SS {server}:{port}",
                "type": "ss",
                "server": server,
                "port": int(port),
                "password": password,
                "cipher": cipher
            }
            return proxy
        except Exception as e_inner:
            print(f"  - 解析 SS 节点时发生错误 (两种方法均失败): {e_inner}")
            return {}

def parse_trojan_node(node_str):
    """解析 Trojan 节点字符串并转换为 Clash 格式"""
    try:
        from urllib.parse import urlparse, parse_qs, unquote
        uri = urlparse(node_str)
        params = parse_qs(uri.query)

        proxy = {
            "name": unquote(uri.fragment) if uri.fragment else f"Trojan {uri.hostname}:{uri.port}",
            "type": "trojan",
            "server": uri.hostname,
            "port": int(uri.port),
            "password": uri.username,
            "sni": params.get('sni', [uri.hostname])[0],
            "alpn": params.get('alpn', [None])[0],
        }
        if proxy.get('alpn'):
             proxy['alpn'] = proxy['alpn'].split(',')
        proxy = {k: v for k, v in proxy.items() if v is not None}
        return proxy
    except Exception as e:
        print(f"  - 解析 Trojan 节点时发生错误: {e}")
        return {}


def parse_hysteria_node(node_str):
    """解析 Hysteria 节点字符串并转换为 Clash 格式"""
    try:
        from urllib.parse import urlparse, parse_qs
        uri = urlparse(node_str)
        params = parse_qs(uri.query)

        proxy = {
            "name": uri.fragment or f"Hysteria {uri.hostname}:{uri.port}",
            "type": "hysteria",
            "server": uri.hostname,
            "port": int(uri.port),
            "auth_str": params.get('auth', [None])[0] or uri.username,
            "up": int(params['up_mbps'][0]),
            "down": int(params['down_mbps'][0]),
            "protocol": params.get('protocol', ['udp'])[0],
            "sni": params.get('sni', [uri.hostname])[0],
            "insecure": params.get('insecure', ['0'])[0] == '1',
            "obfs": params.get('obfs', [None])[0],
        }
        proxy = {k: v for k, v in proxy.items() if v is not None}
        return proxy
    except Exception as e:
        print(f"  - 解析 Hysteria 节点时发生错误: {e}")
        return {}


def parse_hysteria2_node(node_str):
    """解析 Hysteria2 节点字符串并转换为 Clash 格式"""
    try:
        from urllib.parse import urlparse, parse_qs, unquote
        uri = urlparse(node_str)
        params = parse_qs(uri.query)

        proxy = {
            "name": unquote(uri.fragment) if uri.fragment else f"Hysteria2 {uri.hostname}:{uri.port}",
            "type": "hysteria2",
            "server": uri.hostname,
            "port": int(uri.port),
            "password": uri.username,
            "sni": params.get('sni', [uri.hostname])[0],
            "insecure": params.get('insecure', ['0'])[0] == '1',
            "obfs": params.get('obfs', [None])[0],
            "obfs-password": params.get('obfs-password', [None])[0],
        }
        proxy = {k: v for k, v in proxy.items() if v is not None}
        return proxy
    except Exception as e:
        print(f"  - 解析 Hysteria2 节点时发生错误: {e}")
        return {}


def download_subscription(url):
    """下载并解析订阅链接，优先使用 wget，失败后尝试 requests"""
    content = attempt_download_using_wget(url)
    if content is None:
        content = attempt_download_using_requests(url)

    if content is None:
        print(f"  ❌ 两种下载方式均失败，跳过链接: {url}")
        return []

    print(f"  - 下载内容长度: {len(content)}")
    
    # 尝试直接解析为YAML
    proxies = parse_proxies_from_content(content)
    if proxies:
        return proxies

    # 如果YAML解析失败或为空，再检查是否为Base64
    if is_base64(content):
        print("  - 内容识别为 Base64，正在解码...")
        return decode_base64_and_parse(content)
        
    print("  - 警告: 内容既不是有效的 YAML/JSON proxies 格式，也不是 Base64 编码。")
    return []

def test_single_proxy_tcp(proxy):
    """使用 TCP 连接测速（兼容所有协议）"""
    try:
        start = time.time()
        with socket.create_connection((proxy['server'], proxy['port']), timeout=SOCKET_TIMEOUT) as sock:
            end = time.time()
            proxy['delay'] = int((end - start) * 1000)
            return proxy
    except Exception:
        return None

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

def process_proxies(proxies):
    """过滤、验证、识别地区并重命名节点"""
    identified = []
    for p in proxies:
        if not is_valid_proxy(p):
            # print(f"  - 过滤无效节点: {p.get('name', '未知')}")
            continue
        name = JUNK_PATTERNS.sub('', FLAG_EMOJI_PATTERN.sub('', p.get('name', ''))).strip()
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            name = re.sub(r'\b' + re.escape(eng) + r'\b', chn, name, flags=re.IGNORECASE)
        for r_name, rules in CUSTOM_REGEX_RULES.items():
            if re.search(rules['pattern'], name, re.IGNORECASE) and r_name in ALLOWED_REGIONS:
                p['region_info'] = {'name': r_name, 'code': rules['code']}
                identified.append(p)
                break

    print(f"  - 节点过滤: 原始 {len(proxies)} -> 识别并保留 {len(identified)}")
    
    final, counters = [], defaultdict(lambda: defaultdict(int))
    master_pattern = re.compile(
        '|'.join(sorted([p for r in CUSTOM_REGEX_RULES.values() for p in r['pattern'].split('|')], key=len, reverse=True)),
        re.IGNORECASE
    )
    
    for p in identified:
        info = p['region_info']
        match = FLAG_EMOJI_PATTERN.search(p['name'])
        flag = match.group(0) if match else get_country_flag_emoji(info['code'])
        
        # 清理名称以提取特征
        clean_name = master_pattern.sub('', FLAG_EMOJI_PATTERN.sub('', p['name'], 1)).strip()
        clean_name = re.sub(r'^\W+|\W+$', '', clean_name) # 移除开头和结尾的非字母数字字符
        feature = re.sub(r'\s+', ' ', clean_name).strip() or f"{info['code']}{sum(1 for fp in final if fp['region_info']['name'] == info['name']) + 1:02d}"
        
        new_name = f"{flag} {info['name']} {feature}".strip()
        counters[info['name']][new_name] += 1
        if counters[info['name']][new_name] > 1:
            new_name += f" {counters[info['name']][new_name]}"
        
        p['name'] = new_name
        final.append(p)
    return final

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
    """主函数"""
    print("=" * 60 + f"\nClash 订阅自动生成脚本 V1.R5 @ {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S %Z')}\n" + "=" * 60)
    preprocess_regex_rules()
    
    # 周一删除旧文件
    delete_old_yaml()

    # --- 步骤 1: 从 Telegram 抓取新节点 ---
    print("\n[1/5] 从 Telegram 抓取新节点...")
    urls = await scrape_telegram_links()
    new_proxies_list = [p for url in urls for p in download_subscription(url) if p] if urls else []
    
    # 去重抓取到的新节点
    new_proxies_map = {}
    for p in new_proxies_list:
        key = get_proxy_key(p)
        if key not in new_proxies_map:
            new_proxies_map[key] = p
    print(f"✅ 从 Telegram 抓取并去重后，获得 {len(new_proxies_map)} 个新节点。")
    
    # --- 步骤 2: 读取现有节点 ---
    print("\n[2/5] 读取现有节点...")
    existing_proxies = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                loaded_yaml = yaml.safe_load(f)
                if isinstance(loaded_yaml, dict) and 'proxies' in loaded_yaml:
                    # 确保读取的是一个列表
                    if isinstance(loaded_yaml['proxies'], list):
                        existing_proxies = [p for p in loaded_yaml['proxies'] if isinstance(p, dict)]
                        print(f"  - 成功读取 {len(existing_proxies)} 个现有节点。")
                elif isinstance(loaded_yaml, list): # 兼容旧的纯列表格式
                    existing_proxies = [p for p in loaded_yaml if isinstance(p, dict)]
                    print(f"  - 成功读取 {len(existing_proxies)} 个现有节点 (来自旧的列表格式)。")
        except Exception as e:
            print(f"  - 警告: 读取或解析 {OUTPUT_FILE} 失败: {e}。")

    # --- 步骤 3: 合并并去重所有节点 ---
    print("\n[3/5] 合并并去重节点...")
    all_proxies_map = {get_proxy_key(p): p for p in existing_proxies}
    added_count = 0
    for key, p in new_proxies_map.items():
        if key not in all_proxies_map:
            all_proxies_map[key] = p
            added_count += 1
    
    all_proxies_list = list(all_proxies_map.values())
    print(f"✅ 合并完成: 新增 {added_count} 个节点，总计 {len(all_proxies_list)} 个不重复节点。")
    
    if not all_proxies_list:
        sys.exit("\n❌ 无任何可用节点，脚本终止。")
    
    # --- 步骤 4: 过滤、重命名、测速与排序 ---
    print("\n[4/5] 处理、测速与排序节点...")
    processed = process_proxies(all_proxies_list)
    if not processed:
        sys.exit("\n❌ 过滤和重命名后无任何可用节点，脚本终止。")

    final = processed
    if ENABLE_SPEED_TEST:
        print(f"  - 开始 TCP 连接测速（超时: {SOCKET_TIMEOUT}秒, 并发: {MAX_TEST_WORKERS}）...")
        with concurrent.futures.ThreadPoolExecutor(MAX_TEST_WORKERS) as executor:
            tested = list(executor.map(test_single_proxy_tcp, processed))
        
        final = [p for p in tested if p]
        print(f"  - 测速完成, {len(final)} / {len(processed)} 个节点可用。")
        
        if not final:
            print("\n  ⚠️ 警告: 测速后无可用节点，将使用所有过滤后的节点。")
            final = processed
    
    # 排序
    final.sort(key=lambda p: (REGION_PRIORITY.index(p['region_info']['name']) if p['region_info']['name'] in REGION_PRIORITY else 99, p.get('delay', 9999)))
    print(f"✅ 最终处理完成 {len(final)} 个节点。")
    
    # --- 步骤 5: 生成并写入最终配置文件 ---
    print("\n[5/5] 生成最终配置文件...")
    config = generate_config(final)
    if not config:
        sys.exit("\n❌ 无法生成配置文件。")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2)
        print(f"✅ 配置文件已成功保存至: {OUTPUT_FILE}\n\n🎉 任务全部完成！")
    except Exception as e:
        print(f"❌ 写入最终配置文件时出错: {e}")

if __name__ == '__main__':
    asyncio.run(main())

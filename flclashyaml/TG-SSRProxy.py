"""
FlClash节点获取脚本 V1.r2
-------------------------------------
功能描述：
1. 从当前目录下名为 URL.TXT 的订阅列表文件读取订阅地址，支持模糊匹配脚本文件名筛选。
2. 支持通过 wget 优先下载订阅内容，失败后自动降级使用 requests 模块下载，增加兼容性和稳定性。
3. 自动识别并解析订阅内容：
    - 先尝试将内容解析为 YAML 格式，常见 Clash 订阅格式。
    - 若非 YAML，自动检测是否为 Base64 编码，支持解码并解析常用协议链接（vmess、vless、ssr、ss、trojan、hysteria等）为代理节点。
4. 合并多个订阅代理节点，去重，避免重复节点。
5. 支持纯 Python socket 多线程并发测速节点延迟，剔除无响应节点，提升节点质量。
6. 节点名称智能重命名，根据地区优先级及特征提取生成规范名称，自动添加国旗 Emoji。
7. 根据测速结果及预设地区优先级进行排序，并生成可直接用于 Clash 软件的完整配置文件 YAML。
8. 输出配置文件至当前目录下 TG-SSRProxy.yaml。
9. 设计支持灵活的订阅地址管理及自动化批量同步更新。

版本说明：
V1.r2（2024-06-23）
- 修正了 Base64 填充字符串补全的错误用法（确保 padding 正确拼接 '='）
- 优化了正则表达式预处理，增加 `re.escape` 保护特殊字符，防止异常。
- 统一导入 urllib.parse 函数，避免重复导入。


"""

import os
import re
import sys
import time
import json
import base64
import socket
import shutil
import yaml
import hashlib
import subprocess
import requests
import concurrent.futures
from datetime import datetime
from collections import defaultdict
from urllib.parse import urlparse, parse_qs, unquote

# ========== 基础配置 ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
URL_FILE = os.path.join(SCRIPT_DIR, "URL.TXT")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "TG-SSRProxy.yaml")
CURRENT_SCRIPT_NAME = os.path.splitext(os.path.basename(__file__))[0]
print(f"【FlClash节点获取脚本 V1.r2】")
print(f"当前脚本文件名 (不含扩展名): {CURRENT_SCRIPT_NAME}")

# ========== 测速配置 ==========
ENABLE_SPEED_TEST = True      # 是否启用节点的延迟测速功能，True表示开启，False表示跳过测速步骤
SOCKET_TIMEOUT = 10          # 测速时，socket连接单次请求的超时时间（单位：秒），超时则视为测速失败
MAX_TEST_WORKERS = 256       # 并发测速时的最大线程数，用于控制同时测试的节点数量，数值越大测速越快但占用资源更多

# ========== 区域映射与规则 ==========
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国', '加拿大', '澳大利亚']
CHINESE_COUNTRY_MAP = {
    'US': '美国', 'United States': '美国', 'USA': '美国',
    'JP': '日本', 'Japan': '日本',
    'HK': '香港', 'Hong Kong': '香港',
    'SG': '狮城', 'Singapore': '狮城',
    'TW': '湾省', 'Taiwan': '湾省',
    'KR': '韩国', 'Korea': '韩国', 'KOR': '韩国',
    'DE': '德国', 'Germany': '德国',
    'GB': '英国', 'United Kingdom': '英国', 'UK': '英国',
    'CA': '加拿大', 'Canada': '加拿大',
    'AU': '澳大利亚', 'Australia': '澳大利亚',
}

COUNTRY_NAME_TO_CODE_MAP = {
    "阿根廷": "AR", "澳大利亚": "AU", "奥地利": "AT", "孟加拉国": "BD", "比利时": "BE", "巴西": "BR", "保加利亚": "BG", "加拿大": "CA", "智利": "CL", "哥伦比亚": "CO", "克罗地亚": "HR", "捷克": "CZ", "丹麦": "DK", "埃及": "EG", "爱沙尼亚": "EE", "芬兰": "FI", "法国": "FR", "德国": "DE", "希腊": "GR", "香港": "HK", "匈牙利": "HU", "冰岛": "IS", "印度": "IN", "印度尼西亚": "ID", "爱尔兰": "IE", "以色列": "IL", "意大利": "IT", "日本": "JP", "哈萨克斯坦": "KZ", "韩国": "KR", "拉脱维亚": "LV", "立陶宛": "LT", "卢森堡": "LU", "澳门": "MO", "马来西亚": "MY", "墨西哥": "MX", "摩尔多瓦": "MD", "荷兰": "NL", "新西兰": "NZ", "尼日利亚": "NG", "挪威": "NO", "巴基斯坦": "PK", "菲律宾": "PH", "波兰": "PL", "葡萄牙": "PT", "罗马尼亚": "RO", "俄罗斯": "RU", "沙特阿拉伯": "SA", "塞尔维亚": "RS", "新加坡": "SG", "斯洛伐克": "SK", "斯洛文尼亚": "SI", "南非": "ZA", "西班牙": "ES", "瑞典": "SE", "瑞士": "CH", "台湾": "TW", "泰国": "TH", "土耳其": "TR", "乌克兰": "UA", "阿联酋": "AE", "英国": "GB", "美国": "US", "越南": "VN"
}

JUNK_PATTERNS = re.compile(
    r"(?:专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)|"
    r"(?:(?:[\u2460-\u2473\u2776-\u277F\u2780-\u2789]|免費|回家).*?(?=,|$))",
    re.IGNORECASE)
    
CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'香港|港|HK|Hong Kong|HKBN|HGC|PCCW|WTT'},
    '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|沪日|深日|JP|Japan'},
    '狮城': {'code': 'SG', 'pattern': r'新加坡|坡|狮城|SG|Singapore'},
    '美国': {'code': 'US', 'pattern': r'美国|美|波特兰|达拉斯|Oregon|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥'},
    '湾省': {'code': 'TW', 'pattern': r'台湾|湾省|台|新北|彰化|TW|Taiwan'},
    '韩国': {'code': 'KR', 'pattern': r'韩国|韩|首尔|KR|Korea|KOR|韓'},
    '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'},
    '英国': {'code': 'GB', 'pattern': r'英国|英|UK|GB|United Kingdom|England'},
    '加拿大': {'code': 'CA', 'pattern': r'加拿大|枫叶|多伦多|温哥华|蒙特利尔|CA|Canada'},
    '澳大利亚': {'code': 'AU', 'pattern': r'澳大利亚|澳洲|悉尼|AU|Australia'},
}

# 国旗Emoji匹配
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')

def preprocess_regex_rules():
    """对自定义正则表达式的“或”部分按长度降序排序并转义，防止误匹配和正则异常"""
    for region, rules in CUSTOM_REGEX_RULES.items():
        parts = rules['pattern'].split('|')
        sorted_parts = sorted(parts, key=len, reverse=True)
        escaped_parts = [re.escape(p) for p in sorted_parts]
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(escaped_parts)
preprocess_regex_rules()

def get_country_flag_emoji(country_code):
    if not country_code or len(country_code) != 2:
        return "❓"
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in country_code)

# ------------------ 下载部分 ------------------

def attempt_download_using_wget(url):
    """使用 wget 下载订阅链接"""
    print(f"  ⬇️ 正在使用 wget 下载: {url[:80]}...")
    if not shutil.which("wget"):
        print("  ✗ wget 未安装，无法使用 wget 下载。")
        return None
    try:
        result = subprocess.run(
            ["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", url],
            capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore'
        )
        return result.stdout if result.stdout else None
    except subprocess.CalledProcessError as e:
        print(f"  ✗ wget 下载失败: {e.stderr.strip()}")
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

def download_subscription(url):
    """
    尝试用 wget 下载，失败用 requests。
    优先尝试 YAML 解析，不成则判断 Base64 解码 Clash 节点。
    返回代理列表或空列表。
    """
    content = attempt_download_using_wget(url)
    if content is None:
        content = attempt_download_using_requests(url)
    if content is None:
        return []
    proxies = parse_proxies_from_content(content)
    if proxies:
        return proxies
    if is_base64(content):
        proxies = decode_base64_and_parse(content)
        if proxies:
            return proxies
        print("  - Base64 解码后未解析到 Clash 节点")
    else:
        print("  - 内容非 Base64 编码，无法解析为代理节点")
    return []

# ------------------ 解析部分 ------------------

def parse_proxies_from_content(content):
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            proxies = data.get('proxies', [])
            if isinstance(proxies, list):
                return proxies
        elif isinstance(data, list):
            return data
        print(f"  - 警告: 解析内容格式异常，非列表或字典 proxies 字段")
    except yaml.YAMLError as e:
        print(f"  - YAML 解析错误: {e}")
    except Exception as e:
        print(f"  - 解析异常: {e}")
    return []

def is_base64(string):
    try:
        s = ''.join(string.split())
        if not s or len(s) % 4 != 0:
            return False
        if not re.match(r'^[A-Za-z0-9+/=]+$', s):
            return False
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False

def decode_base64_and_parse(base64_str):
    try:
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
        print(f"  - Base64 解码并解析错误: {e}")
        return []

# ------------------ 协议节点解析 ------------------

def safe_b64decode(data):
    data = data.encode() if isinstance(data, str) else data
    missing_padding = (-len(data)) % 4
    data += b'=' * missing_padding
    return base64.urlsafe_b64decode(data)

def parse_vless_node(node_str):
    try:
        uri = urlparse(node_str)
        params = parse_qs(uri.query)
        proxy = {
            "name": uri.fragment or f"VLESS {uri.hostname}:{uri.port}",
            "type": "vless",
            "server": uri.hostname,
            "port": int(uri.port),
            "uuid": uri.username,
            "tls": params.get('security', ['none'])[0].lower() == 'tls',
            "network": params.get('type', ['tcp'])[0],
            "servername": params.get('sni', [uri.hostname])[0],
        }
        return proxy
    except Exception as e:
        print(f"  - 解析 VLESS 节点错误: {e}")
        return {}

def parse_ssr_node(node_str):
    try:
        node_str = node_str[6:]
        decoded = safe_b64decode(node_str).decode('utf-8')
        parts = decoded.split('/?')
        main_part, params_part = parts[0], parts[1] if len(parts) > 1 else ''
        main_params = main_part.split(':')
        server, port, protocol, method, obfs = main_params[:5]
        password_encoded = main_params[5]
        password = safe_b64decode(password_encoded).decode('utf-8')
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
        print(f"  - 解析 SSR 节点错误: {e}")
        return {}

def parse_vmess_node(node_str):
    try:
        base64_str = node_str[8:]
        decoded_str = safe_b64decode(base64_str).decode('utf-8')
        json_data = json.loads(decoded_str)
        proxy = {
            "name": json_data.get('ps', f"Vmess {json_data.get('add')}:{json_data.get('port')}"),
            "type": "vmess",
            "server": json_data.get('add'),
            "port": int(json_data.get('port')),
            "uuid": json_data.get('id'),
            "alterId": int(json_data.get('aid', 0)),
            "cipher": json_data.get('scy', "auto"),
            "tls": json_data.get('tls', '').lower() == "tls",
            "network": json_data.get('net'),
            "ws-opts": {"path": json_data.get('path', ''), "headers": {"Host": json_data.get('host', '')}} if json_data.get('net') == 'ws' else None,
            "servername": json_data.get('sni') or json_data.get('host'),
        }
        if proxy["ws-opts"]:
            proxy["ws-opts"] = {k: v for k, v in proxy["ws-opts"].items() if v}
            if not proxy["ws-opts"]:
                proxy["ws-opts"] = None
        return {k: v for k, v in proxy.items() if v is not None}
    except Exception as e:
        print(f"  - 解析 Vmess 节点错误: {e}")
        return {}

def parse_ss_node(node_str):
    try:
        uri = urlparse(node_str)
        if uri.username is None:  # 备用旧格式解析
            parts = node_str[5:].split('#')
            main_part = parts[0]
            name = unquote(parts[1]) if len(parts) > 1 else None
            at_parts = main_part.split('@')
            if len(at_parts) != 2:
                raise ValueError("SS URI格式不正确")
            cred, server_info = at_parts
            cred_decoded = safe_b64decode(cred).decode('utf-8')
            cipher, password = cred_decoded.split(':', 1)
            server, port = server_info.split(':')
            return {
                "name": name or f"SS {server}:{port}",
                "type": "ss",
                "server": server,
                "port": int(port),
                "password": password,
                "cipher": cipher,
            }
        else:
            userinfo_decoded = safe_b64decode(uri.username).decode('utf-8')
            cipher, password = userinfo_decoded.split(':', 1)
            return {
                "name": unquote(uri.fragment) if uri.fragment else f"SS {uri.hostname}:{uri.port}",
                "type": "ss",
                "server": uri.hostname,
                "port": int(uri.port),
                "password": password,
                "cipher": cipher,
            }
    except Exception as e:
        print(f"  - 解析 SS 节点错误: {e}")
        return {}

def parse_trojan_node(node_str):
    try:
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
        return {k: v for k, v in proxy.items() if v is not None}
    except Exception as e:
        print(f"  - 解析 Trojan 节点错误: {e}")
        return {}

def parse_hysteria_node(node_str):
    try:
        uri = urlparse(node_str)
        params = parse_qs(uri.query)
        proxy = {
            "name": uri.fragment or f"Hysteria {uri.hostname}:{uri.port}",
            "type": "hysteria",
            "server": uri.hostname,
            "port": int(uri.port),
            "auth_str": params.get('auth', [None])[0] or uri.username,
            "up": int(params.get('up_mbps', [0])[0]),
            "down": int(params.get('down_mbps', [0])[0]),
            "protocol": params.get('protocol', ['udp'])[0],
            "sni": params.get('sni', [uri.hostname])[0],
            "insecure": params.get('insecure', ['0'])[0] == '1',
            "obfs": params.get('obfs', [None])[0],
        }
        return {k: v for k, v in proxy.items() if v is not None}
    except Exception as e:
        print(f"  - 解析 Hysteria 节点错误: {e}")
        return {}

def parse_hysteria2_node(node_str):
    try:
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
        return {k: v for k, v in proxy.items() if v is not None}
    except Exception as e:
        print(f"  - 解析 Hysteria2 节点错误: {e}")
        return {}

# ------------------ 合并去重 ------------------

def get_proxy_key(proxy):
    try:
        identifier = f"{proxy.get('server', '')}:{proxy.get('port', 0)}|"
        if 'uuid' in proxy:
            identifier += proxy['uuid']
        elif 'password' in proxy:
            identifier += proxy['password']
        else:
            identifier += proxy.get('name', '')
        return hashlib.md5(identifier.encode('utf-8')).hexdigest()
    except Exception:
        return None

def merge_and_deduplicate_proxies(subscriptions_proxies):
    unique = {}
    for proxy in subscriptions_proxies:
        if not isinstance(proxy, dict) or 'name' not in proxy:
            continue
        key = get_proxy_key(proxy)
        if key and key not in unique:
            unique[key] = proxy
    return list(unique.values())

# ------------------ 处理重命名及排序 ------------------

def process_and_rename_proxies(proxies):
    country_counters = defaultdict(lambda: defaultdict(int))
    final_proxies = []

    all_names = set()
    for rules in CUSTOM_REGEX_RULES.values():
        all_names.update(rules['pattern'].split('|'))
    for k, v in CHINESE_COUNTRY_MAP.items():
        all_names.add(k)
        all_names.add(v)
    for k in COUNTRY_NAME_TO_CODE_MAP.keys():
        all_names.add(k)

    sorted_names = sorted(all_names, key=len, reverse=True)
    master_pattern = re.compile('|'.join(map(re.escape, sorted_names)), re.IGNORECASE)

    # 识别地区
    for p in proxies:
        name_orig = p.get('name', '')
        name_clean = FLAG_EMOJI_PATTERN.sub('', name_orig)
        name_clean = JUNK_PATTERNS.sub('', name_clean).strip()
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            name_clean = re.sub(r'\b'+re.escape(eng)+r'\b', chn, name_clean, flags=re.IGNORECASE)
        p['region'] = '未知'
        for region_name, rules in CUSTOM_REGEX_RULES.items():
            if re.search(rules['pattern'], name_clean, re.IGNORECASE):
                p['region'] = region_name
                break
        if p['region'] == '未知':
            for cname in COUNTRY_NAME_TO_CODE_MAP.keys():
                if re.search(r'\b' + re.escape(cname) + r'\b', name_clean, re.IGNORECASE):
                    p['region'] = cname
                    break

    # 重命名
    for p in proxies:
        orig_name = p.get('name', '')
        region = p.get('region', '未知')
        region_code = COUNTRY_NAME_TO_CODE_MAP.get(region) or CUSTOM_REGEX_RULES.get(region, {}).get('code', '')
        flag = ""
        match_flag = FLAG_EMOJI_PATTERN.search(orig_name)
        if match_flag:
            flag = match_flag.group(0)
            feature_name = FLAG_EMOJI_PATTERN.sub('', orig_name, 1)
        else:
            flag = get_country_flag_emoji(region_code)
            feature_name = orig_name

        # 移除所有地区关键词及垃圾信息
        feature_name = master_pattern.sub(' ', feature_name)
        feature_name = JUNK_PATTERNS.sub(' ', feature_name)
        feature_name = feature_name.replace('-', ' ').strip()
        feature_name = re.sub(r'\s+', ' ', feature_name).strip()

        if not feature_name:
            idx = sum(1 for fp in final_proxies if fp.get('region') == region) + 1
            feature_name = f"{idx:02d}"

        new_name = f"{flag} {region} {feature_name}".strip()
        country_counters[region][new_name] += 1
        count = country_counters[region][new_name]
        if count > 1:
            new_name = f"{new_name} {count}"

        p['name'] = new_name
        final_proxies.append(p)
    return final_proxies

# ------------------ 节点测速 ------------------

def test_single_proxy_socket(proxy):
    server = proxy.get('server')
    port = proxy.get('port')
    if not server or not port:
        return None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        start = time.time()
        sock.connect((str(server), int(port)))
        end = time.time()
        proxy['delay'] = int((end - start) * 1000)
        return proxy
    except (socket.timeout, ConnectionRefusedError, socket.gaierror, OSError):
        return None
    finally:
        if 'sock' in locals():
            sock.close()

def speed_test_proxies(proxies):
    print(f"开始使用纯 Python socket 进行并发测速 (共 {len(proxies)} 个节点)")
    fast_proxies = []
    total = len(proxies)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TEST_WORKERS) as executor:
        futures = {executor.submit(test_single_proxy_socket, p): p for p in proxies}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            if i % 100 == 0 or i == total:
                print(f"\r  测试进度: {i}/{total}", flush=True)
            if result:
                fast_proxies.append(result)
    print(f"\n测速完成，剩余可用节点: {len(fast_proxies)}")
    return fast_proxies

# ------------------ 配置生成 ------------------

def generate_config(proxies):
    if not proxies:
        return None
    proxy_names = [p['name'] for p in proxies]
    clean_proxies = [{k: v for k, v in p.items() if k not in ['region', 'delay']} for p in proxies]
    return {
        'mixed-port': 7890,
        'allow-lan': True,
        'bind-address': '*',
        'mode': 'rule',
        'log-level': 'info',
        'external-controller': '127.0.0.1:9090',
        'dns': {
            'enable': True,
            'listen': '0.0.0.0:53',
            'enhanced-mode': 'fake-ip',
            'fake-ip-range': '198.18.0.1/16',
            'nameserver': ['223.5.5.5', '119.29.29.29'],
            'fallback': ['https://dns.google/dns-query', 'https://1.1.1.1/dns-query']
        },
        'proxies': clean_proxies,
        'proxy-groups': [
            {'name': '🚀 节点选择', 'type': 'select', 'proxies': ['♻️ 自动选择', '🔯 故障转移', 'DIRECT'] + proxy_names},
            {'name': '♻️ 自动选择', 'type': 'url-test', 'proxies': proxy_names, 'url': 'http://www.gstatic.com/generate_204', 'interval': 300},
            {'name': '🔯 故障转移', 'type': 'fallback', 'proxies': proxy_names, 'url': 'http://www.gstatic.com/generate_204', 'interval': 300}
        ],
        'rules': ['GEOIP,CN,DIRECT', 'MATCH,🚀 节点选择']
    }

# ------------------ 订阅地址读取 ------------------

def load_subscription_urls_from_file(url_file_path, script_name_filter):
    urls = []
    if not os.path.exists(url_file_path):
        print(f"错误: 订阅文件 {url_file_path} 不存在。")
        return urls
    print(f"从 {url_file_path} 读取订阅地址，过滤名称含 '{script_name_filter}' 的条目")
    try:
        with open(url_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                match = re.search(r'([^：]+)：\s*(https?://\S+)', line)
                if match:
                    name_cfg, url = match.group(1).strip(), match.group(2)
                    if script_name_filter in name_cfg:
                        urls.append(url)
                        print(f"  ✓ 找到匹配订阅：'{name_cfg}' -> {url[:80]}")
                    else:
                        print(f"  - 跳过不匹配名称 '{name_cfg}'")
                else:
                    print(f"  ✗ 跳过无效行：{line[:60]}")
    except Exception as e:
        print(f"读取订阅文件错误: {e}")
    return urls

# ------------------ 主流程 ------------------

def main():
    print("=" * 60)
    print(f"订阅链接节点合并 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    subscription_urls = load_subscription_urls_from_file(URL_FILE, CURRENT_SCRIPT_NAME)
    if not subscription_urls:
        sys.exit(f"\n❌ 未能从 {URL_FILE} 获取匹配 '{CURRENT_SCRIPT_NAME}' 的订阅地址。")

    print("\n[1/4] 下载并合并订阅")
    all_proxies = []
    for url in subscription_urls:
        all_proxies.extend(download_subscription(url))

    unique_proxies = merge_and_deduplicate_proxies(all_proxies)
    if not unique_proxies:
        sys.exit("\n❌ 无可用节点，任务终止。")
    print(f"  ✓ 合并去重后共有 {len(unique_proxies)} 个节点。")

    print("\n[2/4] 节点测速")
    if ENABLE_SPEED_TEST:
        available_proxies = speed_test_proxies(unique_proxies)
        if not available_proxies:
            print("\n  ⚠️ 测速无节点可用，将使用全部节点。")
            available_proxies = unique_proxies
    else:
        print("  - 跳过测速，使用全部节点。")
        available_proxies = unique_proxies

    print("\n[3/4] 节点排序与重命名")
    region_order = {region: i for i, region in enumerate(REGION_PRIORITY)}
    available_proxies.sort(key=lambda p: (region_order.get(p.get('region', '未知'), 99), p.get('delay', 9999)))
    final_proxies = process_and_rename_proxies(available_proxies)
    print(f"  ✓ {len(final_proxies)} 个节点处理完成。")

    print("\n[4/4] 生成配置文件")
    config = generate_config(final_proxies)
    if not config:
        sys.exit("\n❌ 配置生成失败。")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2)
    print(f"  ✓ 配置文件已生成到：{OUTPUT_FILE}")

    print("\n✅ 任务完成！")

if __name__ == '__main__':
    main()

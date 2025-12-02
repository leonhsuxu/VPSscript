"""
FlClash节点获取脚本 V1.r3 多区块批处理
-----------------------------------------
功能说明：
本脚本用于从 URL.TXT 文件中读取多个以“#”开头划分的订阅区块，每个区块包含若干订阅链接。
脚本会：
1. 自动识别并拆分多个订阅区块；
2. 针对每个区块，提取所有 HTTP/HTTPS 订阅链接；
3. 依次下载订阅内容（优先使用 wget，失败后使用 requests）；
4. 自动识别 YAML 直接解析，或 Base64 解码并支持多协议节点解析（vmess、vless、ssr、ss、trojan、hysteria等）；
5. 合并去重所有节点，同时支持节点测速（通过纯 Python socket）筛选可用节点；
6. 智能为所有节点添加符合规则的区域标识和国旗 Emoji，并重命名；
7. 按地区优先级及测速结果排序节点；
8. 为每个区块生成独立的 Clash 配置 YAML 文件，文件保存在 output_yaml 目录中。


使用说明：
- 在 URL.TXT 中添加订阅，使用“# 区块名称:”格式划分多个区块，每块下方为相关订阅链接列表
- 运行脚本，即可在 output_yaml 目录中得到分块生成的 YAML 配置文件
"""


import os
import re
import sys
import yaml
import base64
import json
import socket
import shutil
import hashlib
import subprocess
import requests
import concurrent.futures
from datetime import datetime
from collections import defaultdict
from urllib.parse import urlparse, parse_qs, unquote

# ========== 基础配置 ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # 获取当前脚本文件所在的目录路径
URL_FILE = os.path.join(SCRIPT_DIR, "URL.TXT")  # 定义订阅链接文件的路径，文件名为 URL.TXT
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output_yaml")  # 定义输出 YAML 配置文件的目录路径
os.makedirs(OUTPUT_DIR, exist_ok=True)  # 创建输出目录，如果目录已存在则不执行任何操作

# ========== 测速配置 ==========
ENABLE_SPEED_TEST = True  # 是否启用节点测速功能 (True为启用, False为禁用)
SOCKET_TIMEOUT = 10  # 测速时网络连接的超时时间（单位：秒）
MAX_TEST_WORKERS = 256  # 执行测速时的最大并发工作线程数

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
    "阿根廷": "AR", "澳大利亚": "AU", "奥地利": "AT", "孟加拉国": "BD", "比利时": "BE",
    "巴西": "BR", "保加利亚": "BG", "加拿大": "CA", "智利": "CL", "哥伦比亚": "CO",
    "克罗地亚": "HR", "捷克": "CZ", "丹麦": "DK", "埃及": "EG", "爱沙尼亚": "EE",
    "芬兰": "FI", "法国": "FR", "德国": "DE", "希腊": "GR", "香港": "HK", "匈牙利": "HU",
    "冰岛": "IS", "印度": "IN", "印度尼西亚": "ID", "爱尔兰": "IE", "以色列": "IL",
    "意大利": "IT", "日本": "JP", "哈萨克斯坦": "KZ", "韩国": "KR", "拉脱维亚": "LV",
    "立陶宛": "LT", "卢森堡": "LU", "澳门": "MO", "马来西亚": "MY", "墨西哥": "MX",
    "摩尔多瓦": "MD", "荷兰": "NL", "新西兰": "NZ", "尼日利亚": "NG", "挪威": "NO",
    "巴基斯坦": "PK", "菲律宾": "PH", "波兰": "PL", "葡萄牙": "PT", "罗马尼亚": "RO",
    "俄罗斯": "RU", "沙特阿拉伯": "SA", "塞尔维亚": "RS", "新加坡": "SG", "斯洛伐克": "SK",
    "斯洛文尼亚": "SI", "南非": "ZA", "西班牙": "ES", "瑞典": "SE", "瑞士": "CH",
    "台湾": "TW", "泰国": "TH", "土耳其": "TR", "乌克兰": "UA", "阿联酋": "AE",
    "英国": "GB", "美国": "US", "越南": "VN", "阿曼": "OM", "柬埔寨": "KH",
    "秘鲁": "PE", "阿塞拜疆": "AZ", "巴林": "BH"
}

JUNK_PATTERNS = re.compile(
    r"(专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|流量|Relay|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*)",
    re.IGNORECASE
)
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
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')

def preprocess_regex_rules():
    for region, rules in CUSTOM_REGEX_RULES.items():
        parts = rules['pattern'].split('|')
        sorted_parts = sorted(parts, key=len, reverse=True)
        escaped_parts = [re.escape(p) for p in sorted_parts]
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(escaped_parts)
preprocess_regex_rules()

def sanitize_filename(name: str) -> str:
    """提取文件名，只取#和冒号间文字，去除空格和非法字符"""
    match = re.match(r"#\s*(.*?)\s*:", name, re.IGNORECASE)
    if match:
        title = match.group(1)
    else:
        title = name.lstrip('#').strip()
    title = re.sub(r'\s+', '', title)
    title = re.sub(r'[\\/:"*?<>|]+', '_', title)
    return title or 'default'

def get_country_flag_emoji(country_code):
    if not country_code or len(country_code) != 2:
        return "❓"
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in country_code)

def safe_b64decode(data):
    data = data.encode() if isinstance(data, str) else data
    missing_padding = (-len(data)) % 4
    data += b'=' * missing_padding
    return base64.urlsafe_b64decode(data)

# ----- 下载函数 -----
def attempt_download_using_wget(url):
    print(f"  ⬇️ wget 下载: {url[:80]}")
    if not shutil.which("wget"):
        print("  ✗ 未安装 wget")
        return None
    try:
        proc = subprocess.run(
            ["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", url],
            capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore'
        )
        return proc.stdout if proc.stdout else None
    except subprocess.CalledProcessError as e:
        print(f"  ✗ wget 失败: {e.stderr.strip()}")
        return None

def attempt_download_using_requests(url):
    print(f"  ⬇️ requests 下载: {url[:80]}")
    try:
        headers = {'User-Agent': 'Clash'}
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or 'utf-8'
        return r.text
    except Exception as e:
        print(f"  ✗ requests 失败: {e}")
        return None

def download_subscription(url):
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
        print("  - Base64 解码无效节点")
    else:
        print("  - 内容非 Base64")
    return []

# ----- 解析函数 -----
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

def decode_base64_and_parse(content):
    try:
        decoded = base64.b64decode(''.join(content.split())).decode('utf-8', errors='ignore')
        proxies = []
        for line in decoded.splitlines():
            line = line.strip()
            proxy = None
            if line.startswith('vmess://'):
                proxy = parse_vmess_node(line)
            elif line.startswith('vless://'):
                proxy = parse_vless_node(line)
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
        return proxies
    except Exception as e:
        print(f"  - Base64 解码解析异常: {e}")
        return []

# ---- 协议解析函数 -- 同上文，请确保实现 ----

# ----- 合并去重 -----
def get_proxy_key(proxy):
    try:
        key = f"{proxy.get('server', '')}:{proxy.get('port', 0)}|"
        if 'uuid' in proxy:
            key += proxy['uuid']
        elif 'password' in proxy:
            key += proxy['password']
        else:
            key += proxy.get('name', '')
        return hashlib.md5(key.encode('utf-8')).hexdigest()
    except:
        return None

def merge_and_deduplicate_proxies(proxies):
    unique = {}
    for proxy in proxies:
        if not isinstance(proxy, dict) or 'name' not in proxy:
            continue
        k = get_proxy_key(proxy)
        if k and k not in unique:
            unique[k] = proxy
    return list(unique.values())

# ----- 重命名排序 -----
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
    
    for p in proxies:
        name_orig = p.get('name', '')
        name_clean = FLAG_EMOJI_PATTERN.sub('', name_orig)
        name_clean = JUNK_PATTERNS.sub('', name_clean).strip()
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            name_clean = re.sub(r'\b' + re.escape(eng) + r'\b', chn, name_clean, flags=re.IGNORECASE)
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

    for p in proxies:
        orig_name = p.get('name', '')
        region = p.get('region', '未知')
        region_code = COUNTRY_NAME_TO_CODE_MAP.get(region) or CUSTOM_REGEX_RULES.get(region, {}).get('code', '')
        flag = ""
        mf = FLAG_EMOJI_PATTERN.search(orig_name)
        if mf:
            flag = mf.group(0)
            feature_name = FLAG_EMOJI_PATTERN.sub('', orig_name, 1)
        else:
            flag = get_country_flag_emoji(region_code)
            feature_name = orig_name
        
        feature_name = master_pattern.sub(' ', feature_name)
        feature_name = JUNK_PATTERNS.sub(' ', feature_name)
        feature_name = feature_name.replace('-', ' ').strip()
        feature_name = re.sub(r'\s+', ' ', feature_name).strip()
        if not feature_name:
            idx = sum(1 for fp in final_proxies if fp.get('region') == region) + 1
            feature_name = f"{idx:02d}"

        new_name = f"{flag} {region} {feature_name}".strip()
        country_counters[region][new_name] += 1
        c = country_counters[region][new_name]
        if c > 1:
            new_name = f"{new_name} {c}"
        p['name'] = new_name
        final_proxies.append(p)

    return final_proxies

# ----- 测速 -----
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
    except Exception:
        return None
    finally:
        if 'sock' in locals():
            sock.close()

def speed_test_proxies(proxies):
    print(f"开始测速: 共 {len(proxies)} 个节点")
    fast_proxies = []
    total = len(proxies)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TEST_WORKERS) as executor:
        futures = {executor.submit(test_single_proxy_socket, p): p for p in proxies}
        for i, f in enumerate(concurrent.futures.as_completed(futures), 1):
            result = f.result()
            if i % 100 == 0 or i == total:
                print(f"\r测速进度: {i}/{total}", end='', flush=True)
            if result:
                fast_proxies.append(result)
    print()
    print(f"测速完成: 有效节点 {len(fast_proxies)}")
    return fast_proxies

# ----- 配置文件生成 -----
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

# ------------------ 多区块读取与处理 ------------------

def parse_url_txt_to_blocks():
    if not os.path.exists(URL_FILE):
        print(f"文件未找到: {URL_FILE}")
        return []

    with open(URL_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    blocks = []
    current_block = {'title': None, 'lines': []}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('#'):
            if current_block['title']:
                blocks.append(current_block)
            current_block = {'title': stripped, 'lines': []}
        else:
            current_block['lines'].append(stripped)
    if current_block['title']:
        blocks.append(current_block)
    return blocks

def extract_urls_from_lines(lines):
    url_pattern = re.compile(r'https?://[^\s]+', re.IGNORECASE)
    urls = []
    for line in lines:
        urls.extend(url_pattern.findall(line))
    return urls

def process_block_to_yaml(block):
    title = block['title']
    lines = block['lines']
    urls = extract_urls_from_lines(lines)
    if not urls:
        print(f"{title} 区块无有效订阅，跳过。")
        return

    print(f"\n处理区块：{title} | {len(urls)} 个订阅链接")

    all_proxies = []
    for url in urls:
        all_proxies.extend(download_subscription(url))

    if not all_proxies:
        print(f"{title} 订阅下载失败或无节点，跳过。")
        return

    unique_proxies = merge_and_deduplicate_proxies(all_proxies)

    if ENABLE_SPEED_TEST:
        tested_proxies = speed_test_proxies(unique_proxies)
        if not tested_proxies:
            print(f"{title} 测速无可用节点，使用所有节点。")
            tested_proxies = unique_proxies
    else:
        tested_proxies = unique_proxies

    region_order = {r: i for i, r in enumerate(REGION_PRIORITY)}
    tested_proxies.sort(key=lambda p: (region_order.get(p.get('region', '未知'), 999), p.get('delay', 9999)))

    final_proxies = process_and_rename_proxies(tested_proxies)

    config = generate_config(final_proxies)
    if not config:
        print(f"{title} 配置生成失败，跳过。")
        return

    filename = sanitize_filename(title) + ".yaml"
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2)

    print(f"{title} 配置已生成：{filepath}，节点数：{len(final_proxies)}")

def main():
    print("="*60)
    print("FlClash节点获取脚本 V1.r2 多区块批处理")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    blocks = parse_url_txt_to_blocks()
    if not blocks:
        print("未检测到有效区块，退出。")
        return

    for block in blocks:
        process_block_to_yaml(block)

    print(f"\n全部区块处理完成，配置文件存放于：{OUTPUT_DIR}")

if __name__ == "__main__":
    main()

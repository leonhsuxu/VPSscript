"""
固定链接获取节点脚本 V2
-----------------------------------------
功能说明：
本脚本用于从 URL.TXT 文件中读取多个以“#”开头划分的订阅区块，每个区块包含若干订阅链接。
脚本会：
1. 自动识别并拆分多个订阅区块；
2. 针对每个区块，提取所有 HTTP/HTTPS 订阅链接；
3. 依次下载订阅内容（优先使用 wget，失败后使用 requests）；
4. V2.自动识别 YAML 直接解析、再明文判定解析、后 Base64 解码节点解析（vmess、vless、ssr、ss、trojan、hysteria等）；
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
import yaml
import base64
import json
import socket
import shutil
import hashlib
import subprocess
import requests
import concurrent.futures
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from urllib.parse import urlparse, parse_qs, unquote

# ========== 基础配置 ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) # 获取当前脚本文件所在的目录的绝对路径
URL_FILE = os.path.join(SCRIPT_DIR, "URL.TXT") # 构建URL文件的完整路径，该文件应位于脚本同目录下
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output_yaml") # 构建输出目录的完整路径，用于存放生成的YAML文件
os.makedirs(OUTPUT_DIR, exist_ok=True) # 创建输出目录，如果目录已存在则不报错

# ========== 测速配置 ========== # 以下是关于速度测试的配置项
ENABLE_SPEED_TEST = True # 是否启用速度测试，设置为True表示启用
SOCKET_TIMEOUT = 10 # 超时时间（秒）
MAX_TEST_WORKERS = 256 # 最大测试工作线程数，表示同时进行速度测试的最大并发连接数

# ========== 区域映射与规则（合并版） ==========
REGION_PRIORITY = ['香港', '日本', '新加坡', '美国', '台湾', '韩国', '德国', '英国', '加拿大', '澳大利亚']

CHINESE_COUNTRY_MAP = {
    'US': '美国', 'United States': '美国', 'USA': '美国', 'America': '美国',
    'New York': '美国', 'Los Angeles': '美国', 'Washington': '美国', 'Chicago': '美国',
    'San Francisco': '美国', 'Las Vegas': '美国', 'Miami': '美国', 'Seattle': '美国',
    'Houston': '美国', 'Boston': '美国', 'Atlanta': '美国', 'Dallas': '美国',

    'JP': '日本', 'Japan': '日本', 'Tokyo': '日本', 'Osaka': '日本', 'Nagoya': '日本',
    'Sapporo': '日本', 'Fukuoka': '日本', 'NTT': '日本', 'IIJ': '日本', 'GMO': '日本', 'Linode': '日本',

    'HK': '香港', 'Hong Kong': '香港', 'HongKong': '香港', 'HKT': '香港',
    '九龙': '香港', '沙田': '香港', '屯门': '香港', '荃湾': '香港', '深水埗': '香港', '油尖旺': '香港',

    'SG': '新加坡', 'Singapore': '新加坡', 'SGP': '新加坡', 'SG': '新加坡',
    '星': '新加坡', '狮城': '新加坡', '坡': '新加坡',

    'TW': '台湾', 'Taiwan': '台湾', 'TWN': '台湾',
    'Taipei': '台湾', 'Taichung': '台湾', 'Kaohsiung': '台湾',
    '新北': '台湾', '彰化': '台湾', 'Hinet': '台湾', '中华电信': '台湾',

    'KR': '韩国', 'Korea': '韩国', 'KOR': '韩国', 'Seoul': '韩国',
    'Busan': '韩国', 'KT': '韩国', 'SK': '韩国', 'LG': '韩国',
    '南朝鲜': '韩国', '韩': '韩国', '韓': '韩国',

    'DE': '德国', 'Germany': '德国', 'Frankfurt': '德国',
    'Munich': '德国', 'Berlin': '德国', 'Hetzner': '德国',

    'GB': '英国', 'United Kingdom': '英国', 'UK': '英国',
    'England': '英国', 'London': '英国', 'Manchester': '英国',

    'CA': '加拿大', 'Canada': '加拿大', 'Toronto': '加拿大',
    'Vancouver': '加拿大', 'Montreal': '加拿大',

    'AU': '澳大利亚', 'Australia': '澳大利亚',
    'Sydney': '澳大利亚', 'Melbourne': '澳大利亚', 'Brisbane': '澳大利亚',
}


COUNTRY_NAME_TO_CODE_MAP = {
"阿富汗":"AF", "阿尔巴尼亚":"AL", "阿尔及利亚":"DZ", "安道尔":"AD", "安哥拉":"AO", "安圭拉":"AI", 
"安提瓜和巴布达":"AG", "阿根廷":"AR", "亚美尼亚":"AM", "阿鲁巴":"AW", "澳大利亚":"AU", "奥地利":"AT", "阿塞拜疆":"AZ", "巴哈马":"BS", 
"巴林":"BH", "孟加拉国":"BD", "巴巴多斯":"BB", "白俄罗斯":"BY", "比利时":"BE", "伯利兹":"BZ", "贝宁":"BJ", "百慕大":"BM", "不丹":"BT", 
"玻利维亚":"BO", "波黑":"BA", "博茨瓦纳":"BW", "巴西":"BR", "文莱":"BN", "保加利亚":"BG", "布基纳法索":"BF", "布隆迪":"BI", "柬埔寨":"KH", 
"喀麦隆":"CM", "加拿大":"CA", "佛得角":"CV", "开曼群岛":"KY", "中非":"CF", "乍得":"TD", "智利":"CL", "中国":"CN", "哥伦比亚":"CO", 
"科摩罗":"KM", "刚果（金）":"CD", "刚果（布）":"CG", "哥斯达黎加":"CR", "科特迪瓦":"CI", "克罗地亚":"HR", "古巴":"CU", "塞浦路斯":"CY", 
"捷克":"CZ", "丹麦":"DK", "吉布提":"DJ", "多米尼克":"DM", "多米尼加":"DO", "厄瓜多尔":"EC", "埃及":"EG", "萨尔瓦多":"SV", "赤道几内亚":"GQ", 
"厄立特里亚":"ER", "爱沙尼亚":"EE", "埃塞俄比亚":"ET", "斐济":"FJ", "芬兰":"FI", "法国":"FR", "加蓬":"GA", "冈比亚":"GM", "格鲁吉亚":"GE", 
"加纳":"GH", "希腊":"GR", "格林纳达":"GD", "危地马拉":"GT", "几内亚":"GN", "几内亚比绍":"GW", "圭亚那":"GY", "海地":"HT", "洪都拉斯":"HN", 
"匈牙利":"HU", "冰岛":"IS", "印度":"IN", "印尼":"ID", "印度尼西亚":"ID", "伊朗":"IR", "伊拉克":"IQ", "爱尔兰":"IE", "以色列":"IL", 
"意大利":"IT", "牙买加":"JM", "日本":"JP", "约旦":"JO", "哈萨克斯坦":"KZ", "肯尼亚":"KE", "基里巴斯":"KI", "科威特":"KW", 
"吉尔吉斯斯坦":"KG", "老挝":"LA", "拉脱维亚":"LV", "黎巴嫩":"LB", "莱索托":"LS", "利比里亚":"LR", "利比亚":"LY", "列支敦士登":"LI", 
"立陶宛":"LT", "卢森堡":"LU", "澳门":"MO", "北马其顿":"MK", "马达加斯加":"MG", "马拉维":"MW", "马来西亚":"MY", "马尔代夫":"MV", "马里":"ML", 
"马耳他":"MT", "马绍尔群岛":"MH", "毛里塔尼亚":"MR", "毛里求斯":"MU", "墨西哥":"MX", "密克罗尼西亚":"FM", "摩尔多瓦":"MD", "摩纳哥":"MC", 
"蒙古":"MN", "黑山":"ME", "摩洛哥":"MA", "莫桑比克":"MZ", "缅甸":"MM", "纳米比亚":"NA", "瑙鲁":"NR", "尼泊尔":"NP", "荷兰":"NL", "新西兰":"NZ", 
"尼加拉瓜":"NI", "尼日尔":"NE", "尼日利亚":"NG", "挪威":"NO", "阿曼":"OM", "巴基斯坦":"PK", "帕劳":"PW", "巴勒斯坦":"PS", "巴拿马":"PA", 
"巴布亚新几内亚":"PG", "巴拉圭":"PY", "秘鲁":"PE", "菲律宾":"PH", "波兰":"PL", "葡萄牙":"PT", "卡塔尔":"QA", "罗马尼亚":"RO", "俄罗斯":"RU", 
"卢旺达":"RW", "圣马力诺":"SM", "沙特阿拉伯":"SA", "塞内加尔":"SN", "塞尔维亚":"RS", "塞舌尔":"SC", "塞拉利昂":"SL", "新加坡":"SG", "斯洛伐克":"SK", 
"斯洛文尼亚":"SI", "所罗门群岛":"SB", "索马里":"SO", "南非":"ZA", "西班牙":"ES", "斯里兰卡":"LK", "苏丹":"SD", "苏里南":"SR", "瑞典":"SE", 
"瑞士":"CH", "叙利亚":"SY", "塔吉克斯坦":"TJ", "坦桑尼亚":"TZ", "泰国":"TH", "东帝汶":"TL", "多哥":"TG", "汤加":"TO", "特立尼达和多巴哥":"TT", 
"突尼斯":"TN", "土耳其":"TR", "土库曼斯坦":"TM", "图瓦卢":"TV", "乌干达":"UG", "乌克兰":"UA", "阿联酋":"AE", "乌拉圭":"UY", "乌兹别克斯坦":"UZ", 
"瓦努阿图":"VU", "委内瑞拉":"VE", "越南":"VN", "也门":"YE", "赞比亚":"ZM", "津巴布韦":"ZW"
}


JUNK_PATTERNS = re.compile(
    r"(?:专线|IPLC|IEPL|BGP|体验|丑团|官网|倍率|x\d[\.\d]*|Rate|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)"
    r"|(?:(?:[\u2460-\u2473\u2776-\u277F\u2780-\u2789]|免費|回家).*?(?=,|$))",
    re.IGNORECASE
)

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
    import re
    match = re.match(r"#\s*(.*?)\s*[:：]", name, re.IGNORECASE)
    if match:
        title = match.group(1)
    else:
        title = name.lstrip('#').strip()
        title = re.sub(r'[:：]+$', '', title).strip()
    title = re.sub(r'[\\/:*?"<>|\s：]+', '_', title)
    title = title.strip('_')
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

# ----- 下载相关 -----
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

# ----- 新增函数：解析明文协议节点 -----
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
        else:
            continue

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

# ----- 修改 download_subscription 函数 -----
def download_subscription(url):
    content = attempt_download_using_wget(url)
    if content is None:
        content = attempt_download_using_requests(url)
    if content is None:
        return []

    # 先尝试yaml格式直接解析
    proxies = parse_proxies_from_content(content)
    if proxies:
        return proxies

    # 尝试从明文协议链接中提取节点
    proxies = parse_plain_nodes_from_text(content)
    if proxies:
        return proxies

    # 再尝试base64编码解码并解析
    if is_base64(content):
        proxies = decode_base64_and_parse(content)
        if proxies:
            return proxies
        print("  - Base64 解码无效节点")
    else:
        print("  - 内容非 Base64，且未匹配到明文协议节点")

    return []

# ----- 解析相关 -----
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
            else:
                continue

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


# ----- 协议解析实现 -----
def parse_vmess_node(line):
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
        node = {
            'name': unquote(parsed.fragment) or f"hysteria2_{parsed.hostname}",
            'type': 'hysteria2',
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

# ----- 重点函数：重命名排序 -----
def process_and_rename_proxies(proxies):
    country_counters = defaultdict(int)
    final_proxies = []
    all_country_names = set()
    # 构造所有可能国家名称集合
    
    for rules in CUSTOM_REGEX_RULES.values():
        # 建议 here 应该用更合适的方式获取国家名
        all_country_names.update(rules['pattern'].split('|'))

    all_country_names.update(CHINESE_COUNTRY_MAP.keys())
    all_country_names.update(CHINESE_COUNTRY_MAP.values())
    all_country_names.update(COUNTRY_NAME_TO_CODE_MAP.keys())

    sorted_country_names = sorted(all_country_names, key=len, reverse=True)
    country_pattern = re.compile('|'.join(map(re.escape, sorted_country_names)), re.IGNORECASE)
    speed_pattern = re.compile(r'(\d+(?:\.\d+)?)\s*(M|K)?B/s', re.IGNORECASE)

    def remove_all_flag_emojis(text):
        return FLAG_EMOJI_PATTERN.sub('', text).strip()

    def replace_country_code(text):
        return CHINESE_COUNTRY_MAP.get(text.upper(), text)

    for proxy in proxies:
        original_name = proxy.get('name', '').strip()
        clean_name = remove_all_flag_emojis(original_name)
        clean_name = JUNK_PATTERNS.sub('', clean_name)
        
        speed_text = ''
        speed_match = speed_pattern.search(clean_name)
        if speed_match:
            number, unit = speed_match.groups()
            unit = unit.upper() if unit else ''
            speed_text = f"{number}{unit}B/s"
            clean_name = speed_pattern.sub('', clean_name, count=1).strip()

        country_match = country_pattern.search(clean_name)
        if country_match:
            region_name_raw = country_match.group(0)
            region_name = replace_country_code(region_name_raw)

            # 再次尝试替换英文简写为中文名
            for eng, chn in CHINESE_COUNTRY_MAP.items():
                if re.fullmatch(re.escape(region_name), eng, re.IGNORECASE):
                    region_name = chn
                    break

            country_counters[region_name] += 1
            seq_num = country_counters[region_name]
            region_code = COUNTRY_NAME_TO_CODE_MAP.get(region_name) or CUSTOM_REGEX_RULES.get(region_name, {}).get('code', '')

            flag_emoji = get_country_flag_emoji(region_code)
            new_name = f"{flag_emoji}{region_name}-{seq_num}"
            if speed_text:
                new_name += f"|{speed_text}"
            proxy['name'] = new_name
        else:
            proxy['name'] = original_name
        final_proxies.append(proxy)
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
            {'name': '🚀 节点选择', 'type': 'select',
             'proxies': ['♻️ 自动选择', '🔯 故障转移', 'DIRECT'] + proxy_names},
            {'name': '♻️ 自动选择', 'type': 'url-test', 'proxies': proxy_names,
             'url': 'http://www.gstatic.com/generate_204', 'interval': 300},
            {'name': '🔯 故障转移', 'type': 'fallback', 'proxies': proxy_names,
             'url': 'http://www.gstatic.com/generate_204', 'interval': 300}],
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
            if stripped:
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
    print("=" * 60)
    print("固定链接获取节点脚本 V2")
    print(f"时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    blocks = parse_url_txt_to_blocks()
    if not blocks:
        print("未检测到有效区块，退出。")
        return
    for block in blocks:
        process_block_to_yaml(block)
    print(f"\n全部区块处理完成，配置文件存放于：{OUTPUT_DIR}")

if __name__ == "__main__":
    main()

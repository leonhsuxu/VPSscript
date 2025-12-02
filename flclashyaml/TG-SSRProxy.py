"""
FlClash节点获取脚本 V1.r1
-------------------------------------
功能描述：
1. 从当前目录下名为 URL.TXT 的订阅列表文件读取订阅地址，支持模糊匹配脚本文件名筛选。
2. 支持通过 wget 优先下载订阅内容，失败后自动降级使用 requests 模块下载，增加兼容性。
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
V1.r1（2025-12-02）
- 初始版本完成，核心订阅下载、格式解析、合并、测速、重命名、配置生成全流程功能。
- 增加 wget + requests 双重下载保障。
- 实现 Base64 自动检测解码及多协议节点解析。
- 智能节点命名，增强节点管理体验。
- 高并发纯 Python 测速实现。

未来待完善项：
- 支持更多代理协议解析。
- 增加更丰富的质量筛选和分类功能。
- 增强订阅文件格式兼容性。
- GUI 或命令行参数控制优化。
- 更多日志输出及错误处理细化。

使用说明：
- 将订阅链接保存在与脚本同目录的 URL.TXT 文件中，格式示例：
  # 渠道名称
  FlClash-V2ray：https://example.com/subscription
- 修改脚本名称匹配关键字控制加载哪些订阅。
- 运行脚本，等待测速和配置生成完成后，直接加载生成的 TG-SSRProxy.yaml 到 Clash 或其他支持 YAML 配置的软件。
"""
# ========== 依赖配置 ==========
import yaml
import base64
import time
from datetime import datetime
import sys
import os
import re
from collections import defaultdict
import socket
import concurrent.futures
import hashlib
import subprocess
import shutil
import requests
import json

# ========== 基础配置 ==========
# SUBSCRIPTION_URLS 将通过从 URL.TXT 文件加载来动态填充
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
URL_FILE = os.path.join(SCRIPT_DIR, "URL.TXT")  # 定义 URL.TXT 文件的路径
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "TG-SSRProxy.yaml")
# 获取当前脚本的文件名（不含扩展名），用于匹配 URL.TXT 中的名称
CURRENT_SCRIPT_NAME = os.path.splitext(os.path.basename(__file__))[0]
print(f"当前脚本文件名 (不含扩展名): {CURRENT_SCRIPT_NAME}")
# ========== 测速过滤配置 (纯 Python socket 版) ==========
ENABLE_SPEED_TEST = True  # False为不测速，True为测速
# socket 连接超时时间(秒)
SOCKET_TIMEOUT = 10
# 并发测速的线程数
MAX_TEST_WORKERS = 256  # socket 非常轻量，可以大幅增加并发数以提高速度，默认128
# ========== 排序与命名配置 ==========
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国', '加拿大', '澳大利亚']
CHINESE_COUNTRY_MAP = {'US': '美国', 'United States': '美国', 'USA': '美国', 'JP': '日本', 'Japan': '日本', 'HK': '香港', 'Hong Kong': '香港', 'SG': '狮城', 'Singapore': '狮城', 'TW': '湾省', 'Taiwan': '湾省', 'KR': '韩国', 'Korea': '韩国', 'KOR': '韩国', 'DE': '德国', 'Germany': '德国', 'GB': '英国', 'United Kingdom': '英国', 'UK': '英国', 'CA': '加拿大', 'Canada': '加拿大', 'AU': '澳大利亚', 'Australia': '澳大利亚', }
COUNTRY_NAME_TO_CODE_MAP = {"阿富汗": "AF", "阿尔巴尼亚": "AL", "阿尔及利亚": "DZ", "安道尔": "AD", "安哥拉": "AO", "安圭拉": "AI", "安提瓜和巴布达": "AG", "阿根廷": "AR", "亚美尼亚": "AM", "阿鲁巴": "AW", "澳大利亚": "AU", "奥地利": "AT", "阿塞拜疆": "AZ", "巴哈马": "BS", "巴林": "BH", "孟加拉国": "BD", "巴巴多斯": "BB", "白俄罗斯": "BY", "比利时": "BE", "伯利兹": "BZ", "贝宁": "BJ", "百慕大": "BM", "不丹": "BT", "玻利维亚": "BO", "波黑": "BA", "博茨瓦纳": "BW", "巴西": "BR", "文莱": "BN", "保加利亚": "BG", "布基纳法索": "BF", "布隆迪": "BI", "柬埔寨": "KH", "喀麦隆": "CM", "加拿大": "CA", "佛得角": "CV", "开曼群岛": "KY", "中非": "CF", "乍得": "TD", "智利": "CL", "中国": "CN", "哥伦比亚": "CO", "科摩罗": "KM", "刚果（金）": "CD", "刚果（布）": "CG", "哥斯达黎加": "CR", "科特迪瓦": "CI", "克罗地亚": "HR", "古巴": "CU", "塞浦路斯": "CY", "捷克": "CZ", "丹麦": "DK", "吉布提": "DJ", "多米尼克": "DM", "多米尼加": "DO", "厄瓜多尔": "EC", "埃及": "EG", "萨尔瓦多": "SV", "赤道几内亚": "GQ", "厄立特里亚": "ER", "爱沙尼亚": "EE", "埃塞俄比亚": "ET", "斐济": "FJ", "芬兰": "FI", "法国": "FR", "加蓬": "GA", "冈比亚": "GM", "格鲁吉亚": "GE", "加纳": "GH", "希腊": "GR", "格林纳达": "GD", "危地马拉": "GT", "几内亚": "GN", "几内亚比绍": "GW", "圭亚那": "GY", "海地": "HT", "洪都拉斯": "HN", "匈牙利": "HU", "冰岛": "IS", "印度": "IN", "印尼": "ID", "印度尼西亚": "ID", "伊朗": "IR", "伊拉克": "IQ", "爱尔兰": "IE", "以色列": "IL", "意大利": "IT", "牙买加": "JM", "日本": "JP", "约旦": "JO", "哈萨克斯坦": "KZ", "肯尼亚": "KE", "基里巴斯": "KI", "科威特": "KW", "吉尔吉斯斯坦": "KG", "老挝": "LA", "拉脱维亚": "LV", "黎巴嫩": "LB", "莱索托": "LS", "利比里亚": "LR", "利比亚": "LY", "列支敦士登": "LI", "立陶宛": "LT", "卢森堡": "LU", "澳门": "MO", "北马其顿": "MK", "马达加斯加": "MG", "马拉维": "MW", "马来西亚": "MY", "马尔代夫": "MV", "马里": "ML", "马耳他": "MT", "马绍尔群岛": "MH", "毛里塔尼亚": "MR", "毛里求斯": "MU", "墨西哥": "MX", "密克罗尼西亚": "FM", "摩尔多瓦": "MD", "摩纳哥": "MC", "蒙古": "MN", "黑山": "ME", "摩洛哥": "MA", "莫桑比克": "MZ", "缅甸": "MM", "纳米比亚": "NA", "瑙鲁": "NR", "尼泊尔": "NP", "荷兰": "NL", "新西兰": "NZ", "尼加拉瓜": "NI", "尼日尔": "NE", "尼日利亚": "NG", "挪威": "NO", "阿曼": "OM", "巴基斯坦": "PK", "帕劳": "PW", "巴勒斯坦": "PS", "巴拿马": "PA", "巴布亚新几内亚": "PG", "巴拉圭": "PY", "秘鲁": "PE", "菲律宾": "PH", "波兰": "PL", "葡萄牙": "PT", "卡塔尔": "QA", "罗马尼亚": "RO", "俄罗斯": "RU", "卢旺达": "RW", "圣马力诺": "SM", "沙特阿拉伯": "SA", "塞内加尔": "SN", "塞尔维亚": "RS", "塞舌尔": "SC", "塞拉利昂": "SL", "新加坡": "SG", "斯洛伐克": "SK", "斯洛文尼亚": "SI", "所罗门群岛": "SB", "索马里": "SO", "南非": "ZA", "西班牙": "ES", "斯里兰卡": "LK", "苏丹": "SD", "苏里南": "SR", "瑞典": "SE", "瑞士": "CH", "叙利亚": "SY", "塔吉克斯坦": "TJ", "坦桑尼亚": "TZ", "泰国": "TH", "东帝汶": "TL", "多哥": "TG", "汤加": "TO", "特立尼达和多巴哥": "TT", "突尼斯": "TN", "土耳其": "TR", "土库曼斯坦": "TM", "图瓦卢": "TV", "乌干达": "UG", "乌克兰": "UA", "阿联酋": "AE", "乌拉圭": "UY", "乌兹别克斯坦": "UZ", "瓦努阿图": "VU", "委内瑞拉": "VE", "越南": "VN", "也门": "YE", "赞比亚": "ZM", "津巴布韦": "ZW"}
JUNK_PATTERNS = re.compile(r"(?:专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)|(?:(?:[\u2460-\u2473\u2776-\u277F\u2780-\u2789]|免費|回家).*?(?=,|$))", re.IGNORECASE)
CUSTOM_REGEX_RULES = {'香港': {'code': 'HK', 'pattern': r'香港|港|HK|Hong Kong|HKBN|HGC|PCCW|WTT'}, '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|沪日|深日|JP|Japan'}, '狮城': {'code': 'SG', 'pattern': r'新加坡|坡|狮城|SG|Singapore'}, '美国': {'code': 'US', 'pattern': r'美国|美|波特兰|达拉斯|Oregon|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥'}, '湾省': {'code': 'TW', 'pattern': r'台湾|湾省|台|新北|彰化|TW|Taiwan'}, '韩国': {'code': 'KR', 'pattern': r'韩国|韩|首尔|KR|Korea|KOR|韓'}, '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'}, '英国': {'code': 'GB', 'pattern': r'英国|英|UK|GB|United Kingdom|England'}, '加拿大': {'code': 'CA', 'pattern': r'加拿大|枫叶|多伦多|温哥华|蒙特利尔|CA|Canada'}, '澳大利亚': {'code': 'AU', 'pattern': r'澳大利亚|澳洲|悉尼|AU|Australia'},}
# ===== 国旗表情正则表达式 =====
# 匹配任意两个区域指示符符号（即国旗表情）
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')

# ========== 预处理自定义正则规则 ==========
def preprocess_regex_rules():
    for region, rules in CUSTOM_REGEX_RULES.items():
        parts = rules['pattern'].split('|')
        sorted_parts = sorted(parts, key=len, reverse=True)  # 按长度降序排序
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(sorted_parts)
preprocess_regex_rules()


def get_country_flag_emoji(country_code):
    if not country_code or len(country_code) != 2:
        return "❓"
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in country_code)


# -------------- 新增的 wget + requests 下载及解析 --------------
def attempt_download_using_wget(url):
    """使用 wget 下载订阅链接"""
    print(f"  ⬇️ 正在使用 wget 下载: {url[:80]}...")
    if not shutil.which("wget"):
        print("  ✗ 错误: wget 未安装，无法执行下载。")
        return None
    try:
        result = subprocess.run(
            ["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", url],
            capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore'
        )
        content = result.stdout
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

def download_subscription(url):
    """
    优先使用 wget 下载，失败后使用 requests 下载。
    返回下载内容或 None。
    """
    content = attempt_download_using_wget(url)
    if content is None:
        content = attempt_download_using_requests(url)
    if content is None:
        return []
    # 尝试直接解析
    proxies = parse_proxies_from_content(content)
    if proxies:
        return proxies
    # 如果非 YAML，检查是否为 base64
    if is_base64(content):
        proxies = decode_base64_and_parse(content)
        if proxies:
            return proxies
        else:
            print("  - Base64 解码后未解析到 Clash 节点")
    else:
        print("  - 内容非 Base64 编码，无法解析为代理节点")
    # 以上都失败返回空列表
    return []

# -------------- 解析YAML代理节点 --------------
def parse_proxies_from_content(content):
    try:
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

# -------------- 判断是否是 base64 --------------
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

# -------------- base64 解码并解析 Clash 节点 --------------
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
        print(f"  - 解码 Base64 并解析时出错: {e}")
        return []


# ---------------- 下面是各种协议解析函数 ----------------

def parse_vless_node(node_str):
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
    try:
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
    try:
        base64_str = node_str[8:]
        decoded_str = base64.urlsafe_b64decode(base64_str + '=' * (-len(base64_str) % 4)).decode('utf-8')
        json_data = json.loads(decoded_str)
        proxy = {
            "name": json_data.get('ps', f"Vmess {json_data.get('add')}:{json_data.get('port')}"),
            "type": "vmess",
            "server": json_data.get('add'),
            "port": int(json_data.get('port')),
            "uuid": json_data.get('id'),
            "alterId": int(json_data.get('aid', 0)),
            "cipher": json_data.get('scy', "auto"),
            "tls": json_data.get('tls') == "tls",
            "network": json_data.get('net'),
            "ws-opts": {"path": json_data.get('path'), "headers": {"Host": json_data.get('host')}} if json_data.get('net') == 'ws' else None,
            "servername": json_data.get('sni', json_data.get('host')),
        }
        if proxy["ws-opts"]:
            proxy["ws-opts"] = {k: v for k, v in proxy["ws-opts"].items() if v}
            if not proxy["ws-opts"]:
                proxy["ws-opts"] = None
        proxy = {k: v for k, v in proxy.items() if v is not None}
        return proxy
    except Exception as e:
        print(f"  - 解析 Vmess 节点时发生错误: {e}")
        return {}

def parse_ss_node(node_str):
    try:
        from urllib.parse import urlparse, unquote
        uri = urlparse(node_str)
        userinfo = uri.username
        if userinfo is None:
            raise ValueError("SS URI 缺少用户信息部分")
        userinfo_decoded = base64.urlsafe_b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode('utf-8')
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
        try:
            from urllib.parse import unquote
            parts = node_str[5:].split('#')
            main_part = parts[0]
            name = unquote(parts[1]) if len(parts) > 1 else None
            at_parts = main_part.split('@')
            if len(at_parts) != 2:
                raise ValueError("SS URI 格式不正确")
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
            "up": int(params['up_mbps'][0]) if 'up_mbps' in params else None,
            "down": int(params['down_mbps'][0]) if 'down_mbps' in params else None,
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

# ======================== 剩余原脚本功能 ========================

def get_proxy_key(proxy):
    try:
        identifier = f"{proxy.get('server','')}:{proxy.get('port',0)}|"
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
    unique_proxies = {}
    for proxy in subscriptions_proxies:
        if not isinstance(proxy, dict) or 'name' not in proxy:
            continue
        proxy_key = get_proxy_key(proxy)
        if proxy_key and proxy_key not in unique_proxies:
            unique_proxies[proxy_key] = proxy
    return list(unique_proxies.values())

def process_and_rename_proxies(proxies):
    country_counters = defaultdict(lambda: defaultdict(int))
    final_proxies = []

    all_region_names_for_stripping = set()
    for rules in CUSTOM_REGEX_RULES.values():
        all_region_names_for_stripping.update(rules['pattern'].split('|'))
    for k, v in CHINESE_COUNTRY_MAP.items():
        all_region_names_for_stripping.add(k)
        all_region_names_for_stripping.add(v)
    for k in COUNTRY_NAME_TO_CODE_MAP.keys():
        all_region_names_for_stripping.add(k)

    sorted_region_names = sorted(list(all_region_names_for_stripping), key=len, reverse=True)
    master_region_pattern = re.compile('|'.join(map(re.escape, sorted_region_names)), re.IGNORECASE)

    for p in proxies:
        original_name = p.get('name', '')
        temp_name_for_region_detection = FLAG_EMOJI_PATTERN.sub('', original_name)
        temp_name_for_region_detection = JUNK_PATTERNS.sub('', temp_name_for_region_detection).strip()
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            temp_name_for_region_detection = re.sub(r'\b' + re.escape(eng) + r'\b', chn, temp_name_for_region_detection,
                                                    flags=re.IGNORECASE)
        p['region'] = '未知'
        for region_name, rules in CUSTOM_REGEX_RULES.items():
            if re.search(rules['pattern'], temp_name_for_region_detection, re.IGNORECASE):
                p['region'] = region_name
                break
        if p['region'] == '未知':
            for country_chn_name, country_code in COUNTRY_NAME_TO_CODE_MAP.items():
                if re.search(r'\b' + re.escape(country_chn_name) + r'\b', temp_name_for_region_detection, re.IGNORECASE):
                    p['region'] = country_chn_name
                    break

    for proxy in proxies:
        original_name = proxy.get('name', '')
        region_info = {'name': proxy['region'], 'code': COUNTRY_NAME_TO_CODE_MAP.get(proxy['region'])}
        if not region_info['code']:
            region_info['code'] = CUSTOM_REGEX_RULES.get(region_info['name'], {}).get('code', '')
        chosen_flag = ""
        name_for_feature_extraction = original_name
        match_existing_flag = FLAG_EMOJI_PATTERN.search(original_name)
        if match_existing_flag:
            chosen_flag = match_existing_flag.group(0)
            name_for_feature_extraction = FLAG_EMOJI_PATTERN.sub('', original_name, 1)
        else:
            chosen_flag = get_country_flag_emoji(region_info['code'])

        node_feature = master_region_pattern.sub(' ', name_for_feature_extraction)
        node_feature = JUNK_PATTERNS.sub(' ', node_feature)
        node_feature = node_feature.replace('-', ' ').strip()
        node_feature = re.sub(r'\s+', ' ', node_feature).strip()

        if not node_feature:
            seq = sum(1 for p_final in final_proxies if p_final.get('region') == region_info['name']) + 1
            node_feature = f"{seq:02d}"

        new_name = f"{chosen_flag} {region_info['name']} {node_feature}".strip()

        country_counters[region_info['name']][new_name] += 1
        count = country_counters[region_info['name']][new_name]
        if count > 1:
            new_name = f"{new_name} {count}"

        proxy['name'] = new_name
        final_proxies.append(proxy)
    return final_proxies

# --- 新的纯 Python socket 测速函数 ---
def test_single_proxy_socket(proxy):
    server = proxy.get('server')
    port = proxy.get('port')
    if not server or not port:
        return None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        start_time = time.time()
        sock.connect((str(server), int(port)))
        end_time = time.time()
        delay = (end_time - start_time) * 1000
        proxy['delay'] = int(delay)
        return proxy
    except (socket.timeout, ConnectionRefusedError, socket.gaierror, OSError):
        return None
    finally:
        if 'sock' in locals():
            sock.close()

def speed_test_proxies(proxies):
    print(f"开始使用纯 Python socket 进行并发测速 (共 {len(proxies)} 个节点)")
    fast_proxies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TEST_WORKERS) as executor:
        future_to_proxy = {executor.submit(test_single_proxy_socket, p): p for p in proxies}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_proxy)):
            result = future.result()
            sys.stdout.write(f"\r  测试进度: {i + 1}/{len(proxies)}")
            sys.stdout.flush()
            if result:
                fast_proxies.append(result)
    print(f"\n测速完成，剩余可用节点: {len(fast_proxies)}")
    return fast_proxies

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

def load_subscription_urls_from_file(url_file_path, script_name_filter):
    urls = []
    if not os.path.exists(url_file_path):
        print(f"错误: 订阅文件 {url_file_path} 不存在。请确保该文件与脚本在同一目录下。")
        return urls
    print(f"正在从 {url_file_path} 读取订阅地址，并过滤名称包含 '{script_name_filter}' 的条目")
    try:
        with open(url_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                match = re.search(r'([^：]+)：\s*(https?://\S+)', line)
                if match:
                    name_from_file = match.group(1).strip()
                    url = match.group(2)
                    if script_name_filter in name_from_file:
                        urls.append(url)
                        print(f"  ✓ 找到并匹配到订阅: '{name_from_file}' -> {url[:80]}")
                    else:
                        print(f"  - 跳过不匹配的订阅 (名称 '{name_from_file}' 不包含 '{script_name_filter}'): {line[:60]}")
                else:
                    print(f"  ✗ 跳过无法识别的行 (不符合 '名称：地址' 格式): {line[:60]}")
    except Exception as e:
        print(f"读取订阅文件 {url_file_path} 时发生错误: {e}")
    return urls

def main():
    print("=" * 60)
    print("FlClash节点获取脚本 V1.r1")
    print(f"Clash 订阅合并 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    subscription_urls_from_file = load_subscription_urls_from_file(URL_FILE, CURRENT_SCRIPT_NAME)
    if not subscription_urls_from_file:
        sys.exit(f"\n❌ 错误: 未能从 {URL_FILE} 文件中读取到任何匹配 '{CURRENT_SCRIPT_NAME}' 的有效订阅地址。请检查文件内容和格式。")

    print("\n[1/4] 下载与合并订阅")
    all_proxies = []
    for url in subscription_urls_from_file:
        all_proxies.extend(download_subscription(url))

    unique_proxies = merge_and_deduplicate_proxies(all_proxies)
    if not unique_proxies:
        sys.exit("\n❌ 错误: 所有订阅下载失败或合并后无节点。")
    print(f"  ✓ 合并后共 {len(unique_proxies)} 个不重复节点。")

    print("\n[2/4] 测速与筛选节点")
    if ENABLE_SPEED_TEST:
        available_proxies = speed_test_proxies(unique_proxies)
        if not available_proxies:
            print("\n  ⚠️ 警告: 测速后无可用节点，将使用所有节点生成配置。")
            available_proxies = unique_proxies
    else:
        print("  - 已跳过延迟测试。")
        available_proxies = unique_proxies

    print("\n[3/4] 排序与重命名节点")
    region_order = {region: i for i, region in enumerate(REGION_PRIORITY)}
    available_proxies.sort(key=lambda p: (region_order.get(p.get('region', '未知'), 99), p.get('delay', 9999)))
    final_proxies = process_and_rename_proxies(available_proxies)
    print(f"\n  ✓ 共 {len(final_proxies)} 个节点完成排序和重命名。")

    print("\n[4/4] 生成最终配置文件")
    config = generate_config(final_proxies)
    if not config:
        sys.exit("\n❌ 错误: 无法生成配置文件。")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2)
    print(f"\n  ✓ 配置文件已成功保存至: {OUTPUT_FILE}")

    print("\n✅ 任务完成！")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
    "立陶宛": "LT", "卢森堡": "LU", "澳门": "MO", "北马其顿": "MK",
    "马达加斯加": "MG", "马拉维": "MW", "马来西亚": "MY", "马尔代夫": "MV",
    "马里": "ML", "马耳他": "MT", "马绍尔群岛": "MH", "毛里塔尼亚": "MR",
    "毛里求斯": "MU", "墨西哥": "MX", "密克罗尼西亚": "FM", "摩尔多瓦": "MD",
    "摩纳哥": "MC", "蒙古": "MN", "黑山": "ME", "摩洛哥": "MA",
    "莫桑比克": "MZ", "缅甸": "MM", "纳米比亚": "NA", "瑙鲁": "NR",
    "尼泊尔": "NP", "荷兰": "NL", "新西兰": "NZ", "尼加拉瓜": "NI",
    "尼日尔": "NE", "尼日利亚": "NG", "挪威": "NO", "阿曼": "OM",
    "巴基斯坦": "PK", "帕劳": "PW", "巴勒斯坦": "PS", "巴拿马": "PA",
    "巴布亚新几内亚": "PG", "巴拉圭": "PY", "秘鲁": "PE", "菲律宾": "PH",
    "波兰": "PL", "葡萄牙": "PT", "卡塔尔": "QA", "罗马尼亚": "RO",
    "俄罗斯": "RU", "卢旺达": "RW", "圣马力诺": "SM", "沙特阿拉伯": "SA",
    "塞内加尔": "SN", "塞尔维亚": "RS", "塞舌尔": "SC", "塞拉利昂": "SL",
    "新加坡": "SG", "斯洛伐克": "SK", "斯洛文尼亚": "SI", "所罗门群岛": "SB",
    "索马里": "SO", "南非": "ZA", "西班牙": "ES", "斯里兰卡": "LK",
    "苏丹": "SD", "苏里南": "SR", "瑞典": "SE", "瑞士": "CH",
    "叙利亚": "SY", "塔吉克斯坦": "TJ", "坦桑尼亚": "TZ", "泰国": "TH",
    "东帝汶": "TL", "多哥": "TG", "汤加": "TO", "特立尼达和多巴哥": "TT",
    "突尼斯": "TN", "土耳其": "TR", "土库曼斯坦": "TM", "图瓦卢": "TV",
    "乌干达": "UG", "乌克兰": "UA", "阿联酋": "AE", "乌拉圭": "UY",
    "乌兹别克斯坦": "UZ", "瓦努阿图": "VU", "委内瑞拉": "VE", "越南": "VN",
    "也门": "YE", "赞比亚": "ZM", "津巴布韦": "ZW"
}

JUNK_PATTERNS = re.compile(
    r'丑团|专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|'
    r'[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量', re.IGNORECASE
)

# (不变) 高质量的正则匹配规则 (优先匹配)
CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'港|HK|Hong Kong'},
    '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan'},
    '狮城': {'code': 'SG', 'pattern': r'新加坡|SG|Singapore|坡|狮城'},
    '美国': {'code': 'US', 'pattern': r'美国|美|波特兰|达拉斯|Oregon|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥'},
    '湾省': {'code': 'TW', 'pattern': r'台湾|湾省|TW|Taiwan|台|新北|彰化'},
    '韩国': {'code': 'KR', 'pattern': r'韩国|韩|KR|Korea|KOR|首尔|韓'},
    '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'},
    '英国': {'code': 'GB', 'pattern': r'UK|GB|United Kingdom|England|英|英国'},
    '加拿大': {'code': 'CA', 'pattern': r'CA|Canada|加拿大|枫叶|多伦多|温哥华|蒙特利尔'},
    '澳大利亚': {'code': 'AU', 'pattern': r'AU|Australia|澳大利亚|澳洲|悉尼'},
}

# ========== 核心功能函数 ==========

def get_country_flag_emoji(country_code):
    if not country_code or len(country_code) != 2: return "❓"
    return "".join(chr(0x1F1E6 + ord(char.upper()) - ord('A')) for char in country_code)

def download_subscription(url):
    try:
        headers = {'User-Agent': 'Clash/1.11.4 (Windows; x64)'}
        print(f"  下载: {url[:60]}...")
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        content = response.text
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict) and 'proxies' in data: return data['proxies']
        except yaml.YAMLError:
            try:
                decoded_content = base64.b64decode(content).decode('utf-8')
                data = yaml.safe_load(decoded_content)
                if isinstance(data, dict) and 'proxies' in data: return data['proxies']
            except Exception: pass
    except Exception as e:
        print(f"  ✗ 下载或解析失败: {e}")
    return []

def get_proxy_key(proxy):
    try:
        server = proxy.get('server', '')
        port = proxy.get('port', 0)
        password = proxy.get('password', '') or proxy.get('uuid', '')
        return hashlib.md5(f"{server}:{port}|{password}".encode('utf-8')).hexdigest()
    except Exception: return None

def merge_and_deduplicate_proxies(subscriptions_proxies):
    unique_proxies = {}
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团 - Clash 订阅合并脚本 (v12.1 - 路径优化版)
- 脚本与输出文件位于同一目录
- 内置权威中文库，最大限度匹配全球中文节点名
- 按指定地区优先级排序
- 智能清洗节点名，对未匹配节点保留并使用清洗后名称
"""

import requests
import yaml
from datetime import datetime
import sys
import os
import hashlib
import re
from collections import defaultdict
import pycountry

# ========== 基础配置 ==========
# 移除了硬编码的 SUBSCRIPTION_URLS 列表，现在将从 URL.TXT 文件动态加载

# 重点：动态获取脚本所在目录，并定义输出路径
# __file__ 是当前脚本的路径
# os.path.abspath 获取绝对路径
# os.path.dirname 获取该路径所在的目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "choutuan-all.yaml")
URL_FILE = os.path.join(SCRIPT_DIR, "URL.TXT") # 定义 URL.TXT 文件的路径

# 修改这里：动态获取脚本名作为关键词
# 获取脚本文件名 (例如 "choutuan_script.py")
script_filename = os.path.basename(__file__)
# 移除文件扩展名 (例如 "choutuan_script")
# 注意：如果你的脚本名是 "丑团.py"，那么 SCRIPT_IDENTITY_NAME 会是 "丑团"。
# 如果你的脚本名是 "我的丑团脚本.py"，那么 SCRIPT_IDENTITY_NAME 会是 "我的丑团脚本"。
# 请根据实际需要调整命名规则，例如如果你只想要 "丑团" 两个字，可能需要更复杂的正则。
# 但按你目前的描述 "关键词为脚本名"，这个实现是符合的。
SCRIPT_IDENTITY_NAME = os.path.splitext(script_filename)[0]


# ========== 排序与命名配置 ==========
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国', '加拿大', '澳大利亚']

# 注意：JUNK_PATTERNS 中的 '丑团' 硬编码可能也需要动态化，
# 如果 SCRIPT_IDENTITY_NAME 变化，这里可能也需要更新。
# 暂时保持不变，因为用户只是要求 SCRIPT_IDENTITY_NAME 为脚本名。
JUNK_PATTERNS = re.compile(
    r'丑团|专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d{1,2}|Rate|'
    r'[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay', re.IGNORECASE
)

CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'港|HK|Hong Kong'},
    '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan'},
    '狮城': {'code': 'SG', 'pattern': r'新加坡|SG|Singapore|坡|狮城'},
    '美国': {'code': 'US', 'pattern': r'^(?!.*(?:aus|rus)).*(?:\b(?:us|usa|united states)\b|美|波特兰|达拉斯|Oregon|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥)'},
    '湾省': {'code': 'TW', 'pattern': r'台湾|TW|Taiwan|台|新北|彰化'},
    '韩国': {'code': 'KR', 'pattern': r'韩|KR|Korea|KOR|首尔|韓'},
    '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'},
    '英国': {'code': 'GB', 'pattern': r'UK|GB|United Kingdom|England|英|英国'},
}

CHINESE_COUNTRY_MAP = {
    "阿富汗": "AF", "阿尔巴尼亚": "AL", "阿尔及利亚": "DZ", "安道尔": "AD",
    "安哥拉": "AO", "安圭拉": "AI", "安提瓜和巴布达": "AG", "阿根廷": "AR",
    "亚美尼亚": "AM", "阿鲁巴": "AW", "澳大利亚": "AU", "奥地利": "AT",
    "阿塞拜疆": "AZ", "巴哈马": "BS", "巴林": "BH", "孟加拉国": "BD",
    "巴巴多斯": "BB", "白俄罗斯": "BY", "比利时": "BE", "伯利兹": "BZ",
    "贝宁": "BJ", "百慕大": "BM", "不丹": "BT", "玻利维亚": "BO",
    "波黑": "BA", "博茨瓦纳": "BW", "巴西": "BR", "文莱": "BN",
    "保加利亚": "BG", "布基纳法索": "BF", "布隆迪": "BI", "柬埔寨": "KH",
    "喀麦隆": "CM", "加拿大": "CA", "佛得角": "CV", "开曼群岛": "KY",
    "中非": "CF", "乍得": "TD", "智利": "CL", "中国": "CN",
    "哥伦比亚": "CO", "科摩罗": "KM", "刚果（金）": "CD", "刚果（布）": "CG",
    "哥斯达黎加": "CR", "科特迪瓦": "CI", "克罗地亚": "HR", "古巴": "CU",
    "塞浦路斯": "CY", "捷克": "CZ", "丹麦": "DK", "吉布提": "DJ",
    "多米尼克": "DM", "多米尼加": "DO", "厄瓜多尔": "EC", "埃及": "EG",
    "萨尔瓦多": "SV", "赤道几内亚": "GQ", "厄立特里亚": "ER", "爱沙尼亚": "EE",
    "埃塞俄比亚": "ET", "斐济": "FJ", "芬兰": "FI", "法国": "FR",
    "加蓬": "GA", "冈比亚": "GM", "格鲁吉亚": "GE", "加纳": "GH",
    "希腊": "GR", "格林纳达": "GD", "危地马拉": "GT", "几内亚": "GN",
    "几内亚比绍": "GW", "圭亚那": "GY", "海地": "HT", "洪都拉斯": "HN",
    "匈牙利": "HU", "冰岛": "IS", "印度": "IN", "印尼": "ID",
    "伊朗": "IR", "伊拉克": "IQ", "爱尔兰": "IE", "以色列": "IL",
    "意大利": "IT", "牙买加": "JM", "日本": "JP", "约旦": "JO",
    "哈萨克斯坦": "KZ", "肯尼亚": "KE", "基里巴斯": "KI", "科威特": "KW",
    "吉尔吉斯斯坦": "KG", "老挝": "LA", "拉脱维亚": "LV", "黎巴嫩": "LB",
    "莱索托": "LS", "利比里亚": "LR", "利比亚": "LY", "列支敦士登": "LI",
    "立陶宛": "LT", "卢森堡": "LU", "澳门": "MO", "北马其顿":"MK",
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

# ========== 核心功能函数 ==========
def code_to_emoji(code):
    if not code or len(code) != 2: return '🌐'
    return "".join(chr(0x1F1E6 + ord(char.upper()) - ord('A')) for char in code)

def build_country_rules():
    print("  - 构建国家匹配规则...")
    rules = {}
    covered_codes = set()

    # 1. 加载高优先级的自定义正则规则
    for display_name, data in CUSTOM_REGEX_RULES.items():
        if data['code'] not in covered_codes:
            rules[display_name] = {'emoji': code_to_emoji(data['code']), 'regex': re.compile(data['pattern'], re.IGNORECASE)}
            covered_codes.add(data['code'])
    print(f"  ✓ 加载了 {len(rules)} 条自定义高优规则。")

    # 2. 从权威中文库构建规则
    chinese_map_added = 0
    for chinese_name, code in CHINESE_COUNTRY_MAP.items():
        if code in covered_codes: continue
        
        keywords = [chinese_name, code]
        try:
            country = pycountry.countries.get(alpha_2=code)
            if country:
                keywords.extend([country.alpha_3, country.name.split(',')[0]])
        except Exception: pass
        
        keywords = sorted(list(set(kw for kw in keywords if kw)), key=len, reverse=True)
        rules[chinese_name] = {'emoji': code_to_emoji(code), 'regex': re.compile('|'.join(map(re.escape, keywords)), re.IGNORECASE)}
        covered_codes.add(code)
        chinese_map_added += 1
    print(f"  ✓ 从权威中文库生成了 {chinese_map_added} 条规则。")

    # 3. 使用 pycountry 动态生成其他国家的规则作为补充
    pycountry_added = 0
    for country in pycountry.countries:
        if country.alpha_2 in covered_codes: continue
        
        keywords = sorted(list(set(kw for kw in [country.alpha_2, country.alpha_3, country.name.split(',')[0]] if len(kw) > 1)), key=len, reverse=True)
        if keywords:
            display_name = country.name.split(',')[0]
            rules[display_name] = {'emoji': code_to_emoji(country.alpha_2), 'regex': re.compile('|'.join(map(re.escape, keywords)), re.IGNORECASE)}
            pycountry_added += 1
            
    print(f"  ✓ 动态生成了 {pycountry_added} 条补充规则。")
    print(f"  - 总计 {len(rules)} 条规则。")
    return rules

COUNTRY_RULES = build_country_rules()

def download_subscription(url):
    try:
        headers = {'User-Agent': 'Clash/1.11.4 (Windows; x64)'}
        print(f"  下载: {url[:60]}...")
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        data = yaml.safe_load(response.text)
        if isinstance(data, dict) and 'proxies' in data: return data
    except Exception as e: print(f"  ✗ 下载或解析失败: {e}")
    return None

def get_proxy_key(proxy):
    try:
        server = proxy.get('server', '')
        port = proxy.get('port', 0)
        password = proxy.get('password', '') or proxy.get('uuid', '')
        return hashlib.md5(f"{server}:{port}|{password}".encode('utf-8')).hexdigest()
    except Exception: return None

def merge_and_deduplicate_proxies(subscriptions):
    unique_proxies = {}
    for sub in subscriptions:
        proxies_in_sub = sub.get('proxies', [])
        if not isinstance(proxies_in_sub, list): continue
        for proxy in proxies_in_sub:
            if not isinstance(proxy, dict) or 'name' not in proxy: continue
            proxy_key = get_proxy_key(proxy)
            if proxy_key and proxy_key not in unique_proxies:
                unique_proxies[proxy_key] = proxy
    return list(unique_proxies.values())

def process_and_rename_proxies(proxies):
    print(f"\n[3/4] 开始排序和重命名节点...")
    
    for proxy in proxies:
        original_name = proxy['name']
        cleaned_name = JUNK_PATTERNS.sub('', original_name).strip()
        
        matched_display_name = None
        for display_name, rules in COUNTRY_RULES.items():
            if rules['regex'].search(cleaned_name) or rules['regex'].search(original_name):
                matched_display_name = display_name
                break
        
        if matched_display_name:
            proxy['_display_name'] = matched_display_name
            try:
                proxy['_region_sort_index'] = REGION_PRIORITY.index(matched_display_name)
            except ValueError:
                proxy['_region_sort_index'] = len(REGION_PRIORITY)
        else:
            proxy['_display_name'] = cleaned_name if cleaned_name else original_name
            proxy['_region_sort_index'] = len(REGION_PRIORITY) + 1

    proxies.sort(key=lambda p: p.get('_region_sort_index', 99))
    print("  ✓ 节点已按 '地区优先级' 完成排序。")

    country_counters = defaultdict(int)
    for proxy in proxies:
        display_name = proxy['_display_name']
        
        if display_name in COUNTRY_RULES:
            country_counters[display_name] += 1
            emoji = COUNTRY_RULES[display_name]['emoji']
            seq_num = country_counters[display_name]
            proxy['name'] = f"{emoji} {display_name} - {seq_num:02d}"
        else:
            proxy['name'] = display_name
        
        del proxy['_display_name'], proxy['_region_sort_index']

    final_proxies = []
    seen_names = set()
    for proxy in proxies:
        base_name = proxy['name']
        final_name = base_name
        counter = 2
        while final_name in seen_names:
            final_name = f"{base_name} ({counter})"
            counter += 1
        proxy['name'] = final_name
        seen_names.add(final_name)
        final_proxies.append(proxy)
        
    print(f"  ✓ 已完成最终命名和冲突检查。总计: {len(final_proxies)} 个。")
    return final_proxies


def generate_config(proxies):
    if not proxies: return None
    proxy_names = [p['name'] for p in proxies]
    
    return {
        'profile-name': SCRIPT_IDENTITY_NAME, # 使用定义好的脚本身份名称
        'mixed-port': 7890, 'allow-lan': True,
        'bind-address': '*', 'mode': 'rule', 'log-level': 'info',
        'external-controller': '127.0.0.1:9090', 'external-ui': 'ui',
        'dns': {
            'enable': True, 'listen': '0.0.0.0:53', 'enhanced-mode': 'fake-ip',
            'fake-ip-range': '198.18.0.1/16', 'nameserver': ['223.5.5.5', '119.29.29.29'],
            'fallback': ['https://dns.google/dns-query', 'https://1.1.1.1/dns-query']
        },
        'proxies': proxies,
        'proxy-groups': [
            {'name': '🚀 节点选择', 'type': 'select', 'proxies': ['♻️ 自动选择', '🔯 故障转移', 'DIRECT'] + proxy_names},
            {'name': '♻️ 自动选择', 'type': 'url-test', 'proxies': proxy_names, 'url': 'http://www.gstatic.com/generate_204', 'interval': 300},
            {'name': '🔯 故障转移', 'type': 'fallback', 'proxies': proxy_names, 'url': 'http://www.gstatic.com/generate_204', 'interval': 300}
        ],
        'rules': ['GEOIP,CN,DIRECT', 'MATCH,🚀 节点选择']
    }

# 新增函数：从 URL.TXT 文件中加载订阅地址，并根据脚本名称进行筛选
def load_subscription_urls_from_file(url_file_path, script_name_to_match):
    """
    从指定路径的 URL.TXT 文件中读取订阅地址。
    只提取那些其“名称”部分包含 script_name_to_match 的订阅地址。
    文件格式为：# 名称 \n 名称 ：地址
    """
    urls = []
    if not os.path.exists(url_file_path):
        print(f"错误: 订阅文件 {url_file_path} 不存在。请确保该文件与脚本在同一目录下。")
        return urls

    print(f"正在从 {url_file_path} 读取订阅地址，筛选包含 '{script_name_to_match}' 的地址...")
    try:
        with open(url_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过空行和以 # 开头的注释行
                if not line or line.startswith('#'):
                    continue
                
                # 使用正则表达式匹配 '名称：地址' 格式，提取名称和地址
                # 注意这里使用全角冒号 '：'
                match = re.search(r'([^：]+)：\s*(https?://\S+)', line)
                if match:
                    entry_name = match.group(1).strip()
                    url = match.group(2)
                    
                    # 检查提取的名称是否包含脚本的身份名称
                    if script_name_to_match.lower() in entry_name.lower():
                        urls.append(url)
                        print(f"  ✓ 找到并载入匹配 '{script_name_to_match}' 的订阅地址: {entry_name} -> {url[:60]}...")
                    else:
                        print(f"  ✗ 跳过不包含 '{script_name_to_match}' 的地址: {entry_name}...")
                else:
                    print(f"  ✗ 跳过无法识别的行 (不符合 '名称 ：地址' 格式): {line[:60]}...")
    except Exception as e:
        print(f"读取订阅文件 {url_file_path} 时发生错误: {e}")
    return urls

def main():
    print("=" * 60)
    print(f"{SCRIPT_IDENTITY_NAME} - Clash 订阅合并 (v12.1 - 路径优化版) @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 从 URL.TXT 文件加载订阅地址，并根据脚本名称进行筛选
    subscription_urls_from_file = load_subscription_urls_from_file(URL_FILE, SCRIPT_IDENTITY_NAME)
    if not subscription_urls_from_file:
        sys.exit(f"\n❌ 错误: 未能从 {URL_FILE} 文件中读取到任何有效的、包含 '{SCRIPT_IDENTITY_NAME}' 的订阅地址。请检查文件内容和格式。")

    print("\n[1/4] 开始下载订阅...")
    subscriptions = [sub for sub in (download_subscription(url) for url in subscription_urls_from_file) if sub]
    if not subscriptions: sys.exit("\n❌ 错误: 所有订阅都下载失败，任务中断。")
    
    print(f"\n[2/4] 开始合并与去重...")
    unique_proxies = merge_and_deduplicate_proxies(subscriptions)
    if not unique_proxies: sys.exit("\n❌ 错误: 合并后没有可用的节点，任务中断。")
    
    final_proxies = process_and_rename_proxies(unique_proxies)

    print(f"\n[4/4] 开始生成最终配置文件...")
    config = generate_config(final_proxies)
    if not config: sys.exit("\n❌ 错误: 无法生成配置文件。")
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2, default_flow_style=False)
    
    print(f"  ✓ 配置文件已成功保存至: {OUTPUT_FILE}")
    print("\n✅ 任务完成！")

if __name__ == '__main__':
    main()

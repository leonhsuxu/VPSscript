#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团 - Clash 订阅合并脚本 (v12 - 权威中文库版)
- 内置权威中文-国家代码映射库，最大限度匹配全球中文节点名
- 优先使用自定义正则，再由权威库和 pycountry 动态生成全球规则
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
SUBSCRIPTION_URLS = [
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4",
]
OUTPUT_DIR = "flclashyaml"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "choutuan-all.yaml")

# ========== 排序与命名配置 ==========
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国', '加拿大', '澳大利亚']

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

# ========== 权威中文-国家代码映射库 ==========
# 数据来源于社区维护的开源项目，确保了高覆盖率和准确性
CHINESE_COUNTRY_MAP = {
    "阿富汗": "AF", "奥兰群岛": "AX", "阿尔巴尼亚": "AL", "阿尔及利亚": "DZ",
    "美属萨摩亚": "AS", "安道尔": "AD", "安哥拉": "AO", "安圭拉": "AI",
    "南极洲": "AQ", "安提瓜和巴布达": "AG", "阿根廷": "AR", "亚美尼亚": "AM",
    "阿鲁巴": "AW", "澳大利亚": "AU", "奥地利": "AT", "阿塞拜疆": "AZ",
    "巴哈马": "BS", "巴林": "BH", "孟加拉国": "BD", "巴巴多斯": "BB",
    "白俄罗斯": "BY", "比利时": "BE", "伯利兹": "BZ", "贝宁": "BJ",
    "百慕大": "BM", "不丹": "BT", "玻利维亚": "BO", "波黑": "BA",
    "博茨瓦на": "BW", "布韦岛": "BV", "巴西": "BR", "英属印度洋领地": "IO",
    "文莱": "BN", "保加利亚": "BG", "布基纳法索": "BF", "布隆迪": "BI",
    "柬埔寨": "KH", "喀麦隆": "CM", "加拿大": "CA", "佛得角": "CV",
    "开曼群岛": "KY", "中非": "CF", "乍得": "TD", "智利": "CL",
    "中国": "CN", "圣诞岛": "CX", "科科斯（基林）群岛": "CC", "哥伦比亚": "CO",
    "科摩罗": "KM", "刚果（金）": "CD", "刚果（布）": "CG", "库克群岛": "CK",
    "哥斯达黎加": "CR", "科特迪瓦": "CI", "克罗地亚": "HR", "古巴": "CU",
    "塞浦路斯": "CY", "捷克": "CZ", "丹麦": "DK", "吉布提": "DJ",
    "多米尼克": "DM", "多米尼加": "DO", "厄瓜多尔": "EC", "埃及": "EG",
    "萨尔瓦多": "SV", "赤道几内亚": "GQ", "厄立特里亚": "ER", "爱沙尼亚": "EE",
    "埃塞俄比亚": "ET", "福克兰群岛": "FK", "法罗群岛": "FO", "斐济": "FJ",
    "芬兰": "FI", "法国": "FR", "法属圭亚那": "GF", "法属波利尼西亚": "PF",
    "法属南部领地": "TF", "加蓬": "GA", "冈比亚": "GM", "格鲁吉亚": "GE",
    "加纳": "GH", "直布罗陀": "GI", "希腊": "GR", "格陵兰": "GL",
    "格林纳达": "GD", "瓜德罗普": "GP", "关岛": "GU", "危地马拉": "GT",
    "根西": "GG", "几内亚": "GN", "几内亚比绍": "GW", "圭亚那": "GY",
    "海地": "HT", "赫德岛和麦克唐纳群岛": "HM", "梵蒂冈": "VA", "洪都拉斯": "HN",
    "匈牙利": "HU", "冰岛": "IS", "印度": "IN", "印尼": "ID",
    "伊朗": "IR", "伊拉克": "IQ", "爱尔兰": "IE", "马恩岛": "IM",
    "以色列": "IL", "意大利": "IT", "牙买加": "JM", "日本": "JP",
    "泽西": "JE", "约旦": "JO", "哈萨克斯坦": "KZ", "肯尼亚": "KE",
    "基里巴斯": "KI", "朝鲜": "KP", "韩国": "KR", "科威特": "KW",
    "吉尔吉斯斯坦": "KG", "老挝": "LA", "拉脱维亚": "LV", "黎巴嫩": "LB",
    "莱索托": "LS", "利比里亚": "LR", "利比亚": "LY", "列支敦士登": "LI",
    "立陶宛": "LT", "卢森堡": "LU", "澳门": "MO", "北马其顿": "MK",
    "马达加斯加": "MG", "马拉维": "MW", "马来西亚": "MY", "马尔代夫": "MV",
    "马里": "ML", "马耳他": "MT", "马绍尔群岛": "MH", "马提尼克": "MQ",
    "毛里塔尼亚": "MR", "毛里求斯": "MU", "马约特": "YT", "墨西哥": "MX",
    "密克罗尼西亚": "FM", "摩尔多瓦": "MD", "摩纳哥": "MC", "蒙古": "MN",
    "黑山": "ME", "蒙特塞拉特": "MS", "摩洛哥": "MA", "莫桑比克": "MZ",
    "缅甸": "MM", "纳米比亚": "NA", "瑙鲁": "NR", "尼泊尔": "NP",
    "荷兰": "NL", "荷属安的列斯": "AN", "新喀里多尼亚": "NC", "新西兰": "NZ",
    "尼加拉瓜": "NI", "尼日尔": "NE", "尼日利亚": "NG", "纽埃": "NU",
    "诺福克岛": "NF", "北马里亚纳群岛": "MP", "挪威": "NO", "阿曼": "OM",
    "巴基斯坦": "PK", "帕劳": "PW", "巴勒斯坦": "PS", "巴拿马": "PA",
    "巴布亚新几内亚": "PG", "巴拉圭": "PY", "秘鲁": "PE", "菲律宾": "PH",
    "皮特凯恩": "PN", "波兰": "PL", "葡萄牙": "PT", "波多黎各": "PR",
    "卡塔尔": "QA", "留尼汪": "RE", "罗马尼亚": "RO", "俄罗斯": "RU",
    "卢旺达": "RW", "圣赫勒拿": "SH", "圣基茨和尼维斯": "KN", "圣卢西亚": "LC",
    "圣皮埃尔和密克隆": "PM", "圣文森特和格林纳丁斯": "VC", "萨摩亚": "WS", "圣马力诺": "SM",
    "圣多美和普林西比": "ST", "沙特阿拉伯": "SA", "塞内加尔": "SN", "塞尔维亚": "RS",
    "塞舌尔": "SC", "塞拉利昂": "SL", "新加坡": "SG", "斯洛伐克": "SK",
    "斯洛文尼亚": "SI", "所罗门群岛": "SB", "索马里": "SO", "南非": "ZA",
    "南乔治亚和南桑威奇群岛": "GS", "西班牙": "ES", "斯里兰卡": "LK", "苏丹": "SD",
    "苏里南": "SR", "斯瓦尔巴和扬马延": "SJ", "斯威士兰": "SZ", "瑞典": "SE",
    "瑞士": "CH", "叙利亚": "SY", "塔吉克斯坦": "TJ", "坦桑尼亚": "TZ",
    "泰国": "TH", "东帝汶": "TL", "多哥": "TG", "托克劳": "TK",
    "汤加": "TO", "特立尼达和多巴哥": "TT", "突尼斯": "TN", "土耳其": "TR",
    "土库曼斯坦": "TM", "图瓦卢": "TV", "乌干达": "UG", "乌克兰": "UA",
    "阿联酋": "AE", "英国": "GB", "美国": "US", "美国本土外小岛屿": "UM",
    "乌拉圭": "UY", "乌兹别克斯坦": "UZ", "瓦努阿图": "VU", "委内瑞拉": "VE",
    "越南": "VN", "英属维尔京群岛": "VG", "美属维尔京群岛": "VI", "瓦利斯和富图纳": "WF",
    "西撒哈拉": "EH", "也门": "YE", "赞比亚": "ZM", "津巴布韦": "ZW"
}

# ========== 核心功能函数 ==========
def code_to_emoji(code):
    if not code or len(code) != 2: return '🌐'
    return "".join(chr(0x1F1E6 + ord(char.upper()) - ord('A')) for char in code)

def build_country_rules():
    """动态构建混合匹配规则：自定义正则 -> 权威中文库 -> pycountry 全球规则"""
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
        except Exception:
            pass # 如果 pycountry 找不到，就只用中文名和代码
        
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
        'profile-name': '丑团', 'mixed-port': 7890, 'allow-lan': True,
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

def main():
    print("=" * 60)
    print(f"丑团 - Clash 订阅合并 (v12 - 权威中文库版) @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("\n[1/4] 开始下载订阅...")
    subscriptions = [sub for sub in (download_subscription(url) for url in SUBSCRIPTION_URLS) if sub]
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

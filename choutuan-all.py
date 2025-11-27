#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团 - Clash 订阅合并脚本 (v7 - 自定义正则版)
- 支持高优先级的自定义正则表达式，用于精准匹配常见地区
- 动态生成全球 ~250 个国家/地区的匹配规则作为补充
- 智能清洗节点名，去除干扰词
- 优先匹配国家/地区并重命名，无法匹配的则清洗名称后保留
- 精准去重: Server + Port + Password/UUID
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

# ========== 订阅配置 ==========
SUBSCRIPTION_URLS = [
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4",
]

OUTPUT_DIR = "flclashyaml"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "choutuan-all.yaml")

# ========== 名称清洗规则 ==========
JUNK_PATTERNS = re.compile(
    r'丑团|专线|IPLC|IEPL|BGP|体验|官网|'
    r'[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*',
    re.IGNORECASE
)

# ========== 高优先级自定义正则规则 ==========
# 在这里可以自由修改和添加正则表达式，它们会最先被用来匹配
CUSTOM_REGEX_RULES = {
    # 显示名称: { code: '两字母国家代码', pattern: r'正则表达式' }
    '香港': {'code': 'HK', 'pattern': r'港|HK|Hong Kong'},
    '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan'},
    '狮城': {'code': 'SG', 'pattern': r'新加坡|SG|Singapore|坡|狮城'},
    '美国': {'code': 'US', 'pattern': r'^(?!.*(?:aus|rus)).*(?:\b(?:us|usa|united states)\b|美|波特兰|达拉斯|Oregon|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥)'},
    '湾省': {'code': 'TW', 'pattern': r'台湾|TW|Taiwan|台|新北|彰化'},
    '韩国': {'code': 'KR', 'pattern': r'韩|KR|Korea|KOR|首尔|韓'},
    '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'},
}

def code_to_emoji(code):
    """将两字母国家代码转换为国旗 Emoji"""
    if not code or len(code) != 2: return '🌐'
    return "".join(chr(0x1F1E6 + ord(char.upper()) - ord('A')) for char in code)

def build_country_rules():
    """动态构建全球国家/地区的匹配规则"""
    print("  - 构建国家匹配规则...")
    rules = {}
    
    # 1. 加载高优先级的自定义正则规则
    for display_name, data in CUSTOM_REGEX_RULES.items():
        rules[display_name] = {
            'emoji': code_to_emoji(data['code']),
            'regex': re.compile(data['pattern'], re.IGNORECASE)
        }
    print(f"  ✓ 加载了 {len(rules)} 条自定义高优规则。")
    
    # 2. 使用 pycountry 动态生成其他国家的规则作为补充
    covered_codes = {data['code'] for data in CUSTOM_REGEX_RULES.values()}
    pycountry_added = 0
    for country in pycountry.countries:
        if country.alpha_2 in covered_codes: continue
        
        keywords = [country.alpha_2, country.alpha_3]
        if hasattr(country, 'common_name'): keywords.append(country.common_name)
        if hasattr(country, 'official_name'): keywords.append(country.official_name)
        
        keywords = sorted(list(set(kw for kw in keywords if len(kw) > 1)), key=len, reverse=True)
        
        if keywords:
            display_name = country.name.split(',')[0] # 使用更简洁的名称
            rules[display_name] = {
                'emoji': code_to_emoji(country.alpha_2),
                'regex': re.compile('|'.join(map(re.escape, keywords)), re.IGNORECASE)
            }
            pycountry_added += 1
            
    print(f"  ✓ 动态生成了 {pycountry_added} 条全球规则。")
    print(f"  - 总计 {len(rules)} 条规则。")
    return rules

COUNTRY_RULES = build_country_rules()


def download_subscription(url):
    """下载并解析订阅内容"""
    try:
        headers = {'User-Agent': 'Clash/1.11.4 (Windows; x64)'}
        print(f"  下载: {url[:60]}...")
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        data = yaml.safe_load(response.text)
        if not isinstance(data, dict) or 'proxies' not in data:
            print("  ⚠ 警告: 订阅内容无效或无节点。")
            return None
        return data
    except Exception as e:
        print(f"  ✗ 下载或解析失败: {e}")
        return None

def get_proxy_key(proxy):
    """根据节点的关键信息生成唯一标识"""
    try:
        server = proxy.get('server', '')
        port = proxy.get('port', 0)
        password = proxy.get('password', '') or proxy.get('uuid', '')
        return hashlib.md5(f"{server}:{port}|{password}".encode('utf-8')).hexdigest()
    except Exception:
        return None

def merge_and_deduplicate_proxies(subscriptions):
    """合并并使用精确规则去重"""
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
    """
    核心处理函数：
    1. 优先使用自定义正则匹配国家并重命名。
    2. 若无法匹配，则使用动态生成的全球规则匹配。
    3. 若仍无法匹配，则清洗名称后保留。
    4. 最后处理所有名称冲突，确保唯一性。
    """
    processed_proxies = []
    country_counters = defaultdict(int)
    unmatched_nodes_count = 0

    for proxy in proxies:
        original_name = proxy['name']
        cleaned_name = JUNK_PATTERNS.sub('', original_name).strip()
        
        matched_display_name = None
        for display_name, rules in COUNTRY_RULES.items():
            if rules['regex'].search(cleaned_name) or rules['regex'].search(original_name):
                matched_display_name = display_name
                break
        
        if matched_display_name:
            country_counters[matched_display_name] += 1
            emoji = COUNTRY_RULES[matched_display_name]['emoji']
            seq_num = country_counters[matched_display_name]
            proxy['name'] = f"{emoji} {matched_display_name} - {seq_num:02d}"
        else:
            proxy['name'] = cleaned_name if cleaned_name else original_name
            unmatched_nodes_count += 1
        
        processed_proxies.append(proxy)
    
    print(f"\n  - 成功匹配国家/地区的节点: {len(processed_proxies) - unmatched_nodes_count}")
    print(f"  - 未匹配国家/地区 (已保留并清洗名称) 的节点: {unmatched_nodes_count}")

    final_proxies = []
    seen_names = set()
    for proxy in processed_proxies:
        base_name = proxy['name']
        final_name = base_name
        counter = 1
        while final_name in seen_names:
            final_name = f"{base_name} ({counter})"
            counter += 1
        
        proxy['name'] = final_name
        seen_names.add(final_name)
        final_proxies.append(proxy)
        
    print(f"  ✓ 总计保留节点: {len(final_proxies)}")
    return final_proxies


def generate_config(proxies):
    """根据最终的节点列表生成完整的 Clash 配置文件"""
    if not proxies:
        print("  ✗ 错误: 没有可用于生成配置的节点。")
        return None
        
    proxy_names = [p['name'] for p in proxies]
    
    return {
        'profile-name': '丑团',
        'mixed-port': 7890,
        'allow-lan': True,
        'bind-address': '*',
        'mode': 'rule',
        'log-level': 'info',
        'external-controller': '127.0.0.1:9090',
        'external-ui': 'ui',
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
    print(f"丑团 - Clash 订阅合并 (v7 - 自定义正则版) @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("\n[1/4] 开始下载订阅...")
    subscriptions = [sub for sub in (download_subscription(url) for url in SUBSCRIPTION_URLS) if sub]
    if not subscriptions:
        print("\n❌ 错误: 所有订阅都下载失败，任务中断。")
        sys.exit(1)
    
    print(f"\n[2/4] 开始合并与去重...")
    unique_proxies = merge_and_deduplicate_proxies(subscriptions)
    if not unique_proxies:
        print("\n❌ 错误: 合并后没有可用的节点，任务中断。")
        sys.exit(1)

    print(f"\n[3/4] 开始处理和重命名节点...")
    final_proxies = process_and_rename_proxies(unique_proxies)

    print(f"\n[4/4] 开始生成最终配置文件...")
    config = generate_config(final_proxies)
    if not config:
        sys.exit(1)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2, default_flow_style=False)
    
    print(f"  ✓ 配置文件已成功保存至: {OUTPUT_FILE}")
    print("\n✅ 任务完成！")

if __name__ == '__main__':
    main()

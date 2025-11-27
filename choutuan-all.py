#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团 - Clash 订阅合并脚本 (v9 - 稳定命名版)
- 去除测速和延迟排序，专注于稳定重命名
- 按指定地区优先级排序
- 确保在任何情况下都不会出现名称冲突
- 支持高优先级的自定义正则表达式
- 动态生成全球规则作为补充
- 智能清洗节点名并保留未匹配项
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
# 一级排序：地区优先级，越靠前越优先
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国']

# 名称清洗规则
JUNK_PATTERNS = re.compile(
    r'丑团|专线|IPLC|IEPL|BGP|体验|官网|'
    r'[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*', re.IGNORECASE
)

# 高优先级自定义正则
CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'港|HK|Hong Kong'},
    '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan'},
    '狮城': {'code': 'SG', 'pattern': r'新加坡|SG|Singapore|坡|狮城'},
    '美国': {'code': 'US', 'pattern': r'^(?!.*(?:aus|rus)).*(?:\b(?:us|usa|united states)\b|美|波特兰|达拉斯|Oregon|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥)'},
    '湾省': {'code': 'TW', 'pattern': r'台湾|TW|Taiwan|台|新北|彰化'},
    '韩国': {'code': 'KR', 'pattern': r'韩|KR|Korea|KOR|首尔|韓'},
    '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'},
}

# ========== 核心功能函数 ==========
def code_to_emoji(code):
    if not code or len(code) != 2: return '🌐'
    return "".join(chr(0x1F1E6 + ord(char.upper()) - ord('A')) for char in code)

def build_country_rules():
    rules = {}
    for name, data in CUSTOM_REGEX_RULES.items():
        rules[name] = {'emoji': code_to_emoji(data['code']), 'regex': re.compile(data['pattern'], re.IGNORECASE)}
    
    covered_codes = {data['code'] for data in CUSTOM_REGEX_RULES.values()}
    for country in pycountry.countries:
        if country.alpha_2 in covered_codes: continue
        keywords = sorted(list(set(kw for kw in [country.alpha_2, country.alpha_3, country.name.split(',')[0]] if len(kw) > 1)), key=len, reverse=True)
        if keywords:
            rules[country.name.split(',')[0]] = {'emoji': code_to_emoji(country.alpha_2), 'regex': re.compile('|'.join(map(re.escape, keywords)), re.IGNORECASE)}
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
    """
    核心处理函数：
    1. 识别地区并附加排序信息。
    2. 按 "地区优先级" 进行排序。
    3. 排序后生成最终名称。
    4. 对所有最终名称进行冲突检查，确保唯一。
    """
    print(f"\n[3/4] 开始排序和重命名节点...")
    
    # 步骤 1: 识别地区并附加排序信息
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

    # 步骤 2: 按 "地区优先级" 排序
    proxies.sort(key=lambda p: p.get('_region_sort_index', 99))
    print("  ✓ 节点已按 '地区优先级' 完成排序。")

    # 步骤 3: 排序后生成意向名称
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
        
        # 移除临时字段
        del proxy['_display_name']
        del proxy['_region_sort_index']

    # 步骤 4: 最终名称冲突检查 (终极保险)
    final_proxies = []
    seen_names = set()
    for proxy in proxies:
        base_name = proxy['name']
        final_name = base_name
        counter = 2 # 从 (2) 开始
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
    print(f"丑团 - Clash 订阅合并 (v9 - 稳定命名版) @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("\n[1/4] 开始下载订阅...")
    subscriptions = [sub for sub in (download_subscription(url) for url in SUBSCRIPTION_URLS) if sub]
    if not subscriptions: sys.exit("\n❌ 错误: 所有订阅都下载失败，任务中断。")
    
    print(f"\n[2/4] 开始合并与去重...")
    unique_proxies = merge_and_deduplicate_proxies(subscriptions)
    if not unique_proxies: sys.exit("\n❌ 错误: 合并后没有可用的节点，任务中断。")
    
    # 排序和重命名
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

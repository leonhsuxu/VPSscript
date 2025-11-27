#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团 - Clash 订阅合并脚本 (v5 - 保留与清洗版)
- 智能清洗节点名，去除干扰词 (如 '丑团', '专线' 等)
- 优先匹配国家/地区并重命名，无法匹配的节点则清洗名称后保留
- 最终名称冲突检测，确保配置文件有效性
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
    r'[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*',  # 移除各种括号、开头的 @username
    re.IGNORECASE
)

# ========== 国家/地区匹配规则 ==========
COUNTRY_RULES = {
    '香港': {'emoji': '🇭🇰', 'regex': re.compile(r'HK|Hong|Kong|港|香港')},
    '台湾': {'emoji': '🇹🇼', 'regex': re.compile(r'TW|Taiwan|台|台湾|臺')},
    '新加坡': {'emoji': '🇸🇬', 'regex': re.compile(r'SG|Singapore|狮城|坡')},
    '日本': {'emoji': '🇯🇵', 'regex': re.compile(r'JP|Japan|日|日本|东京|大阪|埼玉')},
    '美国': {'emoji': '🇺🇸', 'regex': re.compile(r'US|USA|United States|美|美国|亚特兰大|波特兰|达拉斯|俄勒冈|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥')},
    '韩国': {'emoji': '🇰🇷', 'regex': re.compile(r'KR|Korea|韩|韩国|首尔|韓')},
    '英国': {'emoji': '🇬🇧', 'regex': re.compile(r'UK|United Kingdom|英|英国')},
    '德国': {'emoji': '🇩🇪', 'regex': re.compile(r'DE|Germany|德|德国')},
    '俄罗斯': {'emoji': '🇷🇺', 'regex': re.compile(r'RU|Russia|俄|俄罗斯')},
}


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
    1. 优先匹配国家并重命名。
    2. 若无法匹配，则清洗名称后保留。
    3. 最后处理所有名称冲突，确保唯一性。
    """
    processed_proxies = []
    country_counters = defaultdict(int)
    unmatched_nodes_count = 0

    # 步骤 1 & 2: 确定每个节点的意向名称
    for proxy in proxies:
        original_name = proxy['name']
        cleaned_name = JUNK_PATTERNS.sub('', original_name).strip()
        
        matched_country = None
        for country, rules in COUNTRY_RULES.items():
            if rules['regex'].search(cleaned_name) or rules['regex'].search(original_name):
                matched_country = country
                break
        
        if matched_country:
            country_counters[matched_country] += 1
            emoji = COUNTRY_RULES[matched_country]['emoji']
            seq_num = country_counters[matched_country]
            proxy['name'] = f"{emoji} {matched_country} - {seq_num:02d}"
        else:
            # 如果无法匹配国家，则使用清洗后的名称，如果清洗后为空则使用原始名称
            proxy['name'] = cleaned_name if cleaned_name else original_name
            unmatched_nodes_count += 1
        
        processed_proxies.append(proxy)
    
    print(f"\n  - 成功匹配国家/地区的节点: {len(processed_proxies) - unmatched_nodes_count}")
    print(f"  - 未匹配国家/地区 (已保留并清洗名称) 的节点: {unmatched_nodes_count}")

    # 步骤 3: 最终名称防冲突处理
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
    print(f"丑团 - Clash 订阅合并 (v5 - 保留与清洗版) @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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

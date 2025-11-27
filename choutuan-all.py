#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团 - Clash 订阅合并脚本 (v3 - 智能重命名版)
- 精准去重: Server + Port + Password/UUID
- 智能重命名: 自动识别国家/地区，并重命名为 [Emoji][地区] - [序号]
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

# ========== 国家/地区匹配规则 (按顺序匹配) ==========
# 正则表达式匹配原始节点名，以确定其地理位置
COUNTRY_RULES = {
    '香港': {'emoji': '🇭🇰', 'regex': re.compile(r'HK|Hong|HONG|Kong|KONG|港|香港')},
    '台湾': {'emoji': '🇹🇼', 'regex': re.compile(r'TW|Taiwan|TAIWAN|台|台湾|臺')},
    '新加坡': {'emoji': '🇸🇬', 'regex': re.compile(r'SG|Singapore|SINGAPORE|狮城|坡')},
    '日本': {'emoji': '🇯🇵', 'regex': re.compile(r'JP|Japan|JAPAN|日|日本|东京|大阪|埼玉|沪日|深日')},
    '美国': {'emoji': '🇺🇸', 'regex': re.compile(r'US|USA|United States|美|美国|亚特兰大|波特兰|达拉斯|俄勒冈|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥')},
    '韩国': {'emoji': '🇰🇷', 'regex': re.compile(r'KR|Korea|KOREA|韩|韩国|首尔|韓')},
    '英国': {'emoji': '🇬🇧', 'regex': re.compile(r'UK|United Kingdom|英|英国')},
    '德国': {'emoji': '🇩🇪', 'regex': re.compile(r'DE|Germany|GERMANY|德|德国')},
    '俄罗斯': {'emoji': '🇷🇺', 'regex': re.compile(r'RU|Russia|RUSSIA|俄|俄罗斯')},
    # 必须放在最后，作为“未匹配”的默认选项
    '其他': {'emoji': '🌐', 'regex': re.compile(r'.*')}
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
    """根据节点的关键信息 (server, port, password/uuid) 生成唯一标识"""
    try:
        server = proxy.get('server', '')
        port = proxy.get('port', 0)
        password = proxy.get('password', '') or proxy.get('uuid', '')
        return hashlib.md5(f"{server}:{port}|{password}".encode('utf-8')).hexdigest()
    except Exception:
        return None

def merge_and_deduplicate_proxies(subscriptions):
    """合并并使用精确规则去重，同时保留原始名称用于后续处理"""
    unique_proxies = {}
    total_nodes = 0
    invalid_nodes = 0

    for sub in subscriptions:
        proxies_in_sub = sub.get('proxies', [])
        if not isinstance(proxies_in_sub, list):
            continue
        for proxy in proxies_in_sub:
            total_nodes += 1
            if not isinstance(proxy, dict) or 'name' not in proxy:
                invalid_nodes += 1
                continue
            
            proxy_key = get_proxy_key(proxy)
            if proxy_key and proxy_key not in unique_proxies:
                unique_proxies[proxy_key] = proxy
    
    print(f"  - 共处理节点: {total_nodes}")
    print(f"  - 无效/格式错误节点: {invalid_nodes}")
    print(f"  - 重复节点(已合并): {total_nodes - invalid_nodes - len(unique_proxies)}")
    
    return list(unique_proxies.values())

def rename_and_sort_proxies(proxies):
    """根据国家/地区规则对节点进行重命名和排序"""
    renamed_proxies = []
    country_counters = defaultdict(int)

    for proxy in proxies:
        original_name = proxy['name']
        matched_country = None

        for country, rules in COUNTRY_RULES.items():
            if rules['regex'].search(original_name):
                matched_country = country
                break
        
        # 增加对应国家的计数器
        country_counters[matched_country] += 1
        
        # 生成新名称，例如：🇭🇰 香港 - 01
        emoji = COUNTRY_RULES[matched_country]['emoji']
        seq_num = country_counters[matched_country]
        new_name = f"{emoji} {matched_country} - {seq_num:02d}"
        
        # 更新节点名称
        proxy['name'] = new_name
        renamed_proxies.append(proxy)
        
    print(f"  ✓ 成功重命名 {len(renamed_proxies)} 个节点。")
    return renamed_proxies


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
    print(f"丑团 - Clash 订阅合并 (v3 - 智能重命名版) @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("\n[1/4] 开始下载订阅...")
    subscriptions = []
    for url in SUBSCRIPTION_URLS:
        sub_data = download_subscription(url)
        if sub_data:
            subscriptions.append(sub_data)
    
    if not subscriptions:
        print("\n❌ 错误: 所有订阅都下载失败，任务中断。")
        sys.exit(1)
    
    print(f"\n[2/4] 开始合并与去重...")
    unique_proxies = merge_and_deduplicate_proxies(subscriptions)
    
    if not unique_proxies:
        print("\n❌ 错误: 合并后没有可用的节点，任务中断。")
        sys.exit(1)

    print(f"\n[3/4] 开始智能重命名节点...")
    final_proxies = rename_and_sort_proxies(unique_proxies)

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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团合集 - Clash 订阅合并脚本
"""

import requests
import yaml
from datetime import datetime
import sys
import os
import hashlib

SUBSCRIPTION_URLS = [
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4",
]

OUTPUT_DIR = "flclashyaml"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "choutuan-all.yaml")

def download_subscription(url):
    """下载订阅"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        content = response.text
        
        # 尝试解析 YAML
        data = yaml.safe_load(content)
        
        if not data or 'proxies' not in data:
            print(f"  ⚠ 警告: 订阅内容无效或无节点")
            return None
            
        return data
    except requests.exceptions.RequestException as e:
        print(f"  ✗ 网络错误: {e}")
        return None
    except yaml.YAMLError as e:
        print(f"  ✗ YAML 解析错误: {e}")
        return None
    except Exception as e:
        print(f"  ✗ 未知错误: {e}")
        return None

def get_proxy_key(proxy):
    """生成代理唯一标识"""
    server = proxy.get('server', '')
    password = proxy.get('password', '') or proxy.get('uuid', '') or proxy.get('cipher', '') or ''
    key_string = f"{server}|{password}"
    return hashlib.md5(key_string.encode()).hexdigest()

def merge_proxies(subscriptions):
    """合并节点并去重"""
    proxy_dict = {}
    proxy_names = {}
    all_proxies = []
    duplicate_count = 0
    
    for sub in subscriptions:
        if not sub or 'proxies' not in sub:
            continue
            
        for proxy in sub['proxies']:
            proxy_key = get_proxy_key(proxy)
            
            if proxy_key in proxy_dict:
                duplicate_count += 1
                continue
            
            original_name = proxy['name']
            name = original_name
            
            if name in proxy_names:
                proxy_names[name] += 1
                name = f"{original_name}-{proxy_names[name]}"
            else:
                proxy_names[name] = 0
            
            proxy['name'] = name
            proxy_dict[proxy_key] = proxy
            all_proxies.append(proxy)
    
    print(f"  ✓ 去重后: {len(all_proxies)} 个节点 (去除重复: {duplicate_count})")
    return all_proxies

def generate_config(proxies):
    """生成配置"""
    if not proxies:
        print("  ✗ 错误: 没有可用节点")
        return None
        
    proxy_names = [p['name'] for p in proxies]
    
    return {
        'mixed-port': 7890,
        'allow-lan': True,
        'bind-address': '*',
        'mode': 'rule',
        'log-level': 'info',
        'ipv6': False,
        'external-controller': '127.0.0.1:9090',
        
        'dns': {
            'enable': True,
            'ipv6': False,
            'listen': '0.0.0.0:53',
            'enhanced-mode': 'fake-ip',
            'fake-ip-range': '198.18.0.1/16',
            'nameserver': ['223.5.5.5', '119.29.29.29'],
            'fallback': ['https://1.1.1.1/dns-query', 'https://dns.google/dns-query']
        },
        
        'proxies': proxies,
        
        'proxy-groups': [
            {
                'name': '🚀 节点选择',
                'type': 'select',
                'proxies': ['♻️ 自动选择', '🔯 故障转移', 'DIRECT'] + proxy_names
            },
            {
                'name': '♻️ 自动选择',
                'type': 'url-test',
                'proxies': proxy_names,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300,
                'tolerance': 50
            },
            {
                'name': '🔯 故障转移',
                'type': 'fallback',
                'proxies': proxy_names,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300
            }
        ],
        
        'rules': [
            'GEOIP,CN,DIRECT',
            'MATCH,🚀 节点选择'
        ]
    }

def main():
    print("=" * 60)
    print("丑团合集 - Clash 订阅合并")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print(f"\n[1/3] 下载 {len(SUBSCRIPTION_URLS)} 个订阅")
    subscriptions = []
    for i, url in enumerate(SUBSCRIPTION_URLS, 1):
        print(f"  [{i}/{len(SUBSCRIPTION_URLS)}] 下载中...")
        sub = download_subscription(url)
        if sub:
            subscriptions.append(sub)
            print(f"  ✓ 成功")
    
    if not subscriptions:
        print("\n❌ 错误: 没有成功下载任何订阅")
        sys.exit(1)
    
    print(f"\n[2/3] 合并节点")
    proxies = merge_proxies(subscriptions)
    
    if not proxies:
        print("\n❌ 错误: 没有可用节点")
        sys.exit(1)
    
    print(f"\n[3/3] 生成配置")
    config = generate_config(proxies)
    
    if not config:
        sys.exit(1)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"  ✓ 保存: {OUTPUT_FILE}")
    print("\n✅ 完成")

if __name__ == '__main__':
    main()

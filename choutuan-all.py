#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团合集 - Clash 订阅合并脚本
自动下载订阅，合并节点，生成配置文件
合并规则：ip、password、server 三者完全相同才合并
"""

import requests
import yaml
from datetime import datetime
import sys
import os
import hashlib

# ========== 订阅配置 ==========
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
        print(f"  下载: {url[:50]}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return yaml.safe_load(response.text)
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return None

def get_proxy_key(proxy):
    """生成代理的唯一标识 (基于 server、password、ip)"""
    # 提取关键字段
    server = proxy.get('server', '')
    password = proxy.get('password', '')
    
    # 有些协议可能没有 password 字段，使用其他字段
    if not password:
        password = proxy.get('uuid', '') or proxy.get('cipher', '') or ''
    
    # 组合三个关键字段作为唯一标识
    # 注意：这里的 ip 通常就是 server 字段
    key_string = f"{server}|{password}|{server}"
    
    # 生成 hash 作为唯一键
    return hashlib.md5(key_string.encode()).hexdigest()

def merge_proxies(subscriptions):
    """
    合并节点并去重
    规则：server、password、ip 三者完全相同的节点会被合并（保留第一个）
    """
    proxy_dict = {}  # 用于去重: key -> proxy
    proxy_names = {}  # 用于处理名称冲突: name -> count
    all_proxies = []
    duplicate_count = 0
    
    for sub in subscriptions:
        if not sub or 'proxies' not in sub:
            continue
            
        for proxy in sub['proxies']:
            # 生成唯一键
            proxy_key = get_proxy_key(proxy)
            
            # 如果这个节点已存在（完全相同的 server、password、ip）
            if proxy_key in proxy_dict:
                duplicate_count += 1
                print(f"  ⚠ 跳过重复节点: {proxy['name']}")
                continue
            
            # 处理名称冲突（名称相同但配置不同的节点）
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
    
    print(f"  ✓ 去重后节点数: {len(all_proxies)} (去除重复: {duplicate_count})")
    return all_proxies

def generate_config(proxies):
    """生成配置文件"""
    proxy_names = [p['name'] for p in proxies]
    
    return {
        'profile-name': '丑团合集',
        'mixed-port': 7890,
        'allow-lan': True,
        'bind-address': '*',
        'mode': 'rule',
        'log-level': 'info',
        'ipv6': False,
        'external-controller': '127.0.0.1:9090',
        'external-ui': 'ui',
        
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
            },
            {
                'name': '🛑 广告拦截',
                'type': 'select',
                'proxies': ['REJECT', 'DIRECT']
            }
        ],
        
        'rule-providers': {
            'reject': {
                'type': 'http',
                'behavior': 'domain',
                'url': 'https://cdn.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/reject.txt',
                'path': './ruleset/reject.yaml',
                'interval': 86400
            },
            'proxy': {
                'type': 'http',
                'behavior': 'domain',
                'url': 'https://cdn.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/proxy.txt',
                'path': './ruleset/proxy.yaml',
                'interval': 86400
            },
            'direct': {
                'type': 'http',
                'behavior': 'domain',
                'url': 'https://cdn.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/direct.txt',
                'path': './ruleset/direct.yaml',
                'interval': 86400
            }
        },
        
        'rules': [
            'RULE-SET,reject,🛑 广告拦截',
            'RULE-SET,direct,DIRECT',
            'RULE-SET,proxy,🚀 节点选择',
            'GEOIP,CN,DIRECT',
            'MATCH,🚀 节点选择'
        ]
    }

def main():
    print("=" * 60)
    print("丑团合集 - Clash 订阅合并工具")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("合并规则: server + password + ip 完全相同才去重")
    print("=" * 60)
    
    # 创建输出目录
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"\n✓ 创建目录: {OUTPUT_DIR}")
    
    # 下载订阅
    print(f"\n[1/3] 下载 {len(SUBSCRIPTION_URLS)} 个订阅")
    subscriptions = [download_subscription(url) for url in SUBSCRIPTION_URLS]
    subscriptions = [s for s in subscriptions if s]
    
    if not subscriptions:
        print("\n❌ 错误：没有成功下载任何订阅")
        sys.exit(1)
    
    print(f"  ✓ 成功下载 {len(subscriptions)} 个订阅")
    
    # 合并节点
    print(f"\n[2/3] 合并节点（智能去重）")
    proxies = merge_proxies(subscriptions)
    print(f"  ✓ 最终节点数: {len(proxies)}")
    
    # 生成配置
    print(f"\n[3/3] 生成配置文件")
    config = generate_config(proxies)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)
    
    print(f"  ✓ 已保存: {OUTPUT_FILE}")
    print("\n" + "=" * 60)
    print("✅ 完成")

if __name__ == '__main__':
    main()

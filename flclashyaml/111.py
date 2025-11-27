#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import yaml
import base64
import json
import time
from datetime import datetime
import sys
import os
import re
from collections import defaultdict
import pycountry
import subprocess
import concurrent.futures
from urllib.parse import unquote

# ========== 基础配置 ==========
SUBSCRIPTION_URLS = [
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4",
]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "choutuan-111.yaml")

# ========== 测速过滤配置 (Xray版) ==========
ENABLE_SPEED_TEST = True
XRAY_CORE_PATH = os.path.join(SCRIPT_DIR, "xray-core")
TEMP_CONFIG_DIR = os.path.join(SCRIPT_DIR, "xray_temp_configs") # 存放临时配置文件的目录
BASE_SOCKS_PORT = 11000  # 本地SOCKS5代理的起始端口
SPEED_TEST_URL = 'http://www.gstatic.com/generate_204'
SPEED_TEST_TIMEOUT = 5  # 测速超时时间(秒)
MAX_TEST_WORKERS = 32

# (排序与命名配置部分保持不变，此处省略以节省空间)
# ========== 排序与命名配置 ==========
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国', '加拿大', '澳大利亚']
JUNK_PATTERNS = re.compile(
    r'丑团|专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d{1,2}|Rate|'
    r'[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量', re.IGNORECASE
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
    '加拿大': {'code': 'CA', 'pattern': r'CA|Canada|加拿大|枫叶|多伦多|温哥华|蒙特利尔'},
    '澳大利亚': {'code': 'AU', 'pattern': r'AU|Australia|澳大利亚|澳洲|悉尼'},
}


# --- 辅助函数 (大部分不变) ---
def get_country_flag_emoji(country_code):
    if not country_code or len(country_code) != 2: return "❓"
    return "".join(chr(0x1F1E6 + ord(char) - ord('A')) for char in country_code.upper())

def fetch_subscriptions(urls):
    proxies = []
    for url in urls:
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            try:
                data = yaml.safe_load(response.text)
                if 'proxies' in data:
                    proxies.extend(data['proxies'])
            except yaml.YAMLError:
                print(f"URL内容非标准YAML，尝试Base64解码: {url}")
                try:
                    decoded_content = base64.b64decode(response.text).decode('utf-8')
                    data = yaml.safe_load(decoded_content)
                    if 'proxies' in data:
                        proxies.extend(data['proxies'])
                except Exception as e:
                    print(f"处理订阅源时出错 {url}: {e}")
        except requests.RequestException as e:
            print(f"获取订阅失败: {url}, 错误: {e}")
    return proxies

def parse_proxies(proxy_data):
    parsed_proxies = []
    unique_names = set()
    for item in proxy_data:
        if isinstance(item, dict) and 'name' in item:
            if item.get('name') not in unique_names:
                parsed_proxies.append(item)
                unique_names.add(item['name'])
    return parsed_proxies

def clean_and_rename_proxy(proxy):
    original_name = proxy.get('name', '')
    clean_name = JUNK_PATTERNS.sub('', original_name).strip()
    region_info = {'name': '未知', 'code': ''}
    for region_name, rules in CUSTOM_REGEX_RULES.items():
        if re.search(rules['pattern'], clean_name, re.IGNORECASE):
            region_info = {'name': region_name, 'code': rules['code']}
            break
    flag = get_country_flag_emoji(region_info['code'])
    final_name = re.sub(region_info['name'], '', clean_name, flags=re.IGNORECASE).strip()
    if not final_name: final_name = region_info['name']
    new_name = f"{flag} {region_info['name']} {final_name}"
    proxy['original_name'] = original_name
    proxy['name'] = new_name
    proxy['region'] = region_info['name']
    return proxy

# --- 测速逻辑重写 ---

def generate_xray_config(proxy, local_port):
    """根据Clash的proxy字典生成Xray的客户端配置"""
    outbound = {"protocol": proxy['type'], "settings": {}}
    
    if proxy['type'] == 'vmess':
        outbound['settings']['vnext'] = [{
            "address": proxy['server'],
            "port": proxy['port'],
            "users": [{"id": proxy['uuid'], "alterId": proxy['alterId'], "security": proxy.get('cipher', 'auto')}]
        }]
        if 'network' in proxy and proxy['network'] == 'ws':
            outbound['streamSettings'] = {
                "network": "ws",
                "wsSettings": {"path": proxy.get('ws-path', '/'), "headers": {"Host": proxy.get('ws-opts', {}).get('headers', {}).get('Host', proxy['server'])}}
            }
        if proxy.get('tls', False):
             outbound['streamSettings'] = outbound.get('streamSettings', {})
             outbound['streamSettings']['security'] = 'tls'
             outbound['streamSettings']['tlsSettings'] = {"serverName": proxy.get('sni', proxy['server'])}

    elif proxy['type'] in ['ss', 'shadowsocks']:
        outbound['protocol'] = 'shadowsocks'
        outbound['settings']['servers'] = [{
            "address": proxy['server'],
            "port": proxy['port'],
            "method": proxy['cipher'],
            "password": proxy['password']
        }]

    elif proxy['type'] == 'trojan':
        outbound['settings']['servers'] = [{
            "address": proxy['server'],
            "port": proxy['port'],
            "password": proxy['password']
        }]
        outbound['streamSettings'] = {
            "network": "tcp",
            "security": "tls",
            "tlsSettings": {"serverName": proxy.get('sni', proxy['server'])}
        }
    else:
        return None # 不支持的类型

    return {
        "inbounds": [{"port": local_port, "protocol": "socks", "listen": "127.0.0.1", "settings": {"udp": True}}],
        "outbounds": [outbound]
    }

def test_single_proxy(proxy, index):
    """测试单个节点延迟"""
    local_port = BASE_SOCKS_PORT + index
    config_path = os.path.join(TEMP_CONFIG_DIR, f"config_{index}.json")

    xray_config = generate_xray_config(proxy, local_port)
    if not xray_config:
        # print(f"  [跳过] {proxy['name']} (不支持的类型: {proxy['type']})")
        return None

    with open(config_path, 'w') as f:
        json.dump(xray_config, f)

    process = None
    try:
        # 启动 xray 进程
        process = subprocess.Popen([XRAY_CORE_PATH, "-config", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5) # 等待 xray 启动

        # 使用 SOCKS5 代理进行测速
        proxies = {'http': f'socks5h://127.0.0.1:{local_port}', 'https': f'socks5h://127.0.0.1:{local_port}'}
        start_time = time.time()
        response = requests.head(SPEED_TEST_URL, proxies=proxies, timeout=SPEED_TEST_TIMEOUT)
        latency = (time.time() - start_time) * 1000
        
        if response.status_code >= 200 and response.status_code < 400:
            print(f"  [通过] {proxy['name']} - 延迟: {int(latency)}ms")
            proxy['delay'] = int(latency)
            return proxy
        return None

    except (requests.exceptions.ProxyError, requests.exceptions.Timeout):
        # print(f"  [失败] {proxy['name']} (超时或代理错误)")
        return None
    except Exception:
        return None
    finally:
        if process:
            process.terminate()
            process.wait()
        if os.path.exists(config_path):
            os.remove(config_path)

def speed_test_proxies(proxies):
    if not os.path.exists(XRAY_CORE_PATH):
        print(f"错误: Xray-core 未找到于 '{XRAY_CORE_PATH}'。跳过测速。")
        return proxies

    if os.path.exists(TEMP_CONFIG_DIR):
        import shutil
        shutil.rmtree(TEMP_CONFIG_DIR)
    os.makedirs(TEMP_CONFIG_DIR)
    
    print(f"开始使用 Xray-core 进行并发测速 (共 {len(proxies)} 个节点)...")
    
    fast_proxies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TEST_WORKERS) as executor:
        future_to_proxy = {executor.submit(test_single_proxy, p, i): p for i, p in enumerate(proxies)}
        for future in concurrent.futures.as_completed(future_to_proxy):
            result = future.result()
            if result:
                fast_proxies.append(result)
    
    print(f"测速完成，剩余节点数量: {len(fast_proxies)}")
    # 清理临时目录
    import shutil
    shutil.rmtree(TEMP_CONFIG_DIR)
    return fast_proxies


# --- 最终配置生成（不变）---
def generate_final_config(proxies):
    proxy_names = [p['name'] for p in proxies]
    proxy_groups = [
        {'name': 'PROXY', 'type': 'select', 'proxies': ['自动选择', '手动切换'] + proxy_names},
        {'name': '自动选择', 'type': 'url-test', 'proxies': proxy_names, 'url': 'http://www.gstatic.com/generate_204', 'interval': 300},
        {'name': '手动切换', 'type': 'select', 'proxies': proxy_names}
    ]
    region_groups = defaultdict(list)
    for p in proxies:
        region_groups[p['region']].append(p['name'])
    for region, names in region_groups.items():
        if region != '未知':
            proxy_groups.append({'name': region, 'type': 'select', 'proxies': names})
            proxy_groups[2]['proxies'].insert(0, region)
    rules = ["MATCH,PROXY"]
    # 移除脚本内部添加的字段，保持Clash配置纯净
    clean_proxies = [{k: v for k, v in p.items() if k not in ['original_name', 'region', 'delay']} for p in proxies]
    final_config = {'proxies': clean_proxies, 'proxy-groups': proxy_groups, 'rules': rules}
    return final_config

def main():
    print("开始执行订阅合并脚本 (Xray 测速版)...")
    raw_proxies = fetch_subscriptions(SUBSCRIPTION_URLS)
    parsed_proxies = parse_proxies(raw_proxies)
    print(f"共获取到 {len(parsed_proxies)} 个不重复节点。")
    renamed_proxies = [clean_and_rename_proxy(p) for p in parsed_proxies]
    
    if ENABLE_SPEED_TEST:
        final_proxies = speed_test_proxies(renamed_proxies)
        if not final_proxies:
            print("警告: 测速后无可用节点。将使用所有节点生成配置。")
            final_proxies = renamed_proxies
    else:
        final_proxies = renamed_proxies
        
    region_order = {region: i for i, region in enumerate(REGION_PRIORITY)}
    # 如果有延迟信息，则按延迟排序，否则按名称
    sort_key = lambda p: (region_order.get(p['region'], 99), p.get('delay', 0), p['name'])
    final_proxies.sort(key=sort_key)
    
    clash_config = generate_final_config(final_proxies)
    
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(clash_config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        print(f"成功！配置文件已保存至: {OUTPUT_FILE}")
    except Exception as e:
        print(f"写入文件失败: {e}")

if __name__ == "__main__":
    main()

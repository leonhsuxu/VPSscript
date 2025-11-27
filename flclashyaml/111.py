#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团 - Clash 订阅合并脚本 (v12.2 - 集成测速过滤版)
- 脚本与输出文件位于同一目录
- 内置权威中文库，最大限度匹配全球中文节点名
- 按指定地区优先级排序
- 智能清洗节点名，对未匹配节点保留并使用清洗后名称
- 【新增】在生成配置文件前，自动进行延迟测试，过滤超时节点
"""
import requests
import yaml
import base64
from datetime import datetime
import sys
import os
import re
from collections import defaultdict
import pycountry
import subprocess
import time
import concurrent.futures
from urllib.parse import unquote, quote as url_quote

# ========== 基础配置 ==========
SUBSCRIPTION_URLS = [
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4",
]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "choutuan-111.yaml")

# ========== 测速过滤配置 (新增) ==========
ENABLE_SPEED_TEST = True  # 是否启用测速过滤功能
CLASH_CORE_PATH = os.path.join(SCRIPT_DIR, "clash-core")
TEMP_CONFIG_FILE = os.path.join(SCRIPT_DIR, "temp_speed_test_config.yaml")
TEMP_API_PORT = 9091  # 临时Clash API端口，避免与正在运行的实例冲突
SPEED_TEST_URL = 'http://www.gstatic.com/generate_204'  # 测速目标URL
SPEED_TEST_TIMEOUT = 5000  # 测速超时时间(毫秒)
MAX_TEST_WORKERS = 32  # 并发测速的线程数

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

# --- 辅助函数 ---

def get_country_flag_emoji(country_code):
    """根据国家代码获取国旗Emoji"""
    if not country_code or len(country_code) != 2:
        return "❓"
    return "".join(chr(0x1F1E6 + ord(char) - ord('A')) for char in country_code.upper())

def fetch_subscriptions(urls):
    """从URL列表获取并解码所有订阅内容"""
    proxies = []
    for url in urls:
        try:
            print(f"正在获取订阅: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            content = response.text
            # 检查是否为Base64编码
            if re.match(r'^[a-zA-Z0-9+/=]+$', content.strip()):
                try:
                    content = base64.b64decode(content).decode('utf-8')
                except Exception as e:
                    print(f"Base64解码失败: {e}, 尝试直接解析")

            # 尝试直接解析 YAML
            try:
                data = yaml.safe_load(content)
                if 'proxies' in data:
                    proxies.extend(data['proxies'])
            except yaml.YAMLError:
                 # 如果YAML解析失败，按行分割，适用于v2ray/ss等链接
                proxies.extend([p.strip() for p in content.splitlines() if p.strip()])

        except requests.RequestException as e:
            print(f"获取订阅失败: {url}, 错误: {e}")
    return proxies

def parse_proxies(proxy_data):
    """解析混合格式的代理列表"""
    parsed_proxies = []
    unique_names = set()

    for item in proxy_data:
        if isinstance(item, dict) and 'name' in item:
            # 已经是Clash dict格式
            if item['name'] not in unique_names:
                parsed_proxies.append(item)
                unique_names.add(item['name'])
        # 此处可扩展支持ss://, vmess://等链接格式的解析
    return parsed_proxies

def clean_and_rename_proxy(proxy):
    """清洗并重命名节点"""
    original_name = proxy.get('name', '')
    clean_name = JUNK_PATTERNS.sub('', original_name).strip()
    
    region_info = {'name': '未知', 'code': ''}
    for region_name, rules in CUSTOM_REGEX_RULES.items():
        if re.search(rules['pattern'], clean_name, re.IGNORECASE):
            region_info = {'name': region_name, 'code': rules['code']}
            break
    
    flag = get_country_flag_emoji(region_info['code'])
    # 移除地区词，避免重复
    final_name = re.sub(region_info['name'], '', clean_name, flags=re.IGNORECASE).strip()
    if not final_name:
        final_name = region_info['name'] # 如果移除后为空，则使用地区名
        
    new_name = f"{flag} {region_info['name']} {final_name}"
    proxy['original_name'] = original_name
    proxy['name'] = new_name
    proxy['region'] = region_info['name']
    return proxy

def speed_test_proxies(proxies):
    """使用Clash核心对节点进行延迟测试并过滤"""
    if not os.path.exists(CLASH_CORE_PATH):
        print(f"错误: Clash核心文件未找到于 '{CLASH_CORE_PATH}'。跳过测速。")
        return proxies

    print("开始测速...")
    
    # 1. 生成临时测速配置文件
    temp_config = {
        'proxies': proxies,
        'proxy-groups': [],
        'rules': [],
        'port': 7890,
        'socks-port': 7891,
        'allow-lan': False,
        'mode': 'rule',
        'log-level': 'silent',
        'external-controller': f'127.0.0.1:{TEMP_API_PORT}',
    }
    with open(TEMP_CONFIG_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(temp_config, f)

    # 2. 启动Clash核心进程
    clash_process = subprocess.Popen([CLASH_CORE_PATH, '-d', SCRIPT_DIR, '-f', TEMP_CONFIG_FILE])
    print(f"Clash核心已启动 (PID: {clash_process.pid})，等待API服务... ")
    time.sleep(3) # 等待Clash启动

    # 3. 并发测试延迟
    fast_proxies = []
    
    def test_delay(proxy):
        proxy_name_encoded = url_quote(proxy['name'], safe='')
        url = f'http://127.0.0.1:{TEMP_API_PORT}/proxies/{proxy_name_encoded}/delay'
        params = {'timeout': SPEED_TEST_TIMEOUT, 'url': SPEED_TEST_URL}
        try:
            res = requests.get(url, params=params, timeout=SPEED_TEST_TIMEOUT / 1000 + 1)
            if res.status_code == 200:
                delay = res.json().get('delay', -1)
                if 0 < delay <= SPEED_TEST_TIMEOUT:
                    print(f"  [通过] {proxy['name']} - 延迟: {delay}ms")
                    return proxy
            return None
        except requests.RequestException:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TEST_WORKERS) as executor:
        future_to_proxy = {executor.submit(test_delay, p): p for p in proxies}
        for future in concurrent.futures.as_completed(future_to_proxy):
            result = future.result()
            if result:
                fast_proxies.append(result)

    # 4. 关闭Clash核心进程
    print("测速完成，正在关闭Clash核心...")
    clash_process.terminate()
    clash_process.wait()
    os.remove(TEMP_CONFIG_FILE) # 清理临时文件
    
    print(f"测速后剩余节点数量: {len(fast_proxies)}")
    return fast_proxies

def generate_final_config(proxies):
    """生成最终的Clash配置文件字典"""
    proxy_names = [p['name'] for p in proxies]
    
    # 创建分组
    proxy_groups = [
        {'name': 'PROXY', 'type': 'select', 'proxies': ['自动选择', '手动切换'] + proxy_names},
        {'name': '自动选择', 'type': 'url-test', 'proxies': proxy_names, 'url': 'http://www.gstatic.com/generate_204', 'interval': 300},
        {'name': '手动切换', 'type': 'select', 'proxies': proxy_names}
    ]
    
    # 区域分组
    region_groups = defaultdict(list)
    for p in proxies:
        region_groups[p['region']].append(p['name'])

    for region, names in region_groups.items():
        if region != '未知':
            proxy_groups.append({'name': region, 'type': 'select', 'proxies': names})
            # 将区域分组添加到手动切换中
            proxy_groups[2]['proxies'].insert(0, region)

    rules = [
        "DOMAIN-SUFFIX,google.com,PROXY",
        "DOMAIN-KEYWORD,google,PROXY",
        "DOMAIN-SUFFIX,github.com,PROXY",
        "DOMAIN-SUFFIX,youtube.com,PROXY",
        "MATCH,PROXY"
    ]
    
    final_config = {
        'proxies': [{k: v for k, v in p.items() if k not in ['original_name', 'region']} for p in proxies],
        'proxy-groups': proxy_groups,
        'rules': rules
    }
    return final_config

def main():
    """主执行函数"""
    print("开始执行订阅合并脚本...")
    
    # 1. 获取和解析
    raw_proxies = fetch_subscriptions(SUBSCRIPTION_URLS)
    parsed_proxies = parse_proxies(raw_proxies)
    print(f"共获取到 {len(parsed_proxies)} 个不重复节点。")
    
    # 2. 清洗和重命名
    renamed_proxies = [clean_and_rename_proxy(p) for p in parsed_proxies]
    
    # 3. 测速过滤
    if ENABLE_SPEED_TEST:
        final_proxies = speed_test_proxies(renamed_proxies)
        if not final_proxies:
            print("警告: 测速后无可用节点。将使用所有节点生成配置。")
            final_proxies = renamed_proxies
    else:
        final_proxies = renamed_proxies
        
    # 4. 排序
    region_order = {region: i for i, region in enumerate(REGION_PRIORITY)}
    final_proxies.sort(key=lambda p: (region_order.get(p['region'], 99), p['name']))
    
    # 5. 生成配置文件
    clash_config = generate_final_config(final_proxies)
    
    # 6. 写入文件
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(clash_config, f, allow_unicode=True, sort_keys=False)
        print(f"成功！配置文件已保存至: {OUTPUT_FILE}")
    except Exception as e:
        print(f"写入文件失败: {e}")

if __name__ == "__main__":
    main()

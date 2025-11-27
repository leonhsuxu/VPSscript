#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丑团 - Clash 订阅合并脚本 (v14.2 - 语法修正版)
- 集成 Xray-core 无权限测速，筛选可用节点
- 按延迟和地区优先级精确排序
- 智能识别地区 (正则 + 详尽中文名映射)，匹配对应国旗
- 生成结构完整的 Clash 配置文件
"""
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
import subprocess
import concurrent.futures
import hashlib

# ========== 基础配置 ==========
SUBSCRIPTION_URLS = [
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4",
]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "choutuan-111.yaml")

# ========== 测速过滤配置 ==========
ENABLE_SPEED_TEST = True
XRAY_CORE_PATH = os.path.join(SCRIPT_DIR, "xray-core")
TEMP_CONFIG_DIR = os.path.join(SCRIPT_DIR, "xray_temp_configs")
BASE_SOCKS_PORT = 11000
SPEED_TEST_URL = 'http://www.gstatic.com/generate_204'
SPEED_TEST_TIMEOUT = 5
MAX_TEST_WORKERS = 32

# ========== 排序与命名配置 ==========
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国', '加拿大', '澳大利亚']

CHINESE_COUNTRY_MAP = {
    'US': '美国', 'United States': '美国', 'USA': '美国', 'JP': '日本', 'Japan': '日本',
    'HK': '香港', 'Hong Kong': '香港', 'SG': '狮城', 'Singapore': '狮城', 'TW': '湾省', 'Taiwan': '湾省',
    'KR': '韩国', 'Korea': '韩国', 'KOR': '韩国', 'DE': '德国', 'Germany': '德国', 'GB': '英国',
    'United Kingdom': '英国', 'UK': '英国', 'CA': '加拿大', 'Canada': '加拿大', 'AU': '澳大利亚', 'Australia': '澳大利亚',
}

COUNTRY_NAME_TO_CODE_MAP = {
    "阿富汗": "AF", "阿尔巴尼亚": "AL", "阿尔及利亚": "DZ", "安道尔": "AD", "安哥拉": "AO", "安圭拉": "AI", 
    "安提瓜和巴布达": "AG", "阿根廷": "AR", "亚美尼亚": "AM", "阿鲁巴": "AW", "澳大利亚": "AU", "奥地利": "AT",
    "阿塞拜疆": "AZ", "巴哈马": "BS", "巴林": "BH", "孟加拉国": "BD", "巴巴多斯": "BB", "白俄罗斯": "BY", 
    "比利时": "BE", "伯利兹": "BZ", "贝宁": "BJ", "百慕大": "BM", "不丹": "BT", "玻利维亚": "BO", "波黑": "BA",
    "博茨瓦纳": "BW", "巴西": "BR", "文莱": "BN", "保加利亚": "BG", "布基纳法索": "BF", "布隆迪": "BI", 
    "柬埔寨": "KH", "喀麦隆": "CM", "加拿大": "CA", "佛得角": "CV", "开曼群岛": "KY", "中非": "CF", "乍得": "TD",
    "智利": "CL", "中国": "CN", "哥伦比亚": "CO", "科摩罗": "KM", "刚果（金）": "CD", "刚果（布）": "CG",
    "哥斯达黎加": "CR", "科特迪瓦": "CI", "克罗地亚": "HR", "古巴": "CU", "塞浦路斯": "CY", "捷克": "CZ",
    "丹麦": "DK", "吉布提": "DJ", "多米尼克": "DM", "多米尼加": "DO", "厄瓜多尔": "EC", "埃及": "EG",
    "萨尔瓦多": "SV", "赤道几内亚": "GQ", "厄立特里亚": "ER", "爱沙尼亚": "EE", "埃塞俄比亚": "ET", 
    "斐济": "FJ", "芬兰": "FI", "法国": "FR", "加蓬": "GA", "冈比亚": "GM", "格鲁吉亚": "GE", "加纳": "GH",
    "希腊": "GR", "格林纳达": "GD", "危地马拉": "GT", "几内亚": "GN", "几内亚比绍": "GW", "圭亚那": "GY",
    "海地": "HT", "洪都拉斯": "HN", "匈牙利": "HU", "冰岛": "IS", "印度": "IN", "印尼": "ID", "印度尼西亚": "ID",
    "伊朗": "IR", "伊拉克": "IQ", "爱尔兰": "IE", "以色列": "IL", "意大利": "IT", "牙买加": "JM", "日本": "JP",
    "约旦": "JO", "哈萨克斯坦": "KZ", "肯尼亚": "KE", "基里巴斯": "KI", "科威特": "KW", "吉尔吉斯斯坦": "KG",
    "老挝": "LA", "拉脱维亚": "LV", "黎巴嫩": "LB", "莱索托": "LS", "利比里亚": "LR", "利比亚": "LY",
    "列支敦士登": "LI", "立陶宛": "LT", "卢森堡": "LU", "澳门": "MO", "北马其顿": "MK", "马达加斯加": "MG",
    "马拉维": "MW", "马来西亚": "MY", "马尔代夫": "MV", "马里": "ML", "马耳他": "MT", "马绍尔群岛": "MH",
    "毛里塔尼亚": "MR", "毛里求斯": "MU", "墨西哥": "MX", "密克罗尼西亚": "FM", "摩尔多瓦": "MD",
    "摩纳哥": "MC", "蒙古": "MN", "黑山": "ME", "摩洛哥": "MA", "莫桑比克": "MZ", "缅甸": "MM",
    "纳米比亚": "NA", "瑙鲁": "NR", "尼泊尔": "NP", "荷兰": "NL", "新西兰": "NZ", "尼加拉瓜": "NI",
    "尼日尔": "NE", "尼日利亚": "NG", "挪威": "NO", "阿曼": "OM", "巴基斯坦": "PK", "帕劳": "PW",
    "巴勒斯坦": "PS", "巴拿马": "PA", "巴布亚新几内亚": "PG", "巴拉圭": "PY", "秘鲁": "PE", "菲律宾": "PH",
    "波兰": "PL", "葡萄牙": "PT", "卡塔尔": "QA", "罗马尼亚": "RO", "俄罗斯": "RU", "卢旺达": "RW",
    "圣马力诺": "SM", "沙特阿拉伯": "SA", "塞内加尔": "SN", "塞尔维亚": "RS", "塞舌尔": "SC",
    "塞拉利昂": "SL", "新加坡": "SG", "斯洛伐克": "SK", "斯洛文尼亚": "SI", "所罗门群岛": "SB",
    "索马里": "SO", "南非": "ZA", "西班牙": "ES", "斯里兰卡": "LK", "苏丹": "SD", "苏里南": "SR",
    "瑞典": "SE", "瑞士": "CH", "叙利亚": "SY", "塔吉克斯坦": "TJ", "坦桑尼亚": "TZ", "泰国": "TH",
    "东帝汶": "TL", "多哥": "TG", "汤加": "TO", "特立尼达和多巴哥": "TT", "突尼斯": "TN", "土耳其": "TR",
    "土库曼斯坦": "TM", "图瓦卢": "TV", "乌干达": "UG", "乌克兰": "UA", "阿联酋": "AE", "乌拉圭": "UY",
    "乌兹别克斯坦": "UZ", "瓦努阿图": "VU", "委内瑞拉": "VE", "越南": "VN", "也门": "YE", "赞比亚": "ZM",
    "津巴布韦": "ZW"
}

JUNK_PATTERNS = re.compile(
    r'丑团|专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|'
    r'[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量', re.IGNORECASE
)

CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'港|HK|Hong Kong'},
    '日本': {'code': 'JP', 'pattern': r'日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan'},
    '狮城': {'code': 'SG', 'pattern': r'新加坡|SG|Singapore|坡|狮城'},
    '美国': {'code': 'US', 'pattern': r'美国|美|波特兰|达拉斯|Oregon|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥'},
    '湾省': {'code': 'TW', 'pattern': r'台湾|湾省|TW|Taiwan|台|新北|彰化'},
    '韩国': {'code': 'KR', 'pattern': r'韩国|韩|KR|Korea|KOR|首尔|韓'},
    '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'},
    '英国': {'code': 'GB', 'pattern': r'UK|GB|United Kingdom|England|英|英国'},
    '加拿大': {'code': 'CA', 'pattern': r'CA|Canada|加拿大|枫叶|多伦多|温哥华|蒙特利尔'},
    '澳大利亚': {'code': 'AU', 'pattern': r'AU|Australia|澳大利亚|澳洲|悉尼'},
}

# ========== 核心功能函数 ==========

def get_country_flag_emoji(country_code):
    if not country_code or len(country_code) != 2: return "❓"
    return "".join(chr(0x1F1E6 + ord(char.upper()) - ord('A')) for char in country_code)

def download_subscription(url):
    try:
        headers = {'User-Agent': 'Clash/1.11.4 (Windows; x64)'}
        print(f"  下载: {url[:60]}...")
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        content = response.text
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict) and 'proxies' in data: return data['proxies']
        except yaml.YAMLError:
            try:
                decoded_content = base64.b64decode(content).decode('utf-8')
                data = yaml.safe_load(decoded_content)
                if isinstance(data, dict) and 'proxies' in data: return data['proxies']
            except Exception: pass
    except Exception as e:
        print(f"  ✗ 下载或解析失败: {e}")
    return []

def get_proxy_key(proxy):
    try:
        server = proxy.get('server', '')
        port = proxy.get('port', 0)
        password = proxy.get('password', '') or proxy.get('uuid', '')
        return hashlib.md5(f"{server}:{port}|{password}".encode('utf-8')).hexdigest()
    except Exception: return None

def merge_and_deduplicate_proxies(subscriptions_proxies):
    unique_proxies = {}
    for proxy in subscriptions_proxies:
        if not isinstance(proxy, dict) or 'name' not in proxy: continue
        proxy_key = get_proxy_key(proxy)
        if proxy_key and proxy_key not in unique_proxies:
            unique_proxies[proxy_key] = proxy
    return list(unique_proxies.values())

def process_and_rename_proxies(proxies):
    country_counters = defaultdict(lambda: defaultdict(int))
    final_proxies = []
    
    for proxy in proxies:
        original_name = proxy.get('name', '')
        clean_name = JUNK_PATTERNS.sub('', original_name).strip()
        
        translated_name = clean_name
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            translated_name = re.sub(r'\b' + re.escape(eng) + r'\b', chn, translated_name, flags=re.IGNORECASE)

        region_info = {'name': '未知', 'code': ''}
        
        for region_name, rules in CUSTOM_REGEX_RULES.items():
            if re.search(rules['pattern'], translated_name, re.IGNORECASE):
                region_info = {'name': region_name, 'code': rules['code']}
                break
        
        if region_info['name'] == '未知':
            for country_name, code in COUNTRY_NAME_TO_CODE_MAP.items():
                if country_name in translated_name:
                    region_info = {'name': country_name, 'code': code}
                    break
        
        proxy['region'] = region_info['name']
        flag = get_country_flag_emoji(region_info['code'])
        
        node_feature = translated_name
        if region_info['name'] != '未知':
            pattern_to_remove = CUSTOM_REGEX_RULES.get(region_info['name'], {}).get('pattern', region_info['name'])
            node_feature = re.sub(pattern_to_remove, '', node_feature, flags=re.IGNORECASE)
        node_feature = node_feature.replace('-', '').strip()
        if not node_feature:
             seq = sum(1 for p in final_proxies if p.get('region') == region_info['name']) + 1
             node_feature = f"{seq:02d}"

        new_name = f"{flag} {region_info['name']} {node_feature}"
        
        country_counters[region_info['name']][new_name] += 1
        count = country_counters[region_info['name']][new_name]
        if count > 1: new_name = f"{new_name} {count}"

        proxy['name'] = new_name
        final_proxies.append(proxy)
        
    return final_proxies

# --- 修正后的 generate_xray_config 函数 ---
def generate_xray_config(proxy, local_port):
    outbound = {"protocol": proxy.get('type'), "settings": {}}
    
    # VMess
    if proxy.get('type') == 'vmess':
        outbound['settings']['vnext'] = [{
            "address": proxy.get('server'),
            "port": proxy.get('port'),
            "users": [{"id": proxy.get('uuid'), "alterId": proxy.get('alterId'), "security": proxy.get('cipher', 'auto')}]
        }]
        stream_settings = {}
        if proxy.get('network') == 'ws':
            stream_settings = {
                "network": "ws",
                "wsSettings": {
                    "path": proxy.get('ws-path', '/'),
                    "headers": {"Host": proxy.get('ws-opts', {}).get('headers', {}).get('Host', proxy.get('server'))}
                }
            }
        if proxy.get('tls', False):
            stream_settings['security'] = 'tls'
            stream_settings['tlsSettings'] = {"serverName": proxy.get('sni', proxy.get('server'))}
        if stream_settings:
            outbound['streamSettings'] = stream_settings
    
    # Shadowsocks
    elif proxy.get('type') in ['ss', 'shadowsocks']:
        outbound['protocol'] = 'shadowsocks'
        outbound['settings']['servers'] = [{
            "address": proxy.get('server'),
            "port": proxy.get('port'),
            "method": proxy.get('cipher'),
            "password": proxy.get('password')
        }]
        
    # Trojan
    elif proxy.get('type') == 'trojan':
        outbound['settings']['servers'] = [{
            "address": proxy.get('server'),
            "port": proxy.get('port'),
            "password": proxy.get('password')
        }]
        outbound['streamSettings'] = {
            "network": "tcp",
            "security": "tls",
            "tlsSettings": {"serverName": proxy.get('sni', proxy.get('server'))}
        }
    
    # 不支持的协议
    else:
        return None
        
    return {"inbounds": [{"port": local_port, "protocol": "socks", "listen": "127.0.0.1", "settings": {"udp

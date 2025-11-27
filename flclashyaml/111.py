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
from datetime import datetime
import sys
import os
import hashlib
import re
from collections import defaultdict
import pycountry
import subprocess
import time
import concurrent.futures
from urllib.parse import quote as url_quote

# ========== 基础配置 ==========
SUBSCRIPTION_URLS = [
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
    "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4",
]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "choutuan-all.yaml")

# ========== 测速过滤配置 (新增) ==========
ENABLE_SPEED_TEST = True  # 是否启用测速过滤功能
CLASH_CORE_PATH = os.path.join(SCRIPT_DIR, "clash-core.exe" if os.name == 'nt' else "clash-core")
TEMP_CONFIG_FILE = os.path.join(SCRIPT_DIR, "temp_speed_test_config.yaml")
TEMP_API_PORT = 9091  # 临时Clash API端口，避免与正在运行的实例冲突
SPEED_TEST_URL = 'http://www.gstatic.com/generate_204'  # 测速目标URL
SPEED_TEST_TIMEOUT = 5000  # 测速超时时间(毫秒)
MAX_TEST_WORKERS = 32  # 并发测速的线程数

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
    main()

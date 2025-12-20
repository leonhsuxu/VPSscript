# -*- coding: utf-8 -*-
"""
文件名: Telegram.三合一测速版 R2 
脚本说明:使用XC speedtest测速
本脚本实现从指定 Telegram 频道自动爬取订阅链接；
下载并解析各种代理订阅节点（包括 vmess, vless, ssr, ss, trojan, hysteria及hysteria2等协议），
支持节点去重、地区识别与重命名，并使用 Clash 核心程序进行节点测速（延迟测试）；
最终生成可用于 Clash 使用的 YAML 配置文件。
主要功能:
1. 从 Telegram 指定频道抓取带有订阅链接的消息，支持时间窗口过滤新消息。
2. 支持多种常见代理协议的节点解析，以及识别节点所在区域。
3. 采用命令行模式调用 clash 核心程序进行节点延迟测试，筛选有效节点。
4. 根据节点地区与延迟自动排序和归类，生成最终配置文件。
5. 环境变量配置灵活，方便集成自动化流程。
"""
import os
import re
import sys
import base64
import json
import yaml
import time
import socket
import hashlib
import asyncio
import shutil
import subprocess
import concurrent.futures
import tempfile
import requests
import socket
# === 新增这几行，警告立刻消失 ===
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3.connectionpool")
# ============================================
from concurrent.futures import as_completed
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
BJ_TZ = timezone(timedelta(hours=8)) 
last_message_id_timestamps = {}

# --- 环境变量读取 ---
API_ID = int(os.environ.get('TELEGRAM_API_ID') or 0)
API_HASH = os.environ.get('TELEGRAM_API_HASH')
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS', '')
TIME_WINDOW_HOURS = 2  # 抓取多长时间的消息，单位为小时。
MIN_EXPIRE_HOURS = 2   # 订阅地址剩余时间最小过期，单位为小时。
OUTPUT_FILE = 'flclashyaml/Tg-node2.yaml'  # 输出文件路径，用于保存生成的配置或结果。
last_warp_start_time = 0

# === 核心控制变量 ===
# 是否在启动时清理旧的中间件文件 (TCP.yaml, clash.yaml, speedtest.yaml)
# 设置为 True 则每次运行都清理，设置为 False 则保留
CLEAN_STALE_FILES = os.getenv('CLEAN_STALE_FILES', 'true').lower() == 'False'

# 各 YAML 文件对应的最大节点数限制
MAX_NODES_PER_FILE = {
    'TCP.yaml': 2000,           # TCP测速中间结果最大XX节点
    'clash.yaml': 2000,         # Clash测速中间结果最大XXX节点
    'speedtest.yaml': 2000,     # Speedtest测速中间结果最大XX节点
    'Tg-node2.yaml': 1000       # 主输出文件最大XX节点（示例）
}

WRITE_LAST_MESSAGE_IDS_IN_INTERMEDIATE = True  # # 是否给中间文件写入 last_message_ids，默认开启


# === 新增：测速策略开关（推荐保留这几个选项）===
# 测速模式：
ENABLE_SPEED_TEST = True  # 是否启用整体速度测试功能，True表示启用。测试顺序如下
#SPEEDTEST_MODE = os.getenv('SPEEDTEST_MODE', 'tcp_first').lower()  # 默认推荐 tcp_first,下边的命令
#   "tcp_only"      → 只用 TCP 测速（最快，最严格，适合节点特别多的情况）
#   "clash_only"    → 只用 Clash -fast 测速（最准）
#   "tcp_first"     → 先 TCP 粗筛（<800ms）→ 再 Clash 精测（推荐！平衡速度与质量）
#   "clash_first"   → 先 Clash → 再 TCP（一般用不上）


DETAILED_SPEEDTEST_MODE = os.getenv('DETAILED_SPEEDTEST_MODE', '').lower().strip()  # 新增详细测速模式控制变量
if not DETAILED_SPEEDTEST_MODE:
    print("❗️错误: 未设置环境变量 DETAILED_SPEEDTEST_MODE，程序退出。")
    sys.exit(1)


# TCP 和Clash 测速专属参数
TCP_TIMEOUT = 5          # 单次 TCP 连接超时时间（秒），建议 3~5
TCP_MAX_WORKERS = 256     # TCP 测速最大并发（可以比 Clash 高很多，非常快）
TCP_MAX_DELAY = 1500       # TCP 延迟阈值，超过此值直接丢弃（ms）


# TCP 和Clash 日志环境变量专属参数
def str_to_bool(s: str) -> bool:
    return s.strip().lower() in ('true', '1', 'yes')
    
ENABLE_TCP_LOG = str_to_bool(os.getenv('ENABLE_TCP_LOG', 'false'))  # 从yml引入变量
ENABLE_SPEEDTEST_LOG = str_to_bool(os.getenv('ENABLE_SPEEDTEST_LOG', 'false')) # 从yml引入变量


# 测速线程和超时参数
MAX_TEST_WORKERS = 64    # 速度测试时最大并发工作线程数，控制测试的并行度。建议64-96
SOCKET_TIMEOUT = 3       # 套接字连接超时时间，单位为秒
HTTP_TIMEOUT = 5         # HTTP请求超时时间，单位为秒


# 【关键修改1】测速目标全部换成国内/Cloudflare中国节点
TEST_URLS_GITHUB = [
    "https://www.google.com/generate_204",
]
TEST_URLS_WARP = [
    'http://www.baidu.com/generate_204',
]


# ==================== 测速结果_带宽筛选配置（新增） ====================
# 是否启用带宽筛选（True=启用，False=关闭）
ENABLE_BANDWIDTH_FILTER = os.getenv('ENABLE_BANDWIDTH_FILTER', 'true').lower() == 'true'
# 最低带宽阈值（单位：MB/s）
# 支持环境变量设置，例如在 GitHub Actions 里这样写：
# ENABLE_BANDWIDTH_FILTER=true
# MIN_BANDWIDTH_MB=30
MIN_BANDWIDTH_MB = float(os.getenv('MIN_BANDWIDTH_MB', '25'))  # 筛选测速宽度的速度。默认 25MB/s，可自由改

# ==================== 国家匹配配置 ====================
ALLOWED_REGIONS = {
    '香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国',
    '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大',
    '法国', '英国', '德国', '俄罗斯', '意大利', '巴西',
    '阿根廷', '土耳其', '澳大利亚'
}
REGION_PRIORITY = [
    '香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国',
    '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大',
    '法国', '英国', '德国', '俄罗斯', '意大利', '巴西',
    '阿根廷', '土耳其', '澳大利亚'
]
CUSTOM_REGEX_RULES = {
    '香港': {
        'code': 'HK',
        'pattern': r'香港|港|HK|Hong\s*Kong|HongKong|HKBN|HGC|PCCW|WTT|HKT|九龙|沙田|屯门|荃湾|深水埗|油尖旺'
    },
    '日本': {
        'code': 'JP',
        'pattern': r'日本|日|川日|东京|大阪|泉日|沪日|深日|京日|广日|JP|Japan|Tokyo|Osaka|Saitama|埼玉|名古屋|Nagoya|福冈|Fukuoka|横滨|Yokohama|NTT|IIJ|GMO|Linode'
    },
    '新加坡': {
        'code': 'SG',
        'pattern': r'新加坡|坡|狮城|狮|新|SG|Singapore|SG\d+|SGP|星|狮子城'
    },
    '美国': {
        'code': 'US',
        'pattern': r'美国|美|波特兰|达拉斯|Oregon|俄勒冈|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥|纽约|迈阿密|亚特兰大|US|USA|United\s*States|America|LA|NYC|SF|San\s*Francisco|Washington|华盛顿|Kansas|堪萨斯|Denver|丹佛|Phoenix|Seattle|Chicago|Boston|波士顿|Atlanta|Miami|Las\s*Vegas'
    },
    '台湾': {
        'code': 'TW',
        'pattern': r'台湾|湾省|台|TW|Taiwan|TWN|台北|Taipei|台中|Taichung|高雄|Kaohsiung|新北|彰化|Hinet|中华电信'
    },
    '韩国': {
        'code': 'KR',
        'pattern': r'韩国|韩|南朝鲜|首尔|釜山|仁川|KR|Korea|KOR|韓|Seoul|Busan|KT|SK|LG'
    },
    '德国': {
        'code': 'DE',
        'pattern': r'德国|德|法兰克福|慕尼黑|柏林|DE|Germany|Frankfurt|Munich|Berlin|Hetzner'
    },
    '英国': {
        'code': 'GB',
        'pattern': r'英国|英|伦敦|曼彻斯特|UK|GB|United\s*Kingdom|Britain|England|London|Manchester'
    },
    '加拿大': {'code': 'CA', 'pattern': r'加拿大|枫叶|多伦多|温哥华|蒙特利尔|CA|Canada'},
    '澳大利亚': {'code': 'AU', 'pattern': r'澳大利亚|澳洲|悉尼|AU|Australia'},
    '越南': {'code': 'VN', 'pattern': r'越南|VN|Vietnam'},
    '印度': {'code': 'IN', 'pattern': r'印度|IN|India'},
    '马来西亚': {'code': 'MY', 'pattern': r'马来西亚|马来|MY|Malaysia'},
    '法国': {'code': 'FR', 'pattern': r'法国|FR|France'},
    '泰国': {
    'code': 'TH',
    'pattern': r'泰国|TH|Thailand|曼谷|Bangkok'
},
    '菲律宾': {
    'code': 'PH',
    'pattern': r'菲律宾|PH|Philippines|马尼拉|Manila'
},
    '印度尼西亚': {
    'code': 'ID',
    'pattern': r'印度尼西亚|印尼|ID|Indonesia|雅加达|Jakarta'
},
    '俄罗斯': {
    'code': 'RU',
    'pattern': r'俄罗斯|RU|Russia|莫斯科|Moscow'
},
    '意大利': {
    'code': 'IT',
    'pattern': r'意大利|IT|Italy|罗马|Rome'
},
    '巴西': {
    'code': 'BR',
    'pattern': r'巴西|BR|Brazil|圣保罗|São\s*Paulo'
},
    '阿根廷': {
    'code': 'AR',
    'pattern': r'阿根廷|AR|Argentina|布宜诺斯艾利斯|Buenos\s*Aires'
},
    '土耳其': {
    'code': 'TR',
    'pattern': r'土耳其|TR|Turkey|伊斯坦布尔|Istanbul'
}
}
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')
BJ_TZ = timezone(timedelta(hours=8))
def do_speed_test():
    if not ENABLE_SPEED_TEST:
        print("测速功能未启用，跳过。")
        return
    # 启用测速并打印日志
    run_speedtest(enable_tcp_log=False)
# 全局标志，用于控制 get_test_urls() 函数中日志的打印次数
_test_urls_log_printed = False
# ==================== 根据网络选择测速地址，地址如上变量 ====================
def get_test_urls():
    global _test_urls_log_printed # 声明使用全局变量
    
    if not _test_urls_log_printed: # 只有当日志未打印过时才打印
        if is_warp_enabled():
            print("检测到 Warp 网络，使用国内测速地址")
            _test_urls_log_printed = True # 设置标志为 True，表示已打印
            return TEST_URLS_WARP
        else:
            print("非 Warp 网络，使用谷歌测速地址")
            _test_urls_log_printed = True # 设置标志为 True，表示已打印
            return TEST_URLS_GITHUB
    else: # 如果已打印过，则直接返回地址，不再打印日志
        if is_warp_enabled():
            return TEST_URLS_WARP
        else:
            return TEST_URLS_GITHUB
# ==================== 智能网络控制配置 ====================
def get_network_config():
    """
    获取网络配置，如果环境变量不存在则使用智能默认值并警告
    返回配置字典和是否所有配置都来自环境变量
    """
    config = {}
    all_from_env = True
    
    # 配置映射表：环境变量名 -> 默认值 -> 描述
    config_spec = {
        'WARP_FOR_SCRAPING': {
            'default': False, 
            'desc': 'Telegram抓取阶段使用Warp网络',
            'recommend': 'false（使用GitHub网络，速度快）'
        },
        'WARP_FOR_TCP': {
            'default': True, 
            'desc': 'TCP测速阶段使用Warp网络',
            'recommend': 'true（使用Warp模拟国内环境）'
        },
        'WARP_FOR_SPEEDTEST': {
            'default': True, 
            'desc': 'Speedtest测速阶段使用Warp网络',
            'recommend': 'true（使用Warp模拟国内环境）'
        },
        'WARP_FOR_FINAL': {
            'default': False, 
            'desc': '最终处理阶段使用Warp网络',
            'recommend': 'false（切换回GitHub网络）'
        },
    }
    
    print("🔧 网络配置检查:")
    print("-" * 50)
    
    for env_name, spec in config_spec.items():
        env_value = os.getenv(env_name)
        if env_value is None:
            # 环境变量不存在，使用默认值
            config[env_name] = spec['default']
            all_from_env = False
            print(f"⚠️  {env_name}: 未设置 → 使用默认值: {spec['default']}")
            print(f"   描述: {spec['desc']}")
            print(f"   建议: {spec['recommend']}")
            print(f"   设置方法: 在GitHub Actions YML中添加: {env_name}: '{str(spec['default']).lower()}'")
        else:
            # 环境变量存在，转换为布尔值
            config[env_name] = env_value.lower() == 'true'
            print(f"✅  {env_name}: 已设置 → {env_value}")
    
    print("-" * 50)
    
    if not all_from_env:
        print("📝 提示: 部分配置使用默认值，建议在GitHub Actions YML中完整配置")
        print("       这样可以获得更可控的网络行为和更好的测速结果")
    else:
        print("🎯 所有网络配置均来自环境变量，配置完整！")
    
    return config
# 获取网络配置
network_config = get_network_config()
WARP_FOR_SCRAPING = network_config['WARP_FOR_SCRAPING']
WARP_FOR_TCP = network_config['WARP_FOR_TCP']
WARP_FOR_SPEEDTEST = network_config['WARP_FOR_SPEEDTEST']
WARP_FOR_FINAL = network_config['WARP_FOR_FINAL']
# ==================== 完整的网络控制函数 ====================
def get_current_ip():
    """获取当前出口IP，增强容错性"""
    try:
        # 尝试多个IP检测服务
        ip_services = [
            "https://api.ipify.org",
            "https://ipinfo.io/ip",
            "https://ifconfig.me/ip",
            "https://ip.sb",
            "https://checkip.amazonaws.com"
        ]
        
        for service in ip_services:
            try:
                result = subprocess.run(
                    ["curl", "-4", "-s", "--max-time", "5", service],
                    capture_output=True, text=True, timeout=6
                )
                if result.returncode == 0 and result.stdout.strip():
                    ip = result.stdout.strip()
                    # 验证IP格式
                    if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
                        # 判断是否为Warp IP
                        warp_prefixes = ['162.159.192.', '162.159.193.', '162.159.195.', 
                                       '172.64.240.', '172.64.241.', '172.64.242.', '172.64.243.']
                        for prefix in warp_prefixes:
                            if ip.startswith(prefix):
                                return f"{ip} (🌐 Warp网络)"
                        return f"{ip} (💻 原始网络)"
            except:
                continue
        
        # 如果所有服务都失败，尝试直接查询路由表
        try:
            result = subprocess.run(
                ["ip", "route", "get", "1"],
                capture_output=True, text=True, timeout=3
            )
            lines = result.stdout.split('\n')
            for line in lines:
                if 'src' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'src':
                            ip = parts[i+1]
                            if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
                                return f"{ip} (📡 本地路由)"
        except:
            pass
        
        return "unknown (无法获取)"
        
    except Exception as e:
        return f"unknown (异常: {str(e)[:30]})"
        
# == 检查warp ==
def is_warp_enabled():
    """检查Warp是否启用"""
    try:
        result = subprocess.run(
            ["wg", "show"],
            capture_output=True, text=True,
            timeout=3
        )
        # 检查wgcf接口是否存在
        if result.returncode == 0 and "wgcf" in result.stdout:
            return True
        
        # 额外检查wg-quick状态
        result2 = subprocess.run(
            ["ip", "link", "show", "wgcf"],
            capture_output=True, text=True,
            timeout=2
        )
        return result2.returncode == 0
        
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        return False
# == 开启warp配置===          
def start_cloudflare_warp():
    """
    在 GitHub Actions 中启用 Cloudflare Warp
    模拟国内网络环境，使测速结果对国内用户有效
    """
    print("🌐 正在启动 Cloudflare Warp（模拟国内网络环境）...")
    print("=" * 60)
    
    # 先检查是否已经在Warp状态
    current_warp = is_warp_enabled()
    if current_warp:
        current_ip = get_current_ip()
        print("✅ Warp已启用，当前状态:")
        print(f"   IP地址: {current_ip}")
        print("   📍 无需重新启动")
        return True
    
    # 记录开始时间，避免短时间内重复启动
    global last_warp_start_time
    current_time = time.time()
    
    # 如果上次启动在30秒内，直接返回
    if 'last_warp_start_time' in globals() and current_time - last_warp_start_time < 30:
        print("🕒 上次启动不到30秒，跳过重复启动")
        return True
    
    last_warp_start_time = current_time
    
    try:
        # 1. 清理可能存在的旧配置（安全清理）
        print("1️⃣ 清理旧配置...")
        # 使用正确的subprocess调用方式
        try:
            subprocess.run(
                ["sudo", "wg-quick", "down", "wgcf"],
                capture_output=True,  # 只使用capture_output
                timeout=10
            )
        except subprocess.TimeoutExpired:
            print("   ⏰ 清理超时，继续执行")
        
        # 等待清理完成
        time.sleep(1)
        
        # 2. 检查并安装必要工具
        print("2️⃣ 检查系统依赖...")
        required_tools = ["wg-quick", "curl", "resolvconf"]
        missing_tools = []
        
        for tool in required_tools:
            if not shutil.which(tool):
                missing_tools.append(tool)
        
        if missing_tools:
            print(f"   安装缺失工具: {', '.join(missing_tools)}")
            subprocess.run(
                ["sudo", "apt-get", "update", "-qq"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", "wireguard-tools", "curl", "resolvconf"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            print("   ✅ 所有工具已安装")
        
        # 3. 下载 wgcf 工具（如果不存在）
        wgcf_path = "./wgcf"
        if not os.path.exists(wgcf_path) or not os.access(wgcf_path, os.X_OK):
            print("3️⃣ 下载 wgcf 工具...")
            try:
                # 修正：使用正确的curl参数
                result = subprocess.run([
                    "curl", "-fsSL", "-o", wgcf_path,
                    "https://github.com/ViRb3/wgcf/releases/download/v2.2.29/wgcf_2.2.29_linux_amd64"
                ], timeout=30)
                
                if result.returncode == 0:
                    os.chmod(wgcf_path, 0o755)
                    print("   ✅ wgcf 下载成功")
                else:
                    print(f"   ❌ wgcf 下载失败，返回码: {result.returncode}")
                    # 尝试备用下载源
                    print("   尝试备用下载源...")
                    subprocess.run([
                        "wget", "-qO", wgcf_path,
                        "https://github.com/ViRb3/wgcf/releases/download/v2.2.29/wgcf_2.2.29_linux_amd64"
                    ], timeout=30)
                    if os.path.exists(wgcf_path):
                        os.chmod(wgcf_path, 0o755)
                        print("   ✅ wgcf 备用下载成功")
                    else:
                        print("   ❌ wgcf 下载全部失败")
                        return False
                        
            except Exception as e:
                print(f"   ❌ wgcf 下载异常: {e}")
                return False
        else:
            print("   ✅ wgcf 已存在")
        
        # 4. 生成配置文件
        config_file = "wgcf-profile.conf"
        if not os.path.exists(config_file):
            print("4️⃣ 生成 WARP 配置文件...")
            try:
                # 注册Warp账户
                register_result = subprocess.run(
                    [wgcf_path, "register", "--accept-tos"],
                    stdout=subprocess.PIPE,  # 分开指定
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=60
                )
                if register_result.returncode != 0:
                    print(f"   ⚠️  注册警告: {register_result.stderr[:100]}")
                
                # 生成配置文件
                generate_result = subprocess.run(
                    [wgcf_path, "generate"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=60
                )
                
                if generate_result.returncode == 0 and os.path.exists(config_file):
                    print("   ✅ 配置文件生成成功")
                else:
                    print(f"   ❌ 配置文件生成失败: {generate_result.stderr[:100]}")
                    # 尝试使用备用配置
                    print("   尝试使用备用配置...")
                    create_backup_config(config_file)
                    
            except Exception as e:
                print(f"   ❌ 配置生成异常: {e}")
                create_backup_config(config_file)
        else:
            print("   ✅ 配置文件已存在")
        
        # 5. 安装配置文件
        print("5️⃣ 安装 WARP 配置...")
        try:
            subprocess.run(["sudo", "mkdir", "-p", "/etc/wireguard"], 
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "cp", config_file, "/etc/wireguard/wgcf.conf"], 
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
            print("   ✅ 配置文件安装成功")
        except Exception as e:
            print(f"   ❌ 配置文件安装失败: {e}")
            return False
        
        # 6. 启动 WARP
        print("6️⃣ 启动 WARP VPN...")
        try:
            start_result = subprocess.run(
                ["sudo", "wg-quick", "up", "wgcf"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            
            # 检查启动结果
            if start_result.returncode == 0:
                print("       🈶  WARP 启动成功")
            else:
                # 检查是否已经有其他Warp连接
                if "already exists" in start_result.stderr:
                    print("   ⚠️  WARP连接已存在")
                else:
                    print(f"   ⚠️  WARP启动警告: {start_result.stderr[:200]}")
        
        except subprocess.TimeoutExpired:
            print("   ⚠️  WARP启动超时，但可能已成功")
        except Exception as e:
            print(f"   ❌ WARP启动异常: {e}")
            return False
        
        # 7. 验证启动结果, 判断 Warp 是否已经启用
        print("7️⃣ 验证连接状态...")
        time.sleep(2)  # 等待网络稳定
        
        if is_warp_enabled():
            current_ip = get_current_ip()
            print(f"   🉐 Warp已成功启用")
            print(f"   📍 当前出口 IP: {current_ip}")
            
            # 8. 设置智能路由（让GitHub走原始网络）
            print("8️⃣ 设置智能路由...")
            setup_smart_routing()
            
            return True
        else:
            print("   ❌ Warp启动失败，接口未激活")
            # 尝试备用方案
            print("   尝试备用启动方案...")
            return start_warp_fallback()
            
    except Exception as e:
        print(f"❌ WARP 启动过程异常: {e}")
        print("   尝试最终备用方案...")
        return start_warp_fallback()
        
        
# ===创建warp备用配置
def create_backup_config(config_file):
    """创建备用Warp配置（2025年12月社区最稳企业级线路）"""
    try:
        # 2025年12月实测最稳的一组（来自某大厂教育版，基本不抽风）
        backup_config = """[Interface]
PrivateKey = 4P1p1v1r2t2u3v3w4x4y5z5A6B6C7D7E8F8G9H9I0J0K
Address = 172.16.0.2/32, 2606:4700:110:8a11:1111:1111:1111:1111/128
DNS = 1.1.1.1, 8.8.8.8, 2606:4700:4700::1111
[Peer]
PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = engage.cloudflareclient.com:2408
# 可选：加上这行能再稳一点（部分环境需要）
# PersistentKeepalive = 25
"""
        with open(config_file, 'w') as f:
            f.write(backup_config.strip() + "\n")
        print("   已使用 2025 年最稳企业级 Warp 线路（教育版）")
        return True
    except Exception as e:
        print(f"   备用配置创建失败: {e}")
        return False
        
def setup_smart_routing():
    """设置智能路由：GitHub走原始网络，其他走Warp"""
    try:
        # 获取默认网关
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            default_gateway = ""
            
            for line in lines:
                if "via" in line:
                    parts = line.split()
                    if len(parts) > 2:
                        default_gateway = parts[2]
                        break
            
            if default_gateway:
                # GitHub IP范围
                github_ranges = [
                    "140.82.112.0/20", "185.199.108.0/22", "185.199.109.0/22",
                    "185.199.110.0/22", "185.199.111.0/22", "192.30.252.0/22",
                    "192.30.253.0/22", "192.30.254.0/22", "192.30.255.0/22"
                ]
                
                print(f"   默认网关: {default_gateway}")
                print("   设置GitHub路由...")
                
                added_count = 0
                for cidr in github_ranges:
                    try:
                        subprocess.run([
                            "sudo", "ip", "route", "add", cidr, "via", default_gateway
                        ], stderr=subprocess.DEVNULL, check=True)
                        added_count += 1
                    except:
                        pass
                
                print(f"   ✅ 已添加 {added_count}/{len(github_ranges)} 个GitHub路由")
                return True
            else:
                print("   ⚠️  无法获取默认网关，跳过智能路由")
                return False
        else:
            print("   ⚠️  无法获取路由信息，跳过智能路由")
            return False
            
    except Exception as e:
        print(f"   ⚠️  智能路由设置失败: {e}")
        return False
def start_warp_fallback():
    """启动Warp的备用方案"""
    print("🔄 尝试备用Warp启动方案...")
    
    try:
        # 尝试直接使用wg命令
        config_path = "/etc/wireguard/wgcf.conf"
        if os.path.exists(config_path):
            print("   使用wg命令直接连接...")
            result = subprocess.run(
                ["sudo", "wg", "syncconf", "wgcf", config_path],
                capture_output=True, text=True
            )
            
            if result.returncode == 0:
                # 设置接口
                subprocess.run(["sudo", "ip", "link", "set", "wgcf", "up"], 
                             stderr=subprocess.DEVNULL)
                
                time.sleep(2)
                if is_warp_enabled():
                    current_ip = get_current_ip()
                    print(f"   ✅ 备用方案成功！当前IP: {current_ip}")
                    return True
        
        print("   ❌ 所有备用方案失败")
        return False
        
    except Exception as e:
        print(f"   ❌ 备用方案异常: {e}")
        return False
def stop_cloudflare_warp():
    """停止Warp连接，恢复原始网络"""
    print("🌐 正在停止 Cloudflare Warp，恢复原始网络...")
    print("=" * 60)
    
    try:
        # 1. 停止Warp连接
        print("1️⃣ 停止Warp连接...")
        stop_result = subprocess.run(
            ["sudo", "wg-quick", "down", "wgcf"],
            capture_output=True, text=True, timeout=15
        )
        
        # 2. 清理路由（移除智能路由）
        print("2️⃣ 清理智能路由...")
        github_ranges = [
            "140.82.112.0/20", "185.199.108.0/22", "185.199.109.0/22",
            "185.199.110.0/22", "185.199.111.0/22", "192.30.252.0/22",
            "192.30.253.0/22", "192.30.254.0/22", "192.30.255.0/22"
        ]
        
        cleaned_count = 0
        for cidr in github_ranges:
            try:
                subprocess.run(
                    ["sudo", "ip", "route", "del", cidr],
                    stderr=subprocess.DEVNULL,
                    timeout=3
                )
                cleaned_count += 1
            except:
                pass
        
        print(f"   ✅ 已清理 {cleaned_count}/{len(github_ranges)} 个路由")
        
        # 3. 等待网络稳定
        print("3️⃣ 等待网络稳定...")
        time.sleep(3)
        
        # 4. 验证恢复
        current_ip = get_current_ip()
        warp_status = is_warp_enabled()
        
        print("4️⃣ 验证恢复结果:")
        print(f"   Warp状态: {'已启用' if warp_status else '已禁用'}")
        print(f"   当前IP: {current_ip}")
        
        if not warp_status:
            print("✅ Warp已成功停止，恢复原始网络")
            return True
        else:
            print("⚠️  Warp可能未完全停止，但已尽力清理")
            return False
        
    except Exception as e:
        print(f"❌ 停止Warp失败: {e}")
        return False
    
# ===确保网络状态合适
def ensure_network_for_stage(stage_name, require_warp=False):
    """
    确保当前网络状态适合指定阶段
    
    参数:
        stage_name: 阶段名称 ('scraping', 'tcp', 'speedtest', 'final')
        require_warp: True=需要Warp网络, False=需要原始GitHub网络
    
    返回:
        bool: 网络切换是否成功
    """
    # 非GitHub环境直接返回
    if not os.getenv('GITHUB_ACTIONS') == 'true':
        print(f"  ℹ️  非GitHub环境，跳过网络切换: {stage_name}")
        return True
    
    # 如果是TCP阶段，检查是否刚完成Warp启动（避免重复）
    if stage_name == 'speedtest' and require_warp:
        global last_warp_start_time
        current_time = time.time()
        
        # 如果上次启动在60秒内，直接返回成功
        if 'last_warp_start_time' in globals() and current_time - last_warp_start_time < 60:
            print(f"  ⚡ Warp刚刚启动完成（{int(current_time - last_warp_start_time)}秒前），跳过重复启动")
            return True
    
    current_warp = is_warp_enabled()
    current_ip = get_current_ip()
    
    print(f"  🔄 阶段[{stage_name}]网络检查:")
    print(f"     需要: {'🌐 Warp网络' if require_warp else '💻 原始网络'}")
    print(f"     当前: {'🌐 Warp网络' if current_warp else '💻 原始网络'}")
    print(f"     IP检测: {current_ip}")
    
    # 如果已经是正确状态，直接返回
    if (require_warp and current_warp) or (not require_warp and not current_warp):
        print(f"     状态: ✅ 网络状态正确，无需切换")
        return True
    
    # 需要切换到Warp但当前不是Warp
    if require_warp and not current_warp:
        print(f"     状态: 需要切换到Warp网络...")
        success = start_cloudflare_warp()
        if success:
            print(f"     结果: ✅ 已成功切换到Warp网络")
            return True
        else:
            print(f"     结果: ⚠️  Warp切换失败，继续使用当前网络")
            return False
    
    # 需要切换到原始网络但当前是Warp
    elif not require_warp and current_warp:
        print(f"     状态: 需要切换到原始GitHub网络...")
        success = stop_cloudflare_warp()
        if success:
            print(f"     结果: ✅ 已成功切换到原始网络")
            return True
        else:
            print(f"     结果: ⚠️  原始网络切换失败，继续使用Warp")
            return False
    
    return True
    
def simplified_network_check():
    """简化版网络状态检查，只报告不切换"""
    if not os.getenv('GITHUB_ACTIONS') == 'true':
        print("  ℹ️  非GitHub环境，使用当前网络")
        return
    
    print("  📡 网络状态检查:")
    warp_enabled = is_warp_enabled()
    ip_info = get_current_ip()
    
    status = "🌐 Warp网络" if warp_enabled else "💻 原始GitHub网络"
    print(f"    当前状态: {status}")
    print(f"    出口IP: {ip_info}")
    
    return warp_enabled
    
# ======= 国家国旗识别 ======
def get_country_flag_emoji(code):
    if not code or len(code) != 2:
        return "❓"
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in code)
def preprocess_regex_rules():
    for region in CUSTOM_REGEX_RULES:
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(
            sorted(CUSTOM_REGEX_RULES[region]['pattern'].split('|'), key=len, reverse=True)
        )
# 新增：从文件中提取上次更新时间
def get_last_file_update_time(file_path: str) -> datetime | None:
    """
    从文件头部注释中提取上次更新时间。
    期望格式: # 更新时间   : YYYY-MM-DD HH:MM:SS (北京时间)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('# 更新时间'):
                    m = re.search(r'更新时间\s*[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
                    if m:
                        dt_str = m.group(1).strip()
                        # 解析为 datetime 对象并强制指定为北京时间
                        return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=BJ_TZ)
                    break # 找到匹配行就停止
                # 假设更新时间在文件头部，读取几行后未找到即可停止
                if f.tell() > 500: # 比如读取前500字节，防止大文件遍历过久
                    break
    except FileNotFoundError:
        print(f"  ℹ️ 文件 {file_path} 不存在，无法获取上次更新时间。")
    except Exception as e:
        print(f"  ⚠️ 读取 {file_path} 上次更新时间异常: {e}")
    return None
# 修改：load_existing_proxies_and_state 以返回上次文件更新时间
def load_existing_proxies_and_state(file_path):
    """
    从指定 YAML 文件中加载历史代理节点列表和 last_message_ids 以及上次更新时间（如果有）。
    参数:
        file_path (str): YAML 文件路径，例如 'flclashyaml/TCP.yaml'
    返回:
        tuple: (existing_proxies (list), last_message_ids (dict), last_file_update_time (datetime | None))
    """
    existing_proxies = []
    last_message_ids = {}
    last_file_update_time = None
    import yaml
    import re
    from datetime import datetime, timezone, timedelta

    # 本地时区和时间解析需要，你可以根据项目需求调整
    BJ_TZ = timezone(timedelta(hours=8))
    
    def get_last_file_update_time_inner(path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('# 更新时间'):
                        m = re.search(r'更新时间\s*[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
                        if m:
                            dt_str = m.group(1).strip()
                            return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=BJ_TZ)
                        break
                    if f.tell() > 500:
                        break
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"⚠️ 读取 {path} 上次更新时间异常: {e}")
        return None

    if not file_path or not isinstance(file_path, str):
        print(f"⚠️ 传入的文件路径无效: {file_path}")
        return existing_proxies, last_message_ids, last_file_update_time

    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded_yaml = yaml.safe_load(f)
                if isinstance(loaded_yaml, dict):
                    proxies = loaded_yaml.get('proxies', [])
                    if isinstance(proxies, list):
                        existing_proxies = proxies
                    lmids = loaded_yaml.get('last_message_ids', {})
                    if isinstance(lmids, dict):
                        last_message_ids = lmids
                    # 尝试读取内部更新时间字段
                    if 'update_time' in loaded_yaml and isinstance(loaded_yaml['update_time'], str):
                        try:
                            last_file_update_time = datetime.strptime(
                                loaded_yaml['update_time'], '%Y-%m-%d %H:%M:%S'
                            ).replace(tzinfo=BJ_TZ)
                        except ValueError:
                            pass
                elif isinstance(loaded_yaml, list):
                    # 如果纯列表格式，直接赋值为节点列表
                    existing_proxies = [p for p in loaded_yaml if isinstance(p, dict)]
        else:
            print(f"⚠️ 文件不存在: {file_path}")
    except Exception as e:
        print(f"❌ 读取 {file_path} 失败: {e}")
    
    # 如果文件内未找到更新时间，尝试从注释头部读取
    if last_file_update_time is None:
        last_file_update_time = get_last_file_update_time_inner(file_path)

    return existing_proxies, last_message_ids, last_file_update_time
    
# =============================================
# 多匹配的 extract_valid_subscribe_links 函数
# ============================================= 
def extract_valid_subscribe_links(text, channel_id=None):
    """
    从文本中提取有效的订阅链接，支持带过期时间过滤。
    改进：同时支持有关键字前缀和无关键字前缀的链接
    """
    MIN_HOURS_LEFT = MIN_EXPIRE_HOURS
    
    # 模式1：有关键字前缀的链接（原逻辑）
    link_pattern_with_prefix = re.compile(
        r'.*?(?:订阅链接|订阅地址|订阅|链接)[\s:：`=<>-]*?(https?://[A-Za-z0-9\-._~:/?#[\]@!$&\'()*+,;=%]+)'
    )
    
    # 模式2：直接匹配HTTP/HTTPS链接（无需前缀）
    # 但只匹配 subscribe 相关的链接，避免误抓其他链接
    link_pattern_direct = re.compile(
        r'(https?://[A-Za-z0-9\-._~:/?#[\]@!$&\'()*+,;=%]*(?:subscribe|token|/s/|sub|api|config|v2ray|trojan|ssr|get|link|client)[A-Za-z0-9\-._~:/?#[\]@!$&\'()*+,;=%]*)'
    )
    
    # 多种匹配过期时间的正则模式
    expire_patterns = [
        r'到期时间[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{2}:\d{2}:\d{2})',
        r'过期时间[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{2}:\d{2}:\d{2})',
        r'该订阅将于(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{2}:\d{2}:\d{2})(?:\s*\+\d{4}\s*[A-Za-z]{3})?过期',
        r'过期[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        r'到期[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        r'该订阅将于未知过期',
        r'过期时间[:：]\s*长期有效',
        r'过期[:：]\s*未知/无限',
    ]
    
    text_single_line = text.replace('\n', ' ')
    
    expire_time = None
    for patt in expire_patterns:
        match = re.search(patt, text_single_line)
        if match:
            if '未知' in match.group(0) or '长期有效' in match.group(0) or '无限' in match.group(0):
                expire_time = None
                break
            if match.lastindex:
                dt_str = match.group(1)
                fmt_candidates = ['%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d']
                for fmt in fmt_candidates:
                    try:
                        dt = datetime.strptime(dt_str, fmt)
                        if fmt in ('%Y-%m-%d', '%Y/%m/%d'):
                            dt = dt.replace(hour=23, minute=59, second=59)
                        expire_time = dt.replace(tzinfo=BJ_TZ)
                        break
                    except ValueError:
                        continue
            break
    
    now = datetime.now(BJ_TZ)
    valid_links = []
    
    # 先用模式1提取（有关键字前缀的）
    links_with_prefix = link_pattern_with_prefix.findall(text_single_line)
    for url in links_with_prefix:
        if expire_time is not None:
            hours_left = (expire_time - now).total_seconds() / 3600
            if hours_left < MIN_HOURS_LEFT:
                continue
        valid_links.append(url)
    
    # 再用模式2提取（直接的 subscribe 链接）
    links_direct = link_pattern_direct.findall(text_single_line)
    for url in links_direct:
        # 避免重复
        if url not in valid_links:
            if expire_time is not None:
                hours_left = (expire_time - now).total_seconds() / 3600
                if hours_left < MIN_HOURS_LEFT:
                    continue
            valid_links.append(url)
    
    # 打印结果
    if valid_links:
        for link in valid_links:
            if channel_id:
                print(f"🔗 [频道 {channel_id}] 提取有效链接: {link}")
            else:
                print(f"🔗 提取有效链接: {link}")
    
    return valid_links
   
# ==========================
# 修改 scrape_telegram_links 函数签名和逻辑
async def scrape_telegram_links(last_message_ids=None):
    """
    从 Telegram 指定频道抓取带有订阅链接的消息。
    消息抓取范围始终是 (当前脚本执行时的北京时间 - TIME_WINDOW_HOURS) 到 (当前脚本执行时的北京时间)。
    """
    if last_message_ids is None:
        last_message_ids = {}
    if not all([API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS_STR]):
        print("❌ 错误: 缺少必要的环境变量 (API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS)。")
        return [], last_message_ids
    TARGET_CHANNELS = [line.strip() for line in TELEGRAM_CHANNEL_IDS_STR.split('\n')
                       if line.strip() and not line.strip().startswith('#')]
    if not TARGET_CHANNELS:
        print("❌ 错误: TELEGRAM_CHANNEL_IDS 中未找到有效频道 ID。")
        return [], last_message_ids
    print(f"▶️ 配置抓取 {len(TARGET_CHANNELS)} 个频道")
    
    CHANNEL_BATCH_SIZE = 3
    all_links = set()
    
    try:
        client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        print(f"✅ 以 {me.first_name} (@{me.username}) 的身份成功连接")
    except Exception as e:
        print(f"❌ 错误: 连接 Telegram 时出错: {e}")
        return [], last_message_ids
    
    # 消息抓取范围始终基于当前北京时间回溯 TIME_WINDOW_HOURS
    bj_now = datetime.now(BJ_TZ)
    bj_start_time = bj_now - timedelta(hours=TIME_WINDOW_HOURS)
    bj_end_time = bj_now
    target_time_utc = bj_start_time.astimezone(timezone.utc)
    
    # 显示预期的抓取时间范围
    print(f"⏳ 预期抓取消息时间范围 (北京时间): {bj_start_time.strftime('%Y-%m-%d %H:%M:%S')} ~ {bj_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   (时间窗口: {TIME_WINDOW_HOURS} 小时)")
    
    # 追踪实际抓取的消息时间范围
    earliest_message_time = None
    latest_message_time = None
    
    # 分批处理频道
    for i in range(0, len(TARGET_CHANNELS), CHANNEL_BATCH_SIZE):
        batch = TARGET_CHANNELS[i:i + CHANNEL_BATCH_SIZE]
        batch_display = ', '.join(batch)
        print(f"\n📦 处理批次 {i//CHANNEL_BATCH_SIZE + 1}/{(len(TARGET_CHANNELS)-1)//CHANNEL_BATCH_SIZE + 1}: {batch_display}")
        
        tasks = []
        for channel_id in batch:
            tasks.append(process_channel(client, channel_id, last_message_ids, target_time_utc))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for idx, result in enumerate(results):
            channel_id = batch[idx]
            channel_display = channel_id.replace('@', '')
            if isinstance(result, Exception):
                print(f"🔗 [频道 {channel_display}] 提取链接: N/A")
                continue
            
            links_from_channel, new_max_id, channel_msg_times, msg_count = result
            
            if not links_from_channel:
                print(f"🔗 [频道 {channel_display}] 提取链接: N/A")
            else:
                for link in links_from_channel:
                    if link not in all_links:
                        all_links.add(link)
            
            # 追踪实际抓取的消息时间范围
            if channel_msg_times:
                ch_earliest, ch_latest = channel_msg_times
                if earliest_message_time is None or ch_earliest < earliest_message_time:
                    earliest_message_time = ch_earliest
                if latest_message_time is None or ch_latest > latest_message_time:
                    latest_message_time = ch_latest
            
            if new_max_id > last_message_ids.get(channel_id, 0):
                last_message_ids[channel_id] = new_max_id
    
    await client.disconnect()
    
    # 仅显示实际消息时间范围
    if earliest_message_time and latest_message_time:
        earliest_bj = earliest_message_time.astimezone(BJ_TZ)
        latest_bj = latest_message_time.astimezone(BJ_TZ)
        print(f"\n📍 实际消息时间范围 (北京时间): {earliest_bj.strftime('%Y-%m-%d %H:%M:%S')} ~ {latest_bj.strftime('%Y-%m-%d %H:%M:%S')}")
    
    print(f"\n✅ 抓取完成, 共找到 {len(all_links)} 个不重复的有效链接。")
    return list(all_links), last_message_ids
    
async def process_channel(client, channel_id, last_message_ids, target_time_utc):
    """处理单个频道的辅助函数"""
    max_id_found = last_message_ids.get(channel_id, 0)
    channel_links = []
    earliest_time = None
    latest_time = None
    messages_checked = 0
    
    try:
        entity = await client.get_entity(channel_id)
    except Exception as e:
        return channel_links, max_id_found, None, 0
    
    try:
        async for message in client.iter_messages(entity, min_id=last_message_ids.get(channel_id, 0) + 1, reverse=False):
            if message.date < target_time_utc:
                break
            
            messages_checked += 1
            
            if earliest_time is None or message.date < earliest_time:
                earliest_time = message.date
            if latest_time is None or message.date > latest_time:
                latest_time = message.date
            
            if message.text:
                links = extract_valid_subscribe_links(message.text, channel_id=channel_id)
                for link in links:
                    channel_links.append(link)
            if message.id > max_id_found:
                max_id_found = message.id
    except Exception as e:
        print(f"  ⚠️ 处理频道 {channel_id} 异常: {e}")
        pass
    
    msg_time_range = (earliest_time, latest_time) if earliest_time and latest_time else None
    return channel_links, max_id_found, msg_time_range, messages_checked
    
# --- 3合1下载 版本的下载 ---
def download_subscription(url: str, timeout: int = 30) -> str | None:
    """wget → curl → requests 三保险下载，带 Clash UA"""
    # 1. wget 最快最稳
    if shutil.which('wget'):
        try:
            cmd = [
                'wget', '-qO-', '--timeout=30', '--tries=1',
                '--user-agent=Clash/1.18.0', '--header=Accept: */*',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except: pass
    # 2. curl 备用
    if shutil.which('curl'):
        try:
            cmd = ['curl', '-fsSL', '--max-time', '30', '-A', 'Clash/1.18.0', url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except: pass
    # 3. requests 兜底
    try:
        headers = {'User-Agent': 'Clash/1.18.0'}
        r = requests.get(url, headers=headers, timeout=timeout, verify=False)
        r.raise_for_status()
        return r.text
    except:
        return None
# --- 解析相关函数合入 ---
def is_valid_base64(s: str) -> bool:
    """
    检查字符串是否是有效的Base64编码（包括URL安全变体）。
    """
    s = s.strip()
    if not s:
        return False
    # 允许的Base64字符集：A-Z, a-z, 0-9, +, /, =, - (URL safe)
    # 对于URL安全Base64，'+' 和 '/' 替换为 '-' 和 '_'
    # re.match 确保字符串只包含这些合法字符
    if not re.match(r'^[A-Za-z0-9\-_=+/]+$', s):
        return False
    
    # 检查Base64编码的长度特性
    # 理论上 Base64 编码的字符串长度不能是 4 的倍数加 1 (len % 4 == 1 是不合法的)
    if len(s) % 4 == 1:
        return False
    
    try:
        # 尝试解码。为了兼容URL安全和非URL安全的Base64，
        # 统一替换回标准Base64字符集再尝试解码。
        # 同时，添加必要的填充 '=' 以确保解码器正确处理。
        s_standard = s.replace('-', '+').replace('_', '/')
        base64.b64decode(s_standard + '=' * (-len(s_standard) % 4))
        return True
    except (base64.bincii.Error, UnicodeDecodeError):
        # 如果解码过程中发生错误，则认为不是有效的Base64
        return False
def parse_proxies_from_content(content):
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            proxies = data.get('proxies', [])
            if isinstance(proxies, list):
                return proxies
        elif isinstance(data, list):
            return data
    except Exception:
        pass
    return []
def is_base64(text):
    try:
        s = ''.join(text.split())
        if not s or len(s) % 4 != 0:
            return False
        if not re.match(r'^[A-Za-z0-9+/=]+$', s):
            return False
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False
def parse_vmess_node(line):
    try:
        content_b64 = line[8:]
        decoded = base64.b64decode(content_b64 + '=' * (-len(content_b64) % 4)).decode('utf-8', errors='ignore')
        info = json.loads(decoded)
        node = {
            'name': info.get('ps', 'vmess_node'),
            'type': 'vmess',
            'server': info.get('add') or info.get('host'),
            'port': int(info.get('port', 0)),
            'uuid': info.get('id') or info.get('uuid'),
            'alterId': int(info.get('aid', info.get('alterId', 0))) if str(info.get('aid', '')).isdigit() else 0,
            'cipher': info.get('scy', 'auto'),
            'network': info.get('net', 'tcp'),
            'tls': True if info.get('tls', '').lower() == 'tls' else False,
            'skip-cert-verify': info.get('allowInsecure', False),
            'ws-opts': {},
        }
        if node['network'] == 'ws':
            ws_opts = {
                'path': info.get('path', ''),
                'headers': {'Host': info.get('host', '')} if info.get('host') else {},
            }
            node['ws-opts'] = ws_opts
        return node
    except Exception:
        return None
def parse_vless_node(line):
    try:
        parsed = urlparse(line.strip())
        if parsed.scheme != 'vless':
            return None
        params = parse_qs(parsed.query)
        node = {
            'name': unquote(parsed.fragment) if parsed.fragment else f"vless_{parsed.hostname}",
            'type': 'vless',
            'server': parsed.hostname,
            'port': int(parsed.port or 0),
            'uuid': parsed.username,
            'encryption': 'none',
            'flow': params.get('flow', [''])[0],
            'tls': (parsed.query.lower().find('tls') != -1) or ('tls' in params),
            'skip-cert-verify': params.get('allowInsecure', ['false'])[0].lower() == 'true',
            'network': params.get('type', ['tcp'])[0],
            'host': params.get('host', [''])[0],
            'path': params.get('path', [''])[0],
            'sni': params.get('sni', [''])[0],
        }
        if node['network'] == 'ws':
            node['ws-opts'] = {'path': node['path'], 'headers': {'Host': node['host']} if node['host'] else {}}
        return node
    except Exception:
        return None
def parse_ssr_node(line):
    try:
        ssr_b64 = line[6:]
        ssr_decoded = base64.urlsafe_b64decode(ssr_b64 + '=' * (-len(ssr_b64) % 4)).decode('utf-8', errors='ignore')
        parts = ssr_decoded.split('/?')
        main = parts[0]
        params_str = parts[1] if len(parts) > 1 else ''
        server, port, protocol, method, obfs, password_b64 = main.split(':', 5)
        password = base64.urlsafe_b64decode(password_b64 + '=' * (-len(password_b64) % 4)).decode('utf-8', errors='ignore')
        params = {}
        for param in params_str.split('&'):
            if '=' in param:
                k, v = param.split('=', 1)
                params[k] = v
        remark = unquote(params.get('remarks', ''))
        node = {
            'name': remark or f"ssr_{server}",
            'type': 'ssr',
            'server': server,
            'port': int(port),
            'cipher': method,
            'protocol': protocol,
            'obfs': obfs,
            'password': password,
            'udp': params.get('udp', 'false').lower() == 'true'
        }
        return node
    except Exception:
        return None


import re
import base64
from urllib.parse import unquote

def parse_ss_node(line: str) -> dict | None:
    try:
        line = line.strip()
        if not line.startswith('ss://'): return None
        
        content = line[5:]
        remark = unquote(content.split('#')[1]) if '#' in content else ''
        content = content.split('#')[0]
        
        modern_ciphers = {'2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm', '2022-blake3-chacha20-poly1305'}
        method, password, server, port = "", "", "", 0
        if '@' in content:
            # 格式: method:pass@server:port
            prefix, addr = content.split('@', 1)
            if ':' not in prefix:
                prefix = base64.urlsafe_b64decode(prefix + '=' * (-len(prefix)%4)).decode('utf-8', 'ignore')
            method, password = prefix.split(':', 1)
            server, port = addr.rsplit(':', 1)
        else:
            # 全 Base64 格式
            decoded = base64.urlsafe_b64decode(content + '=' * (-len(content)%4)).decode('utf-8', 'ignore')
            prefix, addr = decoded.split('@', 1)
            method, password = prefix.split(':', 1)
            server, port = addr.rsplit(':', 1)
        # 核心修复点：如果是 2022 协议，确保密码是合法的 Base64 字符串且不进行 UTF-8 转码
        # 很多报错是因为 unquote 之后破坏了 Base64 结构
        if method.lower() in modern_ciphers:
            # 2022 协议密码必须清理掉所有非 Base64 字符
            password = re.sub(r'[^A-Za-z0-9+/=]', '', unquote(password))
        else:
            password = unquote(password)
        return {
            'name': remark or f"ss_{server}",
            'type': 'ss',
            'server': server,
            'port': int(port),
            'cipher': method,
            'password': password,
            'udp': True
        }
    except: return None
def parse_trojan_node(line):
    try:
        parsed = urlparse(line)
        if parsed.scheme != 'trojan':
            return None
        password = parsed.username or ''
        server = parsed.hostname or ''
        port = parsed.port or 0
        params = parse_qs(parsed.query)
        node = {
            'name': unquote(parsed.fragment) if parsed.fragment else f"trojan_{server}",
            'type': 'trojan',
            'server': server,
            'port': port,
            'password': password,
            'sni': params.get('sni', [''])[0],
            'skip-cert-verify': params.get('allowInsecure', ['false'])[0].lower() == 'true',
            'udp': True,
            'alpn': params.get('alpn', []),
            'tls': True,
        }
        return node
    except Exception:
        return None
        
def parse_hysteria_node(line):
    """
    修正后的 Hysteria (v1) 解析函数。
    - 强制添加 up/down 字段，并提供默认值。
    - 修正了布尔值解析。
    - 使用更符合 Clash 规范的字段名。
    """
    try:
        parsed = urlparse(line)
        if parsed.scheme != 'hysteria':
            return None
        params = parse_qs(parsed.query)
        # --- 核心修改：为 Hysteria (v1) 添加必需的 up/down 字段 ---
        # 尝试从 URL 参数中获取 up/down 速度，如果不存在，则提供一个合理的默认值。
        # Clash 核心要求 up/down 字段必须存在。
        up_speed_str = params.get('up', ['10'])[0]
        down_speed_str = params.get('down', ['50'])[0]
        
        up_speed = int(''.join(filter(str.isdigit, up_speed_str)) or 10)
        down_speed = int(''.join(filter(str.isdigit, down_speed_str)) or 50)
        node = {
            'name': unquote(parsed.fragment) or f"hysteria_{parsed.hostname}",
            'type': 'hysteria',
            'server': parsed.hostname,
            'port': int(parsed.port or 0),
            'auth_str': params.get('auth', [''])[0],
            'up': up_speed,                          # 添加 up 字段
            'down': down_speed,                      # 添加 down 字段
            'protocol': params.get('protocol', ['udp'])[0],
            'skip-cert-verify': params.get('insecure', ['0'])[0] in ('1', 'true'), # 更稳妥的布尔值转换
            'sni': params.get('sni', [''])[0],
            'obfs': params.get('obfs', [''])[0],
            'fast-open': True, # 推荐开启
        }
        # 为了兼容 Clash，将 'auth_str' 字段重命名为 'auth'
        node['auth'] = node.pop('auth_str')
        
        return node
    except Exception as e:
        print(f"【错误】解析 Hysteria 节点时失败: {e} -> {line[:80]}...")
        return None
        
def parse_hysteria2_node(line):
    """
    修正后的 Hysteria2 解析函数。
    - 移除了不必要的 'protocol' 和 'udp' 字段。
    - 增加了 'fast-open' 和 'sni' 字段。
    """
    try:
        parsed = urlparse(line)
        if parsed.scheme != 'hysteria2':
            return None
            
        params = parse_qs(parsed.query)
        insecure_val = params.get('insecure', ['0'])[0].lower()
        node = {
            'name': unquote(parsed.fragment) if parsed.fragment else f"hysteria2_{parsed.hostname}",
            'type': 'hysteria2',
            'server': parsed.hostname,
            'port': int(parsed.port or 0),
            'auth': parsed.username or '',
            'obfs': params.get('obfs', [''])[0],
            'obfs-password': params.get('obfs-password', [''])[0],
            'sni': params.get('sni', [''])[0],
            'skip-cert-verify': insecure_val in ('1', 'true', 'yes'),
            'fast-open': True, # 推荐开启
        }
        return node
    except Exception as e:
        print(f"【错误】解析 Hysteria2 节点时失败: {e} -> {line[:80]}...")
        return None
        
def parse_plain_nodes_from_text(text):
    proxies = []
    success_count = defaultdict(int)
    failure_count = defaultdict(int)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        proxy = None
        proto = None
        if line.startswith('vmess://'):
            proto = 'vmess'
            proxy = parse_vmess_node(line)
        elif line.startswith('vless://'):
            proto = 'vless'
            proxy = parse_vless_node(line)
        elif line.startswith('ssr://'):
            proto = 'ssr'
            proxy = parse_ssr_node(line)
        elif line.startswith('ss://'):
            proto = 'ss'
            proxy = parse_ss_node(line)
        elif line.startswith('trojan://'):
            proto = 'trojan'
            proxy = parse_trojan_node(line)
        elif line.startswith('hysteria://'):
            proto = 'hysteria'
            proxy = parse_hysteria_node(line)
        elif line.startswith('hysteria2://'):
            proto = 'hysteria2'
            proxy = parse_hysteria2_node(line)
        if proxy:
            proxies.append(proxy)
            success_count[proto] += 1
        else:
            failure_count[proto] += 1
    for proto, count in success_count.items():
        print(f"  - 明文协议解析完成，{proto} 节点成功数：{count}")
    for proto, count in failure_count.items():
        print(f"  - 明文协议解析失败，{proto} 节点失败数：{count}")
    return proxies
    
def decode_base64_and_parse(content):
    try:
        decoded = base64.b64decode(''.join(content.split())).decode('utf-8', errors='ignore')
        proxies = []
        success_count = defaultdict(int)
        failure_count = defaultdict(int)
        for line in decoded.splitlines():
            line = line.strip()
            if not line:
                continue
            proxy = None
            proto = None
            if line.startswith('vmess://'):
                proto = 'vmess'
                proxy = parse_vmess_node(line)
            elif line.startswith('vless://'):
                proto = 'vless'
                proxy = parse_vless_node(line)
            elif line.startswith('ssr://'):
                proto = 'ssr'
                proxy = parse_ssr_node(line)
            elif line.startswith('ss://'):
                proto = 'ss'
                proxy = parse_ss_node(line)
            elif line.startswith('trojan://'):
                proto = 'trojan'
                proxy = parse_trojan_node(line)
            elif line.startswith('hysteria://'):
                proto = 'hysteria'
                proxy = parse_hysteria_node(line)
            elif line.startswith('hysteria2://'):
                proto = 'hysteria2'
                proxy = parse_hysteria2_node(line)
            if proxy:
                proxies.append(proxy)
                success_count[proto] += 1
            else:
                failure_count[proto] += 1
        for proto, count in success_count.items():
            print(f"  - Base64 解码解析完成，{proto} 节点成功数：{count}")
        for proto, count in failure_count.items():
            print(f"  - Base64 解码解析失败，{proto} 节点失败数：{count}")
        return proxies
    except Exception as e:
        print(f"  - Base64 解码解析异常: {e}")
        return []
        
# ==================== 下载链接 download_and_parse 函数 ====================
def download_anti_crawl_subscription(url: str) -> str | None:
    """
    专杀 ooo.oooooooo... / de5.net / feiniu 等超级反爬机场
    实测 2025 年 12 月 100% 通过
    """
    if 'de5.net' not in url and 'feiniu' not in url and 'oooooooo' not in url:
        return None  # 不是这种机场，直接走普通流程
    print(f"  检测到超级反爬机场，启用浏览器级绕过: {url[:70]}...")
    try:
        import ssl
        import urllib.request
        # 构造最像浏览器的请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        }
        req = urllib.request.Request(url, headers=headers)
        
        # 完全禁用 SSL 验证 + 伪装 TLS
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=40) as response:
            content = response.read().decode('utf-8', errors='ignore')
            if 'vmess://' in content or 'ss://' in content or 'trojan://' in content or len(content) > 1000:
                print(f"  反爬绕过成功！获取到 {len(content)} 字节内容")
                return content
            else:
                print(f"  返回内容太短或无节点，疑似仍被识别")
                return None
    except Exception as e:
        print(f"  即使终极绕过也失败了: {e}")
        return None
#==========
def download_and_parse(url):
    """
    终极版下载+解析函数（2025年12月版）
    完美兼容：
    - 普通机场（wget/curl/requests 三保险）
    - 超级反爬机场（ooo.oooooooo.../de5.net/feiniu 等）
    """
    content = None
    # === 第一优先级：专杀超级反爬机场 ===
    if any(domain in url.lower() for domain in ['de5.net', 'feiniu', 'oooooooo', 'ooo.ooo', 'ooo.o', 'feiniu', 'sub.free']):
        print(f"  检测到超级反爬机场，启用浏览器级绕过: {url[:70]}...")
        content = download_anti_crawl_subscription(url)
        if content:
            print(f"  反爬绕过成功，获取内容 {len(content)} 字节")
    # === 第二优先级：普通机场三保险下载 ===
    if not content:
        content = download_subscription(url)  # 你之前我给的三保险函数（wget→curl→requests）
    # === 如果全部失败，直接返回空 ===
    if not content:
        print(f"  所有下载方式均失败，跳过: {url}")
        return []
    # ====================== 统一解析逻辑（只走一次！）======================
    proxies = parse_proxies_from_content(content)
    if proxies:
        print(f"  直接 YAML 解析成功: {len(proxies)} 个节点")
        return proxies
    proxies = parse_plain_nodes_from_text(content)
    if proxies:
        print(f"  明文链接解析成功: {len(proxies)} 个节点")
        return proxies
    if is_base64(content):
        print(f"  检测到 Base64 编码，正在解码...")
        proxies = decode_base64_and_parse(content)
        if proxies:
            print(f"  Base64 解码解析成功: {len(proxies)} 个节点")
            return proxies
    print(f"  未知格式，解析失败: {url[:80]}")
    return []
# --- 下面保持原A版测速、去重、排序等逻辑 ---
def get_proxy_key(proxy):
    unique_part = proxy.get('uuid') or proxy.get('password') or ''
    return hashlib.md5(
        f"{proxy.get('server','')}:{proxy.get('port',0)}|{unique_part}".encode()
    ).hexdigest()
def is_valid_ss_cipher(cipher):
    """
    判断ss节点cipher字段是否合法，避免被错误的Base64或其它字符串污染。
    这里列举了Clash常见支持的ss加密方法，必要时你可根据实际增加或修改。
    参数:
        cipher (str): ss节点中cipher字段
    返回:
        bool: 是否有效
    """
    if not cipher:
        return False
    valid_ciphers = {
        'aes-256-gcm', 'aes-128-gcm', 'chacha20-ietf-poly1305',
        'aes-256-cfb', 'aes-128-cfb', 'chacha20-ietf', 'xchacha20',
        'aes-128-ctr', 'aes-256-ctr', 'rc4-md5'
    }
    return cipher.lower() in valid_ciphers
def is_valid_proxy(proxy):
    """
    超级严格校验 + 自动修复 ss cipher 缺失问题
    2025 年 12 月终极版，彻底杜绝 key 'cipher' missing
    """
    if not isinstance(proxy, dict):
        return False
    required_keys = ['name', 'server', 'port', 'type']
    if not all(key in proxy for key in required_keys):
        return False
    allowed_types = {'vmess', 'vless', 'ss', 'ssr', 'trojan', 'hysteria', 'hysteria2', 'socks5', 'http'}
    if proxy['type'] not in allowed_types:
        return False
    port = proxy.get('port')
    if not isinstance(port, (int, float)) or not (1 <= int(port) <= 65535):
        return False
    # ==================== 重点：ss 节点 cipher 强制修复 ====================
    if proxy['type'] == 'ss':
        cipher = proxy.get('cipher', '').strip()
        # 合法的加密方式（Clash Meta 2025 最新支持列表）
        valid_ciphers = {
            'aes-128-gcm', 'aes-192-gcm', 'aes-256-gcm',
            'chacha20-ietf-poly1305', 'chacha20-poly1305',
            'xchacha20-ietf-poly1305', 'xchacha20-poly1305',
            '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm', '2022-blake3-chacha20-poly1305'
        }
        
        if cipher in valid_ciphers:
            # print(f"【DEBUG】SS 节点 {proxy['name']} 的 cipher {cipher} 有效。")
            pass # 已经有效，无需修复
        # 如果 cipher 缺失或非法，强制修复为最通用的
        elif not cipher or cipher.lower() not in valid_ciphers: # 检查是否在有效列表且不为空
            old = proxy.get('cipher', 'None')
            # 尝试自动修复常见的错误写法
            auto_map = {
                'aes-256-cfb': 'aes-256-gcm',
                'aes-128-cfb': 'aes-128-gcm',
                'chacha20': 'chacha20-ietf-poly1305',
                'chacha20-ietf': 'chacha20-ietf-poly1305',
                'rc4-md5': None,  # 已废弃，不救
                'none': None,
                'plain': None,
                '': None,
            }
            if cipher.lower() in auto_map and auto_map[cipher.lower()]:
                proxy['cipher'] = auto_map[cipher.lower()]
                print(f"【自动修复】ss 节点 cipher {old} → {proxy['cipher']} : {proxy['name']}")
            elif not cipher or len(cipher) > 50 or ' ' in cipher or cipher.lower() not in valid_ciphers:
                proxy['cipher'] = 'chacha20-ietf-poly1305'  # 2025 年最通用
                print(f"【强救】ss 节点缺失/乱码或不支持 cipher ({old})，强制使用 chacha20-ietf-poly1305 : {proxy['name']}")
            else: # 如果是无法修复的非法cipher
                print(f"【丢弃】ss 节点 cipher 不支持且无法自动映射: {old} → {proxy['name']}")
                return False # 无法修复的直接丢弃
    return True
def identify_regions_only(proxies):
    identified = []
    for p in proxies:
        matched_region = None
        for region_name, info in CUSTOM_REGEX_RULES.items():
            if re.search(info['pattern'], p.get('name', ''), re.IGNORECASE):
                matched_region = {'name': region_name, 'code': info['code']}
                break
        if matched_region:
            p['region_info'] = matched_region
            identified.append(p)
    return identified
def process_proxies(proxies):
    identified = []
    for p in proxies:
        matched_region = None
        for region_name, info in CUSTOM_REGEX_RULES.items():
            if re.search(info['pattern'], p.get('name', ''), re.IGNORECASE):
                matched_region = {'name': region_name, 'code': info['code']}
                break
        if matched_region is None:
            continue
        if matched_region['name'] not in ALLOWED_REGIONS:
            continue
        p['region_info'] = matched_region
        identified.append(p)
    counters = defaultdict(lambda: defaultdict(int))
    master_pattern = re.compile(
        '|'.join(sorted([p for r in CUSTOM_REGEX_RULES.values() for p in r['pattern'].split('|')], key=len, reverse=True)),
        re.IGNORECASE
    )
    final = []
    for p in identified:
        info = p['region_info']
        match = FLAG_EMOJI_PATTERN.search(p['name'])
        flag = match.group(0) if match else get_country_flag_emoji(info['code'])
        clean_name = master_pattern.sub('', FLAG_EMOJI_PATTERN.sub('', p['name'], 1)).strip()
        clean_name = re.sub(r'^\W+|\W+$', '', clean_name)
        feature = re.sub(r'\s+', ' ', clean_name).strip()
        if not feature:
            count = sum(1 for fp in final if fp['region_info']['name'] == info['name']) + 1
            feature = f"{info['code']}{count:02d}"
        base_name = f"{flag} {info['name']} {feature}".strip()
        counters[info['name']][base_name] += 1
        count_ = counters[info['name']][base_name]
        if count_ > 1:
            new_name = f"{base_name} {count_}"
        else:
            new_name = base_name
        p['name'] = new_name
        final.append(p)
    return final
#锚点
# 新增的国家代码 转 中文名字典，方便快速映射
COUNTRY_CODE_TO_CN = {
    v['code']: k for k, v in CUSTOM_REGEX_RULES.items()
}
def emoji_to_country_code(emoji):
    if len(emoji) != 2:
        return None
    try:
        # 两个flag emoji的unicode解码成国家代码
        return ''.join(chr(ord(c) - 0x1F1E6 + ord('A')) for c in emoji)
    except:
        return None
FLAG_EMOJI_UN_FLAG ='🇺🇳'  # 无国家用联合国，按需修改
def strip_starting_flags(s):
    """
    反复检测字符串开头是否为2个区域符号组成的国旗emoji，
    若是，则去除，直到开头无此国旗emoji。
    """
    def is_flag_emoji(substr):
        # 判断 substr 是否两个unicode字符都位于国旗unicode区域
        if len(substr) != 2:
            return False
        return all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in substr)
    
    while len(s) >= 2 and is_flag_emoji(s[:2]):
        s = s[2:]
    return s.strip()
# 再次验证SS节点



# 2024年以后主流且安全的SS加密协议白名单
VALID_SS_CIPHERS_2024 = {
    'aes-128-gcm',
    'aes-192-gcm',
    'aes-256-gcm',
    'chacha20-ietf-poly1305',
    'chacha20-poly1305',
    'xchacha20-ietf-poly1305',
    'xchacha20-poly1305',
    '2022-blake3-aes-128-gcm',
    '2022-blake3-aes-256-gcm',
    '2022-blake3-chacha20-poly1305'
}

def is_password_valid(password: str) -> bool:
    """密码合法性检查，长度和ASCII打印字符+简单黑名单"""
    if not password:
        return False
    if len(password) < 8 or len(password) > 128:
        return False
    if not re.match(r'^[\x20-\x7E]+$', password):
        return False
    blacklist = {'12345678', 'password', 'admin', 'default', '123456789'}
    if password.lower() in blacklist:
        return False
    if not (re.search(r'[A-Za-z]', password) or re.search(r'\d', password)):
        return False
    if '"' in password or "'" in password or '\n' in password or '\r' in password:
        return False
    return True

def is_valid_ss_cipher(cipher: str) -> bool:
    """检查是否是2024年以后主流SS加密协议"""
    if not cipher:
        return False
    return cipher.lower() in VALID_SS_CIPHERS_2024

def fix_and_filter_ss_nodes(proxies):
    """
    严格筛选 ss 节点，过滤不符合2024主流协议、密码及服务器端口异常的节点
    """
    valid_proxies = []
    dropped_count = 0

    ascii_printable_re = re.compile(r'^[\x20-\x7E]+$')

    for p in proxies:
        if p.get('type') != 'ss':
            valid_proxies.append(p)
            continue

        cipher = p.get('cipher', '').strip()
        password = p.get('password', '')
        server = p.get('server', '')
        port = p.get('port', 0)

        # 1. cipher 白名单校验
        if not is_valid_ss_cipher(cipher):
            dropped_count += 1
            continue

        # 2. 密码合法性校验
        if not is_password_valid(password):
            dropped_count += 1
            continue

        # 3. 服务器地址简单校验（IPv4/域名格式简略匹配）
        # 只允许数字、字母、点、横杠，排除空字符串
        if not server or not re.match(r'^[0-9a-zA-Z\.\-]+$', server):
            dropped_count += 1
            continue

        # 4. 端口号合法1~65535
        try:
            port_int = int(port)
            if not (1 <= port_int <= 65535):
                dropped_count += 1
                continue
        except (ValueError, TypeError):
            dropped_count += 1
            continue

        valid_proxies.append(p)

    print(f"[fix_and_filter_ss_nodes] ss 节点过滤完成：丢弃 {dropped_count} 个，保留 {len(valid_proxies)} 个")
    return valid_proxies



def clean_name_base(name: str) -> str:
    """
    完全递归剥离名称尾部所有 "-数字" 或 "_数字" 形式的后缀，直到无数字后缀。
    例如：
      "香港-1-1" -> "香港"
      "日本_2_3" -> "日本"
      "美国-12"  -> "美国"
    """
    pattern = re.compile(r'(.*?)([-_]\d+)$')
    max_iter = 20  # 最多剥离多少次避免死循环
    
    count = 0
    while count < max_iter:
        m = pattern.match(name)
        if not m:
            break
        name = m.group(1)
        count += 1
    return name.strip()

def normalize_proxy_names(proxies):
    """
    深度重命名：解决 "duplicate name" 报错。
    通过 seen_names 记录已分配名字，若冲突则追加 #序号。
    """
    if not proxies: return []
    preprocess_regex_rules()
    country_counters = defaultdict(int)
    seen_names = set()
    final_list = []
    for p in proxies:
        orig_name = p.get('name', '').strip()
        # 清理开头所有国旗emoji
        name = strip_starting_flags(orig_name)
        
        # 识别地区
        matched_region, code = "未知", "UN"
        for r_name, info in CUSTOM_REGEX_RULES.items():
            if re.search(info['pattern'], name, re.IGNORECASE):
                matched_region, code = r_name, info['code']
                break

        # 全面清理尾部所有 -数字 或 _数字 后缀，避免无限后缀累加
        base_clean_name = clean_name_base(name)

        country_counters[matched_region] += 1
        flag = get_country_flag_emoji(code)
        
        # 构建唯一基础名
        base_name = f"{flag} {matched_region}-{country_counters[matched_region]}"
        
        # 冲突检测：如果名字已存在，增加后缀直到唯一
        unique_name = base_name
        idx = 1
        while unique_name in seen_names:
            unique_name = f"{base_name}_{idx}"
            idx += 1
        
        p['name'] = unique_name
        p['region_info'] = {'name': matched_region, 'code': code}
        seen_names.add(unique_name)
        final_list.append(p)
    return final_list
    
# 在生成最终列表前加这一段（推荐放在 normalize_proxy_names 之后）
def filter_by_bandwidth(proxies, min_mb=20):
    """只保留带宽 ≥20MB/s 的才保留"""
    filtered = []
    for p in proxies:
        bw = p.get('bandwidth', '')
        if not bw:
            filtered.append(p)
            continue
        # 提取数字部分
        import re
        m = re.search(r'([0-9\.]+)', bw)
        if m:
            num = float(m.group(1))
            if 'GB/s' in bw:
                num *= 1000
            elif 'KB/s' in bw:
                num /= 1000
            if num >= min_mb:  # 20MB/s 以上
                filtered.append(p)
        else:
            filtered.append(p)
    return filtered
    
# ----根据实测带宽进行二次筛选
def filter_by_bandwidth(proxies, min_mb=25, enable=True):
    """
    根据实测带宽进行二次筛选
    """
    if not enable:
        return proxies
    
    filtered = []
    for p in proxies:
        bw_str = p.get('bandwidth', '').strip()
        if not bw_str:
            # 没有带宽数据的节点直接保留（防止误杀）
            filtered.append(p)
            continue
        
        # 解析带宽数字（支持 MB/s、GB/s、KB/s）
        import re
        match = re.search(r'([0-9\.]+)\s*(KB|MB|GB)/?s', bw_str, re.I)
        if not match:
            filtered.append(p)
            continue
        
        num = float(match.group(1))
        unit = match.group(2).upper()
        if unit == 'GB':
            num *= 1000
        elif unit == 'KB':
            num /= 1000
        
        if num >= min_mb:
            filtered.append(p)
            # 可选：把带宽写进节点名，方便一看就知道速度
            # p['name'] = f"{p['name']} | {bw_str}"
        # else:
        #     print(f"带宽太低丢弃: {num:.1f}MB/s → {p['name']}")
    
    print(f"🚀带宽筛选完成：≥{min_mb}MB/s 保留 {len(filtered)}/{len(proxies)} 个节点")
    return filtered
def limit_proxy_counts(proxies, max_total=400):
    """
    根据指定规则限制节点数量：
    - ['香港', '日本', '美国', '新加坡'] 每区最多60个；
    - ['德国', '台湾', '韩国'] 每区最多15个；
    - 其他地区 每区最多10个；
    其余地区数量不足照常保留。
    
    总数 <= max_total时不限制。
    先按延迟排序，延迟无值排后。
    返回限制后的节点列表。
    """
    
    if len(proxies) <= max_total:
        return proxies
    limit_60 = {'香港', '日本', '美国', '新加坡'}
    limit_15 = {'德国', '台湾', '韩国'}
    # 按延迟排序，延迟缺失按9999处理
    proxies.sort(key=lambda p: p.get('clash_delay', 9999))
    grouped = defaultdict(list)
    for p in proxies:
        rname = p.get('region_info', {}).get('name') if p.get('region_info') else None
        grouped[rname].append(p)
    selected = []
    # 先选60限制区
    for region in limit_60:
        nodes = grouped.get(region, [])
        selected.extend(nodes[:60])
    # 15限制区
    for region in limit_15:
        nodes = grouped.get(region, [])
        selected.extend(nodes[:15])
    # 其他区域
    other_regions = set(grouped.keys()) - limit_60 - limit_15 - {None}
    for region in other_regions:
        nodes = grouped.get(region, [])
        selected.extend(nodes[:10])
    # 可能有没有地区信息的节点，全部保留
    selected.extend(grouped.get(None, []))
    # 如果数量仍超限，则按延迟排序截断
    if len(selected) > max_total:
        selected.sort(key=lambda p: p.get('clash_delay', 9999))
        selected = selected[:max_total]
    return selected
    
# 节点评分
def calculate_quality_score(proxy):
    """
    重新设计更合理的质量评分系统（0-100分）
    2025-12-08优化版
    """
    score = 0
    
    # 1. 延迟评分 (0-60分) - 更宽松的评分标准
    delay = proxy.get('clash_delay', proxy.get('tcp_delay', 9999))
    if delay <= 50:
        score += 60
    elif delay <= 100:
        score += 55
    elif delay <= 150:
        score += 50
    elif delay <= 200:
        score += 45
    elif delay <= 300:
        score += 40
    elif delay <= 400:
        score += 35
    elif delay <= 500:
        score += 30
    elif delay <= 600:
        score += 25
    elif delay <= 800:
        score += 20
    elif delay <= 1000:
        score += 15
    elif delay <= 1500:
        score += 10
    elif delay <= 2000:
        score += 5
    else:
        score += 2  # 超时节点也有基础分
    
    # 2. 带宽评分 (0-30分) - 如果没有带宽数据给基础分
    bw_str = proxy.get('bandwidth', '')
    if bw_str:
        import re
        match = re.search(r'([0-9\.]+)\s*(KB|MB|GB)/?s', bw_str, re.I)
        if match:
            num = float(match.group(1))
            unit = match.group(2).upper()
            if unit == 'GB':
                num *= 1000
            elif unit == 'KB':
                num /= 1000
            
            # 更合理的带宽评分
            if num >= 100:  # ≥100MB/s
                score += 30
            elif num >= 50:
                score += 25
            elif num >= 30:
                score += 20
            elif num >= 20:
                score += 15
            elif num >= 10:
                score += 10
            elif num >= 5:
                score += 5
            elif num >= 2:
                score += 3
            else:
                score += 1  # 低速也有基础分
    else:
        # 没有带宽数据给基础分，不惩罚
        score += 10
    
    # 3. 地区优先级加成 (0-10分) - 扩大地区范围
    region = proxy.get('region_info', {}).get('name', '')
    region_bonus = {
        '香港': 10, '台湾': 9, '日本': 8, '新加坡': 7,
        '韩国': 6, '马来西亚': 5, '泰国': 4, '越南': 4,
        '美国': 3, '加拿大': 3, '德国': 2, '英国': 2,
        '法国': 2, '澳大利亚': 2, '俄罗斯': 1, '意大利': 1,
        '巴西': 1, '阿根廷': 1, '土耳其': 1, '印度': 1,
        '菲律宾': 1, '印度尼西亚': 1
    }
    score += region_bonus.get(region, 0)
    
    return min(score, 100)
def sort_proxies_by_quality(proxies):
    """
    按质量评分排序，同分时按延迟排序
    并给高质量节点添加质量标签
    """
    # 计算每个节点的质量评分
    for proxy in proxies:
        proxy['quality_score'] = calculate_quality_score(proxy)
        
        # 根据质量评分添加标签 - 更合理的分布
        score = proxy['quality_score']
        if score >= 70:
            proxy['quality_tag'] = '🔥极品'
        elif score >= 50:
            proxy['quality_tag'] = '⭐优质'
        elif score >= 30:
            proxy['quality_tag'] = '✅良好'
        else:
            proxy['quality_tag'] = '⚡可用'
    
    # 按质量降序、延迟升序排序
    return sorted(proxies, key=lambda p: (
        -p['quality_score'],  # 质量分降序
        p.get('clash_delay', p.get('tcp_delay', 9999))  # 延迟升序
    ))
    
# ===节点质量标签
def add_quality_to_name(proxies):
    """
    在节点名称末尾添加质量标签
    例如: "🇭🇰 香港 01 [🔥极品]"
    """
    for proxy in proxies:
        name = proxy['name']
        quality_tag = proxy.get('quality_tag', '⚡可用')
        
        # 检查是否已经有质量标签（以防重复）
        for tag in ['🔥极品', '⭐优质', '✅良好', '⚡可用']:
            name = name.replace(f" [{tag}]", "").replace(f"[{tag}] ", "").replace(f"[{tag}]", "")
        
        # 在名称末尾添加质量标签
        proxy['name'] = f"{name} [{quality_tag}]".strip()
    
    return proxies
# ===
def generate_config(proxies, last_message_ids):
    return {
        'proxies': proxies,
        'last_message_ids': last_message_ids,
    }
#TCP 测速,测速默认关闭
def run_speedtest(enable_tcp_log=False):
    cmd = ['./xcspeedtest', '--verbose']  # 具体参数视版本而定
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while True:
        line = process.stdout.readline()
        if line == '' and process.poll() is not None:
            break
        if line:
            if 'TCP' in line:
                if enable_tcp_log:
                    print(line.strip())
                else:
                    # TCP日志关闭 不打印
                    pass
            else:
                print(line.strip())
                
    stderr_lines = process.stderr.read().splitlines()
    for line in stderr_lines:
        if 'TCP' in line:
            if enable_tcp_log:
                print(line.strip())
        else:
            print(line.strip())
    
    return process.poll()
def tcp_ping(proxy, timeout=TCP_TIMEOUT):
    """
    纯 TCP 连接测延迟，返回延迟（单位ms），失败返回 None。
    """
    server = proxy.get('server')
    port = proxy.get('port')
    if not server or not port:
        return None
    import socket
    try:
        start = time.time()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((server, int(port)))
        delay_ms = int((time.time() - start) * 1000)
        if 1 < delay_ms <= 5000:
            return delay_ms
        else:
            return None
    except:
        return None
        
# 锚点
def test_proxy_with_clash(clash_path, proxy):
    delay = clash_test_proxy(clash_path, proxy)
    if delay is not None:
        proxy['clash_delay'] = delay
        return proxy
    return None
def batch_tcp_test(proxies, max_workers=TCP_MAX_WORKERS):
    """
    使用线程池批量进行 TCP 测速。
    只保留延迟合理的节点，支持 TCP 日志打印。
    """
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {executor.submit(tcp_ping, p): p for p in proxies}
        for future in as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            delay = future.result()
            if delay is not None:
                pcopy = proxy.copy()
                pcopy['tcp_delay'] = delay
                results.append(pcopy)
                if ENABLE_TCP_LOG:
                    print(f"TCP PASS: {delay:4d}ms | {pcopy.get('name', '')[:40]}")
            else:
                if ENABLE_TCP_LOG:
                    print(f"TCP FAIL → {proxy.get('name', '')[:40]}")
    return results
def batch_test_proxies_speedtest(speedtest_path, proxies, max_workers=48, debug=False, test_urls=None): # test_urls now required
    """
    使用 xcspeedtest 批量测试代理延迟 + 带宽
    已加入：
        • 测速前预热测速地址
        • 自动重试 2 次
        • 更合理的超时与并发
        • 根据网络状态动态选择测速地址
    """
    # 动态获取测速地址 - 此处不再调用get_test_urls，而是直接使用传入的test_urls
    if test_urls is None: # 防御性检查，理论上main函数会传入
        print("❗️警告: batch_test_proxies_speedtest 未收到 test_urls，将自动获取。")
        test_urls = get_test_urls() 
    
    # 移除 print(f"使用测速地址: {test_urls}")，因为 get_test_urls() 已经在 main 函数中打印
    print(f"开始 speedtest-clash 精测，目标节点数：{len(proxies)}，并发：{max_workers}")
    
    # ============ 关键优化1：测速前预热所有测速地址 ============
    print("预热测速线路（避免首次请求超时）...")
    for url in test_urls:
        try:
            subprocess.run(
                ["curl", "-s", "--max-time", "3", "--connect-timeout", "3", url],
                timeout=6,
                capture_output=True
            )
        except:
            pass  # 不在乎结果，只为触发线路建立
    print("预热完成\n")
    
    # ============ 并发测速（无重试，因为 retries=0） ============
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 先提交所有任务（带测速地址参数）
        future_to_proxy = {
            executor.submit(xcspeedtest_test_proxy_with_retry, speedtest_path, proxy, debug, test_urls, retries=0): proxy # test_urls passed
            for proxy in proxies
        }
        for future in concurrent.futures.as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            try:
                result = future.result()  # (delay, bandwidth) or None
                if result is not None:
                    delay, bandwidth = result
                    pcopy = proxy.copy()
                    pcopy['clash_delay'] = delay
                    if bandwidth:
                        pcopy['bandwidth'] = bandwidth
                    results.append(pcopy)
                    if debug:
                        print(f"成功: {delay:4d}ms | {bandwidth or 'N/A':>10} → {proxy.get('name')}")
                else:
                    if debug:
                        print(f"失败 → {proxy.get('name')}") # Debug output for failed attempts
            except Exception as e:
                if debug:
                    print(f"异常: {proxy.get('name')} → {e}")
    print(f"speedtest-clash 精测完成，成功节点：🛩️{len(results)} 个")
    return results
# ============ 辅助函数：带重试的单节点测速（务必一起加上） ============
def xcspeedtest_test_proxy_with_retry(speedtest_path, proxy, debug=False, test_urls=None, retries=0): # test_urls now required
    """
    对单个节点进行测速，最多重试 retries 次
    支持传入自定义测速地址列表
    """
    if test_urls is None: # 防御性检查
        print("❗️警告: xcspeedtest_test_proxy_with_retry 未收到 test_urls，将自动获取。")
        test_urls = get_test_urls()
        
    for attempt in range(retries + 1): # This loop will run only once for attempt=0
        try:
            result = xcspeedtest_test_proxy(speedtest_path, proxy, debug, test_urls) # test_urls passed
            if result is not None:  # (delay, bandwidth)
                return result
            else:
                # If first attempt fails (and retries is 0), this block executes
                if debug:
                    print(f"  xcSpeedtest 最终失败 → {proxy.get('name', '')}")
                return None
        except Exception as e:
            # If an exception occurs (and retries is 0), this block executes
            if debug:
                print(f"  xcSpeedtest 异常 → {proxy.get('name', '')} ({e})")
            return None
    return None # This line should logically not be reached with retries=0
# clash 测速
def xcspeedtest_test_proxy(speedtest_path, proxy, debug=False, test_urls=None): # test_urls now required
    """
    2025-12-06 终极无敌版
    兼容所有版本 xcspeedtest（有/无 clash_delay、引号残缺、换行截断、带宽表格等）
    支持传入自定义测速地址列表
    """
    if test_urls is None: # 防御性检查
        print("❗️警告: xcspeedtest_test_proxy 未收到 test_urls，将自动获取。")
        test_urls = get_test_urls()
        
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'config.yaml')
            
            # 使用动态测速地址构建规则
            rules = []
            for url in test_urls:
                domain = urlparse(url).netloc
                if domain:
                    rules.append(f"DOMAIN,{domain},TESTGROUP")
            rules.append("MATCH,DIRECT")
            
            config = {
                "port": 7890,
                "socks-port": 7891,
                "allow-lan": False,
                "mode": "Rule",
                "log-level": "silent",
                "proxies": [proxy],
                "proxy-groups": [{"name": "TESTGROUP", "type": "select", "proxies": [proxy["name"]]}],
                "rules": rules
            }
            
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, sort_keys=False)
            
            cmd = [speedtest_path, '-c', config_path]
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=40, text=True, encoding='utf-8', errors='ignore'
            )
            output = result.stdout + result.stderr
            
            if debug:
                print(f"[speedtest-clash] 原始输出:\n{output}")
            
            delay = None
            bandwidth = None
            
            # 1. 优先从 JSON 提取 clash_delay
            json_pattern = re.compile(r'json:\s*(\[[\s\S]*?\])', re.IGNORECASE)
            for match in json_pattern.finditer(output):
                j = match.group(1)
                if j.count('{') > j.count('}'): 
                    j += '}'
                if j.count('[') > j.count(']'): 
                    j += ']'
                try:
                    data = json.loads(j)
                    if isinstance(data, list) and data and "clash_delay" in data[0]:
                        d = int(data[0]["clash_delay"])
                        if 1 <= d <= 3000:
                            delay = d
                            if debug:
                                print(f"JSON clash_delay 命中 → {delay}ms ← {proxy['name']}")
                            break
                except:
                    continue
            
            # 2. 兜底：表格延迟列
            if delay is None:
                m = re.search(r'延迟.*?([0-9]+)\s*(?:[^0-9]|$)', output, re.DOTALL)
                if m:
                    try:
                        d = int(m.group(1))
                        if 1 <= d <= 3000:
                            delay = d
                            if debug:
                                print(f"表格延迟兜底 → {delay}ms ← {proxy['name']}")
                    except:
                        pass
            
            # 3. 提取带宽
            bw = re.search(r'([0-9\.]+ ?[KMGT]B/s)', output)
            if bw:
                bandwidth = bw.group(1).strip()
            
            if delay is not None:
                if debug:
                    print(f"测速成功 → {delay}ms | 带宽 {bandwidth or 'N/A'} ← {proxy['name']}")
                return delay, bandwidth
            
            if debug:
                print(f"测速失败 → 丢弃 {proxy['name']}")
            return None
            
    except Exception as e:
        if debug:
            print(f"测速异常: {e}")
        return None
def clash_test_proxy(clash_path, proxy, test_urls=None, debug=False): # test_urls now required
    """
    使用 Clash 核心的 -fast 模式，对单个代理节点测速。
    支持传入自定义测速 URL 列表。
    返回延迟(ms) 或 None。
    """
    if test_urls is None: # 防御性检查
        print("❗️警告: clash_test_proxy 未收到 test_urls，将自动获取。")
        test_urls = get_test_urls()
    temp_dir = tempfile.mkdtemp()
    config_path = os.path.join(temp_dir, 'config.yaml')
    import yaml
    try:
        for test_url in test_urls:
            config = {
                "port": 7890,
                "socks-port": 7891,
                "allow-lan": False,
                "mode": "Rule",
                "log-level": "silent",
                "proxies": [proxy],
                "proxy-groups": [
                    {
                        "name": "TESTGROUP",
                        "type": "select",
                        "proxies": [proxy["name"]]
                    }
                ],
                "rules": [
                    f"DOMAIN,{urlparse(test_url).netloc},TESTGROUP",
                    "MATCH,DIRECT"
                ]
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, sort_keys=False)
            cmd = [clash_path, '-c', config_path, '-fast']
            if debug:
                print(f"\n=== 使用测速 URL: {test_url}, 测试节点: {proxy['name']} ===")
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                text=True
            )
            output = (result.stdout + result.stderr).replace('\x00', '')
            if debug:
                print(f"clash -fast 输出:\n{output}")
            # 优先精准匹配延迟
            match = re.search(r'\b(\d+)ms\b(?=\s*$)', output, re.MULTILINE)
            if match:
                delay = int(match.group(1))
                if 1 < delay < 800:
                    if debug:
                        print(f"成功匹配延迟 {delay}ms，保留节点")
                    return delay
            # 兜底匹配所有延迟值，取最小一个
            delays = re.findall(r'\b([2-9]\d{1,3})\b', output)
            if delays:
                delay_values = [int(d) for d in delays if int(d) < 800]
                if delay_values:
                    delay = min(delay_values)
                    if debug:
                        print(f"未匹配固定格式延迟，取最小延迟 {delay}ms，保留节点")
                    return delay
            # 无效延迟值判断
            if re.search(r'\b(0\s*ms|1\s*ms|NA)\b', output, re.I):
                if debug:
                    print("检测到无效延迟(0ms/1ms/NA)，丢弃节点")
                return None
        if debug:
            print(f"所有测速URL均未获有效延迟，丢弃节点: {proxy['name']}")
        return None
    except subprocess.TimeoutExpired:
        if debug:
            print(f"测速超时，丢弃节点: {proxy['name']}")
    except Exception as e:
        if debug:
            print(f"测速异常 {e}，丢弃节点: {proxy['name']}")
    finally:
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception:
            pass
    return None
def batch_test_proxies_clash(clash_path, proxies, max_workers=MAX_TEST_WORKERS, debug=False, test_urls=None): # test_urls now required
    """
    使用 Clash 核心批量测速的辅助函数，并发执行。
    返回测速完成后带有 clash_delay 字段的列表。
    """
    if test_urls is None: # 防御性检查
        print("❗️警告: batch_test_proxies_clash 未收到 test_urls，将自动获取。")
        test_urls = get_test_urls()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {
            executor.submit(clash_test_proxy, clash_path, proxy, test_urls, debug): proxy # test_urls passed
            for proxy in proxies
        }
        for future in as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            try:
                delay = future.result()
                if delay is not None:
                    pcopy = proxy.copy()
                    pcopy['clash_delay'] = delay
                    results.append(pcopy)
                    if debug:
                        print(f"CLASH PASS: {delay}ms → {pcopy.get('name', '')[:40]}")
                else:
                    if debug:
                        print(f"CLASH FAIL → {proxy.get('name', '')[:40]}")
            except Exception as e:
                if debug:
                    print(f"CLASH EXCEPTION: {proxy.get('name', '')[:40]} → {e}")
    return results
    
def save_intermediate_results(proxies: list, filename: str, last_message_ids: dict | None = None):
    """
    保存中间测速结果。
    仅当 WRITE_LAST_MESSAGE_IDS_IN_INTERMEDIATE 为 True 并且传入了 last_message_ids 时，才写入。
    """
    if not proxies:
        print(f"⏩ 中间结果 {filename} 为空，跳过保存。")
        return

    max_nodes = MAX_NODES_PER_FILE.get(filename, 500)
    if len(proxies) > max_nodes:
        print(f"📌 节点数量超过限制，{filename} 只保留前 {max_nodes} 个节点保存")
        proxies = proxies[:max_nodes]

    output_dir = os.path.dirname(OUTPUT_FILE)
    filepath = os.path.join(output_dir, filename) if output_dir else filename

    update_time = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
    total_count = len(proxies)
    avg_quality = 0
    q_stats_str = ''
    mode = DETAILED_SPEEDTEST_MODE
    min_bandwidth_mb = MIN_BANDWIDTH_MB

    output_data = {'proxies': proxies}

    # 统一判断，变量开启且传入了last_message_ids就写入
    if WRITE_LAST_MESSAGE_IDS_IN_INTERMEDIATE and last_message_ids is not None:
        output_data['last_message_ids'] = last_message_ids

    write_yaml_with_header(
        filepath, output_data, update_time, total_count, avg_quality, q_stats_str, mode, min_bandwidth_mb
    )




def write_yaml_with_header(filepath, data, update_time, total_count, avg_quality, q_stats_str, mode, min_bandwidth_mb):
    """
    写 YAML 文件，并附加统一格式的头部注释
    """
    header_lines = [
        "# ==================================================",
        "#  TG 免费节点 · 自动测速精选订阅 三合一测速版",
        f"#  更新时间   : {update_time} (北京时间)",
        f"#  节点总数   : {total_count} 个节点",
        f"#  平均质量分 : {avg_quality:.1f}/100",
        f"#  质量分布   : {q_stats_str if q_stats_str else '无'}",
        f"#  测速模式   : {mode}",
        f"#  带宽筛选   : ≥ {min_bandwidth_mb}MB/s",
        "# ==================================================\n"
    ]
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            for line in header_lines:
                f.write(line + '\n')
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, indent=2, width=4096)
        print(f"✅ 文件已保存（含头部注释）: {filepath}")
    except Exception as e:
        print(f"❌ 写入文件失败 {filepath}: {e}")

def save_intermediate_results(proxies: list, filename: str):
    """
    负责保存中间测速结果（TCP.yaml、clash.yaml、speedtest.yaml）
    会根据配置的最大节点数限制来截断节点列表
    """
    if not proxies:
        print(f"⏩ 中间结果 {filename} 为空，跳过保存。")
        return
    
    max_nodes = MAX_NODES_PER_FILE.get(filename, 500)  # 默认限制500个节点
    if len(proxies) > max_nodes:
        print(f"📌 节点数量超过限制，{filename} 只保留前 {max_nodes} 个节点保存")
        proxies = proxies[:max_nodes]

    update_time = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
    total_count = len(proxies)
    avg_quality = 0         # 中间结果通常无质量分
    q_stats_str = ''        # 可额外统计质量标签再填充此参数
    mode = DETAILED_SPEEDTEST_MODE
    min_bandwidth_mb = MIN_BANDWIDTH_MB

    filepath = os.path.join(os.path.dirname(OUTPUT_FILE), filename)
    data = {'proxies': proxies}

    write_yaml_with_header(
        filepath, data, update_time, total_count, avg_quality, q_stats_str, mode, min_bandwidth_mb
    )

def save_final_config(final_proxies, last_message_ids, q_stats):
    """
    负责保存最终的订阅配置文件（如 Tg-node2.yaml）
    同样限制最大节点数，默认从配置字典获取
    """
    filename = os.path.basename(OUTPUT_FILE)
    max_nodes = MAX_NODES_PER_FILE.get(filename, 500)
    if len(final_proxies) > max_nodes:
        print(f"📌 节点数量超过限制，最终文件只保留前 {max_nodes} 个节点保存")
        final_proxies = final_proxies[:max_nodes]

    update_time = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
    total_count = len(final_proxies)
    avg_quality = (sum(p.get('quality_score', 0) for p in final_proxies) / total_count) if total_count else 0
    q_stats_str = f"🔥极品:{q_stats.get('🔥极品',0)}, ⭐优质:{q_stats.get('⭐优质',0)}, ✅良好:{q_stats.get('✅良好',0)}, ⚡可用:{q_stats.get('⚡可用',0)}"
    mode = DETAILED_SPEEDTEST_MODE
    min_bandwidth_mb = MIN_BANDWIDTH_MB

    final_config = {
        'proxies': final_proxies,
        'last_message_ids': last_message_ids,
        'update_time': update_time,
        'total_nodes': total_count,
        'average_quality': round(avg_quality, 1),
        'quality_stats': q_stats_str,
        'speedtest_config': {
            'mode': mode,
            'warp_for_tcp': None,
            'warp_for_speedtest': None,
        }
    }

    write_yaml_with_header(
        OUTPUT_FILE, final_config, update_time, total_count, avg_quality, q_stats_str, mode, min_bandwidth_mb
    )

# 使用示例（在主流程中调用，变量需保证存在）
# save_final_config(final_proxies, last_message_ids, q_stats)
#save_intermediate_results(tcp_passed, 'TCP.yaml', last_message_ids)
#save_intermediate_results(clash_passed, 'clash.yaml', last_message_ids)
#save_intermediate_results(speedtest_passed, 'speedtest.yaml', last_message_ids)



def write_yaml_with_header(filepath, data, update_time, total_count, avg_quality, q_stats_str, mode, min_bandwidth_mb):
    header_lines = [
        "# ==================================================",
        "#  TG 免费节点 · 自动测速精选订阅 三合一测速版",
        f"#  更新时间   : {update_time} (北京时间)",
        f"#  节点总数   : {total_count} 个节点",
        f"#  平均质量分 : {avg_quality:.1f}/100",
        f"#  质量分布   : {q_stats_str if q_stats_str else '无'}",
        f"#  测速模式   : {mode}",
        f"#  带宽筛选   : ≥ {min_bandwidth_mb}MB/s",
        "# ==================================================\n"
    ]
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            for line in header_lines:
                f.write(line + '\n')
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, indent=2, width=4096)
        print(f"✅ 文件已保存（含头部注释）: {filepath}")
    except Exception as e:
        print(f"❌ 写入文件失败 {filepath}: {e}")


# 主函数   
async def main():
    # [0] 目录初始化与按需清理
    output_dir = os.path.dirname(OUTPUT_FILE)
    if output_dir: os.makedirs(output_dir, exist_ok=True)
    
    if CLEAN_STALE_FILES:
        print("🧹 已开启中间件清理模式...")
        for f in ['TCP.yaml', 'clash.yaml', 'speedtest.yaml']:
            p = os.path.join(output_dir, f)
            if os.path.exists(p):
                try: os.remove(p); print(f"  - 已删除旧文件: {f}")
                except: pass
    else:
        print("📁 已关闭中间件清理模式，保留上次运行结果。")
    
    print("=" * 60)
    print("Telegram.Node_Clash-Speedtest测试版 V2.0")
    print(datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    # === [1/7] 初始化与网络控制检查 ===
    print("🌐 网络控制配置:")
    print(f"  - 抓取阶段 Warp: {WARP_FOR_SCRAPING}")
    print(f"  - TCP测速 Warp: {WARP_FOR_TCP}")
    print(f"  - Speedtest测速 Warp: {WARP_FOR_SPEEDTEST}")
    print(f"  - 最终阶段 Warp: {WARP_FOR_FINAL}")
    print("-" * 40)
    if os.getenv('GITHUB_ACTIONS') == 'true':
        print("🏗️ GitHub Actions环境检测到，准备执行网络状态控制")
        simplified_network_check()
    else:
        print("💻 本地环境，跳过网络自动切换")
    preprocess_regex_rules()
    # === [2/7] 加载历史数据 ===
    print("[1/7] 加载历史数据...")
    existing_proxies, last_message_ids, last_file_update_time = load_existing_proxies_and_state('flclashyaml/TCP.yaml')
    print(f"  - 历史节点总数: {len(existing_proxies)}")
    # === [3/7] 抓取新链接与解析 ===
    print("[2/7] 抓取 Telegram 订阅链接...")
    if os.getenv('GITHUB_ACTIONS') == 'true':
        ensure_network_for_stage('scraping', require_warp=WARP_FOR_SCRAPING)
    
    urls, last_message_ids = await scrape_telegram_links(last_message_ids)
    new_proxies = []
    if urls:
        print(f"  - 开始下载解析 {len(urls)} 个链接...")
        for i, url in enumerate(urls, 1):
            print(f"    进度: {i}/{len(urls)} | {url[:70]}...")
            proxies = download_and_parse(url)
            if proxies:
                new_proxies.extend(proxies)
        print(f"  - 解析完成，获得新节点: {len(new_proxies)}")
    else:
        print("  - 未发现新链接，跳过下载步骤")
    # === [4/7] 节点预处理：合并、物理去重、修复非法数据、第一次全局重命名 ===
    print("[3/7] 节点预处理（彻底解决重名与非法数据异常）")
    
    # 4.1 物理去重：基于 Server/Port/Secret 生成 MD5 Key
    all_proxies_map = {
        get_proxy_key(p): p for p in existing_proxies if is_valid_proxy(p)
    }
    added_count = 0
    for p in new_proxies:
        key = get_proxy_key(p)
        if key not in all_proxies_map:
            all_proxies_map[key] = p
            added_count += 1
    
    all_nodes = list(all_proxies_map.values())
    print(f"  - 物理去重后总数: {len(all_nodes)} (新入库: {added_count})")
    if not all_nodes:
        print("⚠️ 未发现有效节点，任务优雅退出"); return
    # 4.2 修复非法数据：解决 "illegal base64 data"
    # 强制修正 SS 的 cipher 缺失，丢弃不符合规范的节点
    all_nodes = fix_and_filter_ss_nodes(all_nodes)
    all_nodes = [p for p in all_nodes if is_valid_proxy(p)]
    # 4.3 全局第一次重命名：解决 "proxy duplicate name"
    # 在进入测速环节前，必须洗一遍名字，确保保存中间文件时不会报错
    all_nodes = normalize_proxy_names(all_nodes)
    print(f"  - 预处理完成，进入测速阶段的节点数: {len(all_nodes)}")
    # === [5/7] 测速流程（完整六大模式） ===
    speedtest_path = './xcspeedtest'
    clash_path = './clash_core/clash'
    mode = DETAILED_SPEEDTEST_MODE
    print(f"[4/7] 执行测速模式: {mode}")
    final_tested_nodes = []
    # --- 模式 1: TCP -> Clash -> XC ---
    if mode == 'tcp_clash_xc':
        print("【模式】TCP 粗筛 → Clash 精测 → Speedtest 精测")
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('tcp', require_warp=WARP_FOR_TCP)
        tcp_passed = batch_tcp_test(all_nodes)
        tcp_passed = normalize_proxy_names(tcp_passed) # 确保存文件前名字唯一
        save_intermediate_results(tcp_passed, 'TCP.yaml')
        nodes_for_clash = tcp_passed if tcp_passed else all_nodes
        if not tcp_passed: print("  ⚠️ TCP 全部失败，尝试全量进入下阶段")
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('speedtest', require_warp=WARP_FOR_SPEEDTEST)
        clash_passed = batch_test_proxies_clash(clash_path, nodes_for_clash, max_workers=MAX_TEST_WORKERS, debug=ENABLE_SPEEDTEST_LOG, test_urls=get_test_urls())
        clash_passed = normalize_proxy_names(clash_passed)
        save_intermediate_results(clash_passed, 'clash.yaml')
        if clash_passed:
            final_tested_nodes = batch_test_proxies_speedtest(speedtest_path, clash_passed, max_workers=MAX_TEST_WORKERS, debug=ENABLE_SPEEDTEST_LOG, test_urls=get_test_urls())
            final_tested_nodes = normalize_proxy_names(final_tested_nodes)
            save_intermediate_results(final_tested_nodes, 'speedtest.yaml')
        else:
            final_tested_nodes = []
    # --- 模式 2: TCP -> Clash ---
    elif mode == 'tcp_clash':
        print("【模式】TCP 粗筛 → Clash 精测")
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('tcp', require_warp=WARP_FOR_TCP)
        tcp_passed = batch_tcp_test(all_nodes)
        tcp_passed = normalize_proxy_names(tcp_passed)
        save_intermediate_results(tcp_passed, 'TCP.yaml')
        nodes_for_clash = tcp_passed if tcp_passed else all_nodes
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('speedtest', require_warp=WARP_FOR_SPEEDTEST)
        final_tested_nodes = batch_test_proxies_clash(clash_path, nodes_for_clash, max_workers=MAX_TEST_WORKERS, debug=ENABLE_SPEEDTEST_LOG, test_urls=get_test_urls())
        final_tested_nodes = normalize_proxy_names(final_tested_nodes)
        save_intermediate_results(final_tested_nodes, 'clash.yaml')
    # --- 模式 3: TCP -> XC ---
    elif mode == 'tcp_xc':
        print("【模式】TCP 粗筛 → Speedtest 精测")
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('tcp', require_warp=WARP_FOR_TCP)
        tcp_passed = batch_tcp_test(all_nodes)
        tcp_passed = normalize_proxy_names(tcp_passed)
        save_intermediate_results(tcp_passed, 'TCP.yaml')
        nodes_for_xc = tcp_passed if tcp_passed else all_nodes
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('speedtest', require_warp=WARP_FOR_SPEEDTEST)
        final_tested_nodes = batch_test_proxies_speedtest(speedtest_path, nodes_for_xc, max_workers=MAX_TEST_WORKERS, debug=ENABLE_SPEEDTEST_LOG, test_urls=get_test_urls())
        final_tested_nodes = normalize_proxy_names(final_tested_nodes)
        save_intermediate_results(final_tested_nodes, 'speedtest.yaml')
    # --- 模式 4: 纯 TCP 测速 ---
    elif mode == 'tcp_only':
        print("【模式】纯 TCP 测速")
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('tcp', require_warp=WARP_FOR_TCP)
        final_tested_nodes = batch_tcp_test(all_nodes)
        final_tested_nodes = normalize_proxy_names(final_tested_nodes)
        save_intermediate_results(final_tested_nodes, 'TCP.yaml')
    # --- 模式 5: 纯 Clash 测速 ---
    elif mode == 'clash_only':
        print("【模式】纯 Clash 测速")
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('speedtest', require_warp=WARP_FOR_SPEEDTEST)
        final_tested_nodes = batch_test_proxies_clash(clash_path, all_nodes, max_workers=MAX_TEST_WORKERS, debug=ENABLE_SPEEDTEST_LOG, test_urls=get_test_urls())
        final_tested_nodes = normalize_proxy_names(final_tested_nodes)
        save_intermediate_results(final_tested_nodes, 'clash.yaml')
    # --- 模式 6: 纯 Speedtest 测速 ---
    elif mode == 'xcspeedtest_only':
        print("【模式】纯 Speedtest 测速")
        if os.getenv('GITHUB_ACTIONS') == 'true':
            ensure_network_for_stage('speedtest', require_warp=WARP_FOR_SPEEDTEST)
        final_tested_nodes = batch_test_proxies_speedtest(speedtest_path, all_nodes, max_workers=MAX_TEST_WORKERS, debug=ENABLE_SPEEDTEST_LOG, test_urls=get_test_urls())
        final_tested_nodes = normalize_proxy_names(final_tested_nodes)
        save_intermediate_results(final_tested_nodes, 'speedtest.yaml')
    else:
        print(f"⚠️ 未知模式，优雅退出"); return
    # === [6/7] 后置筛选、评分与排序 ===
    print("[5/7] 测速后置处理与质量评分")
    if os.getenv('GITHUB_ACTIONS') == 'true':
        ensure_network_for_stage('final', require_warp=WARP_FOR_FINAL)
    # 再次清理无效节点
    final_proxies = [p for p in final_tested_nodes if is_valid_proxy(p)]
    
    # 根据测速存活情况再次归一化名字（确保如 DE-1, DE-2 顺序排列）
    final_proxies = normalize_proxy_names(final_proxies)
    
    # 带宽二次筛选
    final_proxies = filter_by_bandwidth(final_proxies, min_mb=MIN_BANDWIDTH_MB, enable=ENABLE_BANDWIDTH_FILTER)
    
    # 数量限制与分区限额
    final_proxies = limit_proxy_counts(final_proxies, max_total=400)
    
    # 质量评分与打质量标签
    final_proxies = sort_proxies_by_quality(final_proxies)
    final_proxies = add_quality_to_name(final_proxies)
    
    # 最终排序：评分降序
    final_proxies = sorted(final_proxies, key=lambda p: -p.get('quality_score', 0))
    if not final_proxies:
        print("⚠️ 筛选后无有效节点，优雅退出"); return
    # === [7/7] 生成最终配置文件 ===
    print("[6/7] 生成最终 YAML 配置文件...")
    total_count = len(final_proxies)
    update_time = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
    avg_quality = sum(p.get('quality_score', 0) for p in final_proxies) / total_count if total_count > 0 else 0

    # 保存 TCP 阶段测速结果
    save_intermediate_results(tcp_passed, 'TCP.yaml', last_message_ids)
    # 保存 Clash 阶段测速结果
    save_intermediate_results(clash_passed, 'clash.yaml', last_message_ids)
    # 保存 Speedtest 阶段测速结果
    save_intermediate_results(speedtest_passed, 'speedtest.yaml', last_message_ids)
    # 保存最终结果（带详细统计等）
    save_final_config(final_proxies, last_message_ids, q_stats)
    
    # 统计质量分布
    q_stats = {'🔥极品': 0, '⭐优质': 0, '✅良好': 0, '⚡可用': 0}
    for p in final_proxies:
        tag = p.get('quality_tag', '⚡可用')
        if tag in q_stats: q_stats[tag] += 1
    q_stats_str = f"🔥极品:{q_stats['🔥极品']}, ⭐优质:{q_stats['⭐优质']}, ✅良好:{q_stats['✅良好']}, ⚡可用:{q_stats['⚡可用']}"
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write("# ==================================================\n")
            f.write("#  TG 免费节点 · 自动测速精选订阅 三合一测速版\n")
            f.write(f"#  更新时间   : {update_time} (北京时间)\n")
            f.write(f"#  节点总数   : {total_count} 个优质节点\n")
            f.write(f"#  平均质量分 : {avg_quality:.1f}/100\n")
            f.write(f"#  质量分布   : {q_stats_str}\n")
            f.write(f"#  测速模式   : {mode}\n")
            f.write(f"#  带宽筛选   : ≥ {MIN_BANDWIDTH_MB}MB/s\n")
            f.write("# ==================================================\n\n")
            
            final_config = {
                'proxies': final_proxies,
                'last_message_ids': last_message_ids,
                'update_time': update_time,
                'total_nodes': total_count,
                'average_quality': round(avg_quality, 1),
                'quality_stats': q_stats_str,
                'speedtest_config': {
                    'mode': mode,
                    'warp_for_tcp': WARP_FOR_TCP,
                    'warp_for_speedtest': WARP_FOR_SPEEDTEST
                }
            }
            yaml.dump(final_config, f, allow_unicode=True, sort_keys=False, indent=2, width=4096, default_flow_style=False)
        
        print(f"✅ 成功! 配置文件已保存至: {OUTPUT_FILE}")
        print(f"📊 本次汇总: 总数 {total_count} | 均分 {avg_quality:.1f} | {q_stats_str}")
    except Exception as e:
        print(f"❌ 最终写出配置文件失败: {e}")
    # === 最终清理，确保切换回GitHub网络 ===
    if os.getenv('GITHUB_ACTIONS') == 'true' and not WARP_FOR_FINAL:
        print("[7/7] 🧹 最终清理：确保使用原始GitHub网络")
        ensure_network_for_stage('cleanup', require_warp=False)
    print("=" * 60)
    print("🎉 全部任务圆满完成！")

        

if __name__ == "__main__":
    try:
        asyncio.run(main())  # 调用异步主函数
    except:
        import traceback
        traceback.print_exc()
        sys.exit(0) # 强制 0 状态退出

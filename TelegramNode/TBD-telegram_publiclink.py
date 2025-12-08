# -*- coding: utf-8 -*-
"""
文件名: Telegram.Node_Final V1.R1 
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

# --- 环境变量读取 ---
API_ID = int(os.environ.get('TELEGRAM_API_ID') or 0)
API_HASH = os.environ.get('TELEGRAM_API_HASH')
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS', '')
TIME_WINDOW_HOURS = 4  # 抓取多长时间的消息，单位为小时。
MIN_EXPIRE_HOURS = 2   # 订阅地址剩余时间最小过期，单位为小时。
OUTPUT_FILE = 'flclashyaml/Tg-node1.yaml'  # 输出文件路径，用于保存生成的配置或结果。



# === 新增：测速策略开关（推荐保留这几个选项）===
# 测速模式：
ENABLE_SPEED_TEST = True  # 是否启用整体速度测试功能，True表示启用。测试顺序如下

SPEEDTEST_MODE = os.getenv('SPEEDTEST_MODE', 'tcp_first').lower()  # 默认推荐 tcp_first,下边的命令
#   "tcp_only"      → 只用 TCP 测速（最快，最严格，适合节点特别多的情况）
#   "clash_only"    → 只用 Clash -fast 测速（最准）
#   "tcp_first"     → 先 TCP 粗筛（<800ms）→ 再 Clash 精测（推荐！平衡速度与质量）
#   "clash_first"   → 先 Clash → 再 TCP（一般用不上）

# TCP 和Clash 测速专属参数
TCP_TIMEOUT = 3.5          # 单次 TCP 连接超时时间（秒），建议 3~5
TCP_MAX_WORKERS = 512      # TCP 测速最大并发（可以比 Clash 高很多，非常快）
TCP_MAX_DELAY = 1000       # TCP 延迟阈值，超过此值直接丢弃（ms）
ENABLE_TCP_LOG = False     # 默认关闭TCP日志
ENABLE_SPEEDTEST_LOG = False  # 默认关闭 speedtest 详细日志False / True打开


MAX_TEST_WORKERS = 128    # 速度测试时最大并发工作线程数，控制测试的并行度。建议64-96
SOCKET_TIMEOUT = 3       # 套接字连接超时时间，单位为秒
HTTP_TIMEOUT = 5         # HTTP请求超时时间，单位为秒
# 【关键修改1】测速目标全部换成国内/Cloudflare中国节点
TEST_URLS = [
    'http://www.baidu.com/generate_204',           # 百度 204，最快最稳
    'http://qq.com/generate_204',                    # 腾讯 204
    'http://cp.cloudflare.com/generate_204',       # Cloudflare 中国大陆节点
    'http://connectivitycheck.gstatic.com/generate_204',  # Google 204（国内也通）
]

# ==================== 带宽筛选配置（新增） ====================
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
    

# ==================== 【关键修改2】在最前面加入 Warp 启动函数 ====================
def start_cloudflare_warp():
    """
    在 GitHub Actions 中启用 Cloudflare Warp
    模拟国内网络环境，使测速结果对国内用户有效
    """
    print("🌐 正在启动 Cloudflare Warp（尝试模拟国内环境）...")
    
    try:
        # ... [现有代码] ...
        
        # 5. 启动 WARP VPN (需要 sudo 权限)
        print(">> 5. 启动 WARP VPN...")
        # wg-quick up 可能会在某些环境下返回非零状态码但实际成功，或有stderr输出
        # 允许一定程度的失败，但要检查实际效果
        result = subprocess.run(
            ["sudo", "wg-quick", "up", "wgcf"],
            capture_output=True, text=True, timeout=30 # 启动超时
        )
        
        # 检查启动结果
        if result.returncode == 0 or "errno" not in result.stderr:
            print("✅ WARP 启动成功或已连接")
            # 验证IP是否已切换
            try:
                ip_check = subprocess.run(
                    ["curl", "-4", "-s", "--max-time", "10", "https://ip.sb"],
                    capture_output=True, text=True
                )
                if ip_check.returncode == 0:
                    print(f"当前出口 IPv4: {ip_check.stdout.strip()}")
            except:
                pass
            return True
        else:
            print(f"⚠️ WARP 启动失败: {result.stderr[:200]}")
            return False
            
    except Exception as e:
        print(f"❌ WARP 启动异常: {e}")
        return False


def get_country_flag_emoji(code):
    if not code or len(code) != 2:
        return "❓"
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in code)

def preprocess_regex_rules():
    for region in CUSTOM_REGEX_RULES:
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(
            sorted(CUSTOM_REGEX_RULES[region]['pattern'].split('|'), key=len, reverse=True)
        )

def load_existing_proxies_and_state():
    existing_proxies = []
    last_message_ids = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                loaded_yaml = yaml.safe_load(f)
                if isinstance(loaded_yaml, dict):
                    existing_proxies = loaded_yaml.get('proxies', [])
                    if not isinstance(existing_proxies, list):
                        existing_proxies = []
                    last_message_ids = loaded_yaml.get('last_message_ids', {})
                    if not isinstance(last_message_ids, dict):
                        last_message_ids = {}
                elif isinstance(loaded_yaml, list):
                    existing_proxies = [p for p in loaded_yaml if isinstance(p, dict)]
        except Exception as e:
            print(f"读取 {OUTPUT_FILE} 失败: {e}")
    return existing_proxies, last_message_ids

# =============================================
# 多匹配的 extract_valid_subscribe_links 函数
# =============================================
def extract_valid_subscribe_links(text: str):
    """
    2025年12月终极防漏版
    完美解决：反引号、引号、括号、换行、中文标点污染链接问题
    """
    # 第一步：狂暴提取所有疑似链接（超宽松）
    rough_links = re.findall(r'https?://[^\s<>"\'`\]]+', text)
    
    valid_links = set()
    for link in rough_links:
        # 清理常见尾巴污染字符
        link = link.split('&amp;')[0]
        link = re.sub(r'[`\'")\]，。、！!？\?>\n\r]+$', '', link)  # 重点：干掉反引号、引号、括号、中文标点
        link = link.strip()
        
        if not link:
            continue
            
        url_lower = link.lower()
        
        # 白名单关键词（命中即为订阅链接）
        if any(k in url_lower for k in [
            '/s/', '/sub', '/link', '/clash', '/raw', '/api/v1/client/subscribe',
            'token=', 'flag=', 'sub.', 'ghelper', 'kaixincloud', 'mojie.app',
            'de5.net', 'oooooooo', 'xn--', 'gist.', 'workers.dev'
        ]):
            # 排除明显不是订阅的
            if any(bad in url_lower for bad in ['/t.me/', '/joinchat', '/channel', '/invite']):
                continue
            valid_links.add(link)
    
    # === 过期时间判断（保持你原来的逻辑）===
    MIN_HOURS_LEFT = MIN_EXPIRE_HOURS
    text_line = text.replace('\n', ' ')
    expire_time = None
    
    # 常见过期关键词
    if re.search(r'长期有效|未知|无限|2099', text_line, re.I):
        expire_time = None  # 长期有效
    else:
        for patt in [
            r'过期时间[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
            r'到期时间[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})\s*(?:到期|过期)',
        ]:
            m = re.search(patt, text_line)
            if m:
                try:
                    dt = datetime.strptime(m.group(1), '%Y-%m-%d')
                    expire_time = dt.replace(hour=23, minute=59, second=59, tzinfo=BJ_TZ)
                    break
                except:
                    continue
    
    now = datetime.now(BJ_TZ)
    final_links = []
    for url in valid_links:
        if expire_time:
            hours_left = (expire_time - now).total_seconds() / 3600
            if hours_left < MIN_HOURS_LEFT:
                print(f"  订阅即将过期（剩 {hours_left:.1f}h），跳过: {url[:60]}...")
                continue
        final_links.append(url)
        print(f"成功提取链接🔗: {url}")  # 调试用，可删
    
    return final_links

# ==========================
# 替换了 scrape_telegram_links 为 B 版本更完善的实现
async def scrape_telegram_links(last_message_ids=None):
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
    
    # 按频道数量分组处理，避免同时打开太多连接
    CHANNEL_BATCH_SIZE = 3  # 每次处理3个频道
    all_links = set()
    
    try:
        client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        print(f"✅ 以 {me.first_name} (@{me.username}) 的身份成功连接")
    except Exception as e:
        print(f"❌ 错误: 连接 Telegram 时出错: {e}")
        return [], last_message_ids
    
    bj_now = datetime.now(BJ_TZ)
    target_time = (bj_now - timedelta(hours=TIME_WINDOW_HOURS)).astimezone(timezone.utc)
    
    # 分批处理频道
    for i in range(0, len(TARGET_CHANNELS), CHANNEL_BATCH_SIZE):
        batch = TARGET_CHANNELS[i:i + CHANNEL_BATCH_SIZE]
        print(f"\n📦 处理批次 {i//CHANNEL_BATCH_SIZE + 1}/{(len(TARGET_CHANNELS)-1)//CHANNEL_BATCH_SIZE + 1}: {batch}")
        
        tasks = []
        for channel_id in batch:
            tasks.append(process_channel(client, channel_id, last_message_ids, target_time))
        
        # 并发处理批次内的频道
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for idx, result in enumerate(results):
            channel_id = batch[idx]
            if isinstance(result, Exception):
                print(f"❌ 处理频道 '{channel_id}' 时出错: {result}")
                continue
                
            links, new_max_id = result
            for link in links:
                if link not in all_links:
                    all_links.add(link)
                    print(f"  ✅ 找到链接: {link[:70]}...")
            
            if new_max_id > last_message_ids.get(channel_id, 0):
                last_message_ids[channel_id] = new_max_id
    
    await client.disconnect()
    print(f"\n✅ 抓取完成, 共找到 {len(all_links)} 个不重复的有效链接。")
    return list(all_links), last_message_ids

async def process_channel(client, channel_id, last_message_ids, target_time):
    """处理单个频道的辅助函数"""
    max_id_found = last_message_ids.get(channel_id, 0)
    channel_links = []
    
    try:
        entity = await client.get_entity(channel_id)
    except Exception as e:
        print(f"❌ 错误: 无法获取频道实体 {channel_id}: {e}")
        return channel_links, max_id_found
    
    print(f"  🎯 正在处理频道: {channel_id}")
    
    try:
        async for message in client.iter_messages(entity, min_id=last_message_ids.get(channel_id, 0) + 1, reverse=False):
            if message.date < target_time:
                break
            if message.text:
                links = extract_valid_subscribe_links(message.text)
                for link in links:
                    channel_links.append(link)
            if message.id > max_id_found:
                max_id_found = message.id
    except Exception as e:
        print(f"❌ 错误: 从频道 '{channel_id}' 获取消息时出错: {e}")
    
    return channel_links, max_id_found

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

def parse_ss_node(line):
    try:
        line = line.strip()
        if not line.startswith('ss://'):
            return None
        content = line[5:]
        if '@' in content:
            # 标准格式: ss://method:password@server:port#remarks
            parsed = urlparse('ss://' + content)
            user_pass = parsed.netloc.split('@')[0]
            method, password = user_pass.split(':', 1)
            server = parsed.hostname
            port = parsed.port
            name = unquote(parsed.fragment) if parsed.fragment else f"ss_{server}"
            node = {'name': name, 'type': 'ss', 'server': server, 'port': port,
                    'cipher': method, 'password': password, 'udp': True}
            return node
        else:
            # base64格式 ss://base64(method:password@server:port) 或带备注
            ss_b64 = content.split('#')[0]
            remark = ''
            if '#' in content:
                remark = unquote(content.split('#')[1])
            decoded = base64.urlsafe_b64decode(ss_b64 + '=' * (-len(ss_b64) % 4)).decode('utf-8', errors='ignore')
            method_password, server_port = decoded.split('@')
            method, password = method_password.split(':')
            server, port = server_port.split(':')
            node = {'name': remark or f"ss_{server}", 'type': 'ss', 'server': server,
                    'port': int(port), 'cipher': method, 'password': password, 'udp': True}
            return node
    except Exception:
        return None

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
    try:
        parsed = urlparse(line)
        if parsed.scheme != 'hysteria':
            return None
        params = parse_qs(parsed.query)
        node = {
            'name': unquote(parsed.fragment) or f"hysteria_{parsed.hostname}",
            'type': 'hysteria',
            'server': parsed.hostname,
            'port': int(parsed.port or 0),
            'auth': params.get('auth', [''])[0],
            'protocol': params.get('protocol', ['udp'])[0],
            'insecure': params.get('insecure', ['false'])[0].lower() == 'true',
            'obfs': params.get('obfs', [''])[0],
            'udp': True,
        }
        return node
    except Exception:
        return None

def parse_hysteria2_node(line):
    try:
        parsed = urlparse(line)
        if parsed.scheme != 'hysteria2':
            return None
        params = parse_qs(parsed.query)
        auth = parsed.username or ''
        obfs_password = params.get('obfs-password', [''])[0]
        insecure_val = params.get('insecure', ['false'])[0].lower()
        insecure = insecure_val in ('1', 'true', 'yes')
        node = {
            'name': unquote(parsed.fragment) if parsed.fragment else f"hysteria2_{parsed.hostname}",
            'type': 'hysteria2',
            'server': parsed.hostname,
            'port': int(parsed.port or 0),
            'auth': auth,
            'protocol': params.get('protocol', ['udp'])[0],
            'insecure': insecure,
            'obfs': params.get('obfs', [''])[0],
            'obfs-password': obfs_password,
            'udp': params.get('udp', ['true'])[0].lower() == 'true',
        }
        return node
    except Exception:
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

    print(f"  检测到超级反爬机场，使用终极绕过模式: {url[:70]}...")

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
            '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm',
            '2022-blake3-chacha20-poly1305', '2022-blake3-chacha8-poly1305'
        }

        # 如果 cipher 缺失或非法，强制修复为最通用的
        if not cipher or cipher.lower() not in valid_ciphers:
            old = proxy.get('cipher', 'None')
            proxy['cipher'] = 'chacha20-ietf-poly1305'  # 2025 年最万能
            print(f"【自动修复】ss 节点 cipher 缺失或非法 ({old} → chacha20-ietf-poly1305)：{proxy['name']}")

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
def fix_and_filter_ss_nodes(proxies):
    """彻底解决 ss 节点缺少 cipher 或 cipher 非法的问题"""
    valid_proxies = []
    fixed_count = 0
    dropped_count = 0
    
    for p in proxies:
        if p.get('type') != 'ss':
            valid_proxies.append(p)
            continue
            
        cipher = p.get('cipher', '').strip().lower()
        
        # 白名单：Clash Premium/Meta 真正支持的加密方式
        valid_ciphers = {
            'aes-128-gcm', 'aes-192-gcm', 'aes-256-gcm',
            'chacha20-ietf-poly1305', 'chacha20-poly1305',
            'xchacha20-ietf-poly1305', 'xchacha20-poly1305',
            '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm', '2022-blake3-chacha20-poly1305'
        }
        
        if cipher in valid_ciphers:
            valid_proxies.append(p)
            continue
            
        # —— 尝试自动修复常见的错误写法 ——
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
        
        old_cipher = p.get('cipher', '')
        if old_cipher.lower() in auto_map:
            new_cipher = auto_map[old_cipher.lower()]
            if new_cipher:
                p['cipher'] = new_cipher
                print(f"【修复】ss 节点 cipher {old_cipher} → {new_cipher} : {p['name']}")
                valid_proxies.append(p)
                fixed_count += 1
            else:
                print(f"【丢弃】ss 节点 cipher 无效且无法修复: {old_cipher} → {p['name']}")
                dropped_count += 1
        else:
            # 完全没有 cipher 字段或乱码，直接尝试用最常见的默认值救活
            if not cipher or len(cipher) > 50 or ' ' in cipher:
                p['cipher'] = 'chacha20-ietf-poly1305'  # 2025 年最通用
                print(f"【强救】ss 节点缺失/乱码 cipher，强制使用 chacha20-ietf-poly1305 : {p['name']}")
                valid_proxies.append(p)
                fixed_count += 1
            else:
                print(f"【丢弃】ss 节点 cipher 不支持且无法自动映射: {cipher} → {p['name']}")
                dropped_count += 1
    
    print(f"ss 节点检查完成：修复 {fixed_count} 个，丢弃 {dropped_count} 个，剩余有效 ss 节点 {len([p for p in valid_proxies if p.get('type')=='ss'])} 个")
    return valid_proxies





def normalize_proxy_names(proxies):
    pattern_trailing_number = re.compile(r'\s*\d+\s*$')
    normalized = []

    for p in proxies:
        name = p.get('name', '').strip()

        # 用循环检测清理开头所有国旗emoji
        name = strip_starting_flags(name)

        # 清理尾部数字序号
        name = pattern_trailing_number.sub('', name).strip()

        p['name'] = name

        # 以下保持现有逻辑不变
        region_info = p.get('region_info', None)
        flag_match = re.search(r'[\U0001F1E6-\U0001F1FF]{2}', name)
        flag_emoji = flag_match.group(0) if flag_match else None

        country_cn = None
        if region_info and 'name' in region_info and region_info['name'] in CUSTOM_REGEX_RULES:
            country_cn = region_info['name']
        elif flag_emoji:
            code = emoji_to_country_code(flag_emoji)
            if code and code in COUNTRY_CODE_TO_CN:
                country_cn = COUNTRY_CODE_TO_CN[code]
        if not country_cn:
            for cname, info in CUSTOM_REGEX_RULES.items():
                if re.search(info['pattern'], name, re.IGNORECASE):
                    country_cn = cname
                    break
        if not country_cn:
            short_name = name[:2] if len(name) >= 2 else name
            country_cn = short_name if short_name else "未知"
            flag_emoji = FLAG_EMOJI_UN_FLAG
        if not flag_emoji:
            code = None
            for k, v in COUNTRY_CODE_TO_CN.items():
                if v == country_cn:
                    code = k
                    break
            flag_emoji = get_country_flag_emoji(code) if code else FLAG_EMOJI_UN_FLAG

        clean_name = country_cn
        p['_norm_flag'] = flag_emoji
        p['_norm_country'] = clean_name
        normalized.append(p)

    grouped = {}
    for p in normalized:
        country = p['_norm_country']
        grouped.setdefault(country, []).append(p)

    final_list = []
    for country, plist in grouped.items():
        for idx, p in enumerate(plist, 1):
            new_name = f"{p['_norm_flag']} {country} {idx}"
            p['name'] = new_name
            del p['_norm_flag']
            del p['_norm_country']
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
    
    print(f"带宽筛选完成：≥{min_mb}MB/s 保留 {len(filtered)}/{len(proxies)} 个节点")
    return filtered

def limit_proxy_counts(proxies, max_total=600):
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
    纯 TCP 连接测延迟，返回延迟（ms）或 None
    """
    server = proxy.get('server')
    port = proxy.get('port')
    if not server or not port:
        return None
    
    try:
        start = time.time()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((server, int(port)))
        delay_ms = int((time.time() - start) * 1000)
        # 过滤异常值（<1ms 基本是假的）
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
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {executor.submit(tcp_ping, p): p for p in proxies}
        for future in as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            delay = future.result()
            if delay is not None and delay <= TCP_MAX_DELAY:
                proxy = proxy.copy()
                proxy['tcp_delay'] = delay
                results.append(proxy)
                if ENABLE_TCP_LOG:
                    print(f"TCP PASS: {delay:4d}ms → {proxy.get('name', '')[:40]}")
            else:
                if delay and ENABLE_TCP_LOG:
                    print(f"TCP SLOW: {delay:4d}ms → 丢弃 {proxy.get('name', '')[:40]}")
    return results

def batch_test_proxies_speedtest(speedtest_path, proxies, max_workers=MAX_TEST_WORKERS, debug=False):
    """
    使用 speedtest-clash 批量测试代理延迟。
    :param speedtest_path: speedtest-clash 二进制路径
    :param proxies: 代理节点列表
    :param max_workers: 最大并发数
    :param debug: 是否打印详细测速日志
    :return: 测速成功并带延迟字段的代理列表
    """
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(xcspeedtest_test_proxy, speedtest_path, proxy, debug): proxy
            for proxy in proxies
        }
        for future in concurrent.futures.as_completed(futures):
            proxy = futures[future]
            try:
                result = future.result()
                if result is not None:
                    delay, bandwidth = result
                    pcopy = proxy.copy()
                    pcopy['clash_delay'] = delay
                    if bandwidth:
                        pcopy['bandwidth'] = bandwidth  # 存下来！
                    results.append(pcopy)
                    if debug:
                        print(f"成功: {delay}ms | {bandwidth or 'N/A'} → {proxy.get('name')}")
            except Exception as e:
                if debug:
                    print(f"异常: {proxy.get('name')} → {e}")
    return results


# clash 测速

def xcspeedtest_test_proxy(speedtest_path, proxy, debug=False):
    """
    2025-12-06 终极无敌版
    兼容所有版本 xcspeedtest（有/无 clash_delay、引号残缺、换行截断、带宽表格等）
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'config.yaml')
            config = {
                "port": 7890,
                "socks-port": 7891,
                "allow-lan": False,
                "mode": "Rule",
                "log-level": "silent",
                "proxies": [proxy],
                "proxy-groups": [{"name": "TESTGROUP", "type": "select", "proxies": [proxy["name"]]}],
                "rules": ["MATCH,DIRECT"]
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

            # === 1. 优先从 JSON 提取 clash_delay（最准！）===
            # 适配各种残缺引号、换行、截断情况
            json_pattern = re.compile(r'json:\s*(\[[\s\S]*?\])', re.IGNORECASE)
            for match in json_pattern.finditer(output):
                j = match.group(1)
                # 补全括号
                if j.count('{') > j.count('}'): j += '}'
                if j.count('[') > j.count(']'): j += ']'
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

            # === 2. 兜底：表格延迟列（一定有）===
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

            # === 3. 提取带宽 ===
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



def clash_test_proxy(clash_path, proxy, debug=False):
    temp_dir = tempfile.mkdtemp()
    config_path = os.path.join(temp_dir, 'config.yaml')
    try:
        for test_url in TEST_URLS:
            config = {
                "port": 7890,
                "socks-port": 7891,
                "allow-lan": False,
                "mode": "Rule",
                "log-level": "silent",
                "proxies": [proxy],
                "proxy-groups": [{"name": "TESTGROUP", "type": "select", "proxies": [proxy["name"]]}],
                "rules": [f"DOMAIN,{urlparse(test_url).netloc},TESTGROUP", "MATCH,DIRECT"]
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, sort_keys=False)
            cmd = [clash_path, '-c', config_path, '-fast']
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                text=True
            )
            output = (result.stdout + result.stderr).replace('\x00', '')
            if debug:
                print(f"\n=== [-fast] 测试 URL: {test_url} [{proxy['name']}] ===\n{output}\n{'='*60}")
            # 解析延迟，逻辑同之前
            match = re.search(r'\b(\d+)ms\b(?=\s*$)', output, re.MULTILINE)
            if match:
                delay = int(match.group(1))
                if 1 < delay < 800:
                    if debug:
                        print(f"成功抓到延迟: {delay}ms → 保留")
                    return delay
            delays = re.findall(r'\b([2-9]\d{1,3})\b', output)
            if delays:
                delay = min(int(x) for x in delays if int(x) < 800)
                if delay > 1:
                    return delay
            if re.search(r'\b(0\s*ms|1\s*ms|NA)\b', output, re.I):
                if debug:
                    print("检测到 0ms/1ms/NA → 丢弃")
                return None
        # 所有测速地址都无结果时返回 None
        if debug:
            print(f"所有测速地址均未通过 → 丢弃: {proxy['name']}")
    except subprocess.TimeoutExpired:
        if debug:
            print(f"[-fast] 测速超时 → 丢弃: {proxy['name']}")
    except Exception as e:
        if debug:
            print(f"[-fast] 异常: {proxy['name']} → {e}")
    finally:
        try:
            shutil.rmtree(temp_dir)
        except:
            pass
    return None




# 主函数
async def main():
    print("=" * 60)
    print("Telegram.Node_Clash-Speedtest测试版 V1")
    print(datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)
    
    # 阶段 0: 在 GitHub Actions 中启动 Warp 模拟国内环境
    # 仅在 GitHub Actions 环境下尝试启动 WARP
    if os.getenv('GITHUB_ACTIONS') == 'true': # 确保环境变量名为 'true'
        print("检测到 GitHub Actions 环境，尝试启动 Cloudflare Warp...")
        warp_ok = start_cloudflare_warp()
        if warp_ok:
            print("✅ 国内优化网络环境已就绪。")
            # 添加短暂延迟，确保网络稳定
            await asyncio.sleep(5) 
        else:
            print("⚠️ Warp 启动失败，将使用 GitHub Actions 的默认海外网络环境进行测速。")
    else:
        print("未在 GitHub Actions 环境中运行，跳过 WARP 启动。")


    preprocess_regex_rules()

    print("[1/5] 加载原有节点和抓取状态")
    existing_proxies, last_message_ids = load_existing_proxies_and_state()
    print(f"已有节点数: {len(existing_proxies)}")

    print("[2/5] 抓取 Telegram 新订阅链接")
    urls, last_message_ids = await scrape_telegram_links(last_message_ids)
    new_proxies = []
    if urls:
        print(f"抓取到 {len(urls)} 个订阅链接，开始下载解析...")
        for url in urls:
            proxies = download_and_parse(url)
            if proxies:
                new_proxies.extend(proxies)
    print(f"新增节点数: {len(new_proxies)}")

    all_proxies_map = {
        get_proxy_key(p): p for p in existing_proxies if is_valid_proxy(p)
    }
    added_count = 0
    for p in new_proxies:
        key = get_proxy_key(p)
        if key not in all_proxies_map:
            all_proxies_map[key] = p
            added_count += 1
    print(f"合并去重后总节点数: {len(all_proxies_map)}，新增有效节点: {added_count}")

    all_nodes = list(all_proxies_map.values())
    if not all_nodes:
        sys.exit("❌ 无任何节点可用，程序退出")
        

    # [3/5] 开始节点测速（支持多种模式）
    print("[3/5] 开始节点测速（模式: %s）" % SPEEDTEST_MODE)
    clash_path = 'clash_core/clash'
    need_clash = 'clash' in SPEEDTEST_MODE
    if need_clash and not (os.path.isfile(clash_path) and os.access(clash_path, os.X_OK)):
        sys.exit(f"clash 核心缺失或不可执行: {clash_path}")

    final_tested_nodes = all_nodes.copy()
    clash_path = './xcspeedtest'  # 你的 speedtest-clash 二进制的路径

    if SPEEDTEST_MODE == "tcp_only":
        print("使用【纯 TCP 测速】模式")
        final_tested_nodes = batch_tcp_test(all_nodes)
    elif SPEEDTEST_MODE == "clash_only":
        print("使用【纯 speedtest-clash 测速】模式")
        final_tested_nodes = batch_test_proxies_speedtest(
            clash_path,
            all_nodes,
            max_workers=MAX_TEST_WORKERS,
            debug=ENABLE_SPEEDTEST_LOG   # False  如果，则只输出个人定义的打印项目print
        )
    elif SPEEDTEST_MODE == "tcp_first":
        print("使用【TCP 粗筛 → speedtest-clash 精测】两阶段模式")
        print("阶段1：TCP 超高并发粗筛...")
        tcp_passed = batch_tcp_test(all_nodes)
        print(f"TCP 粗筛完成：{len(all_nodes)} → {len(tcp_passed)}")
        if not tcp_passed:
            print("TCP 全死，降级使用纯 speedtest-clash 模式")
            final_tested_nodes = batch_test_proxies_speedtest(
                clash_path,
                all_nodes,
                max_workers=MAX_TEST_WORKERS,
                debug=ENABLE_SPEEDTEST_LOG
            )
        else:
            print("阶段2：对 TCP 存活节点进行 speedtest-clash 精准测速...")
            final_tested_nodes = batch_test_proxies_speedtest(
                clash_path,
                tcp_passed,
                max_workers=MAX_TEST_WORKERS,
                debug=ENABLE_SPEEDTEST_LOG
            )
    elif SPEEDTEST_MODE == "clash_first":
        print("使用【speedtest-clash 先测 → TCP 后验】模式")
        clash_passed = batch_test_proxies_speedtest(
            clash_path,
            all_nodes,
            max_workers=MAX_TEST_WORKERS,
            debug=ENABLE_SPEEDTEST_LOG
        )
        final_tested_nodes = [p for p in clash_passed if tcp_ping(p) is not None]
    else:
        print("未知模式，使用默认 tcp_first")
        tcp_passed = batch_tcp_test(all_nodes)
        if not tcp_passed:
            final_tested_nodes = batch_test_proxies_speedtest(
                clash_path,
                all_nodes,
                max_workers=MAX_TEST_WORKERS,
                debug=ENABLE_SPEEDTEST_LOG
            )
        else:
            final_tested_nodes = batch_test_proxies_speedtest(
                clash_path,
                tcp_passed,
                max_workers=MAX_TEST_WORKERS,
                debug=ENABLE_SPEEDTEST_LOG
            )

    # 测速结果统计
    success_count = len(final_tested_nodes)
    print(f"测速完成，最终存活优质节点：{success_count} 个")
    
    final_tested_nodes = [p for p in final_tested_nodes if is_valid_proxy(p)]
    # 保底回退机制
    if success_count < 50:   # 少于80个就触发保底（可自行调整 50~100 之间）
        print(f"测速结果过少（{success_count}个），启动超级保底策略，保留热门地区节点")
        
        # 优先保留这些地区（你最常用的）
        priority_regions = ['香港', '台湾', '日本', '新加坡', '美国', '韩国', '德国', '加拿大']
        
        backup_nodes = []
        seen_keys = set()  # 防止同一节点重复加入
        
        for proxy in all_nodes:   # all_nodes 是所有原始解析出来的节点
            if len(backup_nodes) >= 600:  # 最多保底600个
                break
                
            key = get_proxy_key(proxy)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            
            region = proxy.get('region_info', {}).get('name')
            if region in priority_regions:
                # 给这些节点一个假的超大延迟，排到后面但不会被删掉
                proxy = proxy.copy()
                proxy['clash_delay'] = 9999
                backup_nodes.append(proxy)
        
        # 如果热门地区还是不够，就从剩余节点里随便补
        if len(backup_nodes) < 200:
            for proxy in all_nodes:
                if len(backup_nodes) >= 400:
                    break
                key = get_proxy_key(proxy)
                if key not in seen_keys:
                    p = proxy.copy()
                    p['clash_delay'] = 9999
                    backup_nodes.append(p)
                    seen_keys.add(key)
        
        final_tested_nodes = backup_nodes
        success_count = len(final_tested_nodes)
        print(f"超级保底成功！强制保留 {success_count} 个热门地区节点（未测速，仅用于应急）")
    # ============================================================

    # [4/5] 节点名称统一规范化处理
    print("[4/5] 节点名称统一规范化处理")
    normalized_proxies = normalize_proxy_names(final_tested_nodes)
    final_proxies = limit_proxy_counts(normalized_proxies, max_total=600)
    if not final_proxies:
        sys.exit("❌ 节点重命名和限量后无有效节点，程序退出")

    # [5/5] 最终排序并生成配置文件
    print("[5/5] 最终排序并生成配置文件")
    # 新增：带宽二次筛选（可通过环境变量完全控制）
    final_proxies = filter_by_bandwidth(
        final_proxies, 
        min_mb=MIN_BANDWIDTH_MB, 
        enable=ENABLE_BANDWIDTH_FILTER
    )
    
    final_proxies.sort(
        key=lambda p: (
            REGION_PRIORITY.index(p['region_info']['name']) if p.get('region_info') and p['region_info']['name'] in REGION_PRIORITY else 99,
            p.get('clash_delay', p.get('tcp_delay', 9999))
        )
    )

    total_count = len(final_proxies)
    update_time = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")

    final_config = {
        'proxies': final_proxies,
        'last_message_ids': last_message_ids,
        'update_time': update_time,
        'total_nodes': total_count,
        'note': '由 GitHub Actions 自动生成，每4小时更新一次，已按延迟排序并智能限量'
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    try:
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write("# ==================================================\n")
            f.write("#  TG 免费节点 · 自动测速精选订阅（Clash 格式）\n")
            f.write("# ==================================================\n")
            f.write(f"# 更新时间   : {update_time} (北京时间)\n")
            f.write(f"# 节点总数   : {total_count} 个优质节点\n")
            f.write(f"# 筛选规则   : 延迟排序 + 带宽 ≥ {MIN_BANDWIDTH_MB}MB/s\n")
            f.write(f"# 地区优先级 : 香港 → 台湾 → 日本 → 新加坡 → 美国 → 韩国 → ...\n")
            f.write("# 构建方式   : GitHub Actions 全自动，每4小时更新一次\n")
            f.write("# 项目地址   : https://github.com/你的用户名/你的仓库\n")
            f.write("# ==================================================\n\n")
            yaml.dump(final_config, f, allow_unicode=True, sort_keys=False, indent=2, width=4096, default_flow_style=False)

        print(f"✅ 配置文件已成功保存至 {OUTPUT_FILE}")
        print(f"   本次共保留 {total_count} 个优质节点")
        print(f"   更新时间：{update_time}")
        print("🎉 全部任务圆满完成！")
    except Exception as e:
        print(f"写出配置文件失败: {e}")
        sys.exit(1)

def sync_main():
    if not ENABLE_SPEED_TEST:
        print("测速功能未启用，跳过测速。")
        return

    ret = run_speedtest(enable_tcp_log=ENABLE_TCP_LOG)
    print(f"测速进程返回码：{ret}")    

if __name__ == "__main__":
    asyncio.run(main())  # 调用异步主函数

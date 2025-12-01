# 文件名: TelegramNode/telegram_publiclink.py
# -*- coding: utf-8 -*-
# ============================================================================
# Clash 订阅自动生成脚本 V1.R3
#
# 版本历史:
# V1.R1 (20251130) - 初始版本
# V1.R2 (20251201) - 增加多种下载方式，优先使用 wget
# V1.R3 (20251202) - 支持解析Base64编码，可以处理其他文本格式
# ============================================================================
import os
import re
import asyncio
import yaml
import base64
import json
import time
import requests  # 引入 requests 库
from datetime import datetime, timedelta, timezone
import sys
from collections import defaultdict
import socket
import concurrent.futures
import hashlib
import subprocess
import shutil
# --- Telethon ---
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaWebPage
from telethon.sessions import StringSession

# =================================================================================
# Part 1: 配置
# =================================================================================
API_ID = os.environ.get('TELEGRAM_API_ID')
API_HASH = os.environ.get('TELEGRAM_API_HASH')
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS')
TIME_WINDOW_HOURS = 72
MIN_EXPIRE_HOURS = 7
OUTPUT_FILE = 'flclashyaml/telegram_scraper.yaml'
ENABLE_SPEED_TEST = True
SOCKET_TIMEOUT = 8
MAX_TEST_WORKERS = 128
TEST_URL = 'http://www.gstatic.com/generate_204'
TEST_INTERVAL = 300

# ========== 地区过滤配置 ==========
ALLOWED_REGIONS = {'香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国',
                   '印度', '菲律宾', '印度尼西亚', '越南', '美国', '加拿大', '法国',
                   '英国', '德国', '俄罗斯', '意大利', '巴西', '阿根廷', '土耳其', '澳大利亚'}

# ========== 排序优先级配置 ==========
REGION_PRIORITY = ['香港', '台湾', '日本', '新加坡', '韩国', '马来西亚', '泰国', '印度', '菲律宾',
                   '印度尼西亚', '越南', '美国', '加拿大', '法国', '英国', '德国', '俄罗斯', '意大利',
                   '巴西', '阿根廷', '土耳其', '澳大利亚']

# ========== 国家/地区映射表 ==========
CHINESE_COUNTRY_MAP = {
    'HK': '香港', 'TW': '台湾', 'JP': '日本', 'SG': '新加坡', 'KR': '韩国', 'MY': '马来西亚',
    'TH': '泰国', 'IN': '印度', 'PH': '菲律宾', 'ID': '印度尼西亚', 'VN': '越南', 'US': '美国',
    'CA': '加拿大', 'FR': '法国', 'GB': '英国', 'DE': '德国', 'RU': '俄罗斯', 'IT': '意大利',
    'BR': '巴西', 'AR': '阿根廷', 'TR': '土耳其', 'AU': '澳大利亚'
}

# ========== 地区识别正则规则 ==========
CUSTOM_REGEX_RULES = {
    '香港': {'code': 'HK', 'pattern': r'香港|港|HK|Hong\s*Kong'},
    '台湾': {'code': 'TW', 'pattern': r'台湾|台|TW|Taiwan'},
    '日本': {'code': 'JP', 'pattern': r'日本|日|JP|Japan'},
    '新加坡': {'code': 'SG', 'pattern': r'新加坡|SG|Singapore'},
    '韩国': {'code': 'KR', 'pattern': r'韩国|南朝鲜|KR|Korea'},
    '马来西亚': {'code': 'MY', 'pattern': r'马来西亚|MY|Malaysia'},
    '泰国': {'code': 'TH', 'pattern': r'泰国|TH|Thailand'},
    '印度': {'code': 'IN', 'pattern': r'印度|IN|India'},
    '菲律宾': {'code': 'PH', 'pattern': r'菲律宾|PH|Philippines'},
    '印度尼西亚': {'code': 'ID', 'pattern': r'印度尼西亚|印尼|ID|Indonesia'},
    '越南': {'code': 'VN', 'pattern': r'越南|VN|Vietnam'},
    '美国': {'code': 'US', 'pattern': r'美国|US|USA|United States'},
    '加拿大': {'code': 'CA', 'pattern': r'加拿大|CA|Canada'},
    '法国': {'code': 'FR', 'pattern': r'法国|FR|France'},
    '英国': {'code': 'GB', 'pattern': r'英国|GB|UK|United Kingdom'},
    '德国': {'code': 'DE', 'pattern': r'德国|DE|Germany'},
    '俄罗斯': {'code': 'RU', 'pattern': r'俄罗斯|RU|Russia'},
    '意大利': {'code': 'IT', 'pattern': r'意大利|IT|Italy'},
    '巴西': {'code': 'BR', 'pattern': r'巴西|BR|Brazil'},
    '阿根廷': {'code': 'AR', 'pattern': r'阿根廷|AR|Argentina'},
    '土耳其': {'code': 'TR', 'pattern': r'土耳其|TR|Turkey'},
    '澳大利亚': {'code': 'AU', 'pattern': r'澳大利亚|AU|Australia'},
}

JUNK_PATTERNS = re.compile(r"(?:专线|IPLC|体验|官网|倍率|x\d[\.\d]*|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)", re.IGNORECASE)
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')

# =================================================================================
# Part 2: 函数定义
# =================================================================================
def parse_expire_time(text):
    """解析消息中的到期时间"""
    match = re.search(r'到期时间[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', text)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            return None
    return None

def is_expire_time_valid(expire_time):
    """检查订阅链接是否在有效期内"""
    if expire_time is None:
        return True
    hours_remaining = (expire_time - datetime.now(timezone(timedelta(hours=8)))).total_seconds() / 3600
    if hours_remaining < MIN_EXPIRE_HOURS:
        print(f"  ❌ 已跳过: 链接剩余时间 ({hours_remaining:.1f} 小时) 少于最低要求 ({MIN_EXPIRE_HOURS} 小时)")
        return False
    return True

async def scrape_telegram_links():
    """从 Telegram 频道抓取订阅链接"""
    if not all([API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS_STR]):
        print("❌ 错误: 缺少必要的环境变量 (API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS)。")
        return []

    TARGET_CHANNELS = [line.strip() for line in TELEGRAM_CHANNEL_IDS_STR.split('\n') if line.strip() and not line.strip().startswith('#')]
    
    if not TARGET_CHANNELS:
        print("❌ 错误: TELEGRAM_CHANNEL_IDS 中未找到有效频道 ID。")
        return []

    print(f"▶️ 配置抓取 {len(TARGET_CHANNELS)} 个频道: {TARGET_CHANNELS}")

    try:
        client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        print(f"✅ 以 {me.first_name} (@{me.username}) 的身份成功连接")
    except Exception as e:
        print(f"❌ 错误: 连接 Telegram 时出错: {e}")
        return []

    target_time = datetime.now(timezone.utc) - timedelta(hours=TIME_WINDOW_HOURS)
    all_links = set()

    for channel_id in TARGET_CHANNELS:
        print(f"\n--- 正在处理频道: {channel_id} ---")
        try:
            async for message in client.iter_messages(await client.get_entity(channel_id), limit=500):
                if message.date < target_time:
                    break
                if message.text and is_expire_time_valid(parse_expire_time(message.text)):
                    for url in re.findall(r'订阅链接[:：]\s*`]*\s*(https?://[^\s<>"*`]+)', message.text):
                        cleaned_url = url.strip().strip('.,*`')
                        if cleaned_url:
                            all_links.add(cleaned_url)
                            print(f"  ✅ 找到链接: {cleaned_url[:70]}...")
        except Exception as e:
            print(f"❌ 错误: 从频道 '{channel_id}' 获取消息时出错: {e}")

    await client.disconnect()
    print(f"\n✅ 抓取完成, 共找到 {len(all_links)} 个不重复的有效链接。")
    return list(all_links)

def preprocess_regex_rules():
    """预处理正则规则：按长度排序以优化匹配效率"""
    for region in CUSTOM_REGEX_RULES:
        CUSTOM_REGEX_RULES[region]['pattern'] = '|'.join(
            sorted(CUSTOM_REGEX_RULES[region]['pattern'].split('|'), key=len, reverse=True)
        )

def get_country_flag_emoji(code):
    """根据国家代码生成旗帜 Emoji"""
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in code) if code and len(code) == 2 else "❓"

def attempt_download_using_wget(url):
    """使用 wget 下载订阅链接"""
    print(f"  ⬇️ 正在使用 wget 下载: {url[:80]}...")
    if not shutil.which("wget"):
        print("  ✗ 错误: wget 未安装，无法执行下载。")
        return None
    try:
        content = subprocess.run(
            ["wget", "-O", "-", "--timeout=30", "--header=User-Agent: Clash", url],
            capture_output=True, text=True, check=True
        ).stdout
        return content if content else None
    except subprocess.CalledProcessError as e:
        print(f"  ✗ wget 下载失败: {e}")
        return None

def attempt_download_using_requests(url):
    """使用 requests 下载订阅链接"""
    print(f"  ⬇️ 正在使用 requests 下载: {url[:80]}...")
    try:
        headers = {'User-Agent': 'Clash'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"  ✗ requests 下载失败: {e}")
        return None

def parse_proxies_from_content(content):
    """从下载的内容中解析代理节点"""
    try:
        # 尝试解析 YAML 内容
        proxies = yaml.safe_load(content)
        if isinstance(proxies, dict):
            return proxies.get('proxies', [])
        elif isinstance(proxies, list):
            return proxies  # 如果 content 是一个直接的代理列表
        else:
            print(f"警告: 解析的内容不是有效的 proxies 格式: {content[:100]}")
            return []
    except yaml.YAMLError as e:
        print(f"YAML 解析错误: {e}")
        return []
    except Exception as e:
        print(f"解析内容时其他错误: {e}")
        return []

def is_base64(string):
    """检查字符串是否是 Base64 编码"""
    try:
        if isinstance(string, str):
            base64.b64decode(string, validate=True)
            return True
    except Exception:
        return False
    return False

def decode_base64_and_parse(base64_str):
    """解码 Base64 并解析为 Clash 格式的节点"""
    try:
        decoded_content = base64.b64decode(base64_str).decode('utf-8')
        proxies = []
        
        for line in decoded_content.splitlines():
            line = line.strip()
            if line.startswith('vless://') or line.startswith('vmess://'):
                proxies.append(parse_vmess_node(line))
            elif line.startswith('ssr://'):
                proxies.append(parse_ssr_node(line))
            elif line.startswith('ss://'):
                proxies.append(parse_ss_node(line))
            else:
                print(f"警告: 未支持的节点格式: {line[:100]}")
        
        return proxies
    except Exception as e:
        print(f"解码 Base64 并解析时出错: {e}")
        return []

def parse_ssr_node(node_str):
    """解析 SSR 节点字符串并转换为 Clash 格式"""
    try:
        decoded = base64.urlsafe_b64decode(node_str[5:]).decode('utf-8')
        params = decoded.split(':')
        cipher = params[0]
        password = params[1]
        host = params[2]
        port = params[3]
        obfs = params[4]  # 可选字段
        protocol = params[5]  # 可选字段
        # 组装 Clash 节点格式
        proxy = {
            "name": f"SSR {host}:{port}",
            "type": "ssr",
            "server": host,
            "port": int(port),
            "password": password,
            "cipher": cipher,
            "obfs": obfs,  # 根据SSR配置取值
            "protocol": protocol,  # 根据SSR配置取值
        }
        return proxy
    except Exception as e:
        print(f"解析 SSR 节点时发生错误: {e}")
        return {}

def parse_vmess_node(node_str):
    """解析 Vmess 节点字符串并转换为 Clash 格式"""
    try:
        decoded = base64.urlsafe_b64decode(node_str[8:]).decode('utf-8')
        json_data = json.loads(decoded)

        # 组装 Clash 节点格式
        proxy = {
            "name": json_data.get('ps', f"Vmess {json_data.get('add')}:{json_data.get('port')}"),
            "type": "vmess",
            "server": json_data.get('add'),
            "port": int(json_data.get('port')),
            "uuid": json_data.get('id'),
            "alterId": json_data.get('aid'),
            "cipher": json_data.get('net', "none"),
            "tls": (json_data.get('tls') == "tls"),
        }
        return proxy
    except Exception as e:
        print(f"解析 Vmess 节点时发生错误: {e}")
        return {}

def download_subscription(url):
    """下载并解析订阅链接，优先使用 wget，失败后尝试 requests"""
    content = attempt_download_using_wget(url)
    
    if content is None:
        content = attempt_download_using_requests(url)

    if content is None:
        print(f"  ❌ 两种下载方式均失败，跳过链接: {url}")
        return []

    print(f"  下载内容长度: {len(content)}, 内容示例: {content[:100]}")  # 添加调试输出

    # 判断内容是否为 Base64 编码
    if is_base64(content):
        return decode_base64_and_parse(content)

    return parse_proxies_from_content(content)

def get_proxy_key(p):
    """生成代理节点的唯一标识"""
    return hashlib.md5(
        f"{p.get('server','')}:{p.get('port',0)}|{p.get('uuid') or p.get('password') or ''}".encode()
    ).hexdigest()

def is_valid_proxy(proxy):
    """验证代理节点的协议格式和有效性"""
    required_keys = ['name', 'server', 'port', 'type']
    if not all(key in proxy for key in required_keys):
        return False

    # 进一步检查协议类型
    allowed_types = {'http', 'socks5', 'trojan', 'v2ray', 'ss', 'vmess', 'ssr'}
    if 'type' in proxy and proxy['type'] not in allowed_types:
        return False

    # 确保端口范围在有效范围内
    if not (1 <= proxy['port'] <= 65535):
        return False

    return True

def process_proxies(proxies):
    """过滤、验证、识别地区并重命名节点"""
    identified = []
    for p in proxies:
        if not is_valid_proxy(p):
            print(f"  ❌ 无效节点被过滤: {p.get('name', '未知')}")
            continue

        name = JUNK_PATTERNS.sub('', FLAG_EMOJI_PATTERN.sub('', p.get('name', ''))).strip()
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            name = re.sub(r'\b' + re.escape(eng) + r'\b', chn, name, flags=re.IGNORECASE)
        
        for r_name, rules in CUSTOM_REGEX_RULES.items():
            if re.search(rules['pattern'], name, re.IGNORECASE) and r_name in ALLOWED_REGIONS:
                p['region_info'] = {'name': r_name, 'code': rules['code']}
                identified.append(p)
                break

    print(f"  - 节点过滤: 原始 {len(proxies)} -> 识别并保留 {len(identified)}")
    final, counters = [], defaultdict(lambda: defaultdict(int))
    master_pattern = re.compile(
        '|'.join(sorted([p for r in CUSTOM_REGEX_RULES.values() for p in r['pattern'].split('|')], key=len, reverse=True)),
        re.IGNORECASE
    )

    for p in identified:
        info = p['region_info']
        match = FLAG_EMOJI_PATTERN.search(p['name'])
        if match:
            flag = match.group(0)
        else:
            flag = get_country_flag_emoji(info['code'])

        feature = re.sub(r'\s+', ' ', master_pattern.sub(' ', FLAG_EMOJI_PATTERN.sub('', p['name'], 1)).replace('-', ' ')).strip() or f"{sum(1 for fp in final if fp['region_info']['name'] == info['name']) + 1:02d}"
        new_name = f"{flag} {info['name']} {feature}".strip()
        counters[info['name']][new_name] += 1
        if counters[info['name']][new_name] > 1:
            new_name += f" {counters[info['name']][new_name]}"
        
        p['name'] = new_name
        final.append(p)

    return final

def test_single_proxy_tcp(proxy):
    """使用 TCP 连接测速（兼容所有协议）"""
    try:
        start = time.time()
        sock = socket.create_connection(
            (proxy['server'], proxy['port']),
            timeout=SOCKET_TIMEOUT
        )
        sock.close()
        proxy['delay'] = int((time.time() - start) * 1000)
        return proxy
    except Exception:
        return None

def generate_config(proxies):
    """生成 Clash 配置文件"""
    if not proxies:
        return None
    
    names = [p['name'] for p in proxies]
    clean = [{k: v for k, v in p.items() if k not in ['region_info', 'delay']} for p in proxies]
    
    groups = [
        {
            'name': '🚀 节点选择',
            'type': 'select',
            'proxies': ['♻️ 自动选择', '🔯 故障转移', 'DIRECT'] + names,
            'url': TEST_URL,
            'interval': TEST_INTERVAL
        },
        {
            'name': '♻️ 自动选择',
            'type': 'url-test',
            'proxies': names,
            'url': TEST_URL,
            'interval': TEST_INTERVAL,
            'tolerance': 50,
            'lazy': True
        },
        {
            'name': '🔯 故障转移',
            'type': 'fallback',
            'proxies': names,
            'url': TEST_URL,
            'interval': TEST_INTERVAL,
            'lazy': True
        }
    ]

    return {
        'mixed-port': 7890,
        'allow-lan': True,
        'mode': 'rule',
        'log-level': 'info',
        'external-controller': '127.0.0.1:9090',
        'dns': {
            'enable': True,
            'listen': '0.0.0.0:53',
            'enhanced-mode': 'fake-ip',
            'fake-ip-range': '198.18.0.1/16',
            'nameserver': ['223.5.5.5', '119.29.29.29'],
            'fallback': ['https://dns.google/dns-query', 'https://1.1.1.1/dns-query']
        },
        'proxies': clean,
        'proxy-groups': groups,
        'rules': ['GEOIP,CN,DIRECT', 'MATCH,🚀 节点选择']
    }

async def main():
    """主函数"""
    print("=" * 60 + f"\nClash 订阅自动生成脚本 V1.R3 @ {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S %Z')}\n" + "=" * 60)
    preprocess_regex_rules()
    print("\n[1/4] 从 Telegram 抓取、下载并合并节点...")
    
    urls = await scrape_telegram_links()
    
    if not urls:
        sys.exit("\n❌ 未找到任何有效订阅链接，脚本终止。")
    
    proxies = {get_proxy_key(p): p for url in urls for p in download_subscription(url) if p}
    
    if not proxies:
        sys.exit("\n❌ 下载和解析后，无有效节点，脚本终止。")
    
    print(f"✅ 合并去重后共 {len(proxies)} 个节点。")
    print("\n[2/4] 过滤与重命名节点...")
    
    processed = process_proxies(list(proxies.values()))
    
    if not processed:
        sys.exit("\n❌ 过滤后无任何可用节点，脚本终止。")
    
    print("\n[3/4] TCP 测速与最终排序...")
    final = processed
    
    if ENABLE_SPEED_TEST:
        print(f"  - 开始 TCP 连接测速（超时: {SOCKET_TIMEOUT}秒）...")
        
        with concurrent.futures.ThreadPoolExecutor(MAX_TEST_WORKERS) as executor:
            tested = list(executor.map(test_single_proxy_tcp, processed))
        
        final = [p for p in tested if p]
        print(f"  - 测速完成, {len(final)} / {len(processed)} 个节点可用。")
        
        if not final:
            print("\n  ⚠️ 警告: 测速后无可用节点，将使用所有过滤后的节点。")
            final = processed
    
    final.sort(key=lambda p: (REGION_PRIORITY.index(p['region_info']['name']), p.get('delay', 9999)))
    print(f"✅ 最终处理完成 {len(final)} 个节点。")
    print("\n[4/4] 生成最终配置文件...")
    
    config = generate_config(final)
    
    if not config:
        sys.exit("\n❌ 无法生成配置文件。")
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2)
    
    print(f"✅ 配置文件已成功保存至: {OUTPUT_FILE}\n\n🎉 任务全部完成！")

if __name__ == '__main__':
    asyncio.run(main())

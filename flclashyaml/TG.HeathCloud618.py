#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康中心618 - Clash 订阅合并脚本
- 改用内置的 socket 库进行延迟测试，无任何外部依赖，终极稳定
- 按延迟和地区优先级精确排序
- 智能识别地区 (正则 + 详尽中文名映射)，匹配对应国旗
"""
import requests
import yaml
import base64
import time
from datetime import datetime
import sys
import os
import re
from collections import defaultdict
import socket
import concurrent.futures
import hashlib

# ========== 基础配置 ==========
SUBSCRIPTION_URLS = [
    "https://pastecode.dev/raw/ki7zml2s/健康中心618pro",
    "https://pastecode.dev/raw/hntbocnp/健康中心618ord",
    # 您可以在这里添加更多的订阅链接
    # "https://your.another.subscription/url",
]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "TG.HeathCloud618.yaml")

# ========== 测速过滤配置 (纯 Python socket 版) ==========
ENABLE_SPEED_TEST = True
# socket 连接超时时间(秒)
SOCKET_TIMEOUT = 2
# 并发测速的线程数
MAX_TEST_WORKERS = 256 # socket 非常轻量，可以大幅增加并发数以提高速度，默认128

# ========== 排序与命名配置 ==========
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国', '加拿大', '澳大利亚']
CHINESE_COUNTRY_MAP = {'US':'美国','United States':'美国','USA':'美国','JP':'日本','Japan':'日本','HK':'香港','Hong Kong':'香港','SG':'狮城','Singapore':'狮城','TW':'湾省','Taiwan':'湾省','KR':'韩国','Korea':'韩国','KOR':'韩国','DE':'德国','Germany':'德国','GB':'英国','United Kingdom':'英国','UK':'英国','CA':'加拿大','Canada':'加拿大','AU':'澳大利亚','Australia':'澳大利亚',}
COUNTRY_NAME_TO_CODE_MAP = {"阿富汗":"AF", "阿尔巴尼亚":"AL", "阿尔及利亚":"DZ", "安道尔":"AD", "安哥拉":"AO", "安圭拉":"AI", "安提瓜和巴布达":"AG", "阿根廷":"AR", "亚美尼亚":"AM", "阿鲁巴":"AW", "澳大利亚":"AU", "奥地利":"AT", "阿塞拜疆":"AZ", "巴哈马":"BS", "巴林":"BH", "孟加拉国":"BD", "巴巴多斯":"BB", "白俄罗斯":"BY", "比利时":"BE", "伯利兹":"BZ", "贝宁":"BJ", "百慕大":"BM", "不丹":"BT", "玻利维亚":"BO", "波黑":"BA", "博茨瓦那":"BW", "巴西":"BR", "文莱":"BN", "保加利亚":"BG", "布基纳法索":"BF", "布隆迪":"BI", "柬埔寨":"KH", "喀麦隆":"CM", "加拿大":"CA", "佛得角":"CV", "开曼群岛":"KY", "中非":"CF", "乍得":"TD", "智利":"CL", "中国":"CN", "哥伦比亚":"CO", "科摩罗":"KM", "刚果（金）":"CD", "刚果（布）":"CG", "哥斯达黎加":"CR", "科特迪瓦":"CI", "克罗地亚":"HR", "古巴":"CU", "塞浦路斯":"CY", "捷克":"CZ", "丹麦":"DK", "吉布提":"DJ", "多米尼克":"DM", "多米尼加":"DO", "厄瓜多尔":"EC", "埃及":"EG", "萨尔瓦多":"SV", "赤道几内亚":"GQ", "厄立特里亚":"ER", "爱沙尼亚":"EE", "埃塞俄比亚":"ET", "斐济":"FJ", "芬兰":"FI", "法国":"FR", "加蓬":"GA", "冈比亚":"GM", "格鲁吉亚":"GE", "加纳":"GH", "希腊":"GR", "格林纳达":"GD", "危地马拉":"GT", "几内亚":"GN", "几内亚比绍":"GW", "圭亚那":"GY", "海地":"HT", "洪都拉斯":"HN", "匈牙利":"HU", "冰岛":"IS", "印度":"IN", "印尼":"ID", "印度尼西亚":"ID", "伊朗":"IR", "伊拉克":"IQ", "爱尔兰":"IE", "以色列":"IL", "意大利":"IT", "牙买加":"JM", "日本":"JP", "约旦":"JO", "哈萨克斯坦":"KZ", "肯尼亚":"KE", "基里巴斯":"KI", "科威特":"KW", "吉尔吉斯斯坦":"KG", "老挝":"LA", "拉脱维亚":"LV", "黎巴嫩":"LB", "莱索托":"LS", "利比里亚":"LR", "利比亚":"LY", "列支敦士登":"LI", "立陶宛":"LT", "卢森堡":"LU", "澳门":"MO", "北马其顿":"MK", "马达加斯加":"MG", "马拉维":"MW", "马来西亚":"MY", "马尔代夫":"MV", "马里":"ML", "马耳他":"MT", "马绍尔群岛":"MH", "毛里塔尼亚":"MR", "毛里求斯":"MU", "墨西哥":"MX", "密克罗尼西亚":"FM", "摩尔多瓦":"MD", "摩纳哥":"MC", "蒙古":"MN", "黑山":"ME", "摩洛哥":"MA", "莫桑比克":"MZ", "缅甸":"MM", "纳米比亚":"NA", "瑙鲁":"NR", "尼泊尔":"NP", "荷兰":"NL", "新西兰":"NZ", "尼加拉瓜":"NI", "尼日尔":"NE", "尼日利亚":"NG", "挪威":"NO", "阿曼":"OM", "巴基斯坦":"PK", "帕劳":"PW", "巴勒斯坦":"PS", "巴拿马":"PA", "巴布亚新几内亚":"PG", "巴拉圭":"PY", "秘鲁":"PE", "菲律宾":"PH", "波兰":"PL", "葡萄牙":"PT", "卡塔尔":"QA", "罗马尼亚":"RO", "俄罗斯":"RU", "卢旺达":"RW", "圣马力诺":"SM", "沙特阿拉伯":"SA", "塞内加尔":"SN", "塞尔维亚":"RS", "塞舌尔":"SC", "塞拉利昂":"SL", "新加坡":"SG", "斯洛伐克":"SK", "斯洛文尼亚":"SI", "所罗门群岛":"SB", "索马里":"SO", "南非":"ZA", "西班牙":"ES", "斯里兰卡":"LK", "苏丹":"SD", "苏里南":"SR", "瑞典":"SE", "瑞士":"CH", "叙利亚":"SY", "塔吉克斯坦":"TJ", "坦桑尼亚":"TZ", "泰国":"TH", "东帝汶":"TL", "多哥":"TG", "汤加":"TO", "特立尼达和多巴哥":"TT", "突尼斯":"TN", "土耳其":"TR", "土库曼斯坦":"TM", "图瓦卢":"TV", "乌干达":"UG", "乌克兰":"UA", "阿联酋":"AE", "乌拉圭":"UY", "乌兹别克斯坦":"UZ", "瓦努阿图":"VU", "委内瑞拉":"VE", "越南":"VN", "也门":"YE", "赞比亚":"ZM", "津巴布韦":"ZW"}
JUNK_PATTERNS = re.compile(r'丑团|专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|'r'[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量', re.IGNORECASE)
CUSTOM_REGEX_RULES = {
    '香港':{'code':'HK','pattern':r'港|HK|Hong Kong'},
    '日本':{'code':'JP','pattern':r'日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan'},
    '狮城':{'code':'SG','pattern':r'新加坡|SG|Singapore|坡|狮城'},
    '美国':{'code': 'US','pattern':r'美国|美|波特兰|达拉斯|Oregon|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥'},
    '湾省':{'code':'TW','pattern':r'台湾|湾省|TW|Taiwan|台|新北|彰化'},
    '韩国':{'code':'KR','pattern':r'韩国|韩|KR|Korea|KOR|首尔|韓'},
    '德国':{'code':'DE','pattern':r'德国|DE|Germany'},
    '英国':{'code':'GB','pattern':r'UK|GB|United Kingdom|England|英|英国'},
    '加拿大':{'code':'CA','pattern':r'CA|Canada|加拿大|枫叶|多伦多|温哥华|蒙特利尔'},
    '澳大利亚':{'code':'AU','pattern':r'AU|Australia|澳大利亚|澳洲|悉尼'},
}

# ========== 核心功能函数 ==========
def get_country_flag_emoji(country_code):
    """根据国家代码获取国旗 Emoji"""
    if not country_code or len(country_code) != 2: return "❓"
    return "".join(chr(0x1F1E6 + ord(char.upper()) - ord('A')) for char in country_code)

def download_subscription(url):
    """
    下载并解析订阅内容。
    增加了更通用的User-Agent和Referer，以应对某些网站对非浏览器访问的限制。
    """
    try:
        # 使用更通用的浏览器 User-Agent 和 Referer
        # Referer 应该指向 pastecode.dev 的某个页面，模拟从那里点击“raw”链接
        # 这里使用 pastecode.dev 的主页作为 Referer，如果不行，可能需要更精确的页面
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
            'Referer': 'https://pastecode.dev/'
        }
        print(f"  > 尝试下载: {url[:60]}...")
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status() # 检查HTTP响应状态码，如果不是200会抛出HTTPError

        content = response.text
        
        # 尝试直接解析 YAML
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict) and 'proxies' in data:
                print(f"  ✓ 成功下载并解析 {url[:60]}... 为 YAML")
                return data['proxies']
        except yaml.YAMLError:
            # 如果不是直接的 YAML，尝试 Base64 解码
            try:
                decoded_content = base64.b64decode(content).decode('utf-8')
                data = yaml.safe_load(decoded_content)
                if isinstance(data, dict) and 'proxies' in data:
                    print(f"  ✓ 成功下载并解析 {url[:60]}... (Base64 解码后为 YAML)")
                    return data['proxies']
            except Exception as e_decode:
                # print(f"  ✗ Base64 解码或解析 {url[:60]}... 失败: {e_decode}") # 不打印太多内部错误
                pass # 忽略解码或解析错误，尝试下一个
        
        print(f"  ✗ {url[:60]}... 内容既不是直接 YAML 也不是 Base64 编码的 YAML。")

    except requests.exceptions.RequestException as e:
        print(f"  ✗ 下载 {url[:60]}... 失败 (请求错误): {e}")
    except Exception as e:
        print(f"  ✗ 下载或解析 {url[:60]}... 失败 (未知错误): {e}")
    return []

def get_proxy_key(proxy):
    """生成代理的唯一标识符，用于去重"""
    try:
        # 综合服务器地址、端口、密码或UUID生成哈希
        return hashlib.md5(f"{proxy.get('server','')}:{proxy.get('port',0)}|{proxy.get('password','') or proxy.get('uuid','')} ".encode('utf-8')).hexdigest()
    except Exception as e:
        print(f"  ⚠️ 警告: 生成代理 key 失败: {e}, 代理信息: {proxy.get('name', '未知')}")
        return None

def merge_and_deduplicate_proxies(subscriptions_proxies):
    """合并多个订阅源的代理并去重"""
    unique_proxies = {}
    for proxy in subscriptions_proxies:
        if not isinstance(proxy, dict) or 'name' not in proxy:
            # print(f"  ⚠️ 警告: 跳过无效代理格式: {proxy}")
            continue
        proxy_key = get_proxy_key(proxy)
        if proxy_key and proxy_key not in unique_proxies:
            unique_proxies[proxy_key] = proxy
    return list(unique_proxies.values())

def process_and_rename_proxies(proxies):
    """
    处理代理，识别地区并生成新的命名。
    此函数分为两步，先识别地区，再重命名。
    """
    # 第一步：识别地区
    for p in proxies:
        # 清理原始名称中的垃圾信息，并进行中英文地区名称替换
        temp_name = JUNK_PATTERNS.sub('', p.get('name','')).strip()
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            temp_name = re.sub(r'\b'+re.escape(eng)+r'\b', chn, temp_name, flags=re.IGNORECASE)

        p['region'] = '未知'
        # 优先使用 CUSTOM_REGEX_RULES 识别
        for region, rules in CUSTOM_REGEX_RULES.items():
            if re.search(rules['pattern'], temp_name, re.IGNORECASE):
                p['region'] = region
                break
        
        # 如果 CUSTOM_REGEX_RULES 未匹配，尝试 COUNTRY_NAME_TO_CODE_MAP
        if p['region'] == '未知':
            for country, code in COUNTRY_NAME_TO_CODE_MAP.items():
                if country in temp_name:
                    p['region'] = country
                    break
    
    # 第二步：生成新的命名
    country_counters = defaultdict(lambda: defaultdict(int)) # 用于按地区和名称计数，避免相同命名
    final_proxies = [] # 存储最终处理后的代理

    # 预先计算所有代理的特征字符串，用于排序前命名
    for proxy in proxies:
        region_info = {'name': proxy['region']}
        # 获取国家代码
        region_info['code'] = COUNTRY_NAME_TO_CODE_MAP.get(proxy['region'])
        if not region_info['code']:
            region_info['code'] = CUSTOM_REGEX_RULES.get(proxy['region'], {}).get('code', '')
        
        flag = get_country_flag_emoji(region_info['code'])
        
        # 清理节点特征部分
        node_feature = JUNK_PATTERNS.sub('', proxy.get('name','')).strip()
        # 再次进行中英文地区名称替换
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            node_feature = re.sub(r'\b'+re.escape(eng)+r'\b', chn, node_feature, flags=re.IGNORECASE)

        # 移除已识别的地区模式，避免重复
        if region_info['name'] != '未知':
            pattern_to_remove = CUSTOM_REGEX_RULES.get(region_info['name'], {}).get('pattern', region_info['name'])
            node_feature = re.sub(pattern_to_remove, '', node_feature, flags=re.IGNORECASE)
        
        node_feature = node_feature.replace('-', '').strip()

        # 如果特征为空，则使用序号
        if not node_feature:
             # 这里只是一个占位符，实际的序号会在最终生成名称时确定
             # 为了避免提前计数对排序造成影响，先给一个通用的表示
             node_feature = "节点" 

        # 暂存新的名称草稿
        proxy['_new_name_draft'] = f"{flag} {region_info['name']} {node_feature}"
        final_proxies.append(proxy)
    
    # 对 final_proxies 列表进行排序 (排序逻辑在 main 函数中完成)
    # 排序完成后，再进行最终命名，确保序号正确
    
    # 实际的重命名过程，确保排序后的序号是正确的
    for proxy in final_proxies:
        draft_name = proxy['_new_name_draft']
        region_name = proxy['region']

        country_counters[region_name][draft_name] += 1
        count = country_counters[region_name][draft_name]

        if "节点" in draft_name: # 如果是默认的“节点”特征，替换为序号
             # 找到最后一个数字，如果存在，则替换它，否则添加
             if count > 1:
                 # 替换末尾的“节点”为带序号的“节点01”或“节点02”
                 # 或者如果本身已经有数字，直接替换
                 proxy['name'] = re.sub(r'节点(\d+)?$', f'节点{count:02d}', draft_name)
             else:
                 # 第一次出现，使用“节点01”或直接“节点”
                 proxy['name'] = draft_name.replace('节点', f'节点{count:02d}') if count > 1 or '节点' in draft_name else draft_name

        elif count > 1: # 如果不是“节点”，但有重复，则添加序号
            proxy['name'] = f"{draft_name} {count}"
        else:
            proxy['name'] = draft_name
        
        # 移除临时的草稿字段
        if '_new_name_draft' in proxy:
            del proxy['_new_name_draft']

    return final_proxies

# --- 新的、纯 Python 的 socket 测速函数 ---
def test_single_proxy_socket(proxy):
    """使用 socket 测试单个节点的 TCP 延迟"""
    server = proxy.get('server')
    port = proxy.get('port')
    
    if not server or not port:
        # print(f"  ⚠️ 警告: 代理 {proxy.get('name', '未知')} 缺少服务器或端口信息，跳过测速。")
        return None
    
    # 某些代理类型可能不适合直接TCP连接测试，例如relay/loadbalance
    # 但由于Clash代理通常是直连或转发，所以这里先不特别处理
    
    sock = None
    try:
        # 创建一个 TCP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 设置超时
        sock.settimeout(SOCKET_TIMEOUT)
        
        # 记录开始时间
        start_time = time.time()
        
        # 尝试连接
        sock.connect((str(server), int(port)))
        
        # 记录结束时间
        end_time = time.time()
        
        # 计算延迟（毫秒）
        delay = (end_time - start_time) * 1000
        proxy['delay'] = int(delay)
        return proxy
    except (socket.timeout, ConnectionRefusedError, socket.gaierror, OSError) as e:
        # print(f"  ✗ 代理 {proxy.get('name', '未知')} ({server}:{port}) 测速失败: {

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
import subprocess
import shutil

# ========== 基础配置 ==========
# SUBSCRIPTION_URLS 将通过从 URL.TXT 文件加载来动态填充
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
URL_FILE = os.path.join(SCRIPT_DIR, "URL.TXT") # 定义 URL.TXT 文件的路径
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "TG.HeathCloud618.yaml")
# 获取当前脚本的文件名（不含扩展名），用于匹配 URL.TXT 中的名称
CURRENT_SCRIPT_NAME = os.path.splitext(os.path.basename(__file__))[0]
print(f"当前脚本文件名 (不含扩展名): {CURRENT_SCRIPT_NAME}")
# ========== 测速过滤配置 (纯 Python socket 版) ==========
ENABLE_SPEED_TEST = False #  False为不测速，Ture为测速
# socket 连接超时时间(秒)
SOCKET_TIMEOUT = 3
# 并发测速的线程数
MAX_TEST_WORKERS = 256 # socket 非常轻量，可以大幅增加并发数以提高速度，默认128
# (命名与排序配置保持不变)
# ========== 排序与命名配置 ==========
REGION_PRIORITY = ['香港', '日本', '狮城', '美国', '湾省', '韩国', '德国', '英国', '加拿大', '澳大利亚']
CHINESE_COUNTRY_MAP = {'US':'美国','United States':'美国','USA':'美国','JP':'日本','Japan':'日本','HK':'香港','Hong Kong':'香港','SG':'狮城','Singapore':'狮城','TW':'湾省','Taiwan':'湾省','KR':'韩国','Korea':'韩国','KOR':'韩国','DE':'德国','Germany':'德国','GB':'英国','United Kingdom':'英国','UK':'英国','CA':'加拿大','Canada':'加拿大','AU':'澳大利亚','Australia':'澳大利亚',}
COUNTRY_NAME_TO_CODE_MAP = {"阿富汗":"AF", "阿尔巴尼亚":"AL", "阿尔及利亚":"DZ", "安道尔":"AD", "安哥拉":"AO", "安圭拉":"AI", "安提瓜和巴布达":"AG", "阿根廷":"AR", "亚美尼亚":"AM", "阿鲁巴":"AW", "澳大利亚":"AU", "奥地利":"AT", "阿塞拜疆":"AZ", "巴哈马":"BS", "巴林":"BH", "孟加拉国":"BD", "巴巴多斯":"BB", "白俄罗斯":"BY", "比利时":"BE", "伯利兹":"BZ", "贝宁":"BJ", "百慕大":"BM", "不丹":"BT", "玻利维亚":"BO", "波黑":"BA", "博茨瓦纳":"BW", "巴西":"BR", "文莱":"BN", "保加利亚":"BG", "布基纳法索":"BF", "布隆迪":"BI", "柬埔寨":"KH", "喀麦隆":"CM", "加拿大":"CA", "佛得角":"CV", "开曼群岛":"KY", "中非":"CF", "乍得":"TD", "智利":"CL", "中国":"CN", "哥伦比亚":"CO", "科摩罗":"KM", "刚果（金）":"CD", "刚果（布）":"CG", "哥斯达黎加":"CR", "科特迪瓦":"CI", "克罗地亚":"HR", "古巴":"CU", "塞浦路斯":"CY", "捷克":"CZ", "丹麦":"DK", "吉布提":"DJ", "多米尼克":"DM", "多米尼加":"DO", "厄瓜多尔":"EC", "埃及":"EG", "萨尔瓦多":"SV", "赤道几内亚":"GQ", "厄立特里亚":"ER", "爱沙尼亚":"EE", "埃塞俄比亚":"ET", "斐济":"FJ", "芬兰":"FI", "法国":"FR", "加蓬":"GA", "冈比亚":"GM", "格鲁吉亚":"GE", "加纳":"GH", "希腊":"GR", "格林纳达":"GD", "危地马拉":"GT", "几内亚":"GN", "几内亚比绍":"GW", "圭亚那":"GY", "海地":"HT", "洪都拉斯":"HN", "匈牙利":"HU", "冰岛":"IS", "印度":"IN", "印尼":"ID", "印度尼西亚":"ID", "伊朗":"IR", "伊拉克":"IQ", "爱尔兰":"IE", "以色列":"IL", "意大利":"IT", "牙买加":"JM", "日本":"JP", "约旦":"JO", "哈萨克斯坦":"KZ", "肯尼亚":"KE", "基里巴斯":"KI", "科威特":"KW", "吉尔吉斯斯坦":"KG", "老挝":"LA", "拉脱维亚":"LV", "黎巴嫩":"LB", "莱索托":"LS", "利比里亚":"LR", "利比亚":"LY", "列支敦士登":"LI", "立陶宛":"LT", "卢森堡":"LU", "澳门":"MO", "北马其顿":"MK", "马达加斯加":"MG", "马拉维":"MW", "马来西亚":"MY", "马尔代夫":"MV", "马里":"ML", "马耳他":"MT", "马绍尔群岛":"MH", "毛里塔尼亚":"MR", "毛里求斯":"MU", "墨西哥":"MX", "密克罗尼西亚":"FM", "摩尔多瓦":"MD", "摩纳哥":"MC", "蒙古":"MN", "黑山":"ME", "摩洛哥":"MA", "莫桑比克":"MZ", "缅甸":"MM", "纳米比亚":"NA", "瑙鲁":"NR", "尼泊尔":"NP", "荷兰":"NL", "新西兰":"NZ", "尼加拉瓜":"NI", "尼日尔":"NE", "尼日利亚":"NG", "挪威":"NO", "阿曼":"OM", "巴基斯坦":"PK", "帕劳":"PW", "巴勒斯坦":"PS", "巴拿马":"PA", "巴布亚新几内亚":"PG", "巴拉圭":"PY", "秘鲁":"PE", "菲律宾":"PH", "波兰":"PL", "葡萄牙":"PT", "卡塔尔":"QA", "罗马尼亚":"RO", "俄罗斯":"RU", "卢旺达":"RW", "圣马力诺":"SM", "沙特阿拉伯":"SA", "塞内加尔":"SN", "塞尔维亚":"RS", "塞舌尔":"SC", "塞拉利昂":"SL", "新加坡":"SG", "斯洛伐克":"SK", "斯洛文尼亚":"SI", "所罗门群岛":"SB", "索马里":"SO", "南非":"ZA", "西班牙":"ES", "斯里兰卡":"LK", "苏丹":"SD", "苏里南":"SR", "瑞典":"SE", "瑞士":"CH", "叙利亚":"SY", "塔吉克斯坦":"TJ", "坦桑尼亚":"TZ", "泰国":"TH", "东帝汶":"TL", "多哥":"TG", "汤加":"TO", "特立尼达和多巴哥":"TT", "突尼斯":"TN", "土耳其":"TR", "土库曼斯坦":"TM", "图瓦卢":"TV", "乌干达":"UG", "乌克兰":"UA", "阿联酋":"AE", "乌拉圭":"UY", "乌兹别克斯坦":"UZ", "瓦努阿图":"VU", "委内瑞拉":"VE", "越南":"VN", "也门":"YE", "赞比亚":"ZM", "津巴布韦":"ZW"}
JUNK_PATTERNS = re.compile(r"(?:专线|IPLC|IEPL|BGP|体验|官网|倍率|x\d[\.\d]*|Rate|[\[\(【「].*?[\]\)】」]|^\s*@\w+\s*|Relay|流量)|(?:(?:[\u2460-\u2473\u2776-\u277F\u2780-\u2789]|免費|回家).*?(?=,|$))", re.IGNORECASE)
CUSTOM_REGEX_RULES = {'香港':{'code':'HK','pattern':r'港|HK|Hong Kong|HKBN|HGC|PCCW|WTT'},'日本':{'code':'JP','pattern':r'日本|川日|东京|大阪|泉日|沪日|深日|JP|Japan'},'狮城':{'code':'SG','pattern':r'新加坡|SG|Singapore|坡|狮城'},'美国':{'code': 'US','pattern':r'美国|美|波特兰|达拉斯|Oregon|凤凰城|硅谷|拉斯维加斯|洛杉矶|圣何塞|西雅图|芝加哥'},'湾省':{'code':'TW','pattern':r'台湾|湾省|TW|Taiwan|台|新北|彰化'},'韩国':{'code':'KR','pattern':r'韩国|韩|KR|Korea|KOR|首尔|韓'},'德国':{'code':'DE','pattern':r'德国|DE|Germany'},'英国':{'code':'GB','pattern':r'UK|GB|United Kingdom|England|英|英国'},'加拿大':{'code':'CA','pattern':r'CA|Canada|加拿大|枫叶|多伦多|温哥华|蒙特利尔'},'澳大利亚':{'code':'AU','pattern':r'AU|Australia|澳大利亚|澳洲|悉尼'},}
# ===== 国旗表情正则表达式 =====
# 匹配任意两个区域指示符符号（即国旗表情）
FLAG_EMOJI_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')

# ========== 核心功能函数 ==========
def get_country_flag_emoji(country_code):
    if not country_code or len(country_code) != 2: return "❓"
    return "".join(chr(0x1F1E6 + ord(char.upper()) - ord('A')) for char in country_code)

def download_subscription(url):
    """
    尝试使用 wget 获取订阅链接内容，模拟 Clash 请求头。
    """
    content = None
    # 检查 wget 是否可用
    if not shutil.which("wget"):
        print("  ✗ 错误: wget 未安装或不在系统 PATH 中。无法使用 wget 下载订阅。")
        return []
    print(f"  ⬇️ 尝试使用 wget 下载 {url[:60]} (模拟Clash请求头)")
    try:
        # 构建 wget 命令，并添加 --header 参数
        wget_command = [
            "wget",
            "-O", "-",
            "--timeout=30",
            "--header=User-Agent: Clash/1.11.4 (Windows; x64)", # 模拟 Clash User-Agent
            "--header=Accept: application/yaml",                # 模拟 Clash Accept 头
            url
        ]
        process = subprocess.run(
            wget_command,
            capture_output=True,
            text=True, # 将 stdout/stderr 解码为文本
            check=True # 如果命令返回非零退出代码，则抛出 CalledProcessError 异常
        )
        content = process.stdout
    except subprocess.CalledProcessError as e:
        print(f"  ✗ wget 下载 {url[:60]}... 失败 (错误码: {e.returncode}). 错误输出: {e.stderr.strip()}")
        return []
    except Exception as e:
        print(f"  ✗ wget 下载 {url[:60]}... 时发生未知错误: {e}")
        return []
    if not content:
        print(f"  ✗ {url[:60]}... 下载内容为空。")
        return []
    # 解析下载的内容（这部分逻辑与原始脚本保持一致）
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict) and 'proxies' in data:
            return data['proxies']
    except yaml.YAMLError:
        # 如果不是直接的 YAML，尝试进行 base64 解码
        try:
            decoded_content = base64.b64decode(content).decode('utf-8')
            data = yaml.safe_load(decoded_content)
            if isinstance(data, dict) and 'proxies' in data:
                return data['proxies']
        except Exception:
            # 如果两者都失败，打印特定消息并返回空列表
            print(f"  ✗ {url[:60]}... 解析为 YAML 或 Base64 解码后解析为 YAML 失败。")
            return []
    return []

def get_proxy_key(proxy):
    try:
        identifier = f"{proxy.get('server','')}:{proxy.get('port',0)}|"
        if 'uuid' in proxy:
            identifier += proxy['uuid']
        elif 'password' in proxy:
            identifier += proxy['password']
        else:
            identifier += proxy.get('name', '')
        return hashlib.md5(identifier.encode('utf-8')).hexdigest()
    except Exception:
        return None

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

    # 1. 构建一个全面的、用于剥离的地区/国家名称模式列表
    all_region_patterns_for_stripping = set()

    # 1.1 添加 CUSTOM_REGEX_RULES 中的所有模式
    for rules in CUSTOM_REGEX_RULES.values():
        all_region_patterns_for_stripping.add(rules['pattern'])
    
    # 1.2 添加 CHINESE_COUNTRY_MAP 中的所有英文键 (例如 'US', 'United States')，需要转义
    for eng_name in CHINESE_COUNTRY_MAP.keys():
        all_region_patterns_for_stripping.add(re.escape(eng_name))

    # 1.3 添加 CHINESE_COUNTRY_MAP 中的所有中文值 (例如 '美国', '香港')，需要转义
    for chn_name in CHINESE_COUNTRY_MAP.values():
        all_region_patterns_for_stripping.add(re.escape(chn_name))
        
    # 1.4 添加 COUNTRY_NAME_TO_CODE_MAP 中的所有中文国家名 (键)，需要转义
    for country_name in COUNTRY_NAME_TO_CODE_MAP.keys():
        all_region_patterns_for_stripping.add(re.escape(country_name))

    # 将集合转换回列表，并按长度降序排序，确保长模式先匹配，避免短模式干扰
    all_region_patterns_for_stripping_list = sorted(list(all_region_patterns_for_stripping), key=len, reverse=True)


    # 第一遍循环：识别地区并存储在 'region' 字段中
    for p in proxies:
        original_name = p.get('name', '')
        
        temp_name_for_region_detection = FLAG_EMOJI_PATTERN.sub('', original_name)
        temp_name_for_region_detection = JUNK_PATTERNS.sub('', temp_name_for_region_detection).strip()
        
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            temp_name_for_region_detection = re.sub(r'\b'+re.escape(eng)+r'\b', chn, temp_name_for_region_detection, flags=re.IGNORECASE)
        
        p['region'] = '未知'
        
        for region_name, rules in CUSTOM_REGEX_RULES.items():
            if re.search(rules['pattern'], temp_name_for_region_detection, re.IGNORECASE):
                p['region'] = region_name
                break
        
        if p['region'] == '未知':
            for country_chn_name, country_code in COUNTRY_NAME_TO_CODE_MAP.items():
                if re.search(r'\b' + re.escape(country_chn_name) + r'\b', temp_name_for_region_detection, re.IGNORECASE):
                    p['region'] = country_chn_name 
                    break

    # 第二遍循环：重命名节点，条件性添加国旗，并处理重复
    for proxy in proxies:
        original_name = proxy.get('name', '')
        
        region_info = {'name': proxy['region'], 'code': COUNTRY_NAME_TO_CODE_MAP.get(proxy['region'])}
        if not region_info['code']:
            region_info['code'] = CUSTOM_REGEX_RULES.get(region_info['name'], {}).get('code', '')
        
        chosen_flag = ""
        name_for_feature_extraction = original_name
        match_existing_flag = FLAG_EMOJI_PATTERN.search(original_name)
        if match_existing_flag:
            chosen_flag = match_existing_flag.group(0)
            name_for_feature_extraction = FLAG_EMOJI_PATTERN.sub('', original_name, 1)
        else:
            chosen_flag = get_country_flag_emoji(region_info['code'])
        
        # --- 核心改进: node_feature 提取逻辑 ---
        node_feature = name_for_feature_extraction # 例如: "香港aws①ˣ³𝕋𝔾myFreeNodeChat"

        # 1. 统一将英文国家名替换为中文，以便后续清理能统一处理
        for eng, chn in CHINESE_COUNTRY_MAP.items():
            node_feature = re.sub(r'\b'+re.escape(eng)+r'\b', chn, node_feature, flags=re.IGNORECASE)

        # 2. **最优先** 从 node_feature 中移除 *已识别的主要地区名称本身*
        #    例如，如果识别为 "香港"，就从字符串中移除所有 "香港" 的字面出现。
        #    使用词边界确保只移除完整的词语。
        if region_info['name'] != '未知':
            node_feature = re.sub(r'\b' + re.escape(region_info['name']) + r'\b', ' ', node_feature, flags=re.IGNORECASE)
            
            # 同时移除 CUSTOM_REGEX_RULES 中与该主要地区相关的模式，以防未被字面移除覆盖
            primary_region_pattern = CUSTOM_REGEX_RULES.get(region_info['name'], {}).get('pattern')
            if primary_region_pattern:
                node_feature = re.sub(primary_region_pattern, ' ', node_feature, flags=re.IGNORECASE)

        # 3. 接着移除所有其他已知的地区/国家名称模式（包括其别名、英文名等），防止其他国家名或地区别名残余
        for pattern_to_clean in all_region_patterns_for_stripping_list:
            try:
                re.compile(pattern_to_clean) 
                node_feature = re.sub(pattern_to_clean, ' ', node_feature, flags=re.IGNORECASE)
            except re.error:
                node_feature = re.sub(r'\b' + pattern_to_clean + r'\b', ' ', node_feature, flags=re.IGNORECASE)
        
        # 4. 移除垃圾信息
        node_feature = JUNK_PATTERNS.sub(' ', node_feature).strip()

        # 5. 清理可能的连字符和多余空格
        node_feature = re.sub(r'\s+', ' ', node_feature).strip()
        node_feature = node_feature.replace('-', ' ').strip()
        
        # 如果节点特征仍为空，则使用序号
        if not node_feature:
             seq = sum(1 for p_final in final_proxies if p_final.get('region') == region_info['name']) + 1
             node_feature = f"{seq:02d}"
        
        # 构建最终的新名称
        new_name = f"{chosen_flag} {region_info['name']} {node_feature}".strip()
        
        # 处理同地区内名称重复，添加计数后缀
        country_counters[region_info['name']][new_name] += 1
        count = country_counters[region_info['name']][new_name]
        if count > 1:
            new_name = f"{new_name} {count}"
        
        proxy['name'] = new_name
        final_proxies.append(proxy)
    return final_proxies

# --- 新的、纯 Python 的 socket 测速函数 ---
def test_single_proxy_socket(proxy):
    """使用 socket 测试单个节点的 TCP 延迟"""
    server = proxy.get('server')
    port = proxy.get('port')
    if not server or not port:
        return None
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
    except (socket.timeout, ConnectionRefusedError, socket.gaierror, OSError):
        # 捕获各种可能的连接错误
        return None
    finally:
        # 确保 socket 被关闭
        if 'sock' in locals():
            sock.close()

def speed_test_proxies(proxies):
    """并发执行 socket 测速"""
    print(f"开始使用纯 Python socket 进行并发测速 (共 {len(proxies)} 个节点)...")
    fast_proxies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TEST_WORKERS) as executor:
        future_to_proxy = {executor.submit(test_single_proxy_socket, p): p for p in proxies}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_proxy)):
            result = future.result()
            sys.stdout.write(f"\r  测试进度: {i+1}/{len(proxies)}")
            sys.stdout.flush()
            if result:
                fast_proxies.append(result)
    print(f"\n测速完成，剩余可用节点: {len(fast_proxies)}")
    return fast_proxies

def generate_config(proxies):
    if not proxies: return None
    proxy_names = [p['name'] for p in proxies]
    clean_proxies = [{k: v for k, v in p.items() if k not in ['region', 'delay']} for p in proxies]
    return {'mixed-port':7890,'allow-lan':True,'bind-address':'*','mode':'rule','log-level':'info','external-controller':'127.0.0.1:9090','dns':{'enable':True,'listen':'0.0.0.0:53','enhanced-mode':'fake-ip','fake-ip-range':'198.18.0.1/16','nameserver':['223.5.5.5','119.29.29.29'],'fallback':['https://dns.google/dns-query','https://1.1.1.1/dns-query']},'proxies':clean_proxies,'proxy-groups':[{'name':'🚀 节点选择','type':'select','proxies':['♻️ 自动选择','🔯 故障转移','DIRECT']+proxy_names},{'name':'♻️ 自动选择','type':'url-test','proxies':proxy_names,'url':'http://www.gstatic.com/generate_204','interval':300},{'name':'🔯 故障转移','type':'fallback','proxies':proxy_names,'url':'http://www.gstatic.com/generate_204','interval':300}],'rules':['GEOIP,CN,DIRECT','MATCH,🚀 节点选择']}

def load_subscription_urls_from_file(url_file_path, script_name_filter):
    """
    从指定路径的 URL.TXT 文件中读取订阅地址。
    文件格式为：# 名称 \n 名称 ：地址
    仅读取名称中包含 script_name_filter 的地址。
    """
    urls = []
    if not os.path.exists(url_file_path):
        print(f"错误: 订阅文件 {url_file_path} 不存在。请确保该文件与脚本在同一目录下。")
        return urls
    print(f"正在从 {url_file_path} 读取订阅地址，并过滤名称包含 '{script_name_filter}' 的条目...")
    try:
        with open(url_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                match = re.search(r'([^：]+)：\s*(https?://\S+)', line)
                if match:
                    name_from_file = match.group(1).strip()
                    url = match.group(2)
                    if script_name_filter in name_from_file:
                        urls.append(url)
                        print(f"  ✓ 找到并匹配到订阅: '{name_from_file}' -> {url[:60]}...")
                    else:
                        print(f"  - 跳过不匹配的订阅 (名称 '{name_from_file}' 不包含 '{script_name_filter}'): {line[:60]}...")
                else:
                    print(f"  ✗ 跳过无法识别的行 (不符合 '名称：地址' 格式): {line[:60]}...")
    except Exception as e:
        print(f"读取订阅文件 {url_file_path} 时发生错误: {e}")
    return urls

def main():
    print("=" * 60)
    print(f"健康中心618 - Clash 订阅合并 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    subscription_urls_from_file = load_subscription_urls_from_file(URL_FILE, CURRENT_SCRIPT_NAME)
    if not subscription_urls_from_file:
        sys.exit(f"\n❌ 错误: 未能从 {URL_FILE} 文件中读取到任何匹配 '{CURRENT_SCRIPT_NAME}' 的有效订阅地址。请检查文件内容和格式。")
    print("\n[1/4] 下载与合并订阅...")
    all_proxies = []
    for url in subscription_urls_from_file:
        all_proxies.extend(download_subscription(url))
    unique_proxies = merge_and_deduplicate_proxies(all_proxies)
    if not unique_proxies: sys.exit("\n❌ 错误: 所有订阅下载失败或合并后无节点。")
    print(f"  ✓ 合并后共 {len(unique_proxies)} 个不重复节点。")
    print("\n[2/4] 测速与筛选节点...")
    if ENABLE_SPEED_TEST:
        available_proxies = speed_test_proxies(unique_proxies)
        if not available_proxies:
            print("\n  ⚠️ 警告: 测速后无可用节点，将使用所有节点生成配置。")
            available_proxies = unique_proxies
    else:
        print("  - 已跳过延迟测试。")
        available_proxies = unique_proxies
    print("\n[3/4] 排序与重命名节点...")
    region_order = {region: i for i, region in enumerate(REGION_PRIORITY)}
    available_proxies.sort(key=lambda p: (region_order.get(p.get('region', '未知'), 99), p.get('delay', 9999)))
    final_proxies = process_and_rename_proxies(available_proxies)
    print(f"\n  ✓ 共 {len(final_proxies)} 个节点完成排序和重命名。")
    print("\n[4/4] 生成最终配置文件...")
    config = generate_config(final_proxies)
    if not config: sys.exit("\n❌ 错误: 无法生成配置文件。")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, indent=2)
    print(f"\n  ✓ 配置文件已成功保存至: {OUTPUT_FILE}")
    print("\n✅ 任务完成！")

if __name__ == '__main__':
    main()

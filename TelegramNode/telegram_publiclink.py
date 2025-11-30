import os
import re
from datetime import datetime, timedelta, timezone
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaWebPage
import asyncio
from telethon.sessions import StringSession

# 从环境变量获取配置
API_ID = int(os.environ.get('TELEGRAM_API_ID'))
API_HASH = os.environ.get('TELEGRAM_API_HASH')
STRING_SESSION = os.environ.get('TELEGRAM_STRING_SESSION')
# 获取所有频道/群组ID的字符串，由换行符分隔
TELEGRAM_CHANNEL_IDS_STR = os.environ.get('TELEGRAM_CHANNEL_IDS')
OUTPUT_FILE = 'flclashyaml/telegram_publiclink.txt'  # 输出文件路径
TIME_WINDOW_HOURS = 48  # 过去48小时内的消息
LINK_PREFIX = "telegram_publiclink："  # 链接前缀，注意是中文冒号
MIN_EXPIRE_HOURS = 7  # 最小剩余时间（小时）

def parse_expire_time(text):
    """
    从消息文本中提取到期时间
    格式：📅到期时间: 2025-11-29 21:51:40
    """
    expire_pattern = r'到期时间[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'
    match = re.search(expire_pattern, text)
    if match:
        try:
            # 解析时间字符串（假设为北京时间）
            expire_time_str = match.group(1)
            expire_time = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')
            # 北京时间是 UTC+8
            beijing_offset = timezone(timedelta(hours=8))
            expire_time = expire_time.replace(tzinfo=beijing_offset)
            return expire_time
        except Exception as e:
            print(f"  ⚠️ Failed to parse expire time: {e}")
            return None
    return None

def is_expire_time_valid(expire_time):
    """
    检查到期时间是否距离当前北京时间至少6小时
    """
    if expire_time is None:
        return True  # 如果无法解析到期时间，默认允许提取
    
    # 获取当前北京时间
    beijing_offset = timezone(timedelta(hours=8))
    now_beijing = datetime.now(beijing_offset)
    
    # 计算时间差
    time_diff = expire_time - now_beijing
    hours_remaining = time_diff.total_seconds() / 3600
    
    print(f"  ⏰ Expire time: {expire_time.strftime('%Y-%m-%d %H:%M:%S')} Beijing Time")
    print(f"  ⏱️ Hours remaining: {hours_remaining:.1f} hours")
    
    if hours_remaining < MIN_EXPIRE_HOURS:
        print(f"  ❌ Skipped: Less than {MIN_EXPIRE_HOURS} hours until expiration")
        return False
    
    return True

async def main():
    # 检查基本配置是否存在
    if not all([API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS_STR]):
        print("Error: Missing one or more required environment variables (API_ID, API_HASH, STRING_SESSION, TELEGRAM_CHANNEL_IDS).")
        print("Please check your GitHub Secrets and the TELEGRAM_CHANNEL_IDS in your workflow file.")
        return
    
    # 改进的频道ID解析逻辑
    TARGET_CHANNELS = []
    for line in TELEGRAM_CHANNEL_IDS_STR.split('\n'):
        clean_line = line.split('#', 1)[0].strip()
        if clean_line:
            TARGET_CHANNELS.append(clean_line)
    
    if not TARGET_CHANNELS:
        print("Error: No valid Telegram channel IDs found in TELEGRAM_CHANNEL_IDS environment variable after cleaning.")
        return
    
    print(f"Configured to scrape {len(TARGET_CHANNELS)} channels/groups: {TARGET_CHANNELS}")
    
    # 初始化 Telethon 客户端，使用 StringSession
    session_obj = StringSession(STRING_SESSION)
    client = TelegramClient(session_obj, API_ID, API_HASH)
    
    print("Connecting to Telegram...")
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("Client not authorized. Please check TELEGRAM_STRING_SESSION secret or regenerate it locally.")
            return
        me = await client.get_me()
        print(f"Connected as {me.first_name} {me.last_name or ''} (@{me.username or ''})")
    except Exception as e:
        print(f"Error connecting to Telegram: {e}")
        return
    
    target_time = datetime.now(timezone.utc) - timedelta(hours=TIME_WINDOW_HOURS)
    all_links = set()  # 使用集合存储链接以自动去重
    skipped_count = 0  # 统计跳过的链接数量
    
    # 遍历每个目标频道
    for current_channel_identifier in TARGET_CHANNELS:
        print(f"\n--- Processing channel: {current_channel_identifier} (posted after {target_time} UTC) ---")
        try:
            entity = await client.get_entity(current_channel_identifier)
            async for message in client.iter_messages(entity, limit=500):
                if message.date < target_time:
                    print(f"  Reached messages older than {TIME_WINDOW_HOURS} hours for {current_channel_identifier}. Stopping.")
                    break
                
                # 只提取消息文本中 "订阅链接:" 后面的 URL
                if message.text:
                    # 先检查到期时间
                    expire_time = parse_expire_time(message.text)
                    
                    if not is_expire_time_valid(expire_time):
                        skipped_count += 1
                        continue
                    
                    # 使用正则表达式匹配 "订阅链接:" 后面的 URL（支持中英文冒号）
                    subscription_pattern = r'订阅链接[:：]\s*[\*`]*\s*(https?://[^\s<>"*`]+)'
                    matches = re.findall(subscription_pattern, message.text)
                    for url in matches:
                        # 清理 URL：去除末尾的标点符号和反引号
                        url = url.strip().strip('.,*`')
                        if url:
                            all_links.add(url)
                            print(f"  ✅ Found valid subscription link: {url}")
                
                # 提取消息媒体（例如网页预览）中的 URL - 只在是订阅链接的情况下
                if message.media and \
                   isinstance(message.media, MessageMediaWebPage) and \
                   hasattr(message.media, 'web_page') and \
                   hasattr(message.media.web_page, 'url') and \
                   message.media.web_page.url:
                    # 检查消息文本是否包含 "订阅链接:"
                    if message.text and '订阅链接' in message.text:
                        expire_time = parse_expire_time(message.text)
                        if is_expire_time_valid(expire_time):
                            url = message.media.web_page.url.strip().strip('.,*`')
                            all_links.add(url)
                            print(f"  ✅ Found valid subscription link from media: {url}")
                        else:
                            skipped_count += 1
                        
        except Exception as e:
            print(f"Error fetching messages from channel '{current_channel_identifier}': {e}")
    
    # 断开 Telegram 连接
    await client.disconnect()
    print("Disconnected from Telegram.")
    
    # 确保输出文件所在的目录存在
    output_dir = os.path.dirname(OUTPUT_FILE)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")
    
    # 将所有唯一链接写入文件，覆盖旧内容
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for link in sorted(list(all_links)):
            f.write(f"{LINK_PREFIX}{link}\n")
    
    print(f"\n✅ Found {len(all_links)} valid subscription links (skipped {skipped_count} links expiring soon)")
    print(f"📁 Saved to {OUTPUT_FILE}")

if __name__ == '__main__':
    asyncio.run(main())

# TelegramNode/telegram_publiclink.py
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

OUTPUT_FILE = 'flclashyaml/telegram_publiclink.txt' # 输出文件路径
TIME_WINDOW_HOURS = 36 # 过去X 小时内的消息
LINK_PREFIX = "telegram_publiclink：" # 链接前缀，注意是中文冒号

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
    all_links = set() # 使用集合存储链接以自动去重

    # 遍历每个目标频道
    for current_channel_identifier in TARGET_CHANNELS:
        print(f"\n--- Processing channel: {current_channel_identifier} (posted after {target_time} UTC) ---")
        try:
            entity = await client.get_entity(current_channel_identifier)

            async for message in client.iter_messages(entity, limit=500):
                if message.date < target_time:
                    print(f"  Reached messages older than {TIME_WINDOW_HOURS} hours for {current_channel_identifier}. Stopping.")
                    break

                # 提取消息文本中的 URL
                if message.text:
                    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', message.text)
                    for url in urls:
                        url = url.strip().strip('.,')
                        if url:
                            all_links.add(url)

                # --- 关键修改部分开始 ---
                # 提取消息媒体（例如网页预览）中的 URL
                # 增加检查以确保 message.media.web_page 存在且有 url 属性
                if message.media and \
                   isinstance(message.media, MessageMediaWebPage) and \
                   hasattr(message.media, 'web_page') and \
                   hasattr(message.media.web_page, 'url') and \
                   message.media.web_page.url: # 确保 url 属性存在且不为空
                    all_links.add(message.media.web_page.url)
                # --- 关键修改部分结束 ---

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

    print(f"Found {len(all_links)} unique links from the last {TIME_WINDOW_HOURS} hours and saved to {OUTPUT_FILE}.")

if __name__ == '__main__':
    asyncio.run(main())

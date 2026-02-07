import os
import requests
import logging
import asyncio
import json
from dotenv import load_dotenv

# 添加猴子补丁，解决 websockets.exceptions 不存在的问题
import websockets
if not hasattr(websockets, 'exceptions'):
    # 在 websockets 10.x 版本中，异常类直接暴露在模块顶层
    websockets.exceptions = websockets

from dingtalk_stream import DingTalkStreamClient, ChatbotHandler, ChatbotMessage, Credential

# 1. 必须首先配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("dingtalk_stream")

load_dotenv()

APP_KEY = os.getenv("DINGTALK_APP_KEY")
APP_SECRET = os.getenv("DINGTALK_APP_SECRET")
OC_URL = os.getenv("OPENCLAW_URL")
OC_TOKEN = os.getenv("OPENCLAW_TOKEN")
OC_MODEL = os.getenv("OPENCLAW_MODEL", "qwen")

global_client = None

class MyHandler(ChatbotHandler):
    async def process(self, message: ChatbotMessage):
        prompt = ""
        msg_id = ""
        
        try:
            # 1. 更加鲁棒的数据解析
            data = message.data if isinstance(message.data, dict) else json.loads(message.data)
            prompt = data.get('text', {}).get('content', '').strip()
            msg_id = data.get('msgId') or data.get('messageId') # 钉钉回复必须的 ID
            
            # 提取发送者 ID
            sender_info = data.get('senderId', 'unknown_user')
            
            if not prompt: return
            logging.info(f"收到消息: {prompt} (来自: {sender_info})")

        except Exception as e:
            logging.error(f"解析失败: {e}")
            return

        # 2. 修正后的 OpenClaw 请求 (务必检查 URL)
        headers = {
            "Authorization": f"Bearer {OC_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": OC_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "user": sender_info
        }

        try:
            # 修正 405 错误：确保 URL 准确
            # 请在 .env 中确认 OPENCLAW_URL 是 http://127.0.0.1:18789/v1/chat/completions
            response = requests.post(OC_URL, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            res_json = response.json()
            reply_content = res_json['choices'][0]['message']['content']
            
            # 3. 修正后的回复逻辑 (解决 AttributeError: 'reply_text')
            if global_client:
                # 使用底层 client 的回复方法，这是最稳妥的
                await global_client.reply_chatbot_message(message, reply_content)
                logging.info(">>> 回复已发送")
            else:
                logging.error("全局客户端未初始化，无法回复")

        except Exception as e:
            logging.error(f"交互失败: {e}")

async def start():
    global global_client
    logging.info(f"使用 APP_KEY: {APP_KEY}")
    
    credential = Credential(APP_KEY, APP_SECRET)
    global_client = DingTalkStreamClient(credential) # 赋值给全局变量
    global_client.logger = logger 
    
    global_client.register_callback_handler("/v1.0/im/bot/messages/get", MyHandler())
    
    logging.info(">>> 正在启动钉钉服务...")
    await global_client.start()

if __name__ == "__main__":
    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.error(f"启动异常: {e}")
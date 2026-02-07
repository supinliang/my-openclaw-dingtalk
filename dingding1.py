import os
import requests
import logging
import asyncio
import json
from dotenv import load_dotenv

# 解决 websockets 兼容性问题
import websockets
if not hasattr(websockets, 'exceptions'):
    websockets.exceptions = websockets

from dingtalk_stream import DingTalkStreamClient, ChatbotHandler, ChatbotMessage, Credential

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("dingtalk_stream")

load_dotenv()

APP_KEY = os.getenv("DINGTALK_APP_KEY")
APP_SECRET = os.getenv("DINGTALK_APP_SECRET")
OC_TOKEN = os.getenv("OPENCLAW_TOKEN")
OC_MODEL = os.getenv("OPENCLAW_MODEL", "qwen")

# 【注意】这里手动修正 URL，确保路径末尾没有多余斜杠
OC_URL = os.getenv("OPENCLAW_URL", "").strip().rstrip('/')

global_client = None

class MyHandler(ChatbotHandler):
    async def process(self, message: ChatbotMessage):
        prompt = ""
        sender_info = "unknown"
        
        try:
            # 1. 提取消息
            data = message.data if isinstance(message.data, dict) else json.loads(message.data)
            prompt = data.get('text', {}).get('content', '').strip()
            sender_info = data.get('senderId') or data.get('sender_id') or "unknown_user"
            
            if not prompt: return
            logging.info(f"收到消息: {prompt} (来自: {sender_info})")

        except Exception as e:
            logging.error(f"消息解析失败: {e}")
            return

        # 2. 构造 OpenClaw 请求
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
            # 执行请求
            logging.info(f"正在转发至 OpenClaw: {OC_URL}")
            response = requests.post(OC_URL, headers=headers, json=payload, timeout=60)
            
            # 这里的报错捕获能告诉我们 405 的具体原因
            if response.status_code == 405:
                logging.error("OpenClaw 返回 405：请检查 URL 是否包含 /v1/chat/completions 且没有多余斜杠")
                return

            response.raise_for_status()
            res_json = response.json()
            
            # 提取回复内容（增加安全判断）
            choices = res_json.get('choices', [])
            if choices:
                reply_content = choices[0].get('message', {}).get('content', '')
                
                # 3. 回复钉钉
                if global_client and reply_content:
                    await global_client.reply_chatbot_message(message, reply_content)
                    logging.info(">>> 回复已发送")
            else:
                logging.error(f"OpenClaw 返回数据异常: {res_json}")

        except Exception as e:
            logging.error(f"OpenClaw 交互失败: {e}")

async def start():
    global global_client
    credential = Credential(APP_KEY, APP_SECRET)
    global_client = DingTalkStreamClient(credential)
    global_client.logger = logger 
    global_client.register_callback_handler("/v1.0/im/bot/messages/get", MyHandler())
    
    logging.info(">>> 正在启动钉钉服务...")
    await global_client.start()

if __name__ == "__main__":
    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        pass
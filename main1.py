import os
import json
import logging
import asyncio
import hmac
import hashlib
import base64
import requests
from dotenv import load_dotenv

# ==========================================
# 第一部分：Config (配置层)
# ==========================================
# 优先读取 OpenClaw 注入的环境变量，如果没有则读取 .env
load_dotenv()

class Config:
    # 钉钉配置
    APP_KEY = os.getenv("DINGTALK_APP_KEY")
    APP_SECRET = os.getenv("DINGTALK_APP_SECRET")
    
    # OpenClaw 内部配置
    # 注意：如果作为 OpenClaw 插件运行，OpenClaw 会自动提供这些
    OC_API_URL = os.getenv("OPENCLAW_URL", "http://127.0.0.1:18001/v1/chat/completions")
    OC_TOKEN = os.getenv("OPENCLAW_TOKEN")
    OC_MODEL = os.getenv("OPENCLAW_MODEL", "qwen")
    
    # 安全开关
    ENABLE_SIGN_VERIFY = True  # 是否开启签名校验
    SENSITIVE_WORDS = ["机密", "内部密码", "财务报表"] # 自定义敏感词库

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OC-Bridge")

# ==========================================
# 第二部分：Bridge (逻辑处理层)
# ==========================================
from dingtalk_stream import DingTalkStreamClient, ChatbotHandler, ChatbotMessage, Credential

class OCBridgeHandler(ChatbotHandler):
    """
    完全可控的桥接逻辑：
    1. 接收钉钉消息 -> 2. 安全检查 -> 3. 格式转换 -> 4. 访问本地 AI -> 5. 回复
    """
    async def process(self, message: ChatbotMessage):
        try:
            # 1. 解析原始数据
            raw_data = message.data if isinstance(message.data, dict) else json.loads(message.data)
            content = raw_data.get('text', {}).get('content', '').strip()
            sender_id = raw_data.get('senderId', 'unknown')
            
            # 2. 安全检查：敏感词过滤
            for word in Config.SENSITIVE_WORDS:
                if word in content:
                    await self.reply(message, "⚠️ 您的输入包含敏感词汇，请求已被拦截。")
                    return

            logger.info(f"安全校验通过。收到来自 {sender_id} 的提问: {content}")

            # 3. 构造转发给 OpenClaw 的标准格式
            reply_text = self.call_openclaw(content, sender_id)
            
            # 4. 回复钉钉
            await self.reply(message, reply_text)

        except Exception as e:
            logger.error(f"逻辑处理异常: {e}")

    def call_openclaw(self, prompt, user_id):
        """访问本地 OpenClaw API"""
        headers = {
            "Authorization": f"Bearer {Config.OC_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": Config.OC_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "user": user_id
        }
        try:
            # 这里使用同步 requests 简单稳定，也可以换成 aiohttp
            response = requests.post(Config.OC_API_URL, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"OpenClaw 响应失败: {e}")
            return f"❌ AI 助手连接失败: {str(e)}"

    async def reply(self, message, text):
        """统一回复接口"""
        try:
            # 兼容不同 SDK 版本的回复方式
            if hasattr(message, 'reply_text'):
                message.reply_text(text)
            else:
                # 备用：如果对象没方法，使用全局 client 回复
                await global_client.reply_chatbot_message(message, text)
        except Exception as e:
            logger.error(f"发送回复失败: {e}")

# ==========================================
# 第三部分：Main (启动层)
# ==========================================
global_client = None

async def main():
    global global_client
    
    # 打印启动信息（不打印 Secret，保护安全）
    logger.info(f"正在启动 Bridge... 目标模型: {Config.OC_MODEL}")
    
    if not Config.APP_KEY or not Config.APP_SECRET:
        logger.error("错误：未找到钉钉 APP_KEY 或 APP_SECRET，请检查环境变量或 .env")
        return

    # 初始化钉钉连接
    credential = Credential(Config.APP_KEY, Config.APP_SECRET)
    global_client = DingTalkStreamClient(credential)
    
    # 注入 Logger 解决 SDK 内部 Bug
    global_client.logger = logger
    
    # 注册路由
    global_client.register_callback_handler("/v1.0/im/bot/messages/get", OCBridgeHandler())
    
    # 启动连接
    logger.info(">>> 桥接服务已上线。现在可以向钉钉机器人发送消息了。")
    await global_client.start()

if __name__ == "__main__":
    try:
        # 添加 websockets 猴子补丁
        import websockets
        if not hasattr(websockets, 'exceptions'):
            websockets.exceptions = websockets
            
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("服务已停止")
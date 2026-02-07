import os
import json
import asyncio
import uuid
import logging
import websockets
from dingtalk_stream import DingTalkStreamClient, ChatbotHandler, Credential

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OC-Private-Bridge")

class Config:
    # 插件安装后，OpenClaw 会自动注入这些环境变量
    APP_KEY = os.getenv("DINGTALK_APP_KEY")
    APP_SECRET = os.getenv("DINGTALK_APP_SECRET")
    # 直接敲 OpenClaw 的 WebSocket 门
    OC_WS_URL = "ws://127.0.0.1:18789" 
    OC_TOKEN = os.getenv("OPENCLAW_TOKEN")

class PrivateBridgeHandler(ChatbotHandler):
    async def process(self, message):
        try:
            # 1. 解析钉钉原始消息
            data = message.data if isinstance(message.data, dict) else json.loads(message.data)
            prompt = data.get('text', {}).get('content', '').strip()
            if not prompt: return
            
            logger.info(f"收到钉钉消息: {prompt}")

            # 2. 通过 WebSocket 转发给 OpenClaw
            reply_content = await self.call_openclaw_ws(prompt)
            
            # 3. 回复钉钉 (解决 reply_text 报错问题)
            if hasattr(message, 'reply_text'):
                message.reply_text(reply_content)
            else:
                # 备用方案：通过全局 client 发送，这也是最可控的
                await self.client.reply_chatbot_message(message, reply_content)
                
            logger.info(">>> 已成功通过 WS 转发并回复")

        except Exception as e:
            logger.error(f"处理流程异常: {e}")

    async def call_openclaw_ws(self, prompt):
        """核心逻辑：模拟 OpenClaw 内部通信"""
        try:
            async with websockets.connect(Config.OC_WS_URL) as ws:
                # 构造 OpenClaw 预期的内部消息包 (chat.send)
                payload = {
                    "method": "chat.send",
                    "params": {
                        "messages": [{"role": "user", "content": prompt}],
                        "token": Config.OC_TOKEN
                    },
                    "id": str(uuid.uuid4())
                }
                await ws.send(json.dumps(payload))
                
                # 等待网关返回结果
                response = await ws.recv()
                res_data = json.loads(response)
                
                # 按照 OpenClaw 返回结构提取文字
                # 结构通常在 result -> choices -> message -> content
                choices = res_data.get('result', {}).get('choices', [])
                if choices:
                    return choices[0].get('message', {}).get('content', '')
                return "【系统】AI 返回了空消息，请检查 OpenClaw 控制台。"
                
        except Exception as e:
            return f"【系统】连接 OpenClaw 失败: {str(e)}"

async def start_service():
    # 修复 Websockets 补丁
    if not hasattr(websockets, 'exceptions'):
        websockets.exceptions = websockets

    logger.info("正在启动私有桥接服务...")
    
    credential = Credential(Config.APP_KEY, Config.APP_SECRET)
    client = DingTalkStreamClient(credential)
    
    # 绑定实例，方便在 handler 里调用 client
    handler = PrivateBridgeHandler()
    handler.client = client
    
    client.register_callback_handler("/v1.0/im/bot/messages/get", handler)
    
    await client.start()

if __name__ == "__main__":
    try:
        asyncio.run(start_service())
    except KeyboardInterrupt:
        logger.info("服务已手动停止")
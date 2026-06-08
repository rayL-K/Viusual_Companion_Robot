"""WebSocket 服务入口"""
import asyncio
import json
import logging
import sys
from pathlib import Path

import websockets

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from pipeline import PerceptionPipeline

logger = logging.getLogger(__name__)


async def main():
    app = PerceptionPipeline()
    clients = set()

    def broadcast(data):
        if not clients:
            return
        msg = json.dumps(data, ensure_ascii=False)
        for ws in clients.copy():
            asyncio.ensure_future(_send(ws, msg))

    app.set_broadcast(broadcast)

    async def handler(ws):
        clients.add(ws)
        logger.info("前端已连接 (%d 在线)", len(clients))
        try:
            async for raw in ws:
                try:
                    cmd = json.loads(raw)
                    await app.handle_command(cmd)
                except json.JSONDecodeError:
                    pass
        except websockets.ConnectionClosed:
            pass
        finally:
            clients.discard(ws)
            logger.info("前端已断开 (%d 在线)", len(clients))

    async with websockets.serve(handler, "0.0.0.0", 9765):
        logger.info("感知服务已启动 ws://0.0.0.0:9765")
        logger.info("等待前端 start 命令...")
        await asyncio.Future()


async def _send(ws, msg: str) -> None:
    """安全地向单个 WebSocket 客户端发送消息，断连不抛异常。"""

    try:
        await ws.send(msg)
    except websockets.ConnectionClosed:
        pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

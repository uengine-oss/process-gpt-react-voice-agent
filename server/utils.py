from typing import AsyncIterator
from starlette.websockets import WebSocket


async def websocket_stream(websocket: WebSocket) -> AsyncIterator[str]:
    try:
        while True:
            data = await websocket.receive_text()
            yield data
    except Exception as e:
        print(f"WebSocket 스트림 에러: {e}")
        raise

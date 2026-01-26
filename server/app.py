import uvicorn
import os
import json
import asyncio
import websockets

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

from langchain_openai_voice import OpenAIVoiceReactAgent

from server.utils import websocket_stream
from server.prompt import INSTRUCTIONS
from server.tools import TOOLS

from dotenv import load_dotenv

load_dotenv(override=True)

user_sessions = {}

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = id(websocket)
    user_sessions[session_id] = {}
    
    print(f"새로운 WebSocket 연결: {session_id}")

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            if payload.get("type") == "user_info":
                print(f"사용자 정보 수신: {payload}")
                user_sessions[session_id]["email"] = payload.get("email")
                user_sessions[session_id]["chat_room_id"] = payload.get("chat_room_id")
                user_sessions[session_id]["tenant_id"] = payload.get("tenant_id")
                break
    except Exception as e:
        print(f"사용자 정보 수신 중 에러: {e}")
        raise

    browser_receive_stream = websocket_stream(websocket)

    user_info = user_sessions[session_id]
    user_info_str = "\n".join(f"{k}: {v}" for k, v in user_info.items())
    instructions_with_user = (
        f"{INSTRUCTIONS}\n"
        "[User Info]\n"
        f"{user_info_str}\n"
        "- 모든 툴 호출 시 tenant_id와 query를 반드시 파라미터로 포함하세요. "
        f"tenant_id는 '{user_info.get('tenant_id')}' 입니다."
    )
    
    print(f"OpenAI API Key 설정됨: {bool(os.getenv('OPENAI_API_KEY'))}")
    print(f"사용자 정보: {user_info}")
    
    agent = OpenAIVoiceReactAgent(
        model="gpt-4o-realtime-preview",
        tools=TOOLS,
        instructions=instructions_with_user,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        user_info=user_info,
        silence_duration_ms=1200  # 1.2초로 단축 (빠른 응답)
    )

    try:
        await agent.aconnect(browser_receive_stream, websocket.send_text)
    except Exception as e:
        print(f"Agent 연결 에러: {e}")
        try:
            error_message = json.dumps({"type": "error", "message": str(e)})
            await websocket.send_text(error_message)
        except:
            pass
        raise
    
    # 연결 종료 시 세션 정리
    if session_id in user_sessions:
        del user_sessions[session_id]
        print(f"세션 정리 완료: {session_id}")


async def _client_to_openai(client_ws: WebSocket, openai_ws: websockets.WebSocketClientProtocol):
    while True:
        try:
            message = await client_ws.receive()
        except Exception:
            break
        if message.get("text") is not None:
            if message["text"] == "":
                continue
            await openai_ws.send(message["text"])
        elif message.get("bytes") is not None:
            await openai_ws.send(message["bytes"])
        else:
            break


async def _openai_to_client(client_ws: WebSocket, openai_ws: websockets.WebSocketClientProtocol):
    try:
        async for message in openai_ws:
            if isinstance(message, bytes):
                await client_ws.send_bytes(message)
            else:
                await client_ws.send_text(message)
    except Exception:
        pass


async def websocket_realtime_proxy(websocket: WebSocket):
    """
    하위 호환: 기존 voice-agent의 /ws/realtime 프락시 엔드포인트.
    OpenAI Realtime WebSocket에 단순 중계하여 기존 클라이언트 프로토콜을 유지.
    """
    await websocket.accept()
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_realtime_model = "gpt-realtime"
    openai_realtime_url = "wss://api.openai.com/v1/realtime"
    target_url = f"{openai_realtime_url}?model={openai_realtime_model}"
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    if not openai_api_key:
        await websocket.send_text(json.dumps({"type": "error", "message": "OPENAI_API_KEY not set"}))
        await websocket.close()
        return

    try:
        print(f"[realtime-proxy] connecting -> {target_url}")
        # websockets 12.x: use additional_headers (voice-agent와 동일)
        async with websockets.connect(target_url, additional_headers=headers, max_size=None) as openai_ws:
            client_to_openai = asyncio.create_task(_client_to_openai(websocket, openai_ws))
            openai_to_client = asyncio.create_task(_openai_to_client(websocket, openai_ws))
            done, pending = await asyncio.wait(
                [client_to_openai, openai_to_client],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                try:
                    _ = task.exception()
                except Exception:
                    pass
    except Exception as e:
        print(f"[realtime-proxy] connect/error: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


routes = [
    WebSocketRoute("/ws", websocket_endpoint),
    WebSocketRoute("/ws/realtime", websocket_realtime_proxy),
]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)

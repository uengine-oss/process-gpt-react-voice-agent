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
from server.prompt import build_agent_instructions
from server.tools import TOOLS
from server.realtime_proxy import ProxyState, client_to_openai, openai_to_client, parse as parse_event

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
                user_sessions[session_id]["_agent_info"] = payload.get("agent_info")
                user_sessions[session_id]["_conversation_history"] = payload.get("conversation_history") or []
                break
    except Exception as e:
        print(f"사용자 정보 수신 중 에러: {e}")
        raise

    browser_receive_stream = websocket_stream(websocket)

    agent_info = user_sessions[session_id].pop("_agent_info", None)
    conversation_history = user_sessions[session_id].pop("_conversation_history", [])
    user_info = user_sessions[session_id]
    instructions_with_user = build_agent_instructions(agent_info, user_info)

    agent_name = (agent_info or {}).get("username") or "기본"
    print(f"OpenAI API Key 설정됨: {bool(os.getenv('OPENAI_API_KEY'))}")
    print(f"사용자 정보: {user_info}")
    print(f"에이전트: {agent_name}")
    print(f"대화 히스토리: {len(conversation_history)}턴")
    
    agent = OpenAIVoiceReactAgent(
        model="gpt-realtime",
        tools=TOOLS,
        instructions=instructions_with_user,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        user_info=user_info,
        conversation_history=conversation_history,
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


async def _client_to_openai(client_ws: WebSocket, openai_ws: websockets.WebSocketClientProtocol, state: ProxyState):
    while True:
        try:
            message = await client_ws.receive()
        except Exception:
            break
        if message.get("text") is not None:
            if message["text"] == "":
                continue
            event = parse_event(message["text"])
            if event is None:
                print("[realtime-proxy] dropped a non-JSON text frame from the browser")
                continue
            for out in client_to_openai(event, state):
                await openai_ws.send(json.dumps(out))
            _flush_log(state)
        elif message.get("bytes") is not None:
            await openai_ws.send(message["bytes"])
        else:
            break


async def _openai_to_client(client_ws: WebSocket, openai_ws: websockets.WebSocketClientProtocol, state: ProxyState):
    try:
        async for message in openai_ws:
            if isinstance(message, bytes):
                await client_ws.send_bytes(message)
                continue
            event = parse_event(message)
            if event is None:
                await client_ws.send_text(message)
                continue
            to_client, to_openai = openai_to_client(event, state)
            for out in to_openai:
                await openai_ws.send(json.dumps(out))
            if to_client is not None:
                await client_ws.send_text(json.dumps(to_client))
            _flush_log(state)
    except Exception as e:
        print(f"[realtime-proxy] openai->client stopped: {type(e).__name__}")


def _flush_log(state: ProxyState):
    for line in state.log:
        print(f"[realtime-proxy] {line}")
    state.log.clear()


async def websocket_realtime_proxy(websocket: WebSocket):
    """
    하위 호환: 기존 voice-agent의 /ws/realtime 프락시 엔드포인트(업무 폼의 「음성 에이전트」).
    화면은 Realtime 베타 모양으로 말하고 듣는다. OpenAI 는 정식(GA) 규격만 받으므로
    오가는 이벤트를 server/realtime_proxy.py 에서 맞춘다(그대로 넘기면 session.update 가
    거절돼 폼 스키마·도구·지침이 하나도 안 들어가고, 에이전트 목소리도 나지 않는다).
    """
    await websocket.accept()
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_realtime_model = "gpt-realtime"
    openai_realtime_url = "wss://api.openai.com/v1/realtime"
    target_url = f"{openai_realtime_url}?model={openai_realtime_model}"
    # 정식 규격에서는 베타 헤더를 붙이면 거절당한다.
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
    }

    if not openai_api_key:
        await websocket.send_text(json.dumps({"type": "error", "error": {"type": "proxy_error", "message": "OPENAI_API_KEY not set"}, "message": "OPENAI_API_KEY not set"}))
        await websocket.close()
        return

    try:
        print(f"[realtime-proxy] connecting -> {target_url}")
        # websockets 12.x: use additional_headers (voice-agent와 동일)
        async with websockets.connect(target_url, additional_headers=headers, max_size=None) as openai_ws:
            state = ProxyState()
            up = asyncio.create_task(_client_to_openai(websocket, openai_ws, state))
            down = asyncio.create_task(_openai_to_client(websocket, openai_ws, state))
            done, pending = await asyncio.wait(
                [up, down],
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
        print(f"[realtime-proxy] connect/error: {type(e).__name__}: {e}")
        try:
            # 화면은 error.message 를 읽는다 — 옛 모양(message)도 함께 둔다
            text = f"음성 서버가 OpenAI 에 연결하지 못했습니다 ({type(e).__name__})"
            await websocket.send_text(json.dumps({"type": "error", "error": {"type": "proxy_error", "message": text}, "message": text}))
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

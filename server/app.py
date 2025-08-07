import uvicorn
import os
import json
import asyncio

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


routes = [WebSocketRoute("/ws", websocket_endpoint)]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)

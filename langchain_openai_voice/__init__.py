import asyncio
import json
import websockets

from contextlib import asynccontextmanager
from typing import AsyncGenerator, AsyncIterator, Any, Callable, Coroutine
from langchain_openai_voice.utils import amerge

from langchain_core.tools import BaseTool
from langchain_core._api import beta
from langchain_core.utils import secret_from_env

from pydantic import BaseModel, Field, SecretStr, PrivateAttr

DEFAULT_MODEL = "gpt-4o-realtime-preview-2024-10-01"
DEFAULT_URL = "wss://api.openai.com/v1/realtime"

EVENTS_TO_IGNORE = {
    "response.function_call_arguments.delta",
    "rate_limits.updated",
    "response.created",
    "response.content_part.added",
    "response.content_part.done",
    "conversation.item.created",
    "session.created",
    "session.updated",
    "response.output_item.done",
}


@asynccontextmanager
async def connect(*, api_key: str, model: str, url: str, max_retries: int = 3) -> AsyncGenerator[
    tuple[
        Callable[[dict[str, Any] | str], Coroutine[Any, Any, None]],
        AsyncIterator[dict[str, Any]],
    ],
    None,
]:
    """
    async with connect(model="gpt-4o-realtime-preview-2024-10-01") as websocket:
        await websocket.send("Hello, world!")
        async for message in websocket:
            print(message)
    """

    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    url = url or DEFAULT_URL
    url += f"?model={model}"

    websocket = None
    last_error = None
    
    for attempt in range(max_retries):
        try:
            websocket = await websockets.connect(
                url,
                additional_headers=headers,  # websockets 12.x
                open_timeout=60,
                close_timeout=60,
                ping_interval=20,    # 20초마다 ping (연결 상태 모니터링)
                ping_timeout=10,     # 10초 내 pong 응답 대기
                max_size=2**20     # 최대 메시지 크기
            )
            break
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # 지수 백오프
            else:
                print(f"WebSocket 연결 실패: {e}")
                raise last_error

    try:

        async def send_event(event: dict[str, Any] | str) -> None:
            try:
                formatted_event = json.dumps(event) if isinstance(event, dict) else event
                await websocket.send(formatted_event)
            except Exception as e:
                raise

        async def event_stream() -> AsyncIterator[dict[str, Any]]:
            async for raw_event in websocket:
                yield json.loads(raw_event)

        stream: AsyncIterator[dict[str, Any]] = event_stream()

        yield send_event, stream
    finally:
        await websocket.close()


class VoiceToolExecutor(BaseModel):
    """
    Can accept function calls and emits function call outputs to a stream.
    """

    tools_by_name: dict[str, BaseTool]
    _trigger_future: asyncio.Future = PrivateAttr(default_factory=asyncio.Future)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

    async def _trigger_func(self) -> dict:  # returns a tool call
        return await self._trigger_future

    async def add_tool_call(self, tool_call: dict) -> None:
        # lock to avoid simultaneous tool calls racing and missing
        # _trigger_future being
        async with self._lock:
            if self._trigger_future.done():
                # TODO: handle simultaneous tool calls better
                raise ValueError("Tool call adding already in progress")

            self._trigger_future.set_result(tool_call)

    async def _create_tool_call_task(self, tool_call: dict) -> asyncio.Task[dict]:
        tool = self.tools_by_name.get(tool_call["name"])
        if tool is None:
            # immediately yield error, do not add task
            raise ValueError(
                f"tool {tool_call['name']} not found. "
                f"Must be one of {list(self.tools_by_name.keys())}"
            )

        # try to parse args
        try:
            args = json.loads(tool_call["arguments"])
        except json.JSONDecodeError:
            raise ValueError(
                f"failed to parse arguments `{tool_call['arguments']}`. Must be valid JSON."
            )

        async def run_tool() -> dict:
            try:
                result = await tool.ainvoke(args)
                try:
                    result_str = json.dumps(result)
                except TypeError:
                    # not json serializable, use str
                    result_str = str(result)
                return {
                    "type": "conversation.item.create",
                    "item": {
                        "id": tool_call["call_id"],
                        "call_id": tool_call["call_id"],
                        "type": "function_call_output",
                        "output": result_str,
                    },
                }
            except Exception as e:
                # 폴백: 에러 메시지를 사용자에게 반환
                return {
                    "type": "conversation.item.create",
                    "item": {
                        "id": tool_call["call_id"],
                        "call_id": tool_call["call_id"],
                        "type": "function_call_output",
                        "output": f"도구 실행 중 오류가 발생했습니다: {str(e)}",
                    },
                }

        task = asyncio.create_task(run_tool())
        return task

    async def output_iterator(self) -> AsyncIterator[dict]:  # yield events
        trigger_task = asyncio.create_task(self._trigger_func())
        tasks = set([trigger_task])
        while True:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                tasks.remove(task)
                if task == trigger_task:
                    async with self._lock:
                        self._trigger_future = asyncio.Future()
                    trigger_task = asyncio.create_task(self._trigger_func())
                    tasks.add(trigger_task)
                    tool_call = task.result()
                    try:
                        new_task = await self._create_tool_call_task(tool_call)
                        tasks.add(new_task)
                    except ValueError as e:
                        yield {
                            "type": "conversation.item.create",
                            "item": {
                                "id": tool_call["call_id"],
                                "call_id": tool_call["call_id"],
                                "type": "function_call_output",
                                "output": (f"Error: {str(e)}"),
                            },
                        }
                else:
                    yield task.result()



@beta()
class OpenAIVoiceReactAgent(BaseModel):
    model: str
    openai_api_key: str
    instructions: str | None = None
    tools: list[BaseTool] | None = None
    url: str = Field(default=DEFAULT_URL)
    user_info: dict[str, Any] | None = None
    conversation_history: list[dict[str, Any]] | None = None
    silence_duration_ms: int = Field(default=1200)  # 1.2초 침묵 감지 (빠른 응답)
    
    # 턴 관리 상태 변수
    _is_ai_responding: bool = PrivateAttr(default=False)
    _is_user_speaking: bool = PrivateAttr(default=False)
    _has_audio_response: bool = PrivateAttr(default=False)

    async def aconnect(
        self,
        input_stream: AsyncIterator[str],
        send_output_chunk: Callable[[str], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Connect to the OpenAI API and send and receive messages.

        input_stream: AsyncIterator[str]
            Stream of input events to send to the model. Usually transports input_audio_buffer.append events from the microphone.
        output: Callable[[str], None]
            Callback to receive output events from the model. Usually sends response.audio.delta events to the speaker.

        """
        # formatted_tools: list[BaseTool] = [
        #     tool if isinstance(tool, BaseTool) else tool_converter.wr(tool)  # type: ignore
        #     for tool in self.tools or []
        # ]
        tools_by_name = {tool.name: tool for tool in self.tools}
        tool_executor = VoiceToolExecutor(tools_by_name=tools_by_name)

        # user_info를 instructions에 추가
        instructions = self.instructions or ""
        if self.user_info:
            user_info_str = "\n".join(f"{k}: {v}" for k, v in self.user_info.items())
            instructions += f"\n[User Info]\n{user_info_str}"

        async with connect(
            model=self.model, api_key=self.openai_api_key, url=self.url
        ) as (
            model_send,
            model_receive_stream,
        ):
            # sent tools and instructions with initial chunk
            tool_defs = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {"type": "object", "properties": tool.args},
                }
                for tool in tools_by_name.values()
            ]
            await model_send(
                {
                    "type": "session.update",
                    "session": {
                        "instructions": instructions,
                        "input_audio_transcription": {
                            "model": "whisper-1",
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.8,  # 잡음 필터링 강화 (0.6 → 0.8)
                            "prefix_padding_ms": 200,
                            "silence_duration_ms": self.silence_duration_ms
                        },
                        "tools": tool_defs,
                    },
                }
            )

            # 이전 대화 히스토리를 OpenAI Realtime 컨텍스트에 주입한다.
            # conversation.item.create 이벤트로 이전 턴을 재현해 컨텍스트를 유지한다.
            for msg in (self.conversation_history or []):
                role = msg.get("role", "")
                content = (msg.get("content") or "").strip()
                if role not in ("user", "assistant") or not content:
                    continue
                content_type = "input_text" if role == "user" else "text"
                try:
                    await model_send({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": role,
                            "content": [{"type": content_type, "text": content}],
                        },
                    })
                except Exception as e:
                    print(f"히스토리 주입 실패 ({role}): {e}")
            if self.conversation_history:
                print(f"✅ 대화 히스토리 {len(self.conversation_history)}턴 주입 완료")

            async for stream_key, data_raw in amerge(
                input_mic=input_stream,
                output_speaker=model_receive_stream,
                tool_outputs=tool_executor.output_iterator(),
            ):
                try:
                    data = (
                        json.loads(data_raw) if isinstance(data_raw, str) else data_raw
                    )
                except json.JSONDecodeError:
                    continue

                if stream_key == "input_mic":
                    # 클라이언트에서 보내는 이벤트 처리
                    if isinstance(data, dict):
                        event_type = data.get("type")
                        
                        if event_type == "client_audio_playback_complete":
                            print("AI 응답 완료")
                            if self._is_ai_responding and self._has_audio_response:
                                self._is_ai_responding = False
                                self._has_audio_response = False
                            # OpenAI API로 전송하지 않음
                            continue
                            
                        # AI가 응답 중일 때는 사용자 음성 이벤트 무시 (오디오 데이터는 계속 처리)
                        if self._is_ai_responding and event_type in ["input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"]:
                            print(f"AI 응답 중이므로 음성 이벤트 무시: {event_type}")
                            continue
                            
                    await model_send(data)
                elif stream_key == "tool_outputs":
                    await model_send(data)
                    # 툴 실행 후 AI 응답 시작 (턴 기반)
                    if not self._is_user_speaking:
                        self._is_ai_responding = True
                        self._has_audio_response = False  # 새 응답 시작 시 리셋
                        await model_send({"type": "response.create", "response": {}})
                elif stream_key == "output_speaker":
                    t = data["type"]
                    
                    # OpenAI VAD 이벤트 처리
                    if t == "input_audio_buffer.speech_started":
                        print("🎤 사용자 음성 시작 감지")
                        self._is_user_speaking = True
                        # 인터럽트: AI 응답 중 사용자가 발화하면 현재 응답 취소
                        if self._is_ai_responding:
                            print("⚡ 인터럽트: AI 응답 취소")
                            self._is_ai_responding = False
                            self._has_audio_response = False
                            try:
                                await model_send({"type": "response.cancel"})
                            except Exception as e:
                                print(f"response.cancel 전송 실패: {e}")
                        # 클라이언트에 전달 (오디오 즉시 중단 트리거)
                        try:
                            await send_output_chunk(json.dumps(data))
                        except Exception as e:
                            print(f"speech_started 전송 실패: {e}")
                    elif t == "input_audio_buffer.speech_stopped":
                        print("🛑 사용자 음성 종료 감지")
                        self._is_user_speaking = False
                        # 클라이언트에 전달
                        try:
                            await send_output_chunk(json.dumps(data))
                        except Exception as e:
                            print(f"speech_stopped 전송 실패: {e}")
                        # 사용자 음성 완료 후 AI 응답 트리거 (턴 기반)
                        if not self._is_ai_responding:
                            print("🚀 AI 응답 시작")
                            self._is_ai_responding = True
                            self._has_audio_response = False  # 새 응답 시작 시 리셋
                            await model_send({"type": "response.create", "response": {}})
                    elif t == "input_audio_buffer.committed":
                        print("📝 사용자 오디오 버퍼 커밋됨")
                    
                    # AI 응답 상태 관리
                    elif t == "response.audio.delta":
                        if not self._is_ai_responding:
                            print("🎬 AI 오디오 응답 시작")
                        self._is_ai_responding = True
                        self._has_audio_response = True  # 오디오 응답 감지
                        try:
                            await send_output_chunk(json.dumps(data))
                        except Exception as e:
                            print(f"오디오 델타 전송 실패: {e}")
                            break
                    elif t == "response.function_call_arguments.done":
                        self._is_ai_responding = True
                        await tool_executor.add_tool_call(data)
                    elif t == "response.audio.done":
                        print("🎯 AI 오디오 스트리밍 완료 - 프론트엔드로 전송")
                        try:
                            await send_output_chunk(json.dumps(data))  # 프론트엔드로 전송
                        except Exception as e:
                            print(f"오디오 완료 신호 전송 실패: {e}")
                            # WebSocket 끊어진 경우에도 상태 정리
                            if self._is_ai_responding and self._has_audio_response:
                                print("연결 끊어짐으로 인한 상태 정리")
                                self._is_ai_responding = False
                                self._has_audio_response = False
                    elif t == "response.audio_transcript.delta":
                        try:
                            await send_output_chunk(json.dumps(data))
                        except Exception as e:
                            print(f"트랜스크립트 델타 전송 실패: {e}")
                    elif t == "response.audio_transcript.done":
                        print("model:", data.get("transcript", ""))
                        try:
                            await send_output_chunk(json.dumps(data))
                        except Exception as e:
                            print(f"트랜스크립트 완료 전송 실패: {e}")
                    elif t == "conversation.item.input_audio_transcription.completed":
                        print("user:", data.get("transcript", ""))
                        try:
                            await send_output_chunk(json.dumps(data))
                        except Exception as e:
                            print(f"사용자 트랜스크립트 전송 실패: {e}")
                    elif t == "response.done":
                        status = (data.get("response") or {}).get("status", "")
                        print(f"📝 response.done (상태: {status}, 오디오 응답: {self._has_audio_response})")
                        if status == "cancelled":
                            # 인터럽트로 취소된 응답: 상태 리셋
                            print("📝 response.done (취소됨) - 상태 리셋")
                            self._is_ai_responding = False
                            self._has_audio_response = False
                        elif not self._has_audio_response:
                            # 텍스트만 있는 응답인 경우에만 여기서 완료 처리
                            print("📝 텍스트 전용 응답 완료")
                            self._is_ai_responding = False
                        else:
                            # 오디오 응답이 있는데 response.audio.done이 오지 않는 경우 대비
                            print("⚠️ 오디오 응답 완료 - response.audio.done 미수신으로 여기서 처리")
                            # 여기서는 상태 변경하지 않고 프론트엔드 신호만 기다림
                    elif t == "error":
                        error_code = data.get("error", {}).get("code")
                        if error_code != "conversation_already_has_active_response":
                            print("error:", data)
                        self._is_ai_responding = False  # 오류 시에도 상태 리셋
                    elif t in EVENTS_TO_IGNORE:
                        pass
                    else:
                        print(f"🔍 처리되지 않은 이벤트: {t}")


__all__ = ["OpenAIVoiceReactAgent"]

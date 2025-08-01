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
    "response.audio_transcript.delta",
    "response.created",
    "response.content_part.added",
    "response.content_part.done",
    "conversation.item.created",
    "response.audio.done",
    "session.created",
    "session.updated",
    "response.done",
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
                additional_headers=headers,  # extra_headers → additional_headers
                open_timeout=60, 
                close_timeout=60,
                ping_interval=None,  # 클라이언트 ping 비활성화
                ping_timeout=None,   # 클라이언트 ping 비활성화
                max_size=2**20     # 최대 메시지 크기
            )
            print(f"WebSocket 연결 성공 (시도 {attempt + 1}/{max_retries})")
            break
        except Exception as e:
            last_error = e
            print(f"WebSocket 연결 실패 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # 지수 백오프
            else:
                print(f"최대 재시도 횟수 초과. 최종 에러: {e}")
                print(f"URL: {url}")
                print(f"Headers: {headers}")
                raise last_error

    try:

        async def send_event(event: dict[str, Any] | str) -> None:
            try:
                formatted_event = json.dumps(event) if isinstance(event, dict) else event
                await websocket.send(formatted_event)
            except websockets.exceptions.ConnectionClosedError as e:
                print(f"WebSocket 연결이 끊어짐: {e}")
                raise
            except Exception as e:
                print(f"메시지 전송 실패: {e}")
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

    async def aconnect(
        self,
        input_stream: AsyncIterator[str],
        send_output_chunk: Callable[[str], Coroutine[Any, Any, None]],
        stop_event: asyncio.Event = None,  # 추가
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
                        "tools": tool_defs,
                    },
                }
            )
            async for stream_key, data_raw in amerge(
                input_mic=input_stream,
                output_speaker=model_receive_stream,
                tool_outputs=tool_executor.output_iterator(),
            ):
                if stop_event and stop_event.is_set():
                    print("응답 중단됨 - 새로운 응답 준비")
                    # 응답만 중단하고 세션은 유지
                    stop_event.clear()
                    # 새로운 응답을 위한 초기화
                    await model_send({"type": "response.create", "response": {}})
                    continue
                try:
                    data = (
                        json.loads(data_raw) if isinstance(data_raw, str) else data_raw
                    )
                except json.JSONDecodeError:
                    print("error decoding data:", data_raw)
                    continue

                if stream_key == "input_mic":
                    # 사용자가 말을 시작하면 AI 응답 중단
                    if isinstance(data, dict) and data.get("type") == "input_audio_buffer.speech_started":
                        print("사용자 음성 감지 - AI 응답 중단")
                        if stop_event:
                            stop_event.set()
                    await model_send(data)
                elif stream_key == "tool_outputs":
                    # print("tool output", data)
                    await model_send(data)
                    await model_send({"type": "response.create", "response": {}})
                elif stream_key == "output_speaker":
                    t = data["type"]
                    
                    # AI 응답 중단 확인
                    if stop_event and stop_event.is_set():
                        if t == "response.audio.delta":
                            print("AI 응답 중단됨")
                            continue
                        elif t == "response.function_call_arguments.done":
                            print("툴 호출 중단됨")
                            continue
                        elif t == "response.audio_transcript.done":
                            print("트랜스크립트 처리 중단됨")
                            continue
                    
                    # 정상 처리
                    if t == "response.audio.delta":
                        await send_output_chunk(json.dumps(data))
                    elif t == "response.function_call_arguments.done":
                        await tool_executor.add_tool_call(data)
                    elif t == "response.audio_transcript.done":
                        print("model:", data["transcript"])
                    elif t == "conversation.item.input_audio_transcription.completed":
                        print("user:", data["transcript"])
                    elif t == "error":
                        error_code = data.get("error", {}).get("code")
                        if error_code != "conversation_already_has_active_response":
                            print("error:", data)
                    elif t in EVENTS_TO_IGNORE:
                        pass
                    else:
                        print(t)


__all__ = ["OpenAIVoiceReactAgent"]

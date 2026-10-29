"""
`/ws/realtime` 프락시의 변환 — 화면(폼 음성 에이전트)은 Realtime 베타 모양으로 말하고 듣는데,
OpenAI 는 정식(GA) 규격만 받는다.

왜 필요한가
    프락시가 받은 글을 그대로 넘기던 때, 화면이 보낸 베타 모양 `session.update` 는
    `Missing required parameter: 'session.type'.` 로 거절됐다. 거절돼도 연결은 살아
    있어서 세션은 OpenAI 기본값(지침 없음 · 도구 없음 · 무음 200 ms)으로 돌았다 —
    에이전트가 폼도 도구도 모른 채 대답하고, 칸은 하나도 채워지지 않았다.
    돌아오는 쪽도 GA 이름(`response.output_audio.delta` …)이라 화면이 소리를 내지 못했다.

    대화방 음성 모드(`/ws`, langchain_openai_voice)는 이미 GA 로 바꿔 두었다. 여기서는
    화면을 건드리지 않고, 프락시가 양쪽 모양을 맞춘다.

    화면 → OpenAI   session.update 를 GA 모양으로 · 사용자 말 전사 켜기 · 덜 성급한 VAD ·
                    OpenAI 가 모르는 글(user_info …)은 보내지 않기 · 진행 중인 응답이
                    없을 때의 response.cancel 은 보내지 않기
    OpenAI → 화면   GA 이벤트 이름을 화면이 듣는 이름으로 · 끼어든 뒤 늦게 온 소리 버리기 ·
                    프락시가 일으킨 것이 뻔한 오류는 삼키고, 나머지 오류는 그대로 넘기기
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_openai_voice import GA_EVENT_ALIASES

# OpenAI Realtime(GA)이 받는 클라이언트 이벤트. 이 밖의 것은 OpenAI 로 보내지 않는다
# (보내면 `Invalid value: 'user_info'. Supported values are: …` 오류가 화면으로 돌아온다).
OPENAI_CLIENT_EVENTS = {
    "session.update",
    "input_audio_buffer.append",
    "input_audio_buffer.commit",
    "input_audio_buffer.clear",
    "conversation.item.create",
    "conversation.item.retrieve",
    "conversation.item.truncate",
    "conversation.item.delete",
    "response.create",
    "response.cancel",
    "output_audio_buffer.clear",
}

# 프락시나 화면의 습관이 만든 것이 뻔한 오류 — 화면에 띄울 일이 아니다.
#   response_cancel_not_active      끼어들기 취소는 서버 VAD(interrupt_response)가 이미 했다
#   input_audio_buffer_commit_empty 마이크를 끌 때 화면이 보내는 commit — 서버 VAD 가 이미 넘겼다
BENIGN_ERROR_CODES = {"response_cancel_not_active", "input_audio_buffer_commit_empty"}

# 베타 오디오 형식 이름 → GA 형식
AUDIO_FORMATS = {
    "pcm16": {"type": "audio/pcm", "rate": 24000},
    "g711_ulaw": {"type": "audio/pcmu"},
    "g711_alaw": {"type": "audio/pcma"},
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def default_turn_detection() -> dict:
    """
    서버 VAD 기본값. OpenAI 기본(무음 200 ms)은 「…들어왔어요. 담당자는…」 처럼 문장 사이
    쉼(0.3~0.5초)에서도 턴을 끊어, 한 말이 두 턴이 되고 앞 턴 대답은 곧바로 취소됐다.
    """
    return {
        "type": "server_vad",
        "threshold": _env_float("REALTIME_VAD_THRESHOLD", 0.6),
        "prefix_padding_ms": 300,
        "silence_duration_ms": _env_int("REALTIME_VAD_SILENCE_MS", 700),
        "create_response": True,
        "interrupt_response": True,
    }


def default_transcription() -> dict:
    """사용자가 한 말의 전사 — 화면(과 로그)에 사람 말을 보이려면 켜야 온다."""
    return {"model": os.getenv("REALTIME_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")}


def _audio_format(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return dict(AUDIO_FORMATS.get(value, {"type": value}))
    return None


def _tool_names(tools: Any) -> list[str]:
    return [t.get("name") for t in (tools or []) if isinstance(t, dict) and t.get("name")]


def voice_rules(tools: Any, user_info: dict | None, instructions: str) -> str:
    """
    음성으로 폼을 채울 때의 규칙. 화면의 지침은 글 대화용(「JSON 패치 제안 형식 …」)이라
    음성에서는 JSON 을 소리 내 읽거나, 도구를 부르지 않고 말로만 대답하기 쉽다.
    """
    names = set(_tool_names(tools))
    lines = ["[음성 대화 규칙]", "- 지금은 음성 대화다. JSON·필드 name·코드는 소리 내어 읽지 않는다. 한두 문장으로 짧게 말한다."]
    if "update_form_fields" in names:
        lines.append(
            "- 사용자가 폼에 넣을 값을 말하면 되묻기 전에 곧바로 update_form_fields 로 그 필드들을 채운다"
            "(한 번에 여러 개). 값을 고쳐 말하면 바뀐 필드만 다시 채운다. 채운 뒤 무엇을 채웠는지 짧게 확인하고,"
            " 아직 비어 있는 항목이 있으면 하나만 묻는다."
        )
    if "submit_form" in names:
        lines.append("- 사용자가 제출을 요청하면 submit_form(confirm=true) 을 호출하고, 결과를 짧게 알린다.")
    # 화면이 보낸 user_info 는 OpenAI 로 가지 않는다 — 지침에 아직 없으면 여기서 알려 준다
    info = user_info or {}
    who = [f"{k}={info[k]}" for k in ("user_name", "email", "process_name", "activity_name") if info.get(k)]
    if any(info.get(k) and str(info[k]) not in instructions for k in ("user_name", "email")):
        lines.append("- 사용자·업무: " + ", ".join(who))
    return "\n".join(lines)


def to_ga_session(beta: dict, user_info: dict | None = None) -> dict:
    """
    화면의 베타 모양 session 을 GA 모양으로.

        베타                                   GA
        input_audio_format: 'pcm16'            audio.input.format  {type: audio/pcm, rate: 24000}
        output_audio_format                    audio.output.format
        voice                                  audio.output.voice
        turn_detection                         audio.input.turn_detection
        input_audio_transcription              audio.input.transcription
        input_audio_noise_reduction            audio.input.noise_reduction
        modalities: ['text','audio']           output_modalities: ['audio']  (GA 는 하나만 — 소리면 전사도 온다)
        max_response_output_tokens             max_output_tokens
        temperature                            (GA 에 없음 — 버린다)
    """
    beta = dict(beta or {})
    already_ga = beta.get("type") == "realtime"
    audio = beta.pop("audio", None) or {}
    a_in = dict(audio.get("input") or {})
    a_out = dict(audio.get("output") or {})

    fmt = _audio_format(beta.pop("input_audio_format", None))
    if fmt and "format" not in a_in:
        a_in["format"] = fmt
    fmt = _audio_format(beta.pop("output_audio_format", None))
    if fmt and "format" not in a_out:
        a_out["format"] = fmt
    voice = beta.pop("voice", None)
    if voice and "voice" not in a_out:
        a_out["voice"] = voice
    speed = beta.pop("speed", None)
    if speed and "speed" not in a_out:
        a_out["speed"] = speed

    td_given = "turn_detection" in beta
    td = beta.pop("turn_detection", None)
    if "turn_detection" not in a_in:
        if isinstance(td, dict):
            a_in["turn_detection"] = {**default_turn_detection(), **td}
        elif td_given:  # 화면이 일부러 끈 경우(null) — 말 차례를 화면이 정한다
            a_in["turn_detection"] = None
        else:
            a_in["turn_detection"] = default_turn_detection()
    tr = beta.pop("input_audio_transcription", None)
    if not a_in.get("transcription"):
        a_in["transcription"] = tr if isinstance(tr, dict) and tr.get("model") else default_transcription()
    nr = beta.pop("input_audio_noise_reduction", None)
    if nr and "noise_reduction" not in a_in:
        a_in["noise_reduction"] = nr

    a_in.setdefault("format", dict(AUDIO_FORMATS["pcm16"]))
    a_out.setdefault("format", dict(AUDIO_FORMATS["pcm16"]))

    modalities = beta.pop("modalities", None)
    out: dict[str, Any] = {"type": "realtime"}
    if "output_modalities" in beta:
        out["output_modalities"] = beta.pop("output_modalities")
    elif modalities:
        out["output_modalities"] = ["audio"] if "audio" in modalities else ["text"]
    mrot = beta.pop("max_response_output_tokens", None)
    if mrot is not None and "max_output_tokens" not in beta:
        out["max_output_tokens"] = mrot
    beta.pop("temperature", None)
    beta.pop("type", None)

    instructions = beta.pop("instructions", None) or ""
    if not already_ga:  # GA 모양으로 보내는 화면은 제 지침을 이미 음성에 맞춰 둔 것으로 본다
        instructions = (instructions + "\n\n" + voice_rules(beta.get("tools"), user_info, instructions)).strip()
    out["instructions"] = instructions
    out.update(beta)  # tools · tool_choice · 그 밖에 GA 에서도 같은 이름인 것
    out["audio"] = {"input": a_in, "output": a_out}
    return out


def _content_for_ga(item: dict) -> dict:
    """지난 대화의 에이전트 말은 GA 에서 `output_text` — 예전 이름 `text` 는 그 항목만 거절된다."""
    if not isinstance(item, dict) or item.get("type") != "message":
        return item
    role = item.get("role")
    content = []
    for c in item.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text":
            c = {**c, "type": "output_text" if role == "assistant" else "input_text"}
        elif isinstance(c, dict) and c.get("type") == "audio" and role == "assistant":
            c = {**c, "type": "output_audio"}
        content.append(c)
    return {**item, "content": content}


@dataclass
class ProxyState:
    """한 연결의 상태 — 응답이 진행 중인지, 누가 끼어들었는지, 화면이 알려 준 사용자."""

    user_info: dict = field(default_factory=dict)
    response_active: bool = False
    response_id: str | None = None
    pending_response_create: dict | None = None
    user_speaking: bool = False
    interrupt_response: bool = True
    dropped_response_ids: set = field(default_factory=set)
    session_sent: bool = False
    log: list = field(default_factory=list)

    def note(self, text: str) -> None:
        # OpenAI 오류 글에는 키 끝자리가 섞여 올 수 있다(「Incorrect API key provided: sk-…」)
        self.log.append(re.sub(r"sk-[A-Za-z0-9_\-*]{4,}", "sk-***", text))


def client_to_openai(event: Any, state: ProxyState) -> list[dict]:
    """화면이 보낸 이벤트 하나 → OpenAI 로 보낼 이벤트들(없으면 빈 목록)."""
    if not isinstance(event, dict):
        return []
    t = event.get("type")
    if t == "user_info":
        state.user_info = {k: v for k, v in event.items() if k != "type"}
        state.note("user_info kept (not forwarded)")
        return []
    if t not in OPENAI_CLIENT_EVENTS:
        state.note(f"dropped non-OpenAI event {t!r}")
        return []
    if t == "session.update":
        session = to_ga_session(event.get("session") or {}, state.user_info)
        td = (session.get("audio") or {}).get("input", {}).get("turn_detection")
        state.interrupt_response = bool(td) and td.get("interrupt_response", True)
        state.session_sent = True
        state.note(
            "session.update -> GA (tools: %s; vad: %s; transcription: %s)"
            % (
                ", ".join(_tool_names(session.get("tools"))) or "-",
                f"{td.get('type')} {td.get('silence_duration_ms')}ms" if td else "off",
                (session["audio"]["input"].get("transcription") or {}).get("model"),
            )
        )
        out = {"type": "session.update", "session": session}
        if event.get("event_id"):
            out["event_id"] = event["event_id"]
        return [out]
    if t == "response.cancel":
        # 진행 중인 응답이 없거나, 사람이 말을 시작해 서버 VAD 가 이미 끊었다면 보내지 않는다
        # (보내면 `Cancellation failed: no active response found` 가 돌아온다).
        if not state.response_active or (state.interrupt_response and state.user_speaking):
            state.note("dropped response.cancel (no active response / server VAD interrupts)")
            return []
        return [event]
    if t == "response.create":
        resp = dict(event.get("response") or {})
        if "modalities" in resp:
            m = resp.pop("modalities")
            resp.setdefault("output_modalities", ["audio"] if "audio" in (m or []) else ["text"])
        for k in ("voice", "output_audio_format", "temperature", "max_response_output_tokens"):
            resp.pop(k, None)
        out = {**event, "response": resp} if resp or "response" in event else dict(event)
        if state.response_active:
            # 응답이 끝나면 보낸다 — 지금 보내면 `conversation_already_has_active_response`
            state.pending_response_create = out
            state.note("response.create deferred until the active response is done")
            return []
        return [out]
    if t == "conversation.item.create":
        return [{**event, "item": _content_for_ga(event.get("item") or {})}]
    return [event]


def openai_to_client(event: Any, state: ProxyState) -> tuple[dict | None, list[dict]]:
    """
    OpenAI 가 보낸 이벤트 하나 → (화면으로 보낼 것 또는 None, OpenAI 로 곧바로 다시 보낼 것들).
    """
    if not isinstance(event, dict):
        return event, []
    t = event.get("type")
    back: list[dict] = []

    if t == "response.created":
        state.response_active = True
        state.response_id = (event.get("response") or {}).get("id")
    elif t == "response.done":
        rid = (event.get("response") or {}).get("id")
        state.response_active = False
        state.response_id = None
        state.dropped_response_ids.discard(rid)
        if state.pending_response_create is not None:
            back.append(state.pending_response_create)
            state.pending_response_create = None
        resp = event.get("response") or {}
        calls = [o.get("name") for o in resp.get("output") or [] if o.get("type") == "function_call"]
        state.note(f"response.done {resp.get('status')}" + (f" calls={calls}" if calls else ""))
    elif t == "input_audio_buffer.speech_started":
        state.user_speaking = True
        if state.response_active and state.interrupt_response and state.response_id:
            # 서버가 이 응답을 끊는다 — 그 사이 이미 날아오던 소리·글은 화면으로 보내지 않는다
            state.dropped_response_ids.add(state.response_id)
    elif t == "input_audio_buffer.speech_stopped":
        state.user_speaking = False
    elif t == "session.updated":
        s = event.get("session") or {}
        state.note(f"session.updated tools={_tool_names(s.get('tools'))}")
    elif t == "error":
        err = event.get("error") or {}
        code = err.get("code")
        if code in BENIGN_ERROR_CODES:
            state.note(f"swallowed error {code}")
            return None, back
        if code == "conversation_already_has_active_response":
            state.note("swallowed error conversation_already_has_active_response (will retry after response.done)")
            if state.pending_response_create is None:
                state.pending_response_create = {"type": "response.create"}
            state.response_active = True
            return None, back
        state.note(f"error {code}: {err.get('message')}")
        return event, back

    rid = event.get("response_id")
    if rid and rid in state.dropped_response_ids and t and ("delta" in t):
        return None, back

    legacy = GA_EVENT_ALIASES.get(t)
    if legacy:
        event = {**event, "type": legacy}
    return event, back


def parse(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None

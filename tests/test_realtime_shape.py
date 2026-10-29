"""
정식(GA) Realtime 규격으로 붙는지.

왜 이 시험이 있는가
    OpenAI 가 Realtime 을 정식으로 올리면서 **베타 모양을 껐다.** 옛 모델과
    `OpenAI-Beta: realtime=v1` 헤더로 연결하면
    `invalid_request_error.beta_api_shape_disabled` 로 끊긴다.

    끊기는 자리가 나빴다. 화면에는 "연결 중" 에서 멈춘 것처럼 보이고 오류가
    드러나지 않아, 서버 로그를 보기 전에는 무엇이 잘못됐는지 알 수 없었다.

    그래서 세 가지를 시험으로 고정한다.
      1. 베타 헤더를 보내지 않는 것
      2. 정식 모델을 쓰는 것
      3. 정식 이벤트 이름을 화면이 아는 이름으로 되돌리는 것
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import langchain_openai_voice as voice  # noqa: E402


def test_베타_헤더를_보내지_않는다():
    headers = voice.realtime_headers("sk-test")

    assert headers == {"Authorization": "Bearer sk-test"}, "베타 헤더를 붙이면 정식 규격에서 거절당한다"


def test_정식_모델을_쓴다():
    assert voice.DEFAULT_MODEL == "gpt-realtime"


def test_정식_이벤트_이름을_예전_이름으로_되돌린다():
    """
    화면(웹·앱)은 예전 이름으로 듣는다. 양쪽을 동시에 고치면 배포 순서가
    어긋나는 동안 음성이 통째로 멎는다.
    """
    cases = {
        "response.output_audio.delta": "response.audio.delta",
        "response.output_audio.done": "response.audio.done",
        "response.output_audio_transcript.delta": "response.audio_transcript.delta",
        "response.output_audio_transcript.done": "response.audio_transcript.done",
    }

    for ga, legacy in cases.items():
        assert voice.normalize_event({"type": ga, "delta": "x"})["type"] == legacy


def test_되돌릴_때_나머지_내용은_그대로_둔다():
    out = voice.normalize_event({"type": "response.output_audio.delta", "delta": "abc"})

    assert out["delta"] == "abc"


def test_이름이_같은_이벤트는_건드리지_않는다():
    """사용자 발화 전사는 정식 규격에서도 이름이 그대로다."""
    same = {"type": "conversation.item.input_audio_transcription.completed", "transcript": "안녕"}

    assert voice.normalize_event(same) == same


def test_모르는_모양이_와도_깨지지_않는다():
    assert voice.normalize_event({}) == {}
    assert voice.normalize_event(None) is None
    assert voice.normalize_event("문자열") == "문자열"


def test_정식_규격에서_새로_생긴_이벤트는_흘려보낸다():
    """로그를 채우기만 하고 우리가 쓸 일이 없다."""
    assert "conversation.item.added" in voice.EVENTS_TO_IGNORE
    assert "conversation.item.done" in voice.EVENTS_TO_IGNORE


def test_오디오_설정을_session_audio_아래에_보낸다():
    """
    정식 규격은 오디오 설정을 `session.audio` 아래로 옮겼다. 예전처럼 평평하게
    보내면 **조용히 무시된다** — 사용자가 말해도 아무 반응이 없고 전사도 오지
    않는데, 오류는 나지 않아 원인이 드러나지 않는다.
    """
    source = inspect.getsource(voice.OpenAIVoiceReactAgent.aconnect)

    assert '"type": "realtime"' in source
    assert '"audio": {' in source
    # 평평한 옛 자리에 두면 안 된다.
    assert '"input_audio_transcription": {' not in source


def test_지난_대화를_다시_넣을_때_쓰는_내용_종류():
    """
    정식 규격에서 에이전트가 한 말은 `output_text` 다. 예전 이름 `text` 로 보내면
    그 항목만 거절당하는데, 세션은 살아 있어서 화면에는 아무 표시가 없다.
    대신 에이전트가 방금 자기가 한 말을 모르는 채로 대화를 시작한다.
    """
    assert voice.history_content_type("user") == "input_text"
    assert voice.history_content_type("assistant") == "output_text"


def test_에이전트_말에_예전_이름을_쓰지_않는다():
    assert voice.history_content_type("assistant") != "text"


# ---------------------------------------------------------------------------
# `/ws/realtime` 프락시(업무 폼의 「음성 에이전트」)
#
# 화면(FormRealtimeAssistant.vue)은 베타 모양으로 말하고 듣는다. 프락시가 그대로 넘기던
# 때 OpenAI 는 session.update 를 `Missing required parameter: 'session.type'.` 로
# 거절했고, 연결은 살아 있어 세션은 기본값(지침·도구 없음, 무음 200 ms)으로 돌았다 —
# 에이전트가 폼을 모른 채 대답하고 칸은 하나도 채워지지 않았다. 소리도 나지 않았다
# (GA 이름 `response.output_audio.delta` 를 화면이 모른다).

from server import realtime_proxy as rp  # noqa: E402


def _화면이_보내는_session_update():
    """FormRealtimeAssistant.vue bootstrapSession 이 보내는 그대로."""
    return {
        "type": "session.update",
        "session": {
            "instructions": "너는 프로세스 작업 폼 작성 보조 어시스턴트다.\n폼 스키마(JSON): [{\"name\":\"customer_name\"}]",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "voice": "alloy",
            "modalities": ["text", "audio"],
            "tools": [
                {"type": "function", "name": "update_form_fields", "description": "폼 채우기", "parameters": {"type": "object", "properties": {}}},
                {"type": "function", "name": "submit_form", "description": "제출", "parameters": {"type": "object", "properties": {}}},
            ],
            "tool_choice": "auto",
        },
    }


def _보낸_session(state=None):
    out = rp.client_to_openai(_화면이_보내는_session_update(), state or rp.ProxyState())
    assert len(out) == 1 and out[0]["type"] == "session.update"
    return out[0]["session"]


def test_베타_session_update_를_GA_모양으로_바꾼다():
    s = _보낸_session()

    assert s["type"] == "realtime", "session.type 이 없으면 통째로 거절된다"
    assert s["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert s["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert s["audio"]["output"]["voice"] == "alloy"
    assert s["output_modalities"] == ["audio"], "GA 는 하나만 — 소리를 고르면 전사도 온다"
    for beta_only in ("input_audio_format", "output_audio_format", "voice", "modalities"):
        assert beta_only not in s, f"{beta_only} 는 GA 에서 알 수 없는 인자다"


def test_폼_도구와_지침이_들어간다():
    s = _보낸_session()

    assert [t["name"] for t in s["tools"]] == ["update_form_fields", "submit_form"]
    assert s["tool_choice"] == "auto"
    assert s["instructions"].startswith("너는 프로세스 작업 폼 작성 보조 어시스턴트다."), "화면의 지침(폼 스키마)은 그대로"
    assert "update_form_fields" in s["instructions"] and "submit_form" in s["instructions"], "음성으로 도구를 부르라는 규칙이 붙는다"


def test_사람_말_전사를_켠다():
    s = _보낸_session()

    assert s["audio"]["input"]["transcription"]["model"]


def test_한_문장이_두_턴으로_끊기지_않게_무음을_길게_본다():
    """기본 200 ms 는 「…들어왔어요. 담당자는…」 사이 쉼(0.3~0.5초)에서 턴을 끊었다."""
    td = _보낸_session()["audio"]["input"]["turn_detection"]

    assert td["type"] == "server_vad"
    assert 600 <= td["silence_duration_ms"] <= 800
    assert td["interrupt_response"] is True and td["create_response"] is True


def test_화면이_턴_감지를_끄면_끈_채로_둔다():
    ev = _화면이_보내는_session_update()
    ev["session"]["turn_detection"] = None

    s = rp.client_to_openai(ev, rp.ProxyState())[0]["session"]

    assert s["audio"]["input"]["turn_detection"] is None


def test_user_info_는_OpenAI_로_보내지_않고_지침에_쓴다():
    state = rp.ProxyState()

    assert rp.client_to_openai({"type": "user_info", "email": "a@b.c", "user_name": "장진영", "tenant_id": "localhost"}, state) == []
    s = _보낸_session(state)

    assert "장진영" in s["instructions"] and "a@b.c" in s["instructions"]


def test_OpenAI_가_모르는_이벤트는_보내지_않는다():
    assert rp.client_to_openai({"type": "client_audio_playback_complete"}, rp.ProxyState()) == []


def test_오디오는_그대로_보낸다():
    ev = {"type": "input_audio_buffer.append", "audio": "AAAA"}

    assert rp.client_to_openai(ev, rp.ProxyState()) == [ev]


def test_진행_중인_응답이_없으면_response_cancel_을_보내지_않는다():
    """화면은 마이크를 켤 때와 사람이 말을 시작할 때마다 취소를 보낸다 → `no active response found`."""
    state = rp.ProxyState()

    assert rp.client_to_openai({"type": "response.cancel"}, state) == []


def test_응답_중이면_취소를_보낸다_단_사람이_끼어들면_서버가_끊는다():
    state = rp.ProxyState()
    rp.openai_to_client({"type": "response.created", "response": {"id": "r1"}}, state)

    assert rp.client_to_openai({"type": "response.cancel"}, state) == [{"type": "response.cancel"}]

    rp.openai_to_client({"type": "input_audio_buffer.speech_started"}, state)
    assert rp.client_to_openai({"type": "response.cancel"}, state) == [], "interrupt_response 가 이미 끊었다"


def test_응답_중에_온_response_create_는_끝난_뒤에_보낸다():
    state = rp.ProxyState()
    rp.openai_to_client({"type": "response.created", "response": {"id": "r1"}}, state)

    assert rp.client_to_openai({"type": "response.create"}, state) == []

    to_client, to_openai = rp.openai_to_client({"type": "response.done", "response": {"id": "r1", "status": "completed", "output": []}}, state)
    assert to_client["type"] == "response.done", "화면은 response.done 에서 도구 호출을 처리한다"
    assert to_openai == [{"type": "response.create"}]


def test_GA_이벤트_이름을_화면이_듣는_이름으로_되돌린다():
    state = rp.ProxyState()
    for ga, legacy in voice.GA_EVENT_ALIASES.items():
        out, _ = rp.openai_to_client({"type": ga, "delta": "x"}, state)
        assert out["type"] == legacy


def test_끼어든_뒤_늦게_온_소리는_버린다():
    state = rp.ProxyState()
    rp.openai_to_client({"type": "response.created", "response": {"id": "r1"}}, state)
    rp.openai_to_client({"type": "input_audio_buffer.speech_started"}, state)

    out, _ = rp.openai_to_client({"type": "response.output_audio.delta", "response_id": "r1", "delta": "x"}, state)
    assert out is None

    rp.openai_to_client({"type": "response.done", "response": {"id": "r1", "status": "cancelled"}}, state)
    rp.openai_to_client({"type": "response.created", "response": {"id": "r2"}}, state)
    out, _ = rp.openai_to_client({"type": "response.output_audio.delta", "response_id": "r2", "delta": "y"}, state)
    assert out["type"] == "response.audio.delta"


def test_오류는_화면으로_넘긴다():
    ev = {"type": "error", "error": {"type": "invalid_request_error", "code": "missing_required_parameter", "message": "Missing required parameter: 'session.type'."}}

    out, _ = rp.openai_to_client(ev, rp.ProxyState())

    assert out == ev


def test_프락시가_일으킨_것이_뻔한_오류는_삼킨다():
    for code in ("response_cancel_not_active", "input_audio_buffer_commit_empty"):
        out, _ = rp.openai_to_client({"type": "error", "error": {"code": code, "message": "…"}}, rp.ProxyState())
        assert out is None


def test_이미_응답_중이라_거절된_response_create_는_끝난_뒤_다시_보낸다():
    state = rp.ProxyState()
    out, _ = rp.openai_to_client({"type": "error", "error": {"code": "conversation_already_has_active_response", "message": "…"}}, state)
    assert out is None

    _, to_openai = rp.openai_to_client({"type": "response.done", "response": {"id": "r1", "status": "completed"}}, state)
    assert to_openai == [{"type": "response.create"}]


def test_지난_대화의_에이전트_말은_output_text_로():
    ev = {"type": "conversation.item.create", "item": {"type": "message", "role": "assistant", "content": [{"type": "text", "text": "네"}]}}

    out = rp.client_to_openai(ev, rp.ProxyState())

    assert out[0]["item"]["content"][0]["type"] == "output_text"


def test_로그에_키를_남기지_않는다():
    state = rp.ProxyState()
    rp.openai_to_client({"type": "error", "error": {"code": "invalid_api_key", "message": "Incorrect API key provided: sk-proj-abcd****wxyz."}}, state)

    assert all("abcd" not in line for line in state.log)


def test_프락시가_변환을_거친다():
    import server.app as app

    up = inspect.getsource(app._client_to_openai)
    down = inspect.getsource(app._openai_to_client)
    assert "client_to_openai(" in up, "받은 글을 그대로 넘기면 GA 가 session.update 를 거절한다"
    assert "openai_to_client(" in down

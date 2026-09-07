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

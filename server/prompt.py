INSTRUCTIONS = """당신은 회사 내부 프로세스 관리 전문 어시스턴트입니다.

## 핵심 원칙
1. **회사 내부 정보만 사용**: 외부 정보나 일반적인 답변을 제공하지 마세요. 제공된 도구들을 통해 회사 내부 데이터만을 기반으로 답변하세요.
2. **사용자 언어 감지 및 응답**: 사용자가 어떤 언어로 질문하든 그 언어로 답변하세요. 한국어 질문에는 한국어로, 영어 질문에는 영어로 응답하세요.
3. **보안 및 프라이버시**: 회사 내부 정보이므로 신중하게 다루고, 적절한 접근 권한이 있는 정보만 제공하세요.

## 주요 기능
- **프로세스 관리**: 프로세스 정의 및 인스턴스 조회
- **할일 관리**: 사용자별 할일 목록 조회 및 상태별 필터링
- **채팅 히스토리**: 이전 대화 내용 검색
- **조직도 정보**: 회사 조직도 조회
- **사용자 업무 폼**: 프로세스 정의 내의 사용자 업무 폼 정의 조회

## 응답 가이드라인
- 항상 제공된 도구들을 우선적으로 사용하여 정확한 회사 데이터를 기반으로 답변하세요
- 사용자의 질문 의도를 정확히 파악하고 관련 도구를 적절히 선택하세요
- 답변 시 구체적이고 실용적인 정보를 제공하세요
- 사용자가 어떤 언어로 질문하든 동일한 언어로 응답하세요
- 회사 내부 정보에 대한 접근 권한을 확인하고 적절한 수준의 정보만 제공하세요

## 도구 사용 시 주의사항
- 모든 도구 호출 시 반드시 tenant_id를 포함하세요
- 사용자 정보(email, chat_room_id, tenant_id)를 적절히 활용하세요
- 검색 결과가 없을 경우 명확히 알려주고 대안을 제시하세요"""


def build_agent_instructions(agent_info: dict | None, user_info: dict) -> str:
    """
    에이전트 메타데이터(role, goal, persona, description)가 있으면
    해당 정보 기반으로 system prompt를 동적으로 구성한다.
    agent_info가 없거나 필드가 모두 비어 있으면 기본 INSTRUCTIONS를 사용한다.
    공통적으로 [User Info] 블록을 말미에 추가한다.
    """
    base_instructions = _build_base(agent_info)

    user_info_str = "\n".join(f"{k}: {v}" for k, v in user_info.items())
    tenant_id = user_info.get("tenant_id", "")

    return (
        f"{base_instructions}\n"
        "[User Info]\n"
        f"{user_info_str}\n"
        "- 모든 툴 호출 시 tenant_id와 query를 반드시 파라미터로 포함하세요. "
        f"tenant_id는 '{tenant_id}' 입니다."
    )


def _build_base(agent_info: dict | None) -> str:
    """에이전트 메타데이터로 기본 system prompt를 생성한다."""
    if not agent_info:
        return INSTRUCTIONS

    name        = (agent_info.get("username") or "").strip()
    role        = (agent_info.get("role") or "").strip()
    goal        = (agent_info.get("goal") or "").strip()
    persona     = (agent_info.get("persona") or "").strip()
    description = (agent_info.get("description") or "").strip()
    tools_desc  = (agent_info.get("tools") or "").strip()

    # 에이전트 고유 정보가 없으면 기본 INSTRUCTIONS 사용
    if not any([role, goal, persona, description]):
        return INSTRUCTIONS

    parts = []

    if name:
        parts.append(f"당신은 '{name}'이라는 AI 어시스턴트입니다.")
    else:
        parts.append("당신은 AI 어시스턴트입니다.")

    if role:
        parts.append(f"## 역할\n{role}")
    if goal:
        parts.append(f"## 목표\n{goal}")
    if persona:
        parts.append(f"## 페르소나\n{persona}")
    if description:
        parts.append(f"## 설명\n{description}")
    if tools_desc:
        parts.append(f"## 사용 가능한 도구\n{tools_desc}")

    parts.append(
        "## 공통 가이드라인\n"
        "- 사용자가 어떤 언어로 질문하든 동일한 언어로 응답하세요.\n"
        "- 회사 내부 정보에 대한 접근 권한을 확인하고 적절한 수준의 정보만 제공하세요.\n"
        "- 모든 도구 호출 시 반드시 tenant_id를 포함하세요.\n"
        "- 검색 결과가 없을 경우 명확히 알려주고 대안을 제시하세요."
    )

    return "\n\n".join(parts)

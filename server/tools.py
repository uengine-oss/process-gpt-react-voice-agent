from langchain_core.tools import tool
from server.database import (
    fetch_todolist_by_user_id,
    fetch_todolist_by_user_id_and_status,
    fetch_process_instance_list,
    fetch_all_ui_definition,
    fetch_ui_definition,
    fetch_ui_definition_by_activity_id,
    fetch_organization_chart,
    get_vector_store,
    fetch_process_definition
)

# === 데이터 조회 관련 도구 ===

@tool
def get_process_definitions(query: str, tenant_id: str):
    """
    프로세스 정의 유사도 검색 도구
    Args:
        query (str): 검색할 텍스트
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 유사한 프로세스 정의 목록
    Example:
        get_process_definitions(query="휴가 신청", tenant_id="company123")
    """
    try:
        vector_store = get_vector_store()
        proc_def_list = vector_store.similarity_search(
            query,
            k=3,
            filter={"tenant_id": tenant_id, "type": "process_definition"}
        )
        return proc_def_list
    except Exception as vector_error:
        print(f"Vector search failed in get_process_definitions: {vector_error}")
        return []

@tool
def get_process_definition(def_id: str, tenant_id: str):

    """
    특정 프로세스 정의 조회 도구
    Args:
        def_id (str): 프로세스 정의 ID
        tenant_id (str): 회사(테넌트) ID
    Returns:
        dict: 프로세스 정의 JSON
    Example:
        get_process_definition(def_id="proc_def_123", tenant_id="company123")
    """
    try:
        return fetch_process_definition(def_id, tenant_id)
    except Exception as e:
        raise Exception(str(e))

@tool
def get_process_instances(query: str, tenant_id: str):
    """
    프로세스 인스턴스 유사도 검색 도구
    Args:
        query (str): 검색할 텍스트
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 유사한 프로세스 인스턴스 목록
    Example:
        get_process_instances(query="홍길동의 인스턴스", tenant_id="company123")
    """
    try:
        vector_store = get_vector_store()
        proc_inst_list = vector_store.similarity_search(
            query,
            k=3,
            filter={"tenant_id": tenant_id, "type": "process_instance"}
        )
        return proc_inst_list
    except Exception as vector_error:
        print(f"Vector search failed in get_process_instances: {vector_error}")
        return []

@tool
def get_chat_history(query: str, chat_room_id: str, tenant_id: str):
    """
    채팅 히스토리 유사도 검색 도구
    Args:
        query (str): 검색할 텍스트
        chat_room_id (str): 채팅방 ID
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 유사한 채팅 히스토리 목록
    Example:
        get_chat_history(query="회의록", chat_room_id="room123", tenant_id="company123")
    """
    if not chat_room_id:
        return []
    try:
        vector_store = get_vector_store()
        chat_history = vector_store.similarity_search(
            query,
            k=3,
            filter={"tenant_id": tenant_id, "chat_room_id": chat_room_id}
        )
        return chat_history
    except Exception as vector_error:
        print(f"Vector search failed: {vector_error}")
        return []

@tool
def fetch_todolist_by_user_id_tool(email: str, tenant_id: str):
    """
    유저 이메일로 할일 목록을 조회하는 도구
    Args:
        email (str): 사용자 이메일
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 할일 목록
    Example:
        fetch_todolist(email="user@email.com", tenant_id="company123")
    """
    try:
        return fetch_todolist_by_user_id(email, tenant_id)
    except Exception as e:
        raise Exception(str(e))

@tool
def fetch_todolist_by_user_id_and_status_tool(email: str, status: str, tenant_id: str):
    """
    유저 이메일과 상태로 할일 목록을 조회하는 도구
    Args:
        email (str): 사용자 이메일
        status (str): 할일 상태 (TODO, IN_PROGRESS, PENDING, DONE)
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 할일 목록
    Example:
        fetch_todolist_by_user_id_and_status_tool(email="user@email.com", status="TODO", tenant_id="company123")
    """
    try:
        return fetch_todolist_by_user_id_and_status(email, status, tenant_id)
    except Exception as e:
        raise Exception(str(e))

@tool
def fetch_process_instance_list_tool(email: str, tenant_id: str):
    """
    유저 이메일로 프로세스 인스턴스 목록을 조회하는 도구
    Args:
        email (str): 사용자 이메일
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 프로세스 인스턴스 목록(진행중(RUNNING), 완료됨(COMPLETED) 모두 포함)
    Example:
        fetch_process_instance_list_tool(email="user@email.com", tenant_id="company123")
    """
    try:
        return fetch_process_instance_list(email, tenant_id)
    except Exception as e:
        raise Exception(str(e))

@tool
def fetch_all_ui_definitions_tool(tenant_id: str):
    """
    모든 프로세스 정의 내의 사용자 업무 폼 정의 목록을 조회하는 도구
    Args:
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 사용자 업무 폼 정의 목록
    Example:
        fetch_all_ui_definitions_tool(tenant_id="company123")
    """
    try:
        return fetch_all_ui_definition(tenant_id)
    except Exception as e:
        raise Exception(str(e))

@tool
def fetch_ui_definition_tool(def_id: str, tenant_id: str):
    """
    특정 프로세스 정의 내의 사용자 업무 폼 정의 목록을 조회하는 도구
    Args:
        def_id (str): 프로세스 정의 ID
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 사용자 업무 폼 정의 목록
    Example:
        fetch_ui_definition_tool(def_id="proc_def_123", tenant_id="company123")
    """
    try:
        return fetch_ui_definition(def_id, tenant_id)
    except Exception as e:
        raise Exception(str(e))

@tool
def fetch_ui_definition_by_activity_id_tool(def_id: str, activity_id: str, tenant_id: str):
    """
    특정 프로세스 정의 내의 특정 액티비티(=사용자 업무) 폼 정의 목록을 조회하는 도구
    Args:
        def_id (str): 프로세스 정의 ID
        activity_id (str): 액티비티 ID
        tenant_id (str): 회사(테넌트) ID
    Returns:
        list: 사용자 업무 폼 정의 목록
    Example:
        fetch_ui_definition_by_activity_id_tool(def_id="proc_def_123", activity_id="activity_123", tenant_id="company123")
    """
    try:
        return fetch_ui_definition_by_activity_id(def_id, activity_id, tenant_id)
    except Exception as e:
        raise Exception(str(e))

@tool
def fetch_organization_chart_tool(tenant_id: str):
    """
    조직도 정보를 조회하는 도구
    Args:
        tenant_id (str): 회사(테넌트) ID
    Returns:
        dict: 조직도 정보
    Example:
        fetch_organization_chart_tool(tenant_id="company123")
    """
    try:
        return fetch_organization_chart(tenant_id)
    except Exception as e:
        raise Exception(str(e))

# === End of 데이터 조회 관련 도구 === 

TOOLS = [get_process_definitions, get_process_definition, get_process_instances, get_chat_history, fetch_todolist_by_user_id_tool, fetch_todolist_by_user_id_and_status_tool, fetch_process_instance_list_tool, fetch_all_ui_definitions_tool, fetch_ui_definition_tool, fetch_ui_definition_by_activity_id_tool, fetch_organization_chart_tool]
import logging
import os

from supabase import create_client, Client
from pydantic import BaseModel, validator
from typing import Any, Dict, List, Optional

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore

from server.process_definition import ProcessDefinition, load_process_definition, UIDefinition

from datetime import datetime
from contextvars import ContextVar
from dotenv import load_dotenv

supabase_client_var = ContextVar('supabase', default=None)
subdomain_var = ContextVar('subdomain', default='localhost')

logger = logging.getLogger("server.database")

def setting_database():
    try:
        if os.getenv("ENV") != "production":
            load_dotenv()
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        supabase: Client = create_client(supabase_url, supabase_key)
        supabase_client_var.set(supabase)
        
    except Exception as e:
        logger.error(f"Database configuration error: {e}")

setting_database()    

def db_client_signin(user_info: dict):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        response = supabase.auth.sign_in_with_password({ "email": user_info.get('email'), "password": user_info.get('password') })
        supabase.auth.set_session(response.session.access_token, response.session.refresh_token)
        return response
    except Exception as e:
        logger.error(f"An error occurred while signing in: {e}")
        raise Exception(f"An error occurred while signing in: {e}")

def fetch_all_process_definitions(tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('proc_def').select('*').eq('tenant_id', tenant_id).execute()
        
        return response.data
    
    except Exception as e:
        logger.error(f"An error occurred while fetching process definitions: {e}")
        raise Exception(f"An error occurred while fetching process definitions: {e}")

def fetch_all_process_definition_ids(tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('proc_def').select('id').eq('tenant_id', tenant_id).execute()
        
        return response.data
    
    except Exception as e:
        logger.error(f"An error occurred while fetching process definition ids: {e}")
        raise Exception(f"An error occurred while fetching process definition ids: {e}")

def fetch_process_definition(def_id, tenant_id: Optional[str] = None):
    """
    Fetches the process definition from the 'proc_def' table based on the given definition ID.
    
    Args:
        def_id (str): The ID of the process definition to fetch.
    
    Returns:
        dict: The process definition as a JSON object if found, else None.
    """
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
    
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def').select('*').eq('id', def_id.lower()).eq('tenant_id', tenant_id).execute()
        
        # Check if the response contains data
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            process_definition = response.data[0].get('definition', None)
            return process_definition
        else:
            return None
    except Exception as e:
        logger.error(f"No process definition found with ID {def_id}: {e}")
        raise Exception(f"No process definition found with ID {def_id}: {e}")

def fetch_process_definition_versions(def_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def_arcv').select('*').eq('proc_def_id', def_id.lower()).eq('tenant_id', tenant_id).execute()
        
        return response.data
    except Exception as e:
        logger.error(f"No process definition version found with ID {def_id}: {e}")
        raise Exception(f"No process definition version found with ID {def_id}: {e}")

def fetch_process_definition_version_by_arcv_id(def_id, arcv_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")  


        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def_arcv').select('*').eq('proc_def_id', def_id.lower()).eq('arcv_id', arcv_id).eq('tenant_id', tenant_id).execute()
        
        return response.data
    except Exception as e:
        logger.error(f"No process definition version found with ID {def_id} and version {arcv_id}: {e}")
        raise Exception(f"No process definition version found with ID {def_id} and version {arcv_id}: {e}")

def fetch_process_definition_latest_version(def_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")


        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('proc_def_arcv').select('*').eq('proc_def_id', def_id.lower()).eq('tenant_id', tenant_id).order('version', desc=True).execute()
        
        if response.data:
            return response.data[0]
        else:
            return None
    except Exception as e:
        logger.error(f"No process definition latest version found with ID {def_id}: {e}")
        raise Exception(f"No process definition latest version found with ID {def_id}: {e}")

def fetch_all_ui_definition(tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('form_def').select('*').eq('tenant_id', tenant_id).execute()
        
        if response.data:
            return response.data
        else:
            return []
    except Exception as e:
        logger.error(f"An error occurred while fetching UI definitions: {e}")
        raise Exception(f"An error occurred while fetching UI definitions: {e}")

def fetch_ui_definition(def_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('form_def').select('*').eq('id', def_id.lower()).eq('tenant_id', tenant_id).execute()
        
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            ui_definition = UIDefinition(**response.data[0])
            return ui_definition
        else:
            return None
    except Exception as e:
        logger.error(f"No UI definition found with ID {def_id}: {e}")
        raise Exception(f"No UI definition found with ID {def_id}: {e}")

def fetch_ui_definition_by_activity_id(proc_def_id, activity_id, tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('form_def').select('*').eq('proc_def_id', proc_def_id).eq('activity_id', activity_id).eq('tenant_id', tenant_id).execute()
        
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            ui_definition = UIDefinition(**response.data[0])
            return ui_definition
        else:
            return None
    except Exception as e:
        logger.error(f"No UI definition found with ID {proc_def_id}: {e}")
        raise Exception(f"No UI definition found with ID {proc_def_id}: {e}")

class ProcessInstance(BaseModel):
    proc_inst_id: str
    proc_inst_name: Optional[str] = None
    role_bindings: Optional[List[Dict[str, Any]]] = []
    current_activity_ids: Optional[List[str]] = []
    participants: Optional[List[str]] = []
    variables_data: Optional[List[Dict[str, Any]]] = []
    process_definition: ProcessDefinition = None  # Add a reference to ProcessDefinition
    status: str = None
    tenant_id: str
    proc_def_version: Optional[str] = None


    class Config:
        extra = "allow"


    def __init__(self, **data):
        super().__init__(**data)
        def_id = self.get_def_id()
        tenant_id = self.tenant_id
        self.process_definition = load_process_definition(fetch_process_definition(def_id, tenant_id))  # Load ProcessDefinition


    def get_def_id(self):
        # inst_id 예시: "company_entrance.123e4567-e89b-12d3-a456-426614174000"
        # 여기서 "company_entrance"가 프로세스 정의 ID입니다.
        return self.proc_inst_id.split(".")[0]


    def get_data(self):
        # Return all process variable values as a map
        variable_map = {}
        for variable in self.process_definition.data:
            variable_name = variable.name
            variable_map[variable_name] = getattr(self, variable_name, None)
        return variable_map
  
class WorkItem(BaseModel):
    id: str
    user_id: Optional[str]
    proc_inst_id: Optional[str] = None
    proc_def_id: Optional[str] = None
    activity_id: str
    activity_name: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    status: str
    description: Optional[str] = None
    tool: Optional[str] = None
    tenant_id: str
    reference_ids: Optional[List[str]] = []
    assignees: Optional[List[Dict[str, Any]]] = []
    duration: Optional[int] = None
    output: Optional[Dict[str, Any]] = {}
    retry: Optional[int] = 0
    consumer: Optional[str] = None
    log: Optional[str] = None
    agent_mode: Optional[str] = None
    
    @validator('start_date', 'end_date', 'due_date', pre=True)
    def parse_datetime(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).replace(tzinfo=None)
            except ValueError:
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value


    class Config:
        json_encoders = {
            datetime: lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")
        }


def fetch_process_instance(full_id: str, tenant_id: Optional[str] = None) -> Optional[ProcessInstance]:
    try:
        if full_id == "new" or '.' not in full_id:
            return None

        if not full_id:
            logger.error(f"Instance Id should be provided (full_id: {full_id})")
            raise Exception("Instance Id should be provided")

        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('bpm_proc_inst').select("*").eq('proc_inst_id', full_id).eq('tenant_id', tenant_id).execute()

        if response.data:
            process_instance_data = response.data[0]

            if isinstance(process_instance_data.get('variables_data'), dict):
                process_instance_data['variables_data'] = [process_instance_data['variables_data']]
            
            process_instance = ProcessInstance(**process_instance_data)
            
            return process_instance
        else:
            return None
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e)) from e

def fetch_organization_chart(tenant_id: Optional[str] = None):
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table("configuration").select("*").eq('key', 'organization').eq('tenant_id', tenant_id).execute()
        
        # Check if the response contains data
        if response.data:
            # Assuming the first match is the desired one since ID should be unique
            value = response.data[0].get('value', None)
            organization_chart = value.get('chart', None)
            return organization_chart
        else:
            return None
    except Exception as e:
        logger.error(f"Failed to fetch organization chart: {e}")
        raise Exception(f"Failed to fetch organization chart: {e}")

def fetch_process_instance_list(user_id: str, process_definition_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Optional[List[ProcessInstance]]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        if process_definition_id:
            response = supabase.table('bpm_proc_inst').select("*").eq('tenant_id', tenant_id).eq('proc_def_id', process_definition_id).filter('participants', 'cs', '{' + user_id + '}').execute()
        else:
            response = supabase.table('bpm_proc_inst').select("*").eq('tenant_id', tenant_id).filter('participants', 'cs', '{' + user_id + '}').execute()
        
        if response.data:
            return [ProcessInstance(**item) for item in response.data]
        else:
            return None
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e)) from e

def fetch_todolist_by_user_id(user_id: str, tenant_id: Optional[str] = None) -> Optional[List[WorkItem]]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")


        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('todolist').select("*").like('user_id', f'%{user_id}%').eq('tenant_id', tenant_id).execute()
        
        if response.data:
            return [WorkItem(**item) for item in response.data]
        else:
            return None
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e)) from e

def fetch_todolist_by_user_id_and_status(user_id: str, status: str, tenant_id: Optional[str] = None) -> Optional[List[WorkItem]]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")

        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('todolist').select("*").like('user_id', f'%{user_id}%').eq('status', status).eq('tenant_id', tenant_id).execute()

        if response.data:
            return [WorkItem(**item) for item in response.data]
        else:
            return None
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e)) from e
    
def fetch_todolist_by_proc_inst_id(proc_inst_id: str, tenant_id: Optional[str] = None) -> Optional[List[WorkItem]]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table('todolist').select("*").eq('proc_inst_id', proc_inst_id).eq('tenant_id', tenant_id).execute()
        

        if response.data:
            return [WorkItem(**item) for item in response.data]
        else:
            return None
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e)) from e

def fetch_workitem_by_proc_inst_and_activity(proc_inst_id: str, activity_id: str, tenant_id: Optional[str] = None) -> Optional[WorkItem]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain


        response = supabase.table('todolist').select("*").eq('proc_inst_id', proc_inst_id).eq('activity_id', activity_id).eq('tenant_id', tenant_id).execute()
        
        if response.data:
            return WorkItem(**response.data[0])
        else:
            return None
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e)) from e

class ChatMessage(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    image: Optional[str] = None
    content: Optional[str] = None
    timeStamp: Optional[int] = None
    jsonContent: Optional[Any] = None
    htmlContent: Optional[str] = None
    contentType: Optional[str] = None

class ChatItem(BaseModel):
    id: str
    uuid: str
    messages: Optional[ChatMessage] = None
    tenant_id: str

def fetch_chat_history(chat_room_id: str, tenant_id: Optional[str] = None) -> List[ChatItem]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")

        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table("chats").select("*").eq('id', chat_room_id).eq('tenant_id', tenant_id).execute()

        chatHistory = []
        for chat in response.data:
            chat.pop('jsonContent', None)
            chatHistory.append(ChatItem(**chat))
        return chatHistory
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e)) from e

def fetch_user_info(email: str, tenant_id: Optional[str] = None) -> Dict[str, str]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table("users").select("*").eq('email', email).execute()
        
        if response.data:
            return response.data[0]
        else:
            logger.error(f"User not found for email: {email}")
            raise Exception("User not found")
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e))

def fetch_assignee_info(assignee_id: str, tenant_id: Optional[str] = None) -> Dict[str, str]:
    """
    담당자 정보를 찾는 함수
    담당자가 유저인지 에이전트인지 판단하고 적절한 정보를 반환합니다.
    
    Args:
        assignee_id: 담당자 ID (이메일 또는 에이전트 ID)
    
    Returns:
        담당자 정보 딕셔너리
    """
    try:
        try:
            subdomain = subdomain_var.get()
            if not tenant_id:
                tenant_id = subdomain

            user_info = fetch_user_info(assignee_id, tenant_id)
            type = "user"
            if user_info.get("is_agent") == True:
                type = "agent"
                if user_info.get("url") is not None and user_info.get("url").strip() != "":
                    type = "a2a"
            return {
                "type": type,
                "id": assignee_id,
                "name": user_info.get("username", assignee_id),
                "email": assignee_id,
                "info": user_info
            }
        except Exception as user_error:
            logger.error(f"Assignee info fetch error for id {assignee_id}: {user_error}")
            return {
                "type": "unknown",
                "id": assignee_id,
                "name": assignee_id,
                "email": assignee_id,
                "info": {}
            }
    except Exception as e:
        return {
            "type": "error",
            "id": assignee_id,
            "name": assignee_id,
            "email": assignee_id,
            "info": {},
            "error": str(e)
        }

def get_vector_store():
    supabase = supabase_client_var.get()
    if supabase is None:
        raise Exception("Supabase client is not configured")
    
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", deployment="text-embedding-3-small")
    
    return SupabaseVectorStore(
        client=supabase,
        embedding=embeddings,
        table_name="documents",
        query_name="match_documents",
    )

def fetch_user_info_by_uid(uid: str, tenant_id: Optional[str] = None) -> Dict[str, str]:
    try:
        supabase = supabase_client_var.get()
        if supabase is None:
            logger.error("Supabase client is not configured for this request")
            raise Exception("Supabase client is not configured for this request")
        
        subdomain = subdomain_var.get()
        if not tenant_id:
            tenant_id = subdomain

        response = supabase.table("users").select("*").eq('id', uid).execute()
        if response.data:
            return response.data[0]
        else:
            logger.error(f"User not found for uid: {uid}")
            raise Exception("User not found")
    except Exception as e:
        logger.error(str(e))
        raise Exception(str(e)) from e


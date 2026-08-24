import json
import requests
from src.core.config import AUTH_API_URL
from src.shared.utils.logger import Log


def call_system_connections_get(group_key: list[str], client_register: list[str]):
    """
    Gọi API lấy danh sách System Connections bằng bittech-auth-sdk.
    """
    from src.modules.auth.services.auth_sdk_service import auth_sdk_service
    Log.info(f"--- Calling SDK: get_system_connections ---")
    try:
        data = auth_sdk_service.get_system_connections(
            group_keys=group_key,
            client_register=client_register
        )
        return data
    except Exception as e:
        Log.error(f"SDK get_system_connections failed: {e}")
        return {
            "success": False,
            "message": str(e)
        }


# In-memory token cache: { "system_id": { "access_token": "...", "api_key": "...", "user_id": ... } }
_TOKEN_CACHE = {}

def call_client_register_post(
    system_connection_id: int, 
    system_id: str, 
    system_register: str, 
    external_id: int | str, 
    description: str,
    user_info: str
):
    """
    Đăng ký client mới bằng bittech-auth-sdk.
    """
    from src.modules.auth.services.auth_sdk_service import auth_sdk_service
    Log.info(f"--- Calling SDK: register_client ---")
    try:
        data = auth_sdk_service.register_client(
            connection_id=system_connection_id,
            target_system_id=system_id,
            external_id=external_id,
            description=description
        )
        
        # --- AUTO CALL AUTH TOKEN AFTER CONNECT ---
        is_reg_ok = False
        if data and isinstance(data, dict):
            is_reg_ok = (data.get("success") is True) or (data.get("status") == "success")

        if is_reg_ok:
            first_lv = data.get("data", {})
            nested_data = None
            
            if isinstance(first_lv, dict):
                if "api_key" in first_lv:
                    nested_data = first_lv
                elif isinstance(first_lv.get("data"), dict):
                    nested_data = first_lv.get("data")

            if nested_data:
                api_key = nested_data.get("api_key")
                if api_key:
                    Log.info(f"--- [Auto Auth] Fetching token for {system_id} ---")
                    call_auth_token(system_id, api_key, external_id)
        
        return data
    except Exception as e:
        Log.error(f"SDK register_client failed: {e}")
        return {
            "success": False,
            "message": str(e)
        }


def call_revoke_api_key(system_id: str, api_key: str, password: str):
    """
    Calls the external API to revoke an API key. (Giữ cuộc gọi thủ công vì SDK không hỗ trợ revoke)
    """
    url = f"{AUTH_API_URL}/api/client-registers/revoke-api-key"
    
    payload = {
        "system_id": system_id,
        "api_key": api_key,
        "password": password
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        try:
            return response.json()
        except json.JSONDecodeError:
            return {
                "status": "error",
                "message": "Invalid JSON response from external API",
                "raw_response": response.text,
                "status_code": response.status_code
            }
            
    except requests.exceptions.RequestException as e:
        error_detail = ""
        if hasattr(e, 'response') and e.response is not None:
            error_detail = e.response.text
             
        return {
            "status": "error",
            "message": "External API Request failed",
            "error": str(e),
            "detail": error_detail
        }


def call_auth_token(system_id: str, api_key: str, user_id: int):
    """
    Xác thực API Key lấy Access Token bằng bittech-auth-sdk.
    """
    from src.modules.auth.services.auth_sdk_service import auth_sdk_service
    Log.info(f"--- Calling SDK: authenticate for system_id={system_id}, user_id={user_id} ---")
    try:
        result = auth_sdk_service.authenticate(
            api_key=api_key,
            user_id=user_id
        )
        
        is_auth_ok = False
        if result and isinstance(result, dict):
            is_auth_ok = (result.get("success") is True) or (result.get("status") == "success")

        if is_auth_ok:
            token_data = result.get("data", {})
            access_token = token_data.get("access_token")
            
            if access_token:
                _TOKEN_CACHE[system_id] = {
                    "access_token": access_token,
                    "api_key": api_key,
                    "user_id": user_id
                }
                Log.info(f"--- [Auth Cache] Token updated successfully for {system_id} ---")
            return result
        else:
            Log.error(f"--- [Auth Error] SDK returned failure ---")
            return result

    except Exception as e:
        Log.error(f"SDK authenticate failed: {e}")
        return {
            "success": False,
            "message": str(e)
        }


def get_authorized_headers(system_id: str):
    """
    Returns headers with 'Authorization: Bearer <token>'.
    Auto-refreshes if token is missing or if previous request failed (caller must handle retry).
    """
    cache = _TOKEN_CACHE.get(system_id)
    
    # If no token in cache, logic flow depends on requirements. 
    # Usually we need api_key to refresh. If absent, we can't refresh.
    if not cache:
        return {}
    
    token = cache.get("access_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def refresh_token_if_needed(system_id: str):
    """
    Forces a token refresh using stored credentials in cache.
    """
    cache = _TOKEN_CACHE.get(system_id)
    if not cache:
        return False
        
    api_key = cache.get("api_key")
    user_id = cache.get("user_id")
    
    if api_key and user_id:
        print(f"--- [Auto Refresh] Refreshing token for {system_id} ---")
        call_auth_token(system_id, api_key, user_id)
        return True
    return False


def upload_document(endpoint: str, system_id: str, api_key: str, user_id: int, payload: dict):
    """
    Uploads a document to an external system with authentication.
    
    Args:
        endpoint: The base endpoint URL of the external system
        system_id: System identifier
        api_key: API key for authentication
        user_id: User identifier
        payload: Document data to upload
        
    Returns:
        Response from the external API
    """
    # Get access token from cache or fetch new one
    cache = _TOKEN_CACHE.get(system_id)
    access_token = None
    
    if cache:
        access_token = cache.get("access_token")
    
    # If no token in cache, fetch it
    if not access_token:
        Log.info(f"--- [Upload] No token in cache, fetching for system_id={system_id} ---")
        auth_result = call_auth_token(system_id, api_key, user_id)
        
        is_auth_ok = False
        if auth_result and isinstance(auth_result, dict):
            is_auth_ok = (auth_result.get("success") is True) or (auth_result.get("status") == "success")

        if is_auth_ok:
            token_data = auth_result.get("data", {})
            access_token = token_data.get("access_token")
        else:
            # SECURITY: Không log auth_result (có thể chứa access_token)
            Log.error(f"--- [Upload Error] Could not obtain token for system_id={system_id} ---")
            return {
                "success": False,
                "message": "Failed to authenticate before upload",
                "auth_error": auth_result
            }
    
    # Construct the upload URL
    upload_url = f"{endpoint}/api/share/car-documents"
    
    # Prepare request data
    request_data = {
        "authentication": {
            "system_id": system_id,
            "api_key": api_key,
            "user_id": user_id
        },
        "payload": payload
    }
    
    # Prepare headers
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    Log.info(f"--- [Upload] Sending document to: {upload_url} ---")
    # SECURITY: Mask api_key trong payload trước khi log
    _safe_payload = {**request_data, "authentication": {**request_data.get("authentication", {}), "api_key": "****"}}
    Log.debug(f"Payload (masked): {json.dumps(_safe_payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(upload_url, json=request_data, headers=headers, timeout=30)
        
        Log.info(f"--- [Upload] Response Status: {response.status_code} ---")
        
        try:
            result = response.json()
            # SECURITY: Chỉ log status, không log full response body
            _is_ok = result.get("success") or result.get("status") == "success"
            Log.info(f"--- [Upload] Response Status: {response.status_code} | success={_is_ok} ---")
            Log.debug(f"--- [Upload] Body: {json.dumps(result, indent=2, ensure_ascii=False)} ---")
            return result
        except json.JSONDecodeError:
            Log.error(f"--- [Upload] Raw Body (Text): {response.text} ---")
            return {
                "success": False,
                "message": "Invalid JSON response from external API",
                "raw_response": response.text,
                "status_code": response.status_code
            }
            
    except requests.exceptions.RequestException as e:
        print(f"\n[!] Error uploading document: {e}")
        error_detail = ""
        if hasattr(e, 'response') and e.response is not None:
            print("Error Response Content:", e.response.text)
            error_detail = e.response.text
            
        return {
            "success": False,
            "message": "External API Request failed",
            "error": str(e),
            "detail": error_detail
        }

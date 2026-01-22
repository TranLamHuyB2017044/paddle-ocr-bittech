import json
import requests
from src.config import AUTH_API_URL
from src.utils.logger import Log


def call_system_connections_get(group_key: str, client_register: list[str]):

    Log.info(f"--- Calling API: {AUTH_API_URL}/api/system-connections/get ---")
    Log.info(f"Payload: {json.dumps({'group_key': group_key, 'client_register': client_register}, indent=2, ensure_ascii=False)}")

    url = f"{AUTH_API_URL}/api/system-connections/get"
    
    payload = {
        "group_key": group_key,
        "client_register": client_register
    }

    try:
        response = requests.get(url, json=payload, timeout=10)
        
        try:
            Log.info(f"Response: {response.text}")
            data = response.json()
            return data
        except json.JSONDecodeError:
            Log.error(f"Invalid JSON response: {response.text}")
            return {
                "success": False, 
                "message": "Invalid JSON response", 
                "raw_response": response.text,
                "status_code": response.status_code
            }
            
    except requests.exceptions.RequestException as e:
        error_detail = ""
        if hasattr(e, 'response') and e.response is not None:
             error_detail = e.response.text
        
        return {
            "success": False, 
            "message": "Request failed", 
            "error": str(e),
            "detail": error_detail
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
    Calls https://auth.hkbcert.vn/api/client-register/post
    """
    url = f"{AUTH_API_URL}/api/client-registers"
    
    payload = {
        "system_connection_id": system_connection_id,
        "system_id": system_id,
        "system_register": system_register,
        "external_id": external_id,
        "description": description,
        "user_info": user_info
    }
    
    print(f"--- Calling API: {url} ---")
    print("Payload:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    try:
        response = requests.post(url, json=payload, timeout=10)
        
        print("\n--- Response ---")
        print(f"Status Code: {response.status_code}")
        
        try:
            data = response.json()
            print("Body (JSON):")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            
            # --- AUTO CALL AUTH TOKEN AFTER CONNECT ---
            # data structure check: result["success"] == True
            if data and data.get("success") is True:
                nested_data = data.get("data", {}).get("data", {})
                api_key = nested_data.get("api_key")
                
                if api_key:
                    print(f"--- [Auto Auth] Fetching token for {system_id} ---")
                    # Auto call auth token to cache it
                    call_auth_token(system_id, api_key, external_id)
            
            return data
        except json.JSONDecodeError:
            print("Body (Text):")
            print(response.text)
            return {
                "success": False,
                "message": "Invalid JSON response from external API",
                "raw_response": response.text,
                "status_code": response.status_code
            }
            
    except requests.exceptions.RequestException as e:
        print(f"\n[!] Error calling API: {e}")
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


def call_revoke_api_key(system_id: str, api_key: str, password: str):
    """
    Calls the external API to revoke an API key.
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
    Calls https://auth.hkbcert.vn/api/authenticate
    """
    url = f"{AUTH_API_URL}/api/authenticate"
    
    payload = {
        "system_id": system_id,
        "api_key": api_key, 
        "user_id": user_id
    }
    
    try:
        response = requests.post(url, json=payload)
        
        try:
            result = response.json()
            
            # --- UPDATE CACHE ---
            if result and result.get("success") is True:
                token_data = result.get("data", {})
                access_token = token_data.get("access_token")
                
                if access_token:
                    _TOKEN_CACHE[system_id] = {
                        "access_token": access_token,
                        "api_key": api_key,
                        "user_id": user_id
                    }
                    print(f"--- [Cache] Token updated for {system_id} ---")

            return result
        except json.JSONDecodeError:
            return {
                "success": False,
                "message": "Invalid JSON response from external API",
                "raw_response": response.text,
                "status_code": response.status_code
            }
            
    except requests.exceptions.RequestException as e:
        error_detail = ""
        if hasattr(e, 'response') and e.response is not None:
             error_detail = e.response.text
             
        return {
            "success": False,
            "message": "External API Request failed", 
            "error": str(e),
            "detail": error_detail
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
        print(f"--- [Upload] No token in cache, fetching for {system_id} ---")
        auth_result = call_auth_token(system_id, api_key, user_id)
        
        if auth_result and auth_result.get("success") is True:
            token_data = auth_result.get("data", {})
            access_token = token_data.get("access_token")
        else:
            return {
                "success": False,
                "message": "Failed to authenticate before upload",
                "auth_error": auth_result
            }
    
    # Construct the upload URL
    upload_url = f"{endpoint}/api/vehicle-documents"
    
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
    
    print(f"--- Uploading Document to: {upload_url} ---")
    print("Request Data:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    
    try:
        response = requests.post(upload_url, json=request_data, headers=headers, timeout=30)
        
        print(f"\n--- Upload Response ---")
        print(f"Status Code: {response.status_code}")
        
        try:
            result = response.json()
            print("Body (JSON):")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return result
        except json.JSONDecodeError:
            print("Body (Text):")
            print(response.text)
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

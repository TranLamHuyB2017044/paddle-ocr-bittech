import json
import requests
from src.config import AUTH_API_URL


def call_system_connections_get(group_key: str, client_register: list[str]):
    url = f"{AUTH_API_URL}/api/system-connections/get"
    
    payload = {
        "group_key": group_key,
        "client_register": client_register
    }

    try:
        response = requests.get(url, json=payload, timeout=10)
        
        try:
            data = response.json()
            return data
        except json.JSONDecodeError:
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
        "key": api_key,
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

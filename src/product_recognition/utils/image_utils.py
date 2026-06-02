
import requests
from PIL import Image
import io

def download_image(url):
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception as e:
        raise Exception(f"Failed to download image: {str(e)}")

def validate_image(image_bytes):
    try:
        Image.open(io.BytesIO(image_bytes))
        return True
    except Exception:
        return False


import requests
from io import BytesIO
from PIL import Image

def download_image(url):
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content)).convert('RGB')
    except Exception as e:
        print("Error downloading image:", e)
        return None

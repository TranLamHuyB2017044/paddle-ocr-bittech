
import cloudinary
import cloudinary.uploader
from src.config import CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET
from src.utils.logger import Log

class CloudinaryService:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CloudinaryService, cls).__new__(cls)
            if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
                cloudinary.config(
                    cloud_name = CLOUDINARY_CLOUD_NAME,
                    api_key = CLOUDINARY_API_KEY,
                    api_secret = CLOUDINARY_API_SECRET,
                    secure = True
                )
                cls._instance.configured = True
                Log.info("[CLOUDINARY] ✅ Configured")
            else:
                cls._instance.configured = False
                Log.warning("[CLOUDINARY] ⚠️ Not Configured (Missing ENV vars)")
        return cls._instance

    def upload_image(self, file_path):
        """
        Upload an image to Cloudinary and return the secure URL.
        """
        if not self.configured:
            return None

        try:
            # Upload the image with the original filename for easier debugging
            response = cloudinary.uploader.upload(
                file_path, 
                folder="ocr_uploads",
                use_filename=True,
                unique_filename=False
            )
            return response.get("secure_url")
        except Exception as e:
            Log.error(f"[CLOUDINARY] ❌ Upload failed: {e}")
            return None

cloudinary_service = CloudinaryService()

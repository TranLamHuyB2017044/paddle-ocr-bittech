
from flask import Blueprint, request, jsonify
from src.product_recognition.models import get_embedding_from_image, warmup_model
from src.product_recognition.utils.image_utils import validate_image
from src.product_recognition.utils.qdrant_service import product_qdrant_service
from src.utils.cloudinary_utils import cloudinary_service
import os
import tempfile

product_bp = Blueprint('product', __name__)

@product_bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Product Recognition API is running"}), 200

@product_bp.route('/warmup', methods=['GET'])
def warmup():
    try:
        warmup_model()
        return jsonify({"status": "ok", "message": "Model warmed up successfully"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@product_bp.route('/product/train', methods=['POST'])
def train_product():
    try:
        if 'images' not in request.files:
            return jsonify({"status": "error", "message": "No images provided"}), 400
        
        product_id = request.form.get('id')
        product_name = request.form.get('name')
        product_price = request.form.get('price')
        
        if not product_id:
            return jsonify({"status": "error", "message": "Product ID is required"}), 400
        
        images = request.files.getlist('images')
        if len(images) == 0:
            return jsonify({"status": "error", "message": "At least one image is required"}), 400
        
        image_urls = []
        all_embeddings = []
        
        for img in images:
            img_bytes = img.read()
            if not validate_image(img_bytes):
                return jsonify({"status": "error", "message": f"Invalid image: {img.filename}"}), 400
            
            # Save to temp file to upload
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
                temp_file.write(img_bytes)
                temp_file_path = temp_file.name
            
            try:
                # Upload to Cloudinary
                upload_result = cloudinary_service.upload_private(temp_file_path, folder="product_recognition")
                if upload_result:
                    # Generate signed URL
                    signed_url = cloudinary_service.generate_signed_url(
                        upload_result["public_id"],
                        resource_type=upload_result["resource_type"]
                    )
                    image_urls.append(signed_url)
            finally:
                # Clean up temp file
                os.unlink(temp_file_path)
            
            # Get embedding
            embedding = get_embedding_from_image(img_bytes)
            all_embeddings.append(embedding)
        
        # Use first embedding for the product (or average them)
        if len(all_embeddings) > 0:
            product_embedding = all_embeddings[0]
            
            # Store in Qdrant
            payload = {
                "id": product_id,
                "name": product_name,
                "price": product_price,
                "image_urls": image_urls
            }
            product_qdrant_service.upsert_product(int(product_id), product_embedding, payload)
        
        return jsonify({
            "status": "ok",
            "message": "Product trained successfully",
            "product": {
                "id": product_id,
                "name": product_name,
                "price": product_price,
                "image_urls": image_urls
            }
        }), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@product_bp.route('/product/detect', methods=['POST'])
def detect_product():
    try:
        if 'image' not in request.files:
            return jsonify({"status": "error", "message": "No image provided"}), 400
        
        img_file = request.files['image']
        img_bytes = img_file.read()
        
        if not validate_image(img_bytes):
            return jsonify({"status": "error", "message": "Invalid image"}), 400
        
        # Get embedding
        embedding = get_embedding_from_image(img_bytes)
        
        # Search in Qdrant
        results = product_qdrant_service.search_similar(embedding, limit=5)
        
        detected_products = []
        for result in results:
            detected_products.append({
                "score": result.score,
                "product": result.payload
            })
        
        return jsonify({
            "status": "ok",
            "detected_products": detected_products
        }), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@product_bp.route('/product/update_embedding', methods=['POST'])
def update_embedding():
    try:
        data = request.json
        product_id = data.get('id')
        
        if not product_id:
            return jsonify({"status": "error", "message": "Product ID is required"}), 400
        
        # For simplicity, this endpoint is a placeholder - you would need to retrieve the product and update its embedding
        return jsonify({"status": "ok", "message": "Product embedding update endpoint"}), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


from flask import Blueprint, request, jsonify
import numpy as np
import os
import json
import time
import tempfile
import requests

from src.modules.product_recognition.models import get_embedding_from_image
from src.modules.product_recognition.utils.image_utils import download_image
from src.modules.product_recognition.utils.qdrant_service import product_qdrant_service
from src.core.config import FILES_API_URL, FILES_API_UPLOAD_ENDPOINT, FILES_API_SYSTEM_ID, FILES_API_USER_ID, FILES_API_ALIAS, FILES_API_KEY
from src.shared.utils.logger import Log
from src.shared.utils.auth_middleware import require_auth

product_bp = Blueprint("product_bp", __name__)

# Helper function to upload image to FILES_API
def upload_to_files_api(img, filename: str = "product.jpg", farm_id = None):
    try:
        # Save PIL Image to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            img.save(temp_file, format='JPEG')
            temp_file_path = temp_file.name
        
        try:
            Log.info(f"[Product Recognition] Đang tải file lên FILES_API: {filename} (farm: {farm_id})")
            upload_url = f"{FILES_API_URL}{FILES_API_UPLOAD_ENDPOINT}"
            
            with open(temp_file_path, 'rb') as f:
                files = {
                    'files': (os.path.basename(temp_file_path), f, 'image/jpeg')
                }
                data = {
                    'system_id': FILES_API_SYSTEM_ID,
                    'user_id': FILES_API_USER_ID,
                    'alias': FILES_API_ALIAS,
                    "file_system": False
                }
                headers = {
                    'x-api-key': FILES_API_KEY
                }
                
                response = requests.post(upload_url, files=files, data=data, headers=headers)
                response.raise_for_status()
                upload_result = response.json()
                
                # Extract URL from response
                final_url = None
                if upload_result and isinstance(upload_result, dict):
                    data_obj = upload_result.get('data') if isinstance(upload_result.get('data'), dict) else upload_result
                    
                    # 1. New response structure: data.results[0].file.publicPath
                    results = data_obj.get('results', [])
                    if isinstance(results, list) and len(results) > 0:
                        first_result = results[0]
                        if isinstance(first_result, dict) and first_result.get('success'):
                            file_info = first_result.get('file', {})
                            if isinstance(file_info, dict):
                                public_path = file_info.get('publicPath') or file_info.get('path')
                                if public_path:
                                    if public_path.startswith('/'):
                                        final_url = f"{FILES_API_URL}{public_path}"
                                    else:
                                        final_url = f"{FILES_API_URL}/{public_path}"
                    
                    # 2. Fallbacks
                    if not final_url:
                        if 'file_url' in data_obj:
                            final_url = data_obj['file_url']
                        elif 'url' in data_obj:
                            final_url = data_obj['url']
                        elif 'files' in data_obj and len(data_obj['files']) > 0:
                            file_info = data_obj['files'][0]
                            if isinstance(file_info, dict):
                                if 'file_url' in file_info:
                                    final_url = file_info['file_url']
                                elif 'url' in file_info:
                                    final_url = file_info['url']
                                elif 'publicPath' in file_info:
                                    pp = file_info['publicPath']
                                    final_url = f"{FILES_API_URL}{pp}" if pp.startswith('/') else f"{FILES_API_URL}/{pp}"
                
                Log.info(f"[Product Recognition] Successfully uploaded file: {filename}")
                return final_url
        finally:
            os.unlink(temp_file_path)
    except Exception as e:
        Log.error(f"[Product Recognition] Error uploading file to FILES_API: {str(e)}")
        return None




# ==========================
# API Train Product
# ==========================
@product_bp.route("/product/train", methods=["POST"])
@require_auth
def train_product():
    try:
        # 1. Lấy data từ JSON hoặc Form (cho id, name, price, farm_id, overwrite)
        data = request.get_json(silent=True) or request.form.to_dict()
        
        product_id = data.get("id")
        name = data.get("name")
        price = data.get("price")
        farm_id = data.get("farm_id") or data.get("farmId")
        overwrite = data.get("overwrite")
        
        # Normalize and validate farm_id
        if farm_id is not None:
            farm_id = str(farm_id).strip()
        if not farm_id:
            return jsonify({"error": "Missing farm_id"}), 400
            
        if isinstance(overwrite, str):
            overwrite = overwrite.lower() in ("true", "1", "yes")
        else:
            overwrite = bool(overwrite)
            
        # 2. Lấy danh sách ảnh (có thể là FILE upload hoặc URL list)
        uploaded_files = request.files.getlist("images")
        image_urls = data.get("images")
        
        if isinstance(image_urls, str):
            try:
                image_urls = json.loads(image_urls)
            except:
                image_urls = [image_urls]
        elif not image_urls:
            image_urls = []

        if not product_id or not name or (not uploaded_files and not image_urls):
            return jsonify({"error": "Missing product id, name OR images (files/urls)"}), 400

        product_id = str(product_id)
        Log.info(f"[TRAIN] Starting product training: ID={product_id}, Name='{name}', Price={price}, Farm={farm_id}, Overwrite={overwrite}")
        Log.info(f"[TRAIN] Uploaded files count: {len(uploaded_files)}, Image URLs count: {len(image_urls)}")

        # Nếu truyền overwrite=True, tiến hành xóa sản phẩm cũ trước khi train mới
        if overwrite:
            Log.info(f"[TRAIN] Overwrite requested (overwrite=True). Deleting existing data for product {product_id} (farm: {farm_id}) in Qdrant...")
            product_qdrant_service.delete_product(product_id, farm_id)
            existing_point = None
            existing_num = 0
            existing_vector = None
        else:
            # Kiểm tra xem sản phẩm đã có bao nhiêu ảnh trong Qdrant
            Log.info(f"[TRAIN] Querying Qdrant for existing product data of {product_id} (farm: {farm_id})...")
            existing_point = product_qdrant_service.get_product_by_id(product_id, farm_id)
            existing_num = 0
            existing_vector = None
            if existing_point:
                existing_num = existing_point.payload.get("num_images", 0)
                existing_vector = np.array(existing_point.vector) if existing_point.vector else None
                Log.info(f"[TRAIN] Existing data found in Qdrant: {existing_num} images integrated previously.")
                
                # Nếu đã đủ 5 ảnh thì không cần train thêm (hoặc trả về is_embedded=True)
                if existing_num >= 5:
                    Log.info(f"[TRAIN] Product already has maximum limit of 5 images. Rejecting further training.")
                    return jsonify({
                        "id": product_id,
                        "name": name,
                        "price": price,
                        "farm_id": farm_id,
                        "num_images": existing_num,
                        "is_embedded": True,
                        "message": "Product already has 5 images (max limit)"
                    })
            else:
                Log.info(f"[TRAIN] No existing data found for this product in Qdrant DB.")

        # Get existing URLs list
        existing_urls = []
        if existing_point:
            existing_urls = existing_point.payload.get("urls")
            if isinstance(existing_urls, str):
                existing_urls = [existing_urls] if existing_urls else []
            elif not isinstance(existing_urls, list):
                existing_urls = []
            
            if not existing_urls and existing_point.payload.get("url"):
                existing_urls = [existing_point.payload.get("url")]

        from PIL import Image
        product_embeddings = []
        new_uploaded_urls = []
        upload_errors = []
        
        # Số lượng ảnh tối đa cần bù đắp
        allowed_to_add = 5 - existing_num
        Log.info(f"[TRAIN] Allowed to add: {allowed_to_add} more images to reach maximum limit of 5.")

        # --- PHẦN 1: Xử lý FILE upload (nếu có) ---
        for idx, file in enumerate(uploaded_files):
            if len(product_embeddings) >= allowed_to_add: 
                Log.info(f"[TRAIN] Reached maximum images limit, ignoring remaining files.")
                break
            try:
                Log.info(f"[TRAIN] [File {idx+1}/{len(uploaded_files)}] Opening image file...")
                img = Image.open(file.stream).convert('RGB')
                
                # Upload to FILES_API
                Log.info(f"[TRAIN] [File {idx+1}/{len(uploaded_files)}] Uploading file to FILES_API...")
                remote_url = upload_to_files_api(img, filename=f"product_{product_id}_{idx+1}.jpg", farm_id=farm_id)
                if remote_url:
                    new_uploaded_urls.append(remote_url)
                    Log.info(f"[TRAIN] [File {idx+1}/{len(uploaded_files)}] Uploaded successfully. URL: {remote_url}")
                else:
                    upload_errors.append(f"Upload failed for file {idx+1}")
                    Log.warning(f"[TRAIN] [File {idx+1}/{len(uploaded_files)}] Upload to FILES_API failed.")

                # Embed
                Log.info(f"[TRAIN] [File {idx+1}/{len(uploaded_files)}] Extracting embedding...")
                emb = get_embedding_from_image(img)
                product_embeddings.append(emb)
                Log.info(f"[TRAIN] [File {idx+1}/{len(uploaded_files)}] Embedding generated successfully.")
            except Exception as e:
                Log.error(f"[TRAIN] [File {idx+1}/{len(uploaded_files)}] Error processing file: {e}")
                upload_errors.append(f"Processing failed for file {idx+1}: {str(e)}")

        # --- PHẦN 2: Xử lý URL (nếu có) ---
        if len(product_embeddings) < allowed_to_add:
            for idx, img_url in enumerate(image_urls):
                if len(product_embeddings) >= allowed_to_add:
                    Log.info(f"[TRAIN] Reached maximum images limit, ignoring remaining URLs.")
                    break
                try:
                    Log.info(f"[TRAIN] [URL {idx+1}/{len(image_urls)}] Downloading image from URL: {img_url}")
                    img = download_image(img_url)
                    if not img:
                        upload_errors.append(f"Download failed for URL {idx+1}: {img_url}")
                        Log.warning(f"[TRAIN] [URL {idx+1}/{len(image_urls)}] Download failed.")
                        continue

                    # Upload to FILES_API
                    Log.info(f"[TRAIN] [URL {idx+1}/{len(image_urls)}] Uploading image to FILES_API...")
                    remote_url = upload_to_files_api(img, filename=f"product_{product_id}_url_{idx+1}.jpg", farm_id=farm_id)
                    if remote_url:
                        new_uploaded_urls.append(remote_url)
                        Log.info(f"[TRAIN] [URL {idx+1}/{len(image_urls)}] Uploaded successfully. URL: {remote_url}")
                    else:
                        upload_errors.append(f"Upload failed for image URL {idx+1}")
                        Log.warning(f"[TRAIN] [URL {idx+1}/{len(image_urls)}] Upload to FILES_API failed.")

                    # Embed
                    Log.info(f"[TRAIN] [URL {idx+1}/{len(image_urls)}] Extracting embedding...")
                    emb = get_embedding_from_image(img)
                    product_embeddings.append(emb)
                    Log.info(f"[TRAIN] [URL {idx+1}/{len(image_urls)}] Embedding generated successfully.")
                except Exception as e:
                    Log.error(f"[TRAIN] [URL {idx+1}/{len(image_urls)}] Error processing URL: {e}")
                    upload_errors.append(f"Processing failed for URL {idx+1}: {str(e)}")

        if not product_embeddings and existing_num == 0:
            Log.error(f"[TRAIN] Failed to process any images and no existing data found.")
            return jsonify({"error": "Failed to process any images", "upload_errors": upload_errors}), 400

        # Tính vector trung bình mới
        new_num = existing_num + len(product_embeddings)
        Log.info(f"[TRAIN] Calculating new mean vector. New images: {len(product_embeddings)}, Total integrated images: {new_num}")
        
        if len(product_embeddings) > 0:
            sum_new_vec = np.sum(np.array(product_embeddings), axis=0)
            if existing_vector is not None:
                combined_vec = (existing_vector * existing_num + sum_new_vec) / new_num
                Log.info(f"[TRAIN] Successfully combined existing vector ({existing_num} images) with new vectors.")
            else:
                combined_vec = sum_new_vec / len(product_embeddings)
                Log.info(f"[TRAIN] Successfully created new mean vector (no existing data).")
            final_vec = combined_vec.tolist()
        else:
            final_vec = existing_vector.tolist() if existing_vector is not None else None
            Log.info(f"[TRAIN] No new images processed, keeping existing vector.")

        combined_urls = existing_urls + new_uploaded_urls
        primary_url = combined_urls[0] if combined_urls else ""

        if final_vec:
            # Đẩy lên Qdrant Cloud
            is_embedded = (new_num >= 5)
            Log.info(f"[TRAIN] Upserting product to Qdrant. Payload: ID={product_id}, Name='{name}', Farm={farm_id}, ImagesCount={new_num}, IsEmbedded={is_embedded}")
            product_qdrant_service.upsert_product(
                product_id=product_id,
                vector=final_vec,
                payload={
                    "id": product_id,
                    "name": name,
                    "price": price,
                    "farm_id": farm_id,
                    "url": primary_url,
                    "urls": combined_urls,
                    "num_images": new_num,
                    "is_embedded": is_embedded
                },
                farm_id=farm_id
            )
            Log.info(f"[TRAIN] Successfully trained and upserted product {product_id} to Qdrant!")

            return jsonify({
                "id": product_id,
                "name": name,
                "price": price,
                "farm_id": farm_id,
                "num_images": new_num,
                "is_embedded": is_embedded,
                "url": primary_url,
                "urls": combined_urls,
                "upload_errors": upload_errors if upload_errors else None
            })
        else:
            Log.error(f"[TRAIN] Failed to calculate combined embedding vector.")
            return jsonify({"error": "Failed to generate embedding", "upload_errors": upload_errors}), 500

    except Exception as e:
        Log.error(f"[TRAIN] Internal server error: {str(e)}")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500



@product_bp.route('/product/detect', methods=['POST'])
@require_auth
def detect_product():
    start_total = time.time()
    
    # Nhận file từ multipart/form-data
    if 'image' not in request.files:
        Log.info("[DETECT] Image file not found in request (multipart/form-data)")
        return jsonify({"error": "No image file provided"}), 400

    img_file = request.files['image']
    farm_id = request.form.get("farm_id") or request.form.get("farmId") or request.args.get("farm_id") or request.args.get("farmId")
    
    if farm_id is not None:
        farm_id = farm_id.strip()
        
    if not farm_id:
        Log.info("[DETECT] Missing farm_id in request")
        return jsonify({"error": "Missing farm_id"}), 400
        
    Log.info(f"[DETECT] Running product detection for Farm={farm_id}")
    from PIL import Image
    
    try:
        img = Image.open(img_file.stream).convert('RGB')
        Log.info(f"[DETECT] Image loaded successfully: Size={img.size}, Mode={img.mode}")
    except Exception as e:
        Log.error(f"[DETECT] Error opening input image: {e}")
        return jsonify({"error": f"Invalid image: {e}"}), 400

    # Lấy embedding của ảnh input
    start_emb = time.time()
    input_emb = get_embedding_from_image(img)
    emb_time = time.time() - start_emb
    Log.info(f"[DETECT] Embedding generated successfully in {emb_time:.3f}s")

    # Tìm kiếm trên Qdrant Cloud
    start_search = time.time()
    Log.info(f"[DETECT] Querying similar vectors on Qdrant DB (farm_id={farm_id})...")
    search_results = product_qdrant_service.search_similar(input_emb, farm_id=farm_id, limit=3)
    search_time = time.time() - start_search
    Log.info(f"[DETECT] Qdrant search completed in {search_time:.3f}s")

    if not search_results:
        Log.info("[DETECT] No similar products found in Qdrant DB.")
    else:
        Log.info(f"[DETECT] Found {len(search_results)} candidate products:")
        for i, res in enumerate(search_results):
            p = res.payload
            Log.info(f"  {i+1}. Name: '{p.get('name')}' | ID: {p.get('id')} | Similarity Score: {res.score:.4f} | Images Count: {p.get('num_images')}")

    if search_results:
        best_point = search_results[0]
        threshold = 0.8
        
        if best_point.score > threshold:
            Log.info(f"[DETECT] MATCH FOUND: '{best_point.payload.get('name')}' (Score={best_point.score:.4f} > Threshold={threshold})")
            total_time = time.time() - start_total
            Log.info(f"[DETECT] Total detection processing time: {total_time:.3f}s")
            
            p = best_point.payload
            original_product_id = p.get("id", best_point.id)
            return jsonify({
                "id": original_product_id,
                "name": p.get("name"),
                "price": p.get("price"),
                "farm_id": p.get("farm_id"),
                "url": p.get("url"),
                "similarity": best_point.score,
                "num_images": p.get("num_images",0),
                "is_embedded": p.get("is_embedded", False)
            })
        else:
            Log.warning(f"[DETECT] NO MATCH: Nearest product '{best_point.payload.get('name')}' has Score={best_point.score:.4f} below threshold ({threshold}).")

    total_time = time.time() - start_total
    Log.info(f"[DETECT] Completed detection (No match). Total processing time: {total_time:.3f}s")
    
    return jsonify({
        "data": None,
        "message": "Không tìm thấy sản phẩm phù hợp",
        "status": "error"
    }), 404



# ==========================
# API Update Embedding (Batch)
# ==========================
@product_bp.route("/product/update_embedding", methods=["POST"])
@require_auth
def update_embedding():
    product_id = request.form.get("product_id")
    files = request.files.getlist("image_files")
    
    # Cho phép nhận cả tham số text nếu cần
    name = request.form.get("name")
    price = request.form.get("price")
    farm_id = request.form.get("farm_id") or request.form.get("farmId") or request.args.get("farm_id") or request.args.get("farmId")

    if farm_id is not None:
        farm_id = farm_id.strip()
        
    if not farm_id:
        return jsonify({"error": "Missing farm_id"}), 400

    if not product_id or not files:
        Log.warning(f"[UPDATE] Missing parameters in request: product_id={product_id}, image_files={len(files) if files else 0}")
        return jsonify({"error": "Missing product_id or image_files"}), 400

    Log.info(f"[UPDATE] Starting vector embedding update: ID={product_id}, Name={name}, Price={price}, Farm={farm_id}")
    Log.info(f"[UPDATE] New image files count: {len(files)}")

    # Lấy thông tin hiện tại từ Qdrant
    Log.info(f"[UPDATE] Checking existing data for product {product_id} (farm: {farm_id}) in Qdrant DB...")
    existing_point = product_qdrant_service.get_product_by_id(product_id, farm_id)
    existing_num = 0
    existing_vector = None
    existing_payload = {}
    
    if existing_point:
        existing_num = existing_point.payload.get("num_images", 0)
        existing_vector = np.array(existing_point.vector) if existing_point.vector else None
        existing_payload = existing_point.payload
        Log.info(f"[UPDATE] Existing product found. Images count previously integrated: {existing_num}")
        
        if existing_num >= 5:
            Log.info(f"[UPDATE] Product already has maximum limit of 5 images. Rejecting further updates.")
            return jsonify({
                "message": f"Product {product_id} already has {existing_num} images (max limit)",
                "is_embedded": True,
                "num_images": existing_num
            })
    else:
        Log.info(f"[UPDATE] Product does not exist on Qdrant DB yet. Will create a new one.")

    existing_urls = existing_payload.get("urls")
    if isinstance(existing_urls, str):
        existing_urls = [existing_urls] if existing_urls else []
    elif not isinstance(existing_urls, list):
        existing_urls = []
    
    if not existing_urls and existing_payload.get("url"):
        existing_urls = [existing_payload.get("url")]

    new_embeddings = []
    new_uploaded_urls = []
    allowed_to_add = 5 - existing_num
    upload_errors = []
    Log.info(f"[UPDATE] Max images allowed to add in this session: {allowed_to_add}")

    for idx, file in enumerate(files):
        if len(new_embeddings) >= allowed_to_add:
            Log.info(f"[UPDATE] Reached maximum images limit of 5, ignoring remaining files.")
            break
        try:
            from PIL import Image
            Log.info(f"[UPDATE] [File {idx+1}/{len(files)}] Opening image...")
            img = Image.open(file.stream).convert("RGB")
            
            # Upload to FILES_API
            Log.info(f"[UPDATE] [File {idx+1}/{len(files)}] Uploading file to FILES_API...")
            remote_url = upload_to_files_api(img, filename=f"product_{product_id}_update_{idx+1}.jpg", farm_id=farm_id)
            if remote_url:
                new_uploaded_urls.append(remote_url)
                Log.info(f"[UPDATE] [File {idx+1}/{len(files)}] Uploaded successfully. URL: {remote_url}")
            else:
                upload_errors.append(f"Upload failed for file {idx+1}")
                Log.warning(f"[UPDATE] [File {idx+1}/{len(files)}] Upload to FILES_API failed.")
            
            # Embed
            Log.info(f"[UPDATE] [File {idx+1}/{len(files)}] Extracting embedding...")
            new_emb = get_embedding_from_image(img)
            new_embeddings.append(new_emb)
            Log.info(f"[UPDATE] [File {idx+1}/{len(files)}] Embedding generated successfully.")
        except Exception as e:
            Log.error(f"[UPDATE] [File {idx+1}/{len(files)}] Error processing file: {e}")
            upload_errors.append(f"Processing failed for file {idx+1}: {str(e)}")
            continue

    if not new_embeddings:
        Log.error(f"[UPDATE] Failed to process any new images or limit exceeded.")
        return jsonify({"error": "Failed to process images or limit exceeded", "upload_errors": upload_errors}), 400

    # Tính lại vector trung bình
    total_num = existing_num + len(new_embeddings)
    sum_new_vec = np.sum(np.array(new_embeddings), axis=0)
    Log.info(f"[UPDATE] Calculating combined vector. New images: {len(new_embeddings)}, Total integrated images: {total_num}")
    
    if existing_vector is not None:
        combined_vec = (existing_vector * existing_num + sum_new_vec) / total_num
        Log.info(f"[UPDATE] Combined existing vector ({existing_num} images) and new vectors ({len(new_embeddings)} images).")
    else:
        combined_vec = sum_new_vec / len(new_embeddings)
        Log.info(f"[UPDATE] Created new combined mean vector.")
    
    is_embedded = (total_num >= 5)
    combined_urls = existing_urls + new_uploaded_urls
    primary_url = combined_urls[0] if combined_urls else ""

    # Cập nhật Qdrant
    Log.info(f"[UPDATE] Upserting to Qdrant. Payload: Name='{name if name else existing_payload.get('name', 'Unknown')}', ImagesCount={total_num}, IsEmbedded={is_embedded}")
    product_qdrant_service.upsert_product(
        product_id=product_id,
        vector=combined_vec.tolist(),
        payload={
            "id": product_id,
            "name": name if name else existing_payload.get("name", "Unknown"),
            "price": price if price is not None else existing_payload.get("price"),
            "farm_id": farm_id,
            "url": primary_url,
            "urls": combined_urls,
            "num_images": total_num,
            "is_embedded": is_embedded
        },
        farm_id=farm_id
    )
    Log.info(f"[UPDATE] Successfully updated Qdrant DB for product {product_id}!")

    return jsonify({
        "message": f"Updated Qdrant for product {product_id}",
        "num_images": total_num,
        "is_embedded": is_embedded,
        "url": primary_url,
        "urls": combined_urls,
        "upload_errors": upload_errors if upload_errors else None
    })


# ==========================
# API Delete Product
# ==========================
@product_bp.route("/product/delete", methods=["POST", "DELETE"])
@require_auth
def delete_product():
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or request.args.to_dict()
        product_id = data.get("product_id") or data.get("id")
        farm_id = data.get("farm_id") or data.get("farmId")
        
        if farm_id is not None:
            farm_id = str(farm_id).strip()
            
        if not product_id or not farm_id:
            return jsonify({"error": "Missing product_id or farm_id"}), 400
            
        product_id = str(product_id)
        
        success = product_qdrant_service.delete_product(product_id, farm_id)
        if success:
            return jsonify({
                "message": f"Deleted product {product_id} from farm {farm_id} in Qdrant successfully",
                "status": "success"
            })
        else:
            return jsonify({
                "error": f"Failed to delete product {product_id} from Qdrant",
                "status": "error"
            }), 500
    except Exception as e:
        Log.error(f"[DELETE] Internal server error: {str(e)}")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500

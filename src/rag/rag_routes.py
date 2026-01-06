from flask import Blueprint, request, jsonify, g
import os
from src.utils.auth_middleware import require_auth
from src.repositories.workspaces_repository import workspaces_repo
from src.repositories.chat_history_repository import chat_history_repo
from src.repositories.documents_repository import documents_repo
from src.repositories.extraction_logs_repository import extraction_logs_repo
from src.rag.rag_service import rag_service
from src.rag.qdrant_service import qdrant_service
from src.utils.ocr_utils import ocr_extract
from src.utils.file_utils import save_uploaded_files
from src.utils.pdf_utils import extract_text_from_pdf, get_pdf_pages_as_images
from src.utils.word_utils import extract_text_from_word
from src.utils.logger import Log

rag_bp = Blueprint('rag_bp', __name__)

@rag_bp.route('/api/rag/workspaces', methods=['POST'])
@require_auth
def create_workspace():
    try:
        data = request.json
        name = data.get('name')
        description = data.get('description', '')
        
        if not name:
            return jsonify({"statusCode": 400, "message": "Workspace name is required"}), 400
            
        workspace_id = workspaces_repo.create_workspace(name, g.user_id, description)
        
        return jsonify({
            "statusCode": 201,
            "message": "Workspace created successfully",
            "data": {"workspace_id": workspace_id}
        }), 201
    except Exception as e:
        Log.error(f"[RAG-API] Create workspace failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces', methods=['GET'])
@require_auth
def list_workspaces():
    try:
        workspaces = workspaces_repo.find_by_user(g.user_id)
        
        # Add document count from Qdrant for each workspace
        for ws in workspaces:
            try:
                ws["document_count"] = qdrant_service.get_document_count(ws["_id"])
            except:
                ws["document_count"] = 0
                
        return jsonify({
            "statusCode": 200,
            "data": workspaces
        })
    except Exception as e:
        Log.error(f"[RAG-API] List workspaces failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>', methods=['GET'])
@require_auth
def get_workspace_details(workspace_id):
    try:
        # Verify workspace belongs to user
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied or workspace not found"}), 403
            
        # Add extra info
        try:
            workspace["document_count"] = qdrant_service.get_document_count(workspace_id)
        except:
            workspace["document_count"] = 0
            
        return jsonify({
            "statusCode": 200,
            "data": workspace
        })
    except Exception as e:
        Log.error(f"[RAG-API] Get workspace failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>', methods=['PUT'])
@require_auth
def update_workspace(workspace_id):
    try:
        # Verify workspace belongs to user
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        data = request.json
        name = data.get('name')
        description = data.get('description')
        
        if not name and description is None:
            return jsonify({"statusCode": 400, "message": "Name or description is required"}), 400
            
        success = workspaces_repo.update_workspace(workspace_id, name, description)
        
        if success:
            return jsonify({
                "statusCode": 200,
                "message": "Workspace updated successfully"
            })
        else:
            return jsonify({"statusCode": 400, "message": "Failed to update workspace"}), 400
            
    except Exception as e:
        Log.error(f"[RAG-API] Update workspace failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>', methods=['DELETE'])
@require_auth
def delete_workspace(workspace_id):
    try:
        # 1. Verify workspace exists and belongs to user
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({"statusCode": 404, "message": "Workspace not found"}), 404
            
        if workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        # 2. Delete vectors from Qdrant
        try:
            qdrant_service.delete_by_workspace(workspace_id)
            Log.info(f"[RAG-API] Deleted vectors for workspace: {workspace_id}")
        except Exception as q_err:
            Log.error(f"[RAG-API] Failed to delete vectors from Qdrant: {q_err}")
            # We continue even if Qdrant fails to ensure DB consistency if possible
            
        # 3. Delete chat history from MongoDB
        try:
            chat_history_repo.clear_history(workspace_id)
            Log.info(f"[RAG-API] Deleted chat history for workspace: {workspace_id}")
        except Exception as h_err:
            Log.error(f"[RAG-API] Failed to delete chat history: {h_err}")

        # 4. Delete workspace metadata from MongoDB
        success = workspaces_repo.delete_workspace(workspace_id)
        
        if success:
            return jsonify({
                "statusCode": 200,
                "message": "Workspace and all associated data deleted successfully"
            })
        else:
            return jsonify({"statusCode": 400, "message": "Failed to delete workspace metadata"}), 400
            
    except Exception as e:
        Log.error(f"[RAG-API] Delete workspace failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/clear-all', methods=['DELETE'])
@require_auth
def delete_all_workspaces():
    try:
        # 1. Get all workspaces for this user
        workspaces = workspaces_repo.find_by_user(g.user_id)
        workspace_ids = [w["_id"] for w in workspaces]
        
        Log.info(f"[RAG-API] Clearing all data for user {g.user_id}. Workspaces found: {len(workspace_ids)}")

        # 2. Delete vectors from Qdrant for each workspace
        deleted_vectors_count = 0
        for ws_id in workspace_ids:
            try:
                qdrant_service.delete_by_workspace(ws_id)
                deleted_vectors_count += 1
            except Exception as q_err:
                Log.error(f"[RAG-API] Failed to delete vectors for workspace {ws_id}: {q_err}")

        # 3. Delete chat histories for all workspaces of this user
        try:
            deleted_history_count = chat_history_repo.delete_by_user(g.user_id)
            Log.info(f"[RAG-API] Deleted {deleted_history_count} chat history records")
        except Exception as h_err:
            Log.error(f"[RAG-API] Failed to delete chat history: {h_err}")

        # 4. Delete extraction logs
        try:
            deleted_logs_count = extraction_logs_repo.delete_by_user(g.user_id)
            Log.info(f"[RAG-API] Deleted {deleted_logs_count} extraction logs")
        except Exception as l_err:
            Log.error(f"[RAG-API] Failed to delete extraction logs: {l_err}")

        # 5. Delete documents metadata
        try:
            deleted_docs_count = documents_repo.delete_by_user(g.user_id)
            Log.info(f"[RAG-API] Deleted {deleted_docs_count} document records")
        except Exception as d_err:
            Log.error(f"[RAG-API] Failed to delete documents: {d_err}")

        # 6. Delete all workspaces from MongoDB
        try:
            deleted_workspaces_count = workspaces_repo.delete_by_user(g.user_id)
            Log.info(f"[RAG-API] Deleted {deleted_workspaces_count} workspace records")
        except Exception as w_err:
            Log.error(f"[RAG-API] Failed to delete workspaces: {w_err}")

        return jsonify({
            "statusCode": 200,
            "message": "All workspaces and associated data cleared successfully",
            "data": {
                "workspaces_deleted": len(workspace_ids),
                "history_cleared": True,
                "logs_cleared": True,
                "documents_cleared": True
            }
        })
    except Exception as e:
        Log.error(f"[RAG-API] Clear all failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/upload', methods=['POST'])
@require_auth
def upload_to_workspace(workspace_id):
    saved_paths = []
    try:
        # 1. Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied to workspace"}), 403

        # 2. Get files from 'files' key
        files = request.files.getlist('files')
        if not files:
            return jsonify({"statusCode": 400, "message": "No files uploaded. Use key 'files'"}), 400
            
        if len(files) > 5:
            return jsonify({"statusCode": 400, "message": "Tối đa 5 file cho mỗi lần upload"}), 400

        # 3. Check document limit (Max 5 documents per workspace)
        current_doc_count = qdrant_service.get_document_count(workspace_id)
        if current_doc_count >= 5:
            return jsonify({
                "statusCode": 400, 
                "message": f"Workspace đã đạt giới hạn tối đa 5 tài liệu. Hiện tại bạn đang có {current_doc_count} tài liệu."
            }), 400
            
        if current_doc_count + len(files) > 5:
            return jsonify({
                "statusCode": 400, 
                "message": f"Bạn chỉ có thể upload thêm {5 - current_doc_count} tài liệu nữa để không vượt quá giới hạn 5 file."
            }), 400

        # Check file sizes before saving
        from src.config import MAX_RAG_FILE_SIZE
        for file in files:
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0) # Reset pointer
            if file_size > MAX_RAG_FILE_SIZE:
                return jsonify({
                    "statusCode": 413, 
                    "message": f"File '{file.filename}' quá lớn ({file_size/1024/1024:.1f}MB). Giới hạn {MAX_RAG_FILE_SIZE/1024/1024:.0f}MB để đảm bảo tốc độ xử lý."
                }), 413

        from src.utils.file_utils import save_uploaded_file_list
        saved_paths = save_uploaded_file_list(files)
        
        if not saved_paths:
             return jsonify({"statusCode": 400, "message": "No valid files saved. Check extensions."}), 400

        total_chunks = 0
        indexed_files = []

        # 3. Process each file
        for idx, p1 in enumerate(saved_paths):
            original_filename = files[idx].filename
            Log.info(f"[RAG-API] Processing file {idx+1}/{len(saved_paths)}: {original_filename}")
            
            full_text = ""
            ext = original_filename.lower().split('.')[-1]
            
            # Handle Markdown files (Plain Text)
            if ext == 'md':
                try:
                    with open(p1, 'r', encoding='utf-8') as f:
                        full_text = f.read()
                    Log.info(f"[RAG-API] Read Markdown file directly: {len(full_text)} chars")
                except Exception as e:
                    Log.error(f"[RAG-API] Failed to read MD file: {e}")
            
            # Handle Word files (.docx and .doc)
            elif ext in ['docx', 'doc']:
                Log.info(f"[RAG-API] Extracting text from Word ({ext}): {original_filename}")
                full_text = extract_text_from_word(p1)
                if full_text:
                    Log.info(f"[RAG-API] Successfully extracted {len(full_text)} chars from Word file")
                else:
                    Log.error(f"[RAG-API] Could not extract text from {original_filename}")
            
            elif ext == 'pdf':
                # Optimized PDF handling
                Log.info(f"[RAG-API] Extracting text from PDF: {original_filename}")
                full_text = extract_text_from_pdf(p1)
                
                # If no text extracted (likely scanned PDF), fallback to OCR
                if not full_text.strip():
                    Log.info(f"[RAG-API] PDF appears scanned. Falling back to OCR for {original_filename}")
                    image_paths = get_pdf_pages_as_images(p1)
                    ocr_texts = []
                    for img_p in image_paths:
                        try:
                            # Use OCR for each page
                            res, _ = ocr_extract(img_p)
                            if res:
                                page_text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in res])
                                ocr_texts.append(page_text)
                            # Cleanup temp image
                            if os.path.exists(img_p): os.remove(img_p)
                        except Exception as ocr_err:
                            Log.error(f"[RAG-API] OCR failed for page in {original_filename}: {ocr_err}")
                    
                    full_text = "\n\n".join(ocr_texts)
                else:
                    Log.info(f"[RAG-API] Successfully extracted {len(full_text)} chars directly from PDF")

            elif ext in ['jpg', 'jpeg', 'png', 'bmp']:
                # OCR for Images
                try:
                    ocr_result, _ = ocr_extract(p1)
                    # Concatenate text
                    if ocr_result:
                        full_text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in ocr_result])
                except Exception as e:
                    Log.error(f"[RAG-API] OCR failed for {original_filename}: {e}")
            
            else:
                Log.error(f"[RAG-API] Unsupported file type for indexing: {ext}")
            
            if full_text.strip():
                # Indexing
                num_chunks = rag_service.index_text(full_text, workspace_id, original_filename)
                total_chunks += num_chunks
                indexed_files.append(original_filename)
            else:
                Log.warning(f"[RAG-API] No text extracted from {original_filename}")

        return jsonify({
            "statusCode": 200,
            "message": f"Successfully indexed {len(indexed_files)}/{len(files)} files",
            "data": {
                "indexed_files": indexed_files,
                "total_chunks": total_chunks
            }
        })
    except Exception as e:
        Log.error(f"[RAG-API] Multi-upload failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
    finally:
        # Cleanup
        for p in saved_paths:
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass

@rag_bp.route('/api/rag/workspaces/<workspace_id>/chat', methods=['POST'])
@require_auth
def chat_with_workspace(workspace_id):
    try:
        # Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        data = request.json
        question = data.get('question')
        provider = data.get('provider', 'auto')
        
        if not question:
            return jsonify({"statusCode": 400, "message": "Question is required"}), 400
            
        result = rag_service.query(question, workspace_id, provider=provider)
        
        # Save to History
        chat_history_repo.save_message(
            workspace_id=workspace_id,
            user_id=g.user_id,
            question=question,
            answer=result["answer"],
            sources=result["sources"],
            provider=result["provider"]
        )
        
        return jsonify({
            "statusCode": 200,
            "data": result
        })
    except Exception as e:
        Log.error(f"[RAG-API] Chat failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/suggest', methods=['GET'])
@require_auth
def suggest_workspace_questions(workspace_id):
    try:
        # Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        suggestions = rag_service.suggest_questions(workspace_id)
        
        return jsonify({
            "statusCode": 200,
            "data": {"suggestions": suggestions}
        })
    except Exception as e:
        Log.error(f"[RAG-API] Suggestions failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/history', methods=['GET'])
@require_auth
def get_workspace_chat_history(workspace_id):
    try:
        # Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        limit = request.args.get('limit', default=50, type=int)
        history = chat_history_repo.get_history(workspace_id, limit=limit)
        
        return jsonify({
            "statusCode": 200,
            "data": {
                "workspace_id": workspace_id,
                "history": history
            }
        })
    except Exception as e:
        Log.error(f"[RAG-API] Get history failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/history', methods=['DELETE'])
@require_auth
def delete_workspace_chat_history(workspace_id):
    try:
        # Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        deleted_count = chat_history_repo.clear_history(workspace_id)
        
        return jsonify({
            "statusCode": 200,
            "message": f"Successfully deleted {deleted_count} messages",
            "data": {"workspace_id": workspace_id}
        })
    except Exception as e:
        Log.error(f"[RAG-API] Delete history failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modules.ocr.repositories.documents_repository import documents_repo
from src.modules.rag.rag_service import rag_service
from src.modules.rag.qdrant_service import qdrant_service
from src.shared.utils.logger import Log

def reindex_document(document_id: str):
    doc = documents_repo.find_by_id(document_id)
    if not doc:
        print(f"❌ Không tìm thấy document: {document_id}")
        return

    workspace_id = str(doc.get("workspace_id"))
    doc_name = doc.get("filename") or doc.get("original_filename") or "document"
    category = doc.get("category")
    raw_text = doc.get("raw_text")

    if not raw_text:
        print(f"⚠️ Document '{doc_name}' không có raw_text để reindex!")
        return

    print(f"🚀 Bắt đầu reindex thông minh cho: '{doc_name}' (ID: {document_id}, Category: {category})")
    
    # 1. Xóa các điểm vector cũ của document này trong Qdrant
    try:
        from qdrant_client.http import models
        qdrant_service.client.delete(
            collection_name=qdrant_service.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
                        models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))
                    ]
                )
            )
        )
        print("🗑️ Đã xóa các chunks vector cũ trong Qdrant.")
    except Exception as e:
        print(f"⚠️ Lỗi xóa điểm cũ (bỏ qua nếu chưa có): {e}")

    # 2. Sử dụng thuật toán chunk thông minh mới và index lại
    total_chunks = rag_service.index_text(
        data=raw_text,
        workspace_id=workspace_id,
        document_name=doc_name,
        category=category,
        document_id=document_id
    )

    # 3. Cập nhật lại số lượng chunk trong MongoDB
    documents_repo.update_metadata(document_id, total_chunks=total_chunks)
    print(f"✅ Hoàn tất reindex! Đã tạo và embed {total_chunks} structure-aware chunks.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_id = sys.argv[1]
    else:
        # Mặc định lấy tài liệu mẫu gần nhất
        target_id = "6aa1259f18733351ef90f71f"
    reindex_document(target_id)

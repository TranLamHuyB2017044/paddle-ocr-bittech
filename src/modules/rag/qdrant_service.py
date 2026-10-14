from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams
import src.core.config as config
from src.shared.utils.logger import Log

class QdrantService:
    def __init__(self):
        # Use path-based storage if not a URL
        if config.QDRANT_URL.startswith("http"):
            self.client = QdrantClient(
                url=config.QDRANT_URL,
                api_key=config.QDRANT_API_KEY or None,
                check_compatibility=False
            )
        else:
            Log.info(f"[Qdrant] 📁 Using local storage mode at: {config.QDRANT_URL}")
            self.client = QdrantClient(path=config.QDRANT_URL)
            
        self.collection_name = config.RAG_COLLECTION_NAME
        self._ensure_collection()

    def _ensure_payload_indexes(self):
        """
        Ensure necessary payload indexes exist for filtering and fast retrieval.
        """
        indexes = [
            ("workspace_id", models.PayloadSchemaType.KEYWORD),
            ("document_name", models.PayloadSchemaType.KEYWORD),
            ("document_id", models.PayloadSchemaType.KEYWORD),
            ("category", models.PayloadSchemaType.KEYWORD),
            ("page_num", models.PayloadSchemaType.INTEGER),
        ]
        for field_name, field_schema in indexes:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                )
                Log.info(f"[Qdrant] ✅ Ensured payload index for '{field_name}' exists")
            except Exception as index_err:
                Log.debug(f"[Qdrant] Payload index for '{field_name}': {index_err}")

    def _ensure_collection(self):
        """
        Check collection exists, skip create if it does (avoids 403 errors).
        """
        try:
            from src.modules.rag.embedding_service import embedding_service
            # Get vector size from model
            sample_vector = embedding_service.embed_text(["sample"])[0]
            vector_size = len(sample_vector)
            
            # Check if collection exists
            try:
                col_info = self.client.get_collection(collection_name=self.collection_name)
                # Check vector size compatibility
                existing_size = None
                try:
                    vectors_param = col_info.config.params.vectors
                    if hasattr(vectors_param, 'size'):
                        existing_size = vectors_param.size
                    elif isinstance(vectors_param, dict):
                        # Khi Qdrant trả về dict dạng {'': VectorParams(size=384, ...)}
                        default_vector = vectors_param.get("") or next(iter(vectors_param.values()), None)
                        if default_vector and hasattr(default_vector, 'size'):
                            existing_size = default_vector.size
                        elif isinstance(default_vector, dict):
                            existing_size = default_vector.get("size")
                except Exception as ex:
                    Log.debug(f"[Qdrant] Could not read existing vector size: {ex}")
                
                if existing_size and existing_size != vector_size:
                    Log.warning(
                        f"[Qdrant] ⚠️ Collection '{self.collection_name}' có kích thước vector {existing_size} "
                        f"không khớp với model embedding hiện tại ({vector_size} chiều). "
                        f"Đang tự động xóa và tạo lại collection để tương thích..."
                    )
                    self.client.delete_collection(collection_name=self.collection_name)
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                    )
                    Log.info(f"[Qdrant] ✅ Recreated collection '{self.collection_name}' với size {vector_size}")
                else:
                    Log.info(f"[Qdrant] ✅ Collection '{self.collection_name}' already exists (size: {existing_size or vector_size})")
                
                self._ensure_payload_indexes()
                return
            except Exception as get_err:
                # Collection doesn't exist, try to create it
                Log.info(f"[Qdrant] Creating collection: {self.collection_name} with size {vector_size}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                self._ensure_payload_indexes()
                Log.info(f"[Qdrant] ✅ Collection '{self.collection_name}' created successfully")
        except Exception as e:
            Log.error(f"[Qdrant] Error ensuring collection: {e}")
            Log.info(f"[Qdrant] ⚠️ Continuing with existing collection (if available)")

    def upsert_points(self, points):
        """
        Upsert points to Qdrant.
        """
        return self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def search(self, vector, workspace_id, limit=5, category: str | None = None):
        """
        Search for similar vectors in a specific workspace, optionally filtered by category.
        """
        must_conditions = [
            models.FieldCondition(
                key="workspace_id",
                match=models.MatchValue(value=workspace_id),
            )
        ]
        if category:
            must_conditions.append(
                models.FieldCondition(
                    key="category",
                    match=models.MatchValue(value=category),
                )
            )

        search_filter = models.Filter(must=must_conditions)
        
        Log.debug(f"[Qdrant] Searching in workspace: {workspace_id} (category: {category})")
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=search_filter,
            limit=limit,
            with_payload=True
        )
        return response.points

    def set_document_category(self, workspace_id: str, document_id: str | None, document_name: str, category: str | None):
        """
        Update or clear the 'category' payload on all points of a document without re-embedding.
        Uses document_id if available, with fallback to document_name.
        """
        must_conditions = [
            models.FieldCondition(key="workspace_id", match=models.MatchValue(value=str(workspace_id)))
        ]
        if document_id:
            must_conditions.append(
                models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))
            )
        else:
            must_conditions.append(
                models.FieldCondition(key="document_name", match=models.MatchValue(value=document_name))
            )

        points_filter = models.Filter(must=must_conditions)

        if category:
            return self.client.set_payload(
                collection_name=self.collection_name,
                payload={"category": category},
                points=models.FilterSelector(filter=points_filter)
            )
        else:
            return self.client.delete_payload(
                collection_name=self.collection_name,
                keys=["category"],
                points=models.FilterSelector(filter=points_filter)
            )

    def delete_by_category(self, workspace_id: str, category: str):
        """
        Delete all vector points belonging to a category within a workspace.
        """
        return self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="workspace_id",
                            match=models.MatchValue(value=str(workspace_id)),
                        ),
                        models.FieldCondition(
                            key="category",
                            match=models.MatchValue(value=str(category)),
                        ),
                    ]
                )
            )
        )

    def delete_by_workspace(self, workspace_id):
        """
        Delete all points belonging to a workspace.
        """
        return self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="workspace_id",
                            match=models.MatchValue(value=workspace_id),
                        )
                    ]
                )
            )
        )

    def delete_by_document(self, workspace_id: str, document_name: str, document_id: str | None = None):
        """
        Delete all vector points belonging to a specific document within a workspace.
        """
        must_conditions = [
            models.FieldCondition(
                key="workspace_id",
                match=models.MatchValue(value=workspace_id),
            )
        ]
        if document_id:
            # We can match either document_id or document_name (or should match document_id if present)
            # To be thoroughly safe with old/new points, we match workspace_id and document_name or document_id
            must_conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=str(document_id)),
                )
            )
        else:
            must_conditions.append(
                models.FieldCondition(
                    key="document_name",
                    match=models.MatchValue(value=document_name),
                )
            )

        return self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=must_conditions)
            )
        )

    def get_document_count(self, workspace_id):
        """
        Count unique documents in a workspace.
        """
        try:
            # Scroll through points to collect unique document names
            # We only need the payload field 'document_name'
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="workspace_id",
                            match=models.MatchValue(value=workspace_id),
                        )
                    ]
                ),
                limit=1000, 
                with_payload=["document_name"],
                with_vectors=False
            )
            unique_docs = set()
            for p in points:
                if p.payload and "document_name" in p.payload:
                    unique_docs.add(p.payload["document_name"])
            return len(unique_docs)
        except Exception as e:
            Log.error(f"[Qdrant] Error counting documents: {e}")
            return 0

    def scroll(self, *args, **kwargs):
        """
        Scroll through points in the collection.
        """
        return self.client.scroll(
            collection_name=self.collection_name,
            *args, **kwargs
        )

    def get_chunks_for_page(self, workspace_id: str, document_name: str, page_num: int):
        """
        Lấy toàn bộ các chunks thuộc cùng một trang tài liệu trong một workspace.
        """
        try:
            scroll_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="workspace_id",
                        match=models.MatchValue(value=workspace_id),
                    ),
                    models.FieldCondition(
                        key="document_name",
                        match=models.MatchValue(value=document_name),
                    ),
                    models.FieldCondition(
                        key="page_num",
                        match=models.MatchValue(value=page_num),
                    )
                ]
            )
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=100,  # Một trang thường không quá 10 chunks
                with_payload=True,
                with_vectors=False
            )
            return points
        except Exception as e:
            Log.error(f"[Qdrant] Lỗi khi scroll chunks cho trang {page_num}: {e}")
            return []

# Lazy singleton pattern
_qdrant_service_instance = None

def get_qdrant_service():
    global _qdrant_service_instance
    if _qdrant_service_instance is None:
        try:
            _qdrant_service_instance = QdrantService()
        except Exception as e:
            Log.error(f"[Qdrant] ❌ Critical: Could not initialize Qdrant: {e}")
            # Instead of crashing the whole app import, we return None 
            # and let the routes handle the error
            return None
    return _qdrant_service_instance

# We will use a property-like access in the service module
class QdrantServiceProxy:
    @property
    def instance(self):
        return get_qdrant_service()
    
    def upsert_points(self, *args, **kwargs):
        if self.instance: return self.instance.upsert_points(*args, **kwargs)
        raise Exception("Qdrant not initialized")
        
    def search(self, *args, **kwargs):
        if self.instance: return self.instance.search(*args, **kwargs)
        raise Exception("Qdrant not initialized")
        
    def delete_by_workspace(self, *args, **kwargs):
        if self.instance: return self.instance.delete_by_workspace(*args, **kwargs)
        raise Exception("Qdrant not initialized")

    def set_document_category(self, *args, **kwargs):
        if self.instance: return self.instance.set_document_category(*args, **kwargs)
        raise Exception("Qdrant not initialized")

    def delete_by_category(self, *args, **kwargs):
        if self.instance: return self.instance.delete_by_category(*args, **kwargs)
        raise Exception("Qdrant not initialized")

    def delete_by_document(self, *args, **kwargs):
        if self.instance: return self.instance.delete_by_document(*args, **kwargs)
        raise Exception("Qdrant not initialized")

    def scroll(self, *args, **kwargs):
        if self.instance: return self.instance.scroll(*args, **kwargs)
        raise Exception("Qdrant not initialized")

    def get_document_count(self, *args, **kwargs):
        if self.instance: return self.instance.get_document_count(*args, **kwargs)
        return 0

    def get_chunks_for_page(self, *args, **kwargs):
        if self.instance: return self.instance.get_chunks_for_page(*args, **kwargs)
        return []

qdrant_service = QdrantServiceProxy()


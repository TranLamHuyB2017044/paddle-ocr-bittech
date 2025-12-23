from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams
import src.config as config
from src.utils.logger import Log

class QdrantService:
    def __init__(self):
        # Use path-based storage if not a URL
        if config.QDRANT_URL.startswith("http"):
            self.client = QdrantClient(
                url=config.QDRANT_URL,
                api_key=config.QDRANT_API_KEY
            )
        else:
            Log.info(f"[Qdrant] 📁 Using local storage mode at: {config.QDRANT_URL}")
            self.client = QdrantClient(path=config.QDRANT_URL)
            
        self.collection_name = config.RAG_COLLECTION_NAME
        self._ensure_collection()

    def _ensure_collection(self):
        """
        Create collection if it doesn't exist.
        """
        try:
            from src.rag.embedding_service import embedding_service
            # Get vector size from model
            sample_vector = embedding_service.embed_text(["sample"])[0]
            vector_size = len(sample_vector)
            
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if self.collection_name not in collection_names:
                Log.info(f"[Qdrant] Creating collection: {self.collection_name} with size {vector_size}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                
                # Add index for workspace_id for faster filtering
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="workspace_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
        except Exception as e:
            Log.error(f"[Qdrant] Error ensuring collection: {e}")

    def upsert_points(self, points):
        """
        Upsert points to Qdrant.
        """
        return self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def search(self, vector, workspace_id, limit=5):
        """
        Search for similar vectors in a specific workspace using modern query_points API.
        """
        search_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="workspace_id",
                    match=models.MatchValue(value=workspace_id),
                )
            ]
        )
        
        Log.debug(f"[Qdrant] Searching in workspace: {workspace_id}")
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=search_filter,
            limit=limit,
            with_payload=True
        )
        
        # Modern Qdrant client returns a structure where points are in .points
        return response.points

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

    def scroll(self, *args, **kwargs):
        """
        Scroll through points in the collection.
        """
        return self.client.scroll(
            collection_name=self.collection_name,
            *args, **kwargs
        )

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

    def scroll(self, *args, **kwargs):
        if self.instance: return self.instance.scroll(*args, **kwargs)
        raise Exception("Qdrant not initialized")

qdrant_service = QdrantServiceProxy()

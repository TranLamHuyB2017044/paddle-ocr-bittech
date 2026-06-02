import os
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class QdrantService:
    def __init__(self):
        url = os.getenv("QDRANT_URL")
        api_key = os.getenv("QDRANT_API_KEY")
        
        if not url:
            print("[Qdrant] ⚠️ QDRANT_URL not found in .env. Search will be disabled.")
            self.client = None
            return

        print(f"[Qdrant] 🌐 Connecting to: {url}")
        
        if url.startswith("http"):
            self.client = QdrantClient(
                url=url,
                api_key=api_key
            )
        else:
            # Local storage mode
            self.client = QdrantClient(path=url)
            
        self.collection_name = os.getenv("QDRANT_COLLECTION_NAME", "product_embeddings")
        self._ensure_collection()

    def _ensure_collection(self):
        """
        Create collection if it doesn't exist.
        """
        if not self.client:
            return
            
        try:
            # ResNet18 output is 512 dimensions
            vector_size = 512
            
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if self.collection_name not in collection_names:
                print(f"[Qdrant] Creating collection: {self.collection_name} with size {vector_size}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
        except Exception as e:
            print(f"[Qdrant] Error ensuring collection: {e}")

    def get_product_by_id(self, product_id):
        """
        Get a product by its ID from Qdrant.
        """
        if not self.client:
            return None
        try:
            result = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[int(product_id)],
                with_payload=True,
                with_vectors=True  # useful if we want to average vectors later
            )
            return result[0] if result else None
        except Exception as e:
            print(f"[Qdrant] Error getting product {product_id}: {e}")
            return None

    def upsert_product(self, product_id, vector, payload):
        """
        Upsert a product embedding to Qdrant with full payload.
        """
        if not self.client:
            return None
            
        return self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=int(product_id),
                    vector=vector,
                    payload=payload
                )
            ]
        )

    def search_similar(self, vector, limit=1):
        """
        Search for similar products.
        """
        if not self.client:
            return []
            
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=limit,
            with_payload=True
        )
        return response.points

# Singleton instance
product_qdrant_service = QdrantService()

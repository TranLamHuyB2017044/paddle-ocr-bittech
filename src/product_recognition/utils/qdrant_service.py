import os
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class QdrantService:
    def __init__(self):
        # Use PRODUCT-specific Qdrant config first, fall back to general config
        url = os.getenv("PRODUCT_QDRANT_URL", os.getenv("QDRANT_URL"))
        api_key = os.getenv("PRODUCT_QDRANT_API_KEY", os.getenv("QDRANT_API_KEY"))
        
        if not url:
            print("[Qdrant] ⚠️ PRODUCT_QDRANT_URL/QDRANT_URL not found in .env. Search will be disabled.")
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
            
        self.collection_name = os.getenv("PRODUCT_QDRANT_COLLECTION_NAME", "product_embeddings")
        self._ensure_collection()

    def _ensure_collection(self):
        """
        Check collection exists, skip create if it does (avoids 403 errors).
        """
        if not self.client:
            return
            
        try:
            # ResNet18 output is 512 dimensions
            vector_size = 512
            
            # First check if collection exists (lighter than get_collections)
            try:
                self.client.get_collection(collection_name=self.collection_name)
                print(f"[Qdrant] ✅ Collection '{self.collection_name}' already exists")
                return
            except Exception:
                # Collection doesn't exist, try to create it
                print(f"[Qdrant] Creating collection: {self.collection_name} with size {vector_size}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                print(f"[Qdrant] ✅ Collection '{self.collection_name}' created successfully")
        except Exception as e:
            print(f"[Qdrant] Error ensuring collection: {e}")
            print(f"[Qdrant] ⚠️ Continuing with existing collection (if available)")

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

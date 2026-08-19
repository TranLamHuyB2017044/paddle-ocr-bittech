import os
import uuid
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
            
            # Check if collection exists
            exists = True
            try:
                self.client.get_collection(collection_name=self.collection_name)
                print(f"[Qdrant] ✅ Collection '{self.collection_name}' already exists")
            except Exception:
                exists = False
                
            if not exists:
                # Collection doesn't exist, try to create it
                print(f"[Qdrant] Creating collection: {self.collection_name} with size {vector_size}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                print(f"[Qdrant] ✅ Collection '{self.collection_name}' created successfully")
                
            # Create payload index for farm_id
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="farm_id",
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
                print(f"[Qdrant] ✅ Payload index for 'farm_id' created successfully")
            except Exception as ie:
                print(f"[Qdrant] Info: Payload index for 'farm_id' creation skipped/already exists: {ie}")
                
        except Exception as e:
            print(f"[Qdrant] Error ensuring collection: {e}")
            print(f"[Qdrant] ⚠️ Continuing with existing collection (if available)")

    def generate_qdrant_id(self, product_id, farm_id=None):
        """
        Generates a valid Qdrant point ID (either 64-bit int or UUID string)
        deterministically from product_id and farm_id.
        """
        key = f"{product_id}::{farm_id}" if farm_id else str(product_id)
        
        # 1. Try to convert to unsigned 64-bit integer
        try:
            val = int(key)
            if 0 <= val < 2**63 - 1:
                return val
        except ValueError:
            pass
            
        # 2. Try to parse as valid UUID
        try:
            return str(uuid.UUID(key))
        except ValueError:
            pass
            
        # 3. Generate deterministic UUID based on key
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, key))

    def get_product_by_id(self, product_id, farm_id=None):
        """
        Get a product by its ID and optional farm ID from Qdrant.
        """
        if not self.client:
            return None
        try:
            qdrant_id = self.generate_qdrant_id(product_id, farm_id)
            result = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[qdrant_id],
                with_payload=True,
                with_vectors=True  # useful if we want to average vectors later
            )
            return result[0] if result else None
        except Exception as e:
            print(f"[Qdrant] Error getting product {product_id} (farm: {farm_id}): {e}")
            return None

    def upsert_product(self, product_id, vector, payload, farm_id=None):
        """
        Upsert a product embedding to Qdrant with full payload.
        """
        if not self.client:
            return None
            
        try:
            qdrant_id = self.generate_qdrant_id(product_id, farm_id)
            return self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=qdrant_id,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
        except Exception as e:
            print(f"[Qdrant] Error upserting product {product_id} (farm: {farm_id}): {e}")
            return None

    def delete_product(self, product_id, farm_id):
        """
        Delete a product by its ID and farm ID from Qdrant.
        """
        if not self.client:
            return False
        try:
            qdrant_id = self.generate_qdrant_id(product_id, farm_id)
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(
                    points=[qdrant_id]
                )
            )
            print(f"[Qdrant] Deleted product {product_id} (farm: {farm_id}) successfully")
            return True
        except Exception as e:
            print(f"[Qdrant] Error deleting product {product_id} (farm: {farm_id}): {e}")
            return False

    def search_similar(self, vector, farm_id=None, limit=1):
        """
        Search for similar products.
        """
        if not self.client:
            return []
            
        try:
            query_filter = None
            if farm_id is not None:
                # We filter by matching farm_id payload field
                query_filter = models.Filter(
                    must=[
                        models.FieldCondition(
                            key="farm_id",
                            match=models.MatchValue(value=farm_id)
                        )
                    ]
                )
                
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True
            )
            return response.points
        except Exception as e:
            print(f"[Qdrant] Error searching similar: {e}")
            return []

# Singleton instance
product_qdrant_service = QdrantService()

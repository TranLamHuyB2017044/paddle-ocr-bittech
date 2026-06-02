
import os
from qdrant_client import QdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv

load_dotenv()

class ProductQdrantService:
    def __init__(self):
        self.url = os.getenv("PRODUCT_QDRANT_URL")
        self.api_key = os.getenv("PRODUCT_QDRANT_API_KEY")
        self.collection_name = os.getenv("PRODUCT_QDRANT_COLLECTION_NAME", "product_embeddings")
        self.client = None
        
    def get_client(self):
        if self.client is None:
            self.client = QdrantClient(
                url=self.url,
                api_key=self.api_key
            )
        return self.client
    
    def ensure_collection(self):
        client = self.get_client()
        collections = client.get_collections().collections
        collection_names = [col.name for col in collections]
        
        if self.collection_name not in collection_names:
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=512,
                    distance=models.Distance.COSINE
                )
            )
    
    def upsert_product(self, product_id, embedding, payload):
        client = self.get_client()
        self.ensure_collection()
        client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=product_id,
                    vector=embedding,
                    payload=payload
                )
            ]
        )
    
    def search_similar(self, embedding, limit=5):
        client = self.get_client()
        self.ensure_collection()
        results = client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            limit=limit
        ).points
        return results

product_qdrant_service = ProductQdrantService()


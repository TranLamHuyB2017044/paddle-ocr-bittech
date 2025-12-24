from fastembed import TextEmbedding
from typing import List
import src.config as config

class EmbeddingService:
    def __init__(self, model_name: str = config.EMBEDDING_MODEL):
        self.model = TextEmbedding(model_name=model_name)
        
    def embed_text(self, texts: List[str]) -> List[List[float]]:
        """
        Convert a list of strings into a list of embeddings.
        """
        # FastEmbed's embed method returns an iterator of numpy arrays
        embeddings = list(self.model.embed(texts))
        # Convert numpy arrays to list of floats for Qdrant compatibility
        return [emb.tolist() for emb in embeddings]

# Singleton instance
embedding_service = EmbeddingService()

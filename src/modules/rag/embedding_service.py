from fastembed import TextEmbedding
from typing import List
import src.config as config

class EmbeddingService:
    def __init__(self, model_name: str = config.EMBEDDING_MODEL):
        # Increase threads for faster processing on multicore CPUs
        import os
        num_threads = min(os.cpu_count() or 4, 8)
        self.model = TextEmbedding(model_name=model_name, threads=num_threads)
        
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

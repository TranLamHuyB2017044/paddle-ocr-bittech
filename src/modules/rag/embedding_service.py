import os
import gc
import time
from typing import List
import src.core.config as config
from src.shared.utils.logger import Log

class EmbeddingService:
    def __init__(self):
        self.provider = getattr(config, "EMBEDDING_PROVIDER", "fastembed").lower()
        self.fastembed_model = None
        self.openai_model = getattr(config, "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.fastembed_model_name = getattr(config, "EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        
        Log.info(f"[Embedding] 🚀 Active provider: '{self.provider.upper()}'")
        
        if self.provider == "openai":
            Log.info(f"[Embedding-OpenAI] Initialized with model: {self.openai_model}")
        else:
            self._init_fastembed()

    def _init_fastembed(self):
        from fastembed import TextEmbedding
        num_threads = min(max(1, (os.cpu_count() or 2) // 2), 2)
        Log.info(f"[Embedding-FastEmbed] Initializing TextEmbedding ({self.fastembed_model_name}) with {num_threads} threads...")
        self.fastembed_model = TextEmbedding(model_name=self.fastembed_model_name, threads=num_threads)

    def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        from src.shared.extractors.openai_extractor import openai_extractor
        if not openai_extractor.client:
            raise RuntimeError("[Embedding-OpenAI] ❌ OPENAI_API_KEY chưa được cấu hình hoặc client chưa sẵn sàng.")
        
        # OpenAI cho phép gửi batch tối đa 2048 items mỗi request
        # Chia batch nhỏ 100 texts để tránh quá tải payload
        batch_size = 100
        all_embeddings: List[List[float]] = []
        start_time = time.time()
        
        Log.info(f"[Embedding-OpenAI] 📤 Bắt đầu embed {len(texts)} đoạn văn bản (Model: {self.openai_model})...")
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Làm sạch chuỗi rỗng
            cleaned_batch = [t if t and t.strip() else " " for t in batch]
            try:
                t0 = time.time()
                response = openai_extractor.client.embeddings.create(
                    model=self.openai_model,
                    input=cleaned_batch
                )
                batch_vectors = [item.embedding for item in response.data]
                all_embeddings.extend(batch_vectors)
                elapsed_batch = time.time() - t0
                Log.debug(f"[Embedding-OpenAI] Batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}: {len(batch)} items ({elapsed_batch:.2f}s)")
            except Exception as e:
                Log.error(f"[Embedding-OpenAI] ❌ Lỗi khi gọi OpenAI API cho batch {i//batch_size + 1}: {e}")
                raise e

        total_elapsed = time.time() - start_time
        Log.info(f"[Embedding-OpenAI] ✅ Hoàn tất embed {len(all_embeddings)} vectors trong {total_elapsed:.2f}s!")
        return all_embeddings

    def _embed_fastembed(self, texts: List[str]) -> List[List[float]]:
        if not self.fastembed_model:
            self._init_fastembed()
        
        start_time = time.time()
        Log.info(f"[Embedding-FastEmbed] ⚙️ Đang tính toán embedding cho {len(texts)} đoạn trên CPU...")
        try:
            embeddings = list(self.fastembed_model.embed(texts, batch_size=16))
            result = [emb.tolist() for emb in embeddings]
            del embeddings
            gc.collect()
            elapsed = time.time() - start_time
            Log.info(f"[Embedding-FastEmbed] ✅ Hoàn tất {len(result)} vectors trên CPU ({elapsed:.2f}s)")
            return result
        except Exception as e:
            Log.error(f"[Embedding-FastEmbed] ❌ Lỗi FastEmbed CPU: {e}")
            raise e

    def embed_text(self, texts: List[str]) -> List[List[float]]:
        """
        Convert a list of strings into a list of embeddings.
        Ưu tiên OpenAI nếu EMBEDDING_PROVIDER=openai, fallback FastEmbed nếu provider=fastembed.
        """
        if not texts:
            return []
            
        if self.provider == "openai":
            try:
                return self._embed_openai(texts)
            except Exception as e:
                Log.error(f"[Embedding] ⚠️ OpenAI failed: {e}. Đang thử fallback sang FastEmbed CPU...")
                return self._embed_fastembed(texts)
        else:
            return self._embed_fastembed(texts)

# Singleton instance
embedding_service = EmbeddingService()


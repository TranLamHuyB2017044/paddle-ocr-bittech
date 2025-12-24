import uuid
from typing import List, Dict
from src.rag.embedding_service import embedding_service
from src.rag.qdrant_service import qdrant_service
from src.rag.llm_service import llm_service
from src.utils.logger import Log
import src.config as config
from qdrant_client.http import models

class RagService:
    def split_text(self, text: str, chunk_size: int = config.RAG_CHUNK_SIZE, chunk_overlap: int = config.RAG_CHUNK_OVERLAP) -> List[str]:
        """
        Simple recursive character splitter.
        """
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - chunk_overlap
        return chunks

    def index_text(self, text: str, workspace_id: str, document_name: str):
        """
        Chunk text, embed it, and store in Qdrant.
        """
        Log.info(f"[RAG] Indexing document '{document_name}' for workspace '{workspace_id}'")
        chunks = self.split_text(text)
        Log.info(f"[RAG] Created {len(chunks)} chunks")
        
        embeddings = embedding_service.embed_text(chunks)
        
        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "text": chunk,
                        "workspace_id": workspace_id,
                        "document_name": document_name,
                        "chunk_index": i
                    }
                )
            )
        
        qdrant_service.upsert_points(points)
        Log.info(f"[RAG] Successfully indexed {len(points)} points in Qdrant")
        return len(points)

    def query(self, question: str, workspace_id: str, provider: str = "auto") -> Dict:
        """
        Perform RAG: Search -> Augment -> Generate.
        """
        # 1. Embed question
        Log.info(f"[RAG] 🔍 Querying for: '{question}' in Workspace '{workspace_id}'")
        question_vector = embedding_service.embed_text([question])[0]
        
        # 2. Search Qdrant
        results = qdrant_service.search(question_vector, workspace_id, limit=5)
        Log.info(f"[RAG] 🔎 Found {len(results)} relevant context chunks")
        
        context_parts = []
        sources = []
        for i, res in enumerate(results):
            txt = res.payload["text"]
            doc = res.payload["document_name"]
            score = res.score
            Log.debug(f"   [{i}] Score: {score:.4f} | Source: {doc} | Text: {txt[:50]}...")
            
            context_parts.append(txt)
            sources.append({
                "document_name": doc,
                "score": score
            })
            
        context = "\n\n---\n\n".join(context_parts)
        
        # 3. Augment & Generate
        system_instruction = (
            "Bạn là một trợ lý AI thông minh. Hãy trả lời câu hỏi dựa trên ngữ cảnh được cung cấp. "
            "Nếu thông tin không có trong ngữ cảnh, hãy trả lời chính xác là: 'Tôi không có thông tin', tuyệt đối không tự bịa ra câu trả lời. "
            "Nếu có thông tin, hãy trả lời một cách chi tiết và chuyên nghiệp bằng Tiếng Việt."
        )
        
        prompt = f"NGỮ CẢNH:\n{context}\n\nCÂU HỎI: {question}"
        
        answer, used_provider = llm_service.chat(prompt, system_instruction, provider=provider)
        
        Log.info(f"[RAG] ✅ Answer generated using provider: {used_provider}")
        
        return {
            "answer": answer,
            "provider": used_provider,
            "sources": sources
        }

    def suggest_questions(self, workspace_id: str) -> List[str]:
        """
        Suggest potential questions based on randomly sampled context from workspace.
        """
        # Since we don't have a "get random" easily, we search with a generic vector 
        # or just fetch recent points. In Qdrant we can scroll.
        scroll_result = qdrant_service.scroll(
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="workspace_id",
                        match=models.MatchValue(value=workspace_id),
                    )
                ]
            ),
            limit=10
        )
        
        points = scroll_result[0]
        if not points:
            return ["Tài liệu chưa có dữ liệu để gợi ý."]
        
        context = "\n".join([p.payload["text"] for p in points])[:2000]
        
        prompt = (
            f"Dựa trên nội dung sau đây, hãy gợi ý 3 câu hỏi ngắn gọn mà người dùng có thể muốn hỏi "
            f"để tìm hiểu thông tin từ tài liệu này. Chỉ trả về danh sách các câu hỏi, mỗi câu một dòng.\n\n"
            f"NỘI DUNG:\n{context}"
        )
        
        suggestion_text, _ = llm_service.chat(prompt, "Bạn là trợ lý gợi ý câu hỏi.")
        # Simple parsing (split by newline and clean)
        suggestions = [s.strip('- ').strip() for s in suggestion_text.split('\n') if s.strip()]
        return suggestions[:5]

rag_service = RagService()

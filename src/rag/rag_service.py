import uuid
import concurrent.futures
import os
import re
from typing import List, Dict
from src.rag.embedding_service import embedding_service
from src.rag.qdrant_service import qdrant_service
from src.rag.llm_service import llm_service
from src.utils.logger import Log
import src.config as config
from qdrant_client.http import models

def clean_question(question: str) -> str:
    """
    Loại bỏ các ký tự số thứ tự hoặc gạch đầu dòng dư thừa ở đầu câu hỏi gợi ý.
    Ví dụ: "1. Tiêu chí đánh giá..." -> "Tiêu chí đánh giá..."
    """
    if not question:
        return ""
    return re.sub(r'^\s*[\d\.\-\*\•]+\s*', '', question).strip()

class RagService:
    @staticmethod
    def _chunk_worker(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
        """
        Worker function for multiprocessing chunking.
        """
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - chunk_overlap
            if start >= len(text) - chunk_overlap: # Avoid infinite loop or tiny last chunk
                break
        return chunks

    def split_text(self, text: str, chunk_size: int = config.RAG_CHUNK_SIZE, chunk_overlap: int = config.RAG_CHUNK_OVERLAP) -> List[str]:
        """
        Public API for splitting text.
        """
        return self._chunk_worker(text, chunk_size, chunk_overlap)

    def index_text(self, data, workspace_id: str, document_name: str, batch_size: int = 50):
        """
        Chunk text, embed it, and store in Qdrant.
        data can be:
        - str: raw text
        - list: List of dicts [{"text": str, "page_num": int}]
        """
        Log.info(f"[RAG] Indexing document '{document_name}' for workspace '{workspace_id}'")
        
        all_chunks_with_meta = []
        
        if isinstance(data, str):
            # Fallback for simple string
            chunks = self.split_text(data)
            for i, chunk in enumerate(chunks):
                all_chunks_with_meta.append({
                    "text": chunk,
                    "page_num": 1, # Default to page 1
                    "chunk_index": i
                })
        elif isinstance(data, list):
            # Structured data with pages
            for item in data:
                text = item.get("text", "")
                page_num = item.get("page_num", 1)
                if not text.strip():
                    continue
                
                chunks = self.split_text(text)
                for i, chunk in enumerate(chunks):
                    all_chunks_with_meta.append({
                        "text": chunk,
                        "page_num": page_num,
                        "chunk_index": i # Index within page, but we'll re-index later if needed
                    })
        
        if not all_chunks_with_meta:
            Log.warning("[RAG] No text to index")
            return 0
            
        Log.info(f"[RAG] Created {len(all_chunks_with_meta)} chunks across all pages")
        
        # 2. Batch Embedding & Upserting
        total_indexed = 0
        for i in range(0, len(all_chunks_with_meta), batch_size):
            batch = all_chunks_with_meta[i : i + batch_size]
            batch_texts = [item["text"] for item in batch]
            
            Log.debug(f"[RAG] Processing batch {i//batch_size + 1}/{(len(all_chunks_with_meta)-1)//batch_size + 1}")
            
            embeddings = embedding_service.embed_text(batch_texts)
            
            points = []
            for j, (item, vector) in enumerate(zip(batch, embeddings)):
                points.append(
                    models.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload={
                            "text": item["text"],
                            "workspace_id": workspace_id,
                            "document_name": document_name,
                            "page_num": item["page_num"],
                            "chunk_index": i + j
                        }
                    )
                )
            
            qdrant_service.upsert_points(points)
            total_indexed += len(points)
            
        Log.info(f"[RAG] Successfully indexed {total_indexed} points in Qdrant")
        return total_indexed

    def query(self, question: str, workspace_id: str, provider: str = "auto") -> Dict:
        """
        Perform RAG: Search -> Augment -> Generate.
        """
        # 1. Clean and Embed question
        cleaned_q = clean_question(question)
        Log.info(f"[RAG] 🔍 Querying for: '{cleaned_q}' (original: '{question}') in Workspace '{workspace_id}'")
        question_vector = embedding_service.embed_text([cleaned_q])[0]
        
        # 2. Search Qdrant
        results = qdrant_service.search(question_vector, workspace_id, limit=5)
        Log.info(f"[RAG] 🔎 Found {len(results)} relevant context chunks")
        
        context_parts = []
        sources = []
        unique_sources = set()
        
        retrieved_pages = set()
        parent_pages_count = 0
        MAX_PARENT_PAGES = 2 # Giới hạn tối đa 2 trang nguyên vẹn để tránh bùng nổ Token
        
        for i, res in enumerate(results):
            txt = res.payload["text"]
            doc = res.payload.get("document_name", "unknown")
            page = res.payload.get("page_num", 1)
            score = res.score
            
            Log.debug(f"   [{i}] Score: {score:.4f} | Source: {doc} (P.{page}) | Text: {txt[:50]}...")
            
            source_key = f"{doc}_page_{page}"
            page_key = (doc, page)
            
            # Nếu trang này đã được lấy nguyên bản trước đó -> Bỏ qua
            if page_key in retrieved_pages:
                if source_key not in unique_sources:
                    sources.append({
                        "document_name": doc,
                        "page_num": page,
                        "score": score
                    })
                    unique_sources.add(source_key)
                continue
                
            # Kiểm tra điều kiện nạp nguyên trang (Parent Page)
            if doc != "unknown" and page > 0 and parent_pages_count < MAX_PARENT_PAGES:
                retrieved_pages.add(page_key)
                parent_pages_count += 1
                
                # Fetch toàn bộ các mảnh của trang đó để ghép lại
                page_chunks = qdrant_service.get_chunks_for_page(workspace_id, doc, page)
                if page_chunks:
                    # Sắp xếp theo chunk_index để giữ đúng thứ tự đọc tự nhiên
                    page_chunks.sort(key=lambda x: x.payload.get("chunk_index", 0))
                    full_page_text = "\n".join([c.payload["text"] for c in page_chunks])
                    
                    context_parts.append(f"--- NGUỒN: {doc}, TRANG: {page} ---\n{full_page_text}")
                    Log.info(f"[RAG] Reconstructed full parent page context: {doc} (Page {page})")
                    
                    if source_key not in unique_sources:
                        sources.append({
                            "document_name": doc,
                            "page_num": page,
                            "score": score
                        })
                        unique_sources.add(source_key)
                    continue
            
            # Fallback: Nếu vượt quá giới hạn trang hoặc không thể ghép trang, dùng chính nội dung chunk thô
            if source_key not in unique_sources:
                context_parts.append(f"--- NGUỒN: {doc}, TRANG: {page} (Đoạn trích) ---\n{txt}")
                sources.append({
                    "document_name": doc,
                    "page_num": page,
                    "score": score
                })
                unique_sources.add(source_key)
            
        context = "\n\n".join(context_parts)
        
        # 3. Augment & Generate
        system_instruction = (
            "Bạn là một trợ lý AI thông minh. Hãy trả lời câu hỏi dựa trên ngữ cảnh được cung cấp. "
            "Ngữ cảnh bao gồm các đoạn trích từ tài liệu, mỗi đoạn có thông tin 'NGUỒN' và 'TRANG'.\n\n"
            "QUY TẮC:\n"
            "1. Nếu thông tin có trong ngữ cảnh, hãy trả lời ngắn gọn, chính xác bằng Tiếng Việt.\n"
            "2. Cuối câu trả lời, hãy luôn thêm một phần 'Trích nguồn:' liệt kê các tài liệu và số trang bạn đã dùng để trả lời. "
            "Ví dụ: 'Trích nguồn: Thong_tu_01.pdf (Trang 5), Cong_van_123.pdf (Trang 2)'.\n"
            "3. Nếu thông tin KHÔNG có trong ngữ cảnh, hãy trả lời chính xác là: 'Tôi không có thông tin trong tài liệu đã cung cấp.', tuyệt đối không tự bịa ra câu trả lời.\n"
            "4. Giữ văn phong chuyên nghiệp và khách quan."
        )
        
        prompt = f"DỰA TRÊN NGỮ CẢNH SAU:\n{context}\n\nCÂU HỎI: {question}"
        
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
            f"để tìm hiểu thông tin từ tài liệu này. QUY TẮC: Chỉ gợi ý các câu hỏi mà câu trả lời chi tiết "
            f"của nó có thể được tìm thấy trực tiếp trong đoạn nội dung được cung cấp bên dưới (không gợi ý câu hỏi "
            f"nếu nội dung chỉ đề cập lướt qua tên tiêu đề hoặc từ khóa mà không giải thích chi tiết).\n"
            f"Chỉ trả về danh sách các câu hỏi, mỗi câu một dòng.\n\n"
            f"NỘI DUNG:\n{context}"
        )
        
        suggestion_text, _ = llm_service.chat(prompt, "Bạn là trợ lý gợi ý câu hỏi.")
        # Simple parsing (split by newline and clean)
        suggestions = [s.strip('- ').strip() for s in suggestion_text.split('\n') if s.strip()]
        return suggestions[:5]

    def chat_store(self, question: str, workspace_id: str, provider: str = "auto", 
                   telegram_bot_token: str = None, telegram_chat_id: str = None, 
                   chatbot_name: str = "Chatbot") -> Dict:
        """
        Chat for store: no source citations, optimized for customer support.
        Sends Telegram notification if no information is found.
        """
        # 1. Clean and Embed question
        cleaned_q = clean_question(question)
        Log.info(f"[RAG Store Chat] 🔍 Querying for: '{cleaned_q}' (original: '{question}') in Workspace '{workspace_id}'")
        question_vector = embedding_service.embed_text([cleaned_q])[0]
        
        # 2. Search Qdrant
        results = qdrant_service.search(question_vector, workspace_id, limit=5)
        Log.info(f"[RAG Store Chat] 🔎 Found {len(results)} relevant context chunks")
        
        # Log what Qdrant returned (for debugging)
        if len(results) > 0:
            Log.info(f"[RAG Store Chat] 📄 Context chunks found:")
            for i, res in enumerate(results):
                doc_name = res.payload.get("document_name", "unknown")
                Log.info(f"   [{i+1}] Doc: {doc_name} | Text: {res.payload['text'][:80]}...")
        else:
            Log.info(f"[RAG Store Chat] 📭 NO context found in Qdrant!")
        
        context_parts = []
        retrieved_pages = set()
        parent_pages_count = 0
        MAX_PARENT_PAGES = 2 # Giới hạn tối đa 2 trang nguyên vẹn để tránh bùng nổ Token
        
        for i, res in enumerate(results):
            txt = res.payload["text"]
            doc = res.payload.get("document_name", "unknown")
            page = res.payload.get("page_num", 1)
            
            page_key = (doc, page)
            
            # Nếu trang này đã được lấy nguyên bản trước đó -> Bỏ qua
            if page_key in retrieved_pages:
                continue
                
            # Kiểm tra điều kiện nạp nguyên trang (Parent Page)
            if doc != "unknown" and page > 0 and parent_pages_count < MAX_PARENT_PAGES:
                retrieved_pages.add(page_key)
                parent_pages_count += 1
                
                # Fetch toàn bộ các mảnh của trang đó để ghép lại
                page_chunks = qdrant_service.get_chunks_for_page(workspace_id, doc, page)
                if page_chunks:
                    # Sắp xếp theo chunk_index để giữ đúng thứ tự đọc tự nhiên
                    page_chunks.sort(key=lambda x: x.payload.get("chunk_index", 0))
                    full_page_text = "\n".join([c.payload["text"] for c in page_chunks])
                    context_parts.append(full_page_text)
                    Log.info(f"[RAG Store Chat] Reconstructed full parent page context: {doc} (Page {page})")
                    continue
            
            # Fallback: dùng chính nội dung chunk thô
            context_parts.append(txt)
        
        context = "\n\n".join(context_parts)
        
        # 3. Augment & Generate - NO SOURCE CITATIONS
        # Strict system prompt to prevent hallucination
        if len(results) == 0:
            # No context at all - force "no information"
            system_instruction = (
                "Bạn là một trợ lý chatbot hỗ trợ khách hàng. "
                "Hiện tại bạn KHÔNG CÓ NỘI DUNG TÀI LIỆU NÀO. "
                "BẠN CHỈ ĐƯỢC NÓI: 'Tôi không có thông tin về câu hỏi này. Vui lòng cung cấp thông tin liên hệ để nhân viên hỗ trợ bạn.' "
                "TUYỆT ĐỘI KHÔNG TỰ TẠO RA CÂU TRẢ LỜI NÀO KHÁC. "
                "KHÔNG ĐỀ CẬP ĐẾN Bittech. "
            )
        else:
            system_instruction = (
                "Bạn là một trợ lý chatbot hỗ trợ khách hàng chuyên nghiệp. "
                "CHỈ trả lời dựa TRỰC TIẾP trên NỘI DUNG TÀI LIỆU được cung cấp bên dưới. "
                "Nếu thông tin không có trong tài liệu, hãy nói một cách lịch sự rằng bạn không có thông tin đó. "
                "Giữ văn phong thân thiện, lịch sự và ngắn gọn. "
                "KHÔNG tự bịa ra câu trả lời. "
                "KHÔNG trả lời liên quan tới Bittech. "
                "CHỈ trả lời dựa trên nội dung tài liệu được cung cấp."
            )
        
        prompt = f"DỰA TRÊN NỘI DUNG TÀI LIỆU SAU:\n{context}\n\nCÂU HỎI CỦA KHÁCH HÀNG: {question}"
        
        answer, used_provider = llm_service.chat(prompt, system_instruction, provider=provider)
        
        Log.info(f"[RAG Store Chat] ✅ Answer generated using provider: {used_provider}")
        
        # 4. Check if we need to send Telegram notification
        # Detect if the answer indicates no information is available
        no_info_keywords = ["không có thông tin", "không tìm thấy", "không biết", "sẽ liên hệ", "liên hệ lại"]
        is_no_info = any(keyword.lower() in answer.lower() for keyword in no_info_keywords)
        
        if is_no_info and telegram_bot_token and telegram_chat_id:
            try:
                from src.services.telegram_service import send_telegram_message, format_customer_question_notification
                notification_message = format_customer_question_notification(question, chatbot_name)
                send_telegram_message(telegram_bot_token, telegram_chat_id, notification_message)
            except Exception as e:
                Log.error(f"[RAG Store Chat] Lỗi khi gửi thông báo Telegram: {str(e)}")
        
        return {
            "answer": answer,
            "provider": used_provider
        }

rag_service = RagService()

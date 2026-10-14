import uuid
import concurrent.futures
import os
import re
from typing import List, Dict
from src.modules.rag.embedding_service import embedding_service
from src.modules.rag.qdrant_service import qdrant_service
from src.modules.rag.llm_service import llm_service
from src.shared.utils.logger import Log
import src.core.config as config
from qdrant_client.http import models
from src.modules.chatbot.services.prompt_service import get_chatbot_prompt

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

    def index_text(self, data, workspace_id: str, document_name: str, batch_size: int = 32,
                   category: str | None = None, document_id: str | None = None):
        """
        Chunk text, embed it, and store in Qdrant with optional category and document_id metadata.
        data can be:
        - str: raw text
        - list: List of dicts [{"text": str, "page_num": int}]
        """
        import gc
        Log.info(f"[RAG] Indexing document '{document_name}' (ID: {document_id}, Category: {category}) for workspace '{workspace_id}'")
        
        all_chunks_with_meta = []
        
        if isinstance(data, str):
            chunks = self.split_text(data)
            for i, chunk in enumerate(chunks):
                all_chunks_with_meta.append({
                    "text": chunk,
                    "page_num": 1,
                    "chunk_index": i
                })
        elif isinstance(data, list):
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
                        "chunk_index": i
                    })
        
        if not all_chunks_with_meta:
            Log.warning("[RAG] No text to index")
            return 0
            
        Log.info(f"[RAG] Created {len(all_chunks_with_meta)} chunks across all pages")
        
        # Batch Embedding & Upserting
        total_indexed = 0
        for i in range(0, len(all_chunks_with_meta), batch_size):
            batch = all_chunks_with_meta[i : i + batch_size]
            batch_texts = [item["text"] for item in batch]
            
            Log.debug(f"[RAG] Processing batch {i//batch_size + 1}/{(len(all_chunks_with_meta)-1)//batch_size + 1}")
            embeddings = embedding_service.embed_text(batch_texts)
            
            points = []
            for j, (item, vector) in enumerate(zip(batch, embeddings)):
                payload = {
                    "text": item["text"],
                    "workspace_id": str(workspace_id),
                    "document_name": document_name,
                    "page_num": item["page_num"],
                    "chunk_index": i + j
                }
                if document_id:
                    payload["document_id"] = str(document_id)
                if category:
                    payload["category"] = category

                points.append(
                    models.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload=payload
                    )
                )
            
            qdrant_service.upsert_points(points)
            total_indexed += len(points)
            del points, embeddings, batch_texts, batch
            gc.collect()
            
        Log.info(f"[RAG] Successfully indexed {total_indexed} points in Qdrant")
        return total_indexed

    def _retrieve_context(self, question_vector, workspace_id: str, category: str | None = None, limit: int = 5):
        """
        Helper method to retrieve chunks from Qdrant, reconstruct parent pages, and build sources.
        """
        results = qdrant_service.search(question_vector, workspace_id, limit=limit, category=category)
        Log.info(f"[RAG Retrieve] 🔎 Found {len(results)} relevant context chunks (category: {category})")

        context_parts = []
        sources = []
        unique_sources = set()
        retrieved_pages = set()
        parent_pages_count = 0
        MAX_PARENT_PAGES = 2

        for i, res in enumerate(results):
            txt = res.payload.get("text", "")
            doc = res.payload.get("document_name", "unknown")
            page = res.payload.get("page_num", 1)
            doc_id = res.payload.get("document_id")
            cat = res.payload.get("category")
            score = float(getattr(res, "score", 0.0))

            source_key = f"{doc}_page_{page}"
            page_key = (doc, page)

            snippet = txt.strip()
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."

            source_item = {
                "document_id": doc_id,
                "document_name": doc,
                "page_num": page,
                "score": round(score, 4),
                "category": cat,
                "snippet": snippet
            }

            if page_key in retrieved_pages:
                if source_key not in unique_sources:
                    sources.append(source_item)
                    unique_sources.add(source_key)
                continue

            if doc != "unknown" and page > 0 and parent_pages_count < MAX_PARENT_PAGES:
                retrieved_pages.add(page_key)
                parent_pages_count += 1
                page_chunks = qdrant_service.get_chunks_for_page(workspace_id, doc, page)
                if page_chunks:
                    page_chunks.sort(key=lambda x: x.payload.get("chunk_index", 0))
                    full_page_text = "\n".join([c.payload.get("text", "") for c in page_chunks])
                    context_parts.append(f"--- NGUỒN: {doc}, TRANG: {page} ---\n{full_page_text}")
                    if source_key not in unique_sources:
                        sources.append(source_item)
                        unique_sources.add(source_key)
                    continue

            if source_key not in unique_sources:
                context_parts.append(f"--- NGUỒN: {doc}, TRANG: {page} (Đoạn trích) ---\n{txt}")
                sources.append(source_item)
                unique_sources.add(source_key)

        context = "\n\n".join(context_parts)
        return context, sources, results

    def query(self, question: str, workspace_id: str, provider: str = "auto", category: str | None = None) -> Dict:
        """
        Perform RAG: Search -> Augment -> Generate.
        """
        cleaned_q = clean_question(question)
        Log.info(f"[RAG] 🔍 Querying for: '{cleaned_q}' (original: '{question}') in Workspace '{workspace_id}' (Category: '{category}')")
        question_vector = embedding_service.embed_text([cleaned_q])[0]
        
        context, sources, _ = self._retrieve_context(question_vector, workspace_id, category=category, limit=5)
        
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
        
        # Filter sources with minimum relevance score
        min_score = getattr(config, "RAG_SOURCE_MIN_SCORE", 0.35)
        filtered_sources = [s for s in sources if s["score"] >= min_score]
        
        Log.info(f"[RAG] ✅ Answer generated using provider: {used_provider}")
        
        return {
            "answer": answer,
            "provider": used_provider,
            "sources": filtered_sources
        }

    def suggest_questions(self, workspace_id: str, domain: str = "general", category: str | None = None) -> List[str]:
        """
        Suggest potential questions based on context from workspace and optional category.
        """
        must_conditions = [
            models.FieldCondition(
                key="workspace_id",
                match=models.MatchValue(value=str(workspace_id)),
            )
        ]
        if category:
            must_conditions.append(
                models.FieldCondition(
                    key="category",
                    match=models.MatchValue(value=str(category)),
                )
            )

        scroll_result = qdrant_service.scroll(
            scroll_filter=models.Filter(must=must_conditions),
            limit=10
        )
        
        points = scroll_result[0]
        if not points:
            return ["Tài liệu chưa có dữ liệu để gợi ý."]
        
        context = "\n".join([p.payload.get("text", "") for p in points])[:2000]
        
        if domain == "administrative_doc":
            prompt = (
                f"Dựa trên nội dung văn bản hành chính sau đây, hãy gợi ý 3 câu hỏi ngắn gọn, thiết thực mà người dân hoặc cán bộ có thể muốn hỏi "
                f"(ví dụ về thành phần hồ sơ, điều kiện áp dụng, trình tự thực hiện, thẩm quyền hoặc thời hạn giải quyết). "
                f"QUY TẮC: Chỉ gợi ý các câu hỏi mà câu trả lời chi tiết của nó có thể được tìm thấy trực tiếp trong đoạn nội dung được cung cấp bên dưới.\n"
                f"Chỉ trả về danh sách các câu hỏi, mỗi câu một dòng.\n\n"
                f"NỘI DUNG:\n{context}"
            )
            suggestion_text, _ = llm_service.chat(prompt, "Bạn là chuyên viên hành chính gợi ý câu hỏi tra cứu thủ tục.")
        else:
            prompt = (
                f"Dựa trên nội dung sau đây, hãy gợi ý 3 câu hỏi ngắn gọn mà người dùng có thể muốn hỏi "
                f"để tìm hiểu thông tin từ tài liệu này. QUY TẮC: Chỉ gợi ý các câu hỏi mà câu trả lời chi tiết "
                f"của nó có thể được tìm thấy trực tiếp trong đoạn nội dung được cung cấp bên dưới (không gợi ý câu hỏi "
                f"nếu nội dung chỉ đề cập lướt qua tên tiêu đề hoặc từ khóa mà không giải thích chi tiết).\n"
                f"Chỉ trả về danh sách các câu hỏi, mỗi câu một dòng.\n\n"
                f"NỘI DUNG:\n{context}"
            )
            suggestion_text, _ = llm_service.chat(prompt, "Bạn là trợ lý gợi ý câu hỏi.")

        suggestions = [s.strip('- ').strip() for s in suggestion_text.split('\n') if s.strip()]
        return suggestions[:5]

    def chat_store(self, question: str, workspace_id: str, provider: str = "auto", 
                   telegram_bot_token: str | None = None, telegram_chat_id: str | None = None, 
                   chatbot_name: str = "Chatbot", domain: str = "ecommerce",
                   category: str | None = None, include_sources: bool = False) -> Dict:
        """
        Chat for store: optionally includes verified source citations when requested.
        Sends Telegram notification if no information is found.
        """
        cleaned_q = clean_question(question)
        Log.info(f"[RAG Store Chat] 🔍 Querying for: '{cleaned_q}' (original: '{question}') in Workspace '{workspace_id}' (Domain: '{domain}', Category: '{category}')")
        question_vector = embedding_service.embed_text([cleaned_q])[0]
        
        context, sources, results = self._retrieve_context(question_vector, workspace_id, category=category, limit=5)
        
        domain_prompt = get_chatbot_prompt(domain)
        if len(results) == 0:
            if domain == "administrative_doc":
                system_instruction = (
                    f"{domain_prompt}\n\n"
                    "LƯU Ý QUAN TRỌNG: Hiện tại bạn KHÔNG TÌM THẤY thông tin quy định hoặc văn bản liên quan đến câu hỏi này. "
                    "BẠN CHỈ ĐƯỢC NÓI: 'Nội dung này chưa được quy định hoặc chưa có trong tài liệu văn bản được cung cấp. Vui lòng liên hệ cơ quan ban hành hoặc Bộ phận Một cửa có thẩm quyền để được giải đáp chính thức.' "
                    "TUYỆT ĐỐI KHÔNG TỰ TẠO RA CÂU TRẢ LỜI NÀO KHÁC NGOÀI TÀI LIỆU ĐÃ CÓ. "
                    "KHÔNG ĐỀ CẬP ĐẾN Bittech."
                )
            else:
                system_instruction = (
                    f"{domain_prompt}\n\n"
                    "LƯU Ý QUAN TRỌNG: Hiện tại bạn KHÔNG TÌM THẤY thông tin tài liệu liên quan đến câu hỏi này. "
                    "BẠN CHỈ ĐƯỢC NÓI: 'Tôi không có thông tin về câu hỏi này. Vui lòng cung cấp thông tin liên hệ để nhân viên hỗ trợ bạn.' "
                    "TUYỆT ĐỘI KHÔNG TỰ TẠO RA CÂU TRẢ LỜI NÀO KHÁC NGOÀI THỰC TẾ. "
                    "KHÔNG ĐỀ CẬP ĐẾN Bittech."
                )
        else:
            if domain == "administrative_doc":
                system_instruction = (
                    f"{domain_prompt}\n\n"
                    "QUY TẮC BẮT BUỘC:\n"
                    "- CHỈ trả lời dựa TRỰC TIẾP trên NỘI DUNG VĂN BẢN HÀNH CHÍNH được cung cấp bên dưới.\n"
                    "- NÊU RÕ CĂN CỨ VĂN BẢN: Trích dẫn rõ Số/Ký hiệu văn bản, Cơ quan ban hành, Ngày ban hành, và Điều/Khoản/Điểm cụ thể nếu có trong nội dung.\n"
                    "- Nếu thông tin không có trong tài liệu, hãy nói một cách lịch sự rằng nội dung này chưa được quy định trong tài liệu được cung cấp.\n"
                    "- Giữ văn phong chuẩn mực hành chính, rõ ràng, khách quan và chính xác.\n"
                    "- KHÔNG tự bịa ra câu trả lời hay điều khoản không tồn tại.\n"
                    "- KHÔNG trả lời liên quan tới Bittech."
                )
            else:
                system_instruction = (
                    f"{domain_prompt}\n\n"
                    "QUY TẮC BẮT BUỘC:\n"
                    "- CHỈ trả lời dựa TRỰC TIẾP trên NỘI DUNG TÀI LIỆU được cung cấp bên dưới.\n"
                    "- Nếu thông tin không có trong tài liệu, hãy nói một cách lịch sự rằng bạn không có thông tin đó.\n"
                    "- Giữ văn phong phù hợp với vai trò được giao, thân thiện, lịch sự và ngắn gọn.\n"
                    "- KHÔNG tự bịa ra câu trả lời.\n"
                    "- KHÔNG trả lời liên quan tới Bittech.\n"
                    "- CHỈ trả lời dựa trên nội dung tài liệu được cung cấp."
                )
        
        prompt = f"DỰA TRÊN NỘI DUNG TÀI LIỆU SAU:\n{context}\n\nCÂU HỎI: {question}"
        answer, used_provider = llm_service.chat(prompt, system_instruction, provider=provider)
        Log.info(f"[RAG Store Chat] ✅ Answer generated using provider: {used_provider}")
        
        # Check no-info keywords
        no_info_keywords = ["không có thông tin", "không tìm thấy", "không biết", "sẽ liên hệ", "liên hệ lại"]
        is_no_info = any(keyword.lower() in answer.lower() for keyword in no_info_keywords)
        
        if is_no_info and telegram_bot_token and telegram_chat_id:
            try:
                from src.shared.services.telegram_service import send_telegram_message, format_customer_question_notification
                notification_message = format_customer_question_notification(question, chatbot_name)
                send_telegram_message(telegram_bot_token, telegram_chat_id, notification_message)
            except Exception as e:
                Log.error(f"[RAG Store Chat] Lỗi khi gửi thông báo Telegram: {str(e)}")
        
        # Determine sources to return
        final_sources = []
        if include_sources and not is_no_info:
            min_score = getattr(config, "RAG_SOURCE_MIN_SCORE", 0.35)
            final_sources = [s for s in sources if s["score"] >= min_score]
        
        return {
            "answer": answer,
            "provider": used_provider,
            "sources": final_sources
        }

rag_service = RagService()


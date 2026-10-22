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

def extract_document_identifiers(text: str) -> dict:
    """
    Trích xuất mã định danh cụ thể từ câu hỏi:
    - arrival_no (Số đến): Số 68, số đến 68, công văn số 68...
    - document_no (Ký hiệu): 157/CV-2026, 148/UBND-2026, BG260819B404...
    """
    res = {"arrival_no": None, "document_no": None}
    if not text:
        return res
    
    # 1. Bắt số đến: "số đến 68", "công văn số 68", "số 68"
    arrival_match = re.search(r'(?:công văn|văn bản|cv|vb)?\s*(?:số\s+đến|số)\s*[:#]?\s*(\d+)\b', text, re.IGNORECASE)
    if arrival_match:
        try:
            num = int(arrival_match.group(1))
            if num < 1900 or num > 2100:  # Tránh bắt nhầm năm 2024, 2026
                res["arrival_no"] = num
        except:
            pass

    # 2. Bắt số ký hiệu có dấu gạch chéo: ví dụ "157/CV-2026", "148/UBND-2026"
    doc_no_match = re.search(r'\b(\d+/[A-Z0-9\-_]+)\b', text, re.IGNORECASE)
    if doc_no_match:
        res["document_no"] = doc_no_match.group(1).upper()
    else:
        # 3. Bắt mã ký hiệu chữ + số dạng đặc thù: ví dụ "BG260819B404", "BG260819B40433"
        code_match = re.search(r'\b([A-Z]{2,}\d+[A-Z0-9]*)\b', text)
        if code_match:
            res["document_no"] = code_match.group(1)

    return res

def format_record_as_context(payload: dict) -> str:
    """Format payload của 1 dòng dữ liệu văn bản đến thành block context chuẩn từ tài liệu gốc cho LLM"""
    parts = ["--- NGUỒN: VĂN BẢN ĐẾN (BẢN GỐC TỪ HỆ THỐNG) ---"]
    if payload.get("arrivalNo"):
        parts.append(f"- Số đến (Số công văn đến): Số {payload.get('arrivalNo')}")
    if payload.get("documentNo"):
        parts.append(f"- Số ký hiệu văn bản: {payload.get('documentNo')}")
    if payload.get("title"):
        parts.append(f"- Tiêu đề (Trích yếu nội dung): {payload.get('title')}")
    if payload.get("senderOrg"):
        parts.append(f"- Cơ quan ban hành / Đơn vị gửi: {payload.get('senderOrg')}")
    if payload.get("categoryName") or payload.get("category"):
        parts.append(f"- Lĩnh vực: {payload.get('categoryName') or payload.get('category')}")
    if payload.get("bookNo"):
        parts.append(f"- Sổ văn bản: {payload.get('bookNo')}")
    
    rec_date = payload.get("receiveDate") or "Chưa có"
    iss_date = payload.get("issueDate") or "Chưa có"
    parts.append(f"- Ngày đến (Ngày nhận): {rec_date} | Ngày ban hành: {iss_date}")
    
    deadline = payload.get("deadline")
    if deadline:
        parts.append(f"- Hạn xử lý (Thời hạn giải quyết): {deadline}")
    else:
        parts.append("- Hạn xử lý (Thời hạn giải quyết): Không đặt hạn")
        
    parts.append(f"- Trạng thái xử lý hiện tại: {payload.get('status', 'Mới nhận')}")
    parts.append(f"- Mức độ khẩn: {payload.get('priority', 'Thường')} | Mức độ mật: {payload.get('security', 'Thường')}")
    
    dept = payload.get("currentDeptName") or "Chưa phân luồng"
    user = payload.get("currentUserName") or "Chưa giao"
    parts.append(f"- Đơn vị thụ lý: {dept}")
    parts.append(f"- Cán bộ phụ trách: {user}")
    
    assignees = payload.get("assignees")
    if assignees and isinstance(assignees, list):
        ass_str = ", ".join([f"{a.get('fullName', '')} ({a.get('role', '')})" for a in assignees if isinstance(a, dict)])
        if ass_str:
            parts.append(f"- Cán bộ phối hợp: {ass_str}")
            
    if payload.get("note"):
        parts.append(f"- Ghi chú: {payload.get('note')}")
        
    return "\n".join(parts)


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
        Public API for splitting text using smart structure-aware chunking.
        """
        from src.modules.rag.chunking_service import chunk_document_smart
        chunks = chunk_document_smart(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        return [c["text"] for c in chunks]

    def index_text(self, data, workspace_id: str, document_name: str, batch_size: int = 32,
                   category: str | None = None, document_id: str | None = None):
        """
        Smart structure-aware chunking, embedding, and storing in Qdrant with
        section/chapter hierarchy, category, and document_id metadata.
        data can be:
        - str: raw text
        - list: List of dicts [{"text": str, "page_num": int}]
        """
        import gc
        from src.modules.rag.chunking_service import chunk_document_smart
        
        Log.info(f"[RAG] Indexing document '{document_name}' (ID: {document_id}, Category: {category}) for workspace '{workspace_id}'")
        
        all_chunks_with_meta = chunk_document_smart(
            data,
            document_name=document_name,
            chunk_size=getattr(config, "RAG_CHUNK_SIZE", 1000),
            chunk_overlap=getattr(config, "RAG_CHUNK_OVERLAP", 150)
        )
        
        if not all_chunks_with_meta:
            Log.warning("[RAG] No text to index")
            return 0
            
        Log.info(f"[RAG] 📦 Created {len(all_chunks_with_meta)} structure-aware chunks for '{document_name}'")
        
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
                    "page_num": item.get("page_num", 1),
                    "chunk_index": item.get("chunk_index", i + j)
                }
                if item.get("section_title"):
                    payload["section_title"] = item["section_title"]
                if item.get("chapter_title"):
                    payload["chapter_title"] = item["chapter_title"]
                if item.get("raw_text"):
                    payload["raw_text"] = item["raw_text"]
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
                "section_title": res.payload.get("section_title"),
                "chapter_title": res.payload.get("chapter_title"),
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
                f"Dựa trên nội dung trích xuất từ văn bản sau đây, hãy gợi ý 3 câu hỏi ngắn gọn, thiết thực nhất mà người đọc có thể muốn tra cứu.\n"
                f"QUY TẮC BẮT BUỘC:\n"
                f"1. Câu hỏi PHẢI có câu trả lời rõ ràng, trực tiếp ngay trong đoạn trích xuất bên dưới.\n"
                f"2. KHÔNG đặt câu hỏi suy diễn chéo (ví dụ: nếu đoạn trích chỉ nêu mức phạt của hành vi thì KHÔNG hỏi về thẩm quyền ai xử phạt, trừ khi đoạn trích nêu cụ thể thẩm quyền của hành vi đó).\n"
                f"3. Ưu tiên hỏi thẳng vào các thông tin cụ thể có sẵn: mức phạt, điều kiện, giấy tờ, trình tự.\n"
                f"4. Chỉ trả về các câu hỏi, mỗi câu một dòng, không đánh số thứ tự đầu dòng (không thêm 1., 2., -).\n\n"
                f"NỘI DUNG:\n{context}"
            )
            suggestion_text, _ = llm_service.chat(prompt, "Bạn là chuyên viên pháp lý gợi ý câu hỏi tra cứu chính xác từ tài liệu.")
        else:
            prompt = (
                f"Dựa trên nội dung sau đây, hãy gợi ý 3 câu hỏi ngắn gọn mà người dùng có thể muốn hỏi "
                f"để tìm hiểu thông tin từ tài liệu này.\n"
                f"QUY TẮC BẮT BUỘC:\n"
                f"1. Chỉ gợi ý câu hỏi mà câu trả lời chi tiết có sẵn trực tiếp trong đoạn nội dung bên dưới.\n"
                f"2. Không hỏi về các từ khóa chỉ xuất hiện thoáng qua mà không có nội dung giải thích.\n"
                f"3. Chỉ trả về danh sách các câu hỏi, mỗi câu một dòng, không đánh số thứ tự đầu dòng.\n\n"
                f"NỘI DUNG:\n{context}"
            )
            suggestion_text, _ = llm_service.chat(prompt, "Bạn là trợ lý gợi ý câu hỏi.")

        suggestions = []
        for line in suggestion_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            cleaned_s = re.sub(r'^\s*(\d+[\.\)]|[-*•])\s*', '', line).strip()
            if cleaned_s:
                suggestions.append(cleaned_s)

        return suggestions[:5]

    def chat_store(self, question: str, workspace_id: str, provider: str = "auto", 
                   telegram_bot_token: str | None = None, telegram_chat_id: str | None = None, 
                   chatbot_name: str = "Chatbot", domain: str = "ecommerce",
                   category: str | None = None, include_sources: bool = False,
                   session_id: str | None = None) -> Dict:
        """
        Chat for store:
        1. Nhận diện mã định danh cụ thể (Số đến, Số ký hiệu) để gọi thẳng bộ lọc Qdrant Filter (bỏ qua tính vector).
        2. Nhận diện ngữ cảnh câu hỏi nối tiếp (Follow-up Context) để xác định đúng văn bản mục tiêu mà KHÔNG làm lẫn tài liệu.
        3. TUYỆT ĐỐI KHÔNG dùng câu trả lời trước của bot làm Ground Truth (luôn đối chiếu lại tài liệu/record gốc).
        """
        cleaned_q = clean_question(question)
        Log.info(f"[RAG Store Chat] 🔍 Querying for: '{cleaned_q}' (original: '{question}') in Workspace '{workspace_id}' (Domain: '{domain}', Category: '{category}', Session: '{session_id}')")
        
        # 1. Trích xuất mã định danh từ câu hỏi hiện tại
        target_ids = extract_document_identifiers(cleaned_q)
        is_exact_match = False
        
        # 2. Xử lý Follow-up Context: Nếu câu hỏi hiện tại không có mã định danh, kiểm tra tin nhắn trước trong session
        if not target_ids["arrival_no"] and not target_ids["document_no"] and session_id:
            try:
                from src.modules.chatbot.repositories.chat_history_repository import chat_history_repo
                recent_msgs = chat_history_repo.get_recent_messages(session_id, limit=2)
                if recent_msgs:
                    # Quét câu hỏi của tin nhắn trước để xác định văn bản mục tiêu (Coreference Resolution)
                    prev_q = recent_msgs[-1].get("question", "")
                    prev_ids = extract_document_identifiers(prev_q)
                    if prev_ids["arrival_no"] or prev_ids["document_no"]:
                        target_ids = prev_ids
                        Log.info(f"[RAG Store Chat] 🔗 Follow-up detected! Context linked to document: {target_ids}")
            except Exception as hist_err:
                Log.debug(f"[RAG Store Chat] Could not fetch recent history: {hist_err}")

        context = ""
        sources = []
        results = []

        # 3. NẾU CÓ MÃ ĐỊNH DANH CỤ THỂ: GỌI THẲNG BỘ LỌC QDRANT (BỎ QUA TÍNH TOÁN VECTOR)
        if target_ids["arrival_no"] or target_ids["document_no"]:
            Log.info(f"[RAG Store Chat] ⚡ Exact Match Triggered: arrivalNo={target_ids['arrival_no']}, documentNo={target_ids['document_no']} -> Skipping Vector Embedding!")
            try:
                exact_points = qdrant_service.search_document_records(
                    workspace_id=workspace_id,
                    vector=None, # KHÔNG TÍNH VECTOR EMBEDDING
                    arrival_no=target_ids["arrival_no"],
                    document_no=target_ids["document_no"],
                    limit=3
                )
                if exact_points:
                    is_exact_match = True
                    results = exact_points
                    payload = exact_points[0].payload or {}
                    # Luôn format context trực tiếp từ RECORD GỐC của hệ thống để chống ảo giác
                    context = format_record_as_context(payload)
                    sources = [{
                        "document_id": payload.get("document_id"),
                        "document_name": payload.get("documentNo") or f"Số đến {payload.get('arrivalNo')}",
                        "page_num": 1,
                        "section_title": "Chi tiết văn bản đến",
                        "score": 1.0,
                        "category": payload.get("categoryName") or payload.get("category"),
                        "snippet": payload.get("title")
                    }]
                    Log.info(f"[RAG Store Chat] 🎯 Exact Record Found: '{payload.get('documentNo')}' (arrivalNo: {payload.get('arrivalNo')})")
            except Exception as ex_err:
                Log.warning(f"[RAG Store Chat] Exact search failed, falling back to vector search: {ex_err}")

        # 4. NẾU KHÔNG CÓ MÃ ĐỊNH DANH HOẶC EXACT MATCH KHÔNG RA: CHẠY VECTOR SEARCH BÌNH THƯỜNG
        if not is_exact_match:
            question_vector = embedding_service.embed_text([cleaned_q])[0]
            retrieval_limit = 7 if domain == "administrative_doc" else 5
            context, sources, results = self._retrieve_context(question_vector, workspace_id, category=category, limit=retrieval_limit)
        
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
                from datetime import datetime
                today_str = datetime.now().strftime("%d/%m/%Y")
                system_instruction = (
                    f"{domain_prompt}\n\n"
                    f"THÔNG TIN THỜI GIAN THỰC: Hôm nay là ngày {today_str}.\n\n"
                    "QUY TẮC BẮT BUỘC:\n"
                    "- CHỈ trả lời dựa TRỰC TIẾP trên NỘI DUNG VĂN BẢN VÀ METADATA HỆ THỐNG được cung cấp bên dưới.\n"
                    "- NÊU RÕ CĂN CỨ VĂN BẢN: Trích dẫn rõ Số đến (nếu có), Số/Ký hiệu văn bản, Cơ quan ban hành, Ngày ban hành, và Điều/Khoản/Điểm cụ thể nếu có.\n"
                    "- ƯU TIÊN METADATA KHI CÓ MÂU THUẪN: Nếu nội dung file gốc và metadata cập nhật (Độ khẩn, Độ mật, Trạng thái, Cán bộ phụ trách) có mâu thuẫn, LUÔN ƯU TIÊN thông tin metadata mới nhất.\n"
                    "- XỬ LÝ QUÁ HẠN: Chỉ xác định quá hạn nếu có ngày hạn cụ thể < ngày hôm nay và chưa hoàn thành. Nếu ghi 'Không đặt hạn', tuyệt đối không báo quá hạn.\n"
                    "- Nếu thông tin không có trong tài liệu, hãy nói một cách lịch sự rằng nội dung này chưa có trong dữ liệu được cung cấp.\n"
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

    def inspect_search(
        self,
        question: str,
        workspace_id: str,
        category: str | None = None,
        limit: int = 7,
        min_score: float = 0.35,
        domain: str = "administrative_doc",
        generate_answer: bool = True,
        provider: str = "auto"
    ) -> Dict:
        """
        Playground/Debug Inspection API:
        Retrieves chunks with detailed similarity scores and metadata,
        optionally generates answer, and computes has_answer flag with explanation.
        """
        import time
        t_start = time.time()
        
        cleaned_q = clean_question(question)
        Log.info(f"[RAG Playground] 🔍 Inspect query: '{cleaned_q}' in workspace '{workspace_id}' (category: '{category}', domain: '{domain}')")
        
        t_embed_start = time.time()
        question_vector = embedding_service.embed_text([cleaned_q])[0]
        embed_time_ms = round((time.time() - t_embed_start) * 1000, 2)
        
        t_search_start = time.time()
        context, sources, raw_results = self._retrieve_context(
            question_vector,
            workspace_id,
            category=category,
            limit=limit
        )
        search_time_ms = round((time.time() - t_search_start) * 1000, 2)
        
        retrieved_chunks = []
        for r in raw_results:
            chunk_id = str(getattr(r, "id", ""))
            score = round(float(getattr(r, "score", 0.0)), 4)
            payload = getattr(r, "payload", {}) or {}
            raw_text = payload.get("text", "")
            snippet = raw_text.strip()[:180] + "..." if len(raw_text.strip()) > 180 else raw_text.strip()
            
            retrieved_chunks.append({
                "chunk_id": chunk_id,
                "document_id": payload.get("document_id"),
                "document_name": payload.get("document_name", "unknown"),
                "page_num": payload.get("page_num", 1),
                "chunk_index": payload.get("chunk_index", 0),
                "section_title": payload.get("section_title"),
                "chapter_title": payload.get("chapter_title"),
                "category": payload.get("category"),
                "score": score,
                "snippet": snippet,
                "text": raw_text
            })
            
        highest_score = retrieved_chunks[0]["score"] if retrieved_chunks else 0.0
        lowest_score = retrieved_chunks[-1]["score"] if retrieved_chunks else 0.0
        
        llm_answer = None
        used_provider = None
        llm_time_ms = 0.0
        
        if generate_answer:
            t_llm_start = time.time()
            domain_prompt = get_chatbot_prompt(domain)
            
            if len(retrieved_chunks) == 0:
                if domain == "administrative_doc":
                    system_instruction = (
                        f"{domain_prompt}\n\n"
                        "LƯU Ý QUAN TRỌNG: Hiện tại bạn KHÔNG TÌM THẤY thông tin quy định hoặc văn bản liên quan đến câu hỏi này. "
                        "BẠN CHỈ ĐƯỢC NÓI: 'Nội dung này chưa được quy định hoặc chưa có trong tài liệu văn bản được cung cấp. Vui lòng liên hệ cơ quan ban hành hoặc Bộ phận Một cửa có thẩm quyền để được giải đáp chính thức.' "
                        "TUYỆT ĐỐI KHÔNG TỰ TẠO RA CÂU TRẢ LỜI NÀO KHÁC NGOÀI TÀI LIỆU ĐÃ CÓ."
                    )
                else:
                    system_instruction = (
                        f"{domain_prompt}\n\n"
                        "LƯU Ý QUAN TRỌNG: Hiện tại bạn KHÔNG TÌM THẤY thông tin tài liệu liên quan đến câu hỏi này. "
                        "BẠN CHỈ ĐƯỢC NÓI: 'Tôi không có thông tin về câu hỏi này.' "
                        "TUYỆT ĐỐI KHÔNG TỰ TẠO RA CÂU TRẢ LỜI NÀO KHÁC."
                    )
            else:
                if domain == "administrative_doc":
                    from datetime import datetime
                    today_str = datetime.now().strftime("%d/%m/%Y")
                    system_instruction = (
                        f"{domain_prompt}\n\n"
                        f"THÔNG TIN THỜI GIAN THỰC: Hôm nay là ngày {today_str}.\n\n"
                        "QUY TẮC BẮT BUỘC:\n"
                        "- CHỈ trả lời dựa TRỰC TIẾP trên NỘI DUNG VĂN BẢN VÀ METADATA HỆ THỐNG được cung cấp bên dưới.\n"
                        "- NÊU RÕ CĂN CỨ VĂN BẢN: Trích dẫn rõ Số đến (nếu có), Số/Ký hiệu văn bản, Cơ quan ban hành, Ngày ban hành, và Điều/Khoản/Điểm cụ thể nếu có.\n"
                        "- ƯU TIÊN METADATA KHI CÓ MÂU THUẪN: Nếu nội dung file gốc và metadata cập nhật (Độ khẩn, Độ mật, Trạng thái, Cán bộ phụ trách) có mâu thuẫn, LUÔN ƯU TIÊN thông tin metadata mới nhất.\n"
                        "- XỬ LÝ QUÁ HẠN: Chỉ xác định quá hạn nếu có ngày hạn cụ thể < ngày hôm nay và chưa hoàn thành. Nếu ghi 'Không đặt hạn', tuyệt đối không báo quá hạn.\n"
                        "- Nếu thông tin không có trong tài liệu, hãy nói một cách lịch sự rằng nội dung này chưa có trong dữ liệu được cung cấp.\n"
                        "- KHÔNG tự bịa ra câu trả lời hay điều khoản không tồn tại."
                    )
                else:
                    system_instruction = (
                        f"{domain_prompt}\n\n"
                        "QUY TẮC BẮT BUỘC:\n"
                        "- CHỈ trả lời dựa TRỰC TIẾP trên NỘI DUNG TÀI LIỆU được cung cấp bên dưới.\n"
                        "- Nếu thông tin không có trong tài liệu, hãy nói một cách lịch sự rằng bạn không có thông tin đó.\n"
                        "- KHÔNG tự bịa ra câu trả lời."
                    )
            
            prompt = f"DỰA TRÊN NỘI DUNG TÀI LIỆU SAU:\n{context}\n\nCÂU HỎI: {question}"
            llm_answer, used_provider = llm_service.chat(prompt, system_instruction, provider=provider)
            llm_time_ms = round((time.time() - t_llm_start) * 1000, 2)
            
        no_answer_patterns = [
            "không có thông tin", "không tìm thấy", "chưa được quy định", 
            "không được nêu rõ", "không đề cập", "chưa có trong tài liệu",
            "chưa được nêu", "vui lòng liên hệ cơ quan", "tôi không biết"
        ]
        
        is_refusal = False
        if llm_answer:
            is_refusal = any(p in llm_answer.lower() for p in no_answer_patterns)
            
        # Determine has_answer flag & exact reason
        if len(retrieved_chunks) == 0:
            has_answer = False
            reason = "NO_CHUNKS_FOUND"
            reason_vi = "Không tìm thấy bất kỳ đoạn văn bản nào phù hợp trong bộ lọc (workspace/category)."
        elif highest_score < min_score:
            has_answer = False
            reason = "LOW_SIMILARITY_SCORE"
            reason_vi = f"Điểm tương đồng cao nhất ({highest_score}) thấp hơn ngưỡng tối thiểu ({min_score}), tài liệu không liên quan đến câu hỏi."
        elif is_refusal:
            has_answer = False
            reason = "NOT_FOUND_IN_DOCUMENT_CONTENT"
            reason_vi = "Đoạn văn bản được kéo về không chứa câu trả lời cho câu hỏi này, LLM từ chối trả lời theo cơ chế chống ảo giác."
        else:
            has_answer = True
            reason = "ANSWER_FOUND"
            reason_vi = "Tìm thấy nội dung phù hợp và LLM đã trích xuất được câu trả lời từ tài liệu."
            
        total_time_ms = round((time.time() - t_start) * 1000, 2)
        
        return {
            "query": question,
            "cleaned_query": cleaned_q,
            "workspace_id": workspace_id,
            "category": category,
            "domain": domain,
            "stats": {
                "total_chunks_found": len(retrieved_chunks),
                "highest_score": highest_score,
                "lowest_score": lowest_score,
                "min_score_threshold": min_score,
                "embed_time_ms": embed_time_ms,
                "search_time_ms": search_time_ms,
                "llm_time_ms": llm_time_ms,
                "total_time_ms": total_time_ms
            },
            "retrieved_chunks": retrieved_chunks,
            "full_context_sent_to_llm": context,
            "llm_answer": llm_answer,
            "provider": used_provider,
            "has_answer": has_answer,
            "reason": reason,
            "reason_vi": reason_vi
        }

    # =========================================================================
    # DOCUMENT RECORD MANAGEMENT (VĂN BẢN ĐẾN DẠNG DÒNG DỮ LIỆU)
    # =========================================================================

    def build_record_semantic_text(self, record: dict) -> str:
        """
        Chuẩn hóa chuỗi ngữ nghĩa bao quát toàn bộ thực thể cho 1 dòng dữ liệu văn bản đến.
        Chuỗi này dùng để sinh vector embedding duy nhất cho dòng đó.
        """
        parts = []
        if record.get("arrivalNo"):
            parts.append(f"Số đến: {record.get('arrivalNo')}")
        if record.get("documentNo"):
            parts.append(f"Số ký hiệu: {record.get('documentNo')}")
        if record.get("senderOrg"):
            parts.append(f"Cơ quan ban hành: {record.get('senderOrg')}")
        if record.get("title"):
            parts.append(f"Trích yếu nội dung: {record.get('title')}")
        
        category = record.get("categoryName") or record.get("category")
        if category:
            parts.append(f"Lĩnh vực: {category}")

        dept = record.get("currentDeptName")
        if dept:
            parts.append(f"Đơn vị thụ lý: {dept}")
        
        user = record.get("currentUserName")
        if user:
            parts.append(f"Cán bộ phụ trách: {user}")

        if record.get("receiveDate"):
            parts.append(f"Ngày đến: {record.get('receiveDate')}")
        if record.get("deadline"):
            parts.append(f"Hạn xử lý: {record.get('deadline')}")
        else:
            parts.append("Hạn xử lý: Không đặt hạn")

        if record.get("priority"):
            parts.append(f"Độ khẩn: {record.get('priority')}")
        if record.get("security"):
            parts.append(f"Độ mật: {record.get('security')}")
        if record.get("note"):
            parts.append(f"Ghi chú: {record.get('note')}")

        return ". ".join(parts) + "."

    def index_document_record(self, record: dict, workspace_id: str):
        """
        Tiếp nhận và lưu trữ 1 dòng văn bản đến vào Qdrant.
        Chỉ embed 1 lần duy nhất cho chuỗi ngữ nghĩa của dòng này (không re-chunking).
        """
        document_id = record.get("id") or record.get("document_id")
        if not document_id:
            raise ValueError("Record phải có trường 'id' hoặc 'document_id'")

        semantic_text = self.build_record_semantic_text(record)
        vector = embedding_service.embed_text([semantic_text])[0]

        # Chuẩn bị metadata lưu vào Qdrant
        clean_meta = dict(record)
        clean_meta.pop("id", None)
        clean_meta.pop("document_id", None)
        clean_meta.pop("workspace_id", None)

        return qdrant_service.upsert_document_record(
            workspace_id=str(workspace_id),
            document_id=str(document_id),
            semantic_text=semantic_text,
            vector=vector,
            record_meta=clean_meta
        )

    def patch_document_record_metadata(self, workspace_id: str, document_id: str, updates: dict):
        """
        Cập nhật metadata động (priority, security, status, assignees, deadline...)
        cho 1 dòng dữ liệu văn bản đến. Tuyệt đối KHÔNG re-embed (0% chi phí AI).
        """
        clean_updates = dict(updates)
        clean_updates.pop("id", None)
        clean_updates.pop("document_id", None)
        clean_updates.pop("workspace_id", None)

        return qdrant_service.patch_document_metadata(
            workspace_id=str(workspace_id),
            document_id=str(document_id),
            payload_updates=clean_updates
        )

    def delete_document_record(self, workspace_id: str, document_id: str):
        """
        Xóa dòng dữ liệu văn bản đến khỏi Vector DB.
        """
        return qdrant_service.delete_document_record(
            workspace_id=str(workspace_id),
            document_id=str(document_id)
        )

    def search_document_records(self, workspace_id: str, query: str = None,
                                arrival_no: int = None, document_no: str = None,
                                status: str = None, priority: str = None, security: str = None,
                                current_dept: str = None, current_user: str = None,
                                limit: int = 10):
        """
        Tìm kiếm thông minh kết hợp Exact Match (Số đến, Số ký hiệu, Trạng thái...)
        và Semantic Search (Truy vấn theo nội dung trích yếu).
        """
        vector = None
        if query and query.strip():
            vector = embedding_service.embed_text([query.strip()])[0]

        points = qdrant_service.search_document_records(
            workspace_id=str(workspace_id),
            vector=vector,
            arrival_no=arrival_no,
            document_no=document_no,
            status=status,
            priority=priority,
            security=security,
            current_dept=current_dept,
            current_user=current_user,
            limit=limit
        )

        results = []
        for p in points:
            payload = p.payload or {}
            score = getattr(p, "score", None)
            results.append({
                "point_id": p.id,
                "document_id": payload.get("document_id"),
                "score": score,
                "payload": payload
            })
        return results

rag_service = RagService()


import re
from typing import List, Dict, Tuple, Optional
from src.shared.utils.logger import Log

ARTICLE_REGEX = re.compile(
    r'(?m)^(?:\*{1,2}|_{1,2})?\s*(?:Điều|ĐIỀU)\s+(\d+)[\.\:\s\-]+([^\n]+)',
    re.UNICODE
)

CHAPTER_REGEX = re.compile(
    r'(?m)^(?:\*{1,2}|_{1,2})?\s*(?:Chương|CHƯƠNG)\s+([IVXLCDM\d]+)[\.\:\s\-]*(?:[\r\n]+|\s+)([^\n]*)',
    re.UNICODE
)

SECTION_REGEX = re.compile(
    r'(?m)^(?:\*{1,2}|_{1,2})?\s*(?:Mục|MỤC)\s+(\d+)[\.\:\s\-]*(?:[\r\n]+|\s+)([^\n]*)',
    re.UNICODE
)

MD_HEADING_REGEX = re.compile(
    r'(?m)^(#{1,4})\s+([^\n]+)'
)

CLAUSE_BOUNDARY_REGEX = re.compile(
    r'(?m)(?=^\s*(?:\d+[\.\)]|[a-z]\))\s+)'
)


def smart_split_by_sentences(text: str, max_chunk_size: int = 1000, chunk_overlap: int = 150) -> List[str]:
    """
    Chia đoạn văn bản lớn thành các chunk nhỏ hơn nhưng không cắt ngang giữa câu hay từ.
    Ưu tiên tách theo dấu chấm kết câu (. ? !), dấu xuống dòng hoặc chấm phẩy.
    """
    if len(text) <= max_chunk_size:
        return [text]

    sentences = re.split(r'(?<=[.?!;\n])\s+', text)
    chunks = []
    current_chunk = []
    current_len = 0

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        
        sent_len = len(sent)
        if current_len + sent_len + 1 > max_chunk_size and current_chunk:
            chunk_str = " ".join(current_chunk).strip()
            if chunk_str:
                chunks.append(chunk_str)
            
            # Giữ lại overlap từ các câu cuối
            overlap_chunk = []
            overlap_len = 0
            for prev_sent in reversed(current_chunk):
                if overlap_len + len(prev_sent) + 1 <= chunk_overlap:
                    overlap_chunk.insert(0, prev_sent)
                    overlap_len += len(prev_sent) + 1
                else:
                    break
            
            current_chunk = overlap_chunk
            current_len = overlap_len

        # Nếu 1 câu duy nhất quá dài vượt max_chunk_size
        if sent_len > max_chunk_size:
            words = sent.split()
            sub_chunk = []
            sub_len = 0
            for w in words:
                if sub_len + len(w) + 1 > max_chunk_size and sub_chunk:
                    chunks.append(" ".join(sub_chunk).strip())
                    sub_chunk = []
                    sub_len = 0
                sub_chunk.append(w)
                sub_len += len(w) + 1
            if sub_chunk:
                current_chunk.append(" ".join(sub_chunk).strip())
                current_len += sub_len
        else:
            current_chunk.append(sent)
            current_len += sent_len + 1

    if current_chunk:
        chunk_str = " ".join(current_chunk).strip()
        if chunk_str:
            chunks.append(chunk_str)

    return chunks if chunks else [text]


def _chunk_legal_articles(
    full_text: str,
    page_spans: List[Tuple[int, int, int]],
    document_name: str = "",
    max_chunk_size: int = 1200
) -> List[Dict]:
    """
    Cắt văn bản quy phạm pháp luật / hành chính theo cấu trúc: Chương -> Mục -> Điều -> Khoản.
    Tự động gắn Header ngữ cảnh vào từng chunk để vector search bắt trúng cả tiêu đề Điều và nội dung.
    """
    def get_page_for_pos(pos: int) -> int:
        for s_idx, e_idx, p_num in page_spans:
            if s_idx <= pos < e_idx:
                return p_num
        return page_spans[-1][2] if page_spans else 1

    # Tìm tất cả mốc Chương, Mục, Điều
    markers = []
    for m in CHAPTER_REGEX.finditer(full_text):
        markers.append({
            "type": "CHAPTER",
            "start": m.start(),
            "end": m.end(),
            "title": f"Chương {m.group(1)}: {m.group(2).strip()}".strip(" :")
        })
    for m in SECTION_REGEX.finditer(full_text):
        markers.append({
            "type": "SECTION",
            "start": m.start(),
            "end": m.end(),
            "title": f"Mục {m.group(1)}: {m.group(2).strip()}".strip(" :")
        })
    for m in ARTICLE_REGEX.finditer(full_text):
        markers.append({
            "type": "ARTICLE",
            "start": m.start(),
            "end": m.end(),
            "num": m.group(1),
            "title": f"Điều {m.group(1)}. {m.group(2).strip()}"
        })

    markers.sort(key=lambda x: x["start"])

    # Lấy danh sách riêng các Điều
    article_indices = [i for i, m in enumerate(markers) if m["type"] == "ARTICLE"]
    if not article_indices:
        return []

    chunks = []
    
    # 1. Phần mở đầu trước Điều đầu tiên (nếu có căn cứ pháp lý, tên cơ quan)
    first_art_pos = markers[article_indices[0]]["start"]
    if first_art_pos > 80:
        preamble_text = full_text[:first_art_pos].strip()
        if preamble_text:
            sub_chunks = smart_split_by_sentences(preamble_text, max_chunk_size=max_chunk_size)
            for sc in sub_chunks:
                header = f"[{document_name} | Phần mở đầu & Căn cứ ban hành]\n" if document_name else "[Phần mở đầu & Căn cứ ban hành]\n"
                chunks.append({
                    "text": header + sc,
                    "raw_text": sc,
                    "page_num": get_page_for_pos(0),
                    "section_title": "Phần mở đầu",
                    "chapter_title": None
                })

    # Duyệt qua từng Điều
    for idx_in_articles, m_idx in enumerate(article_indices):
        art_marker = markers[m_idx]
        start_pos = art_marker["start"]
        
        # Điểm kết thúc của Điều này là điểm bắt đầu của Điều kế tiếp (hoặc hết văn bản)
        if idx_in_articles + 1 < len(article_indices):
            next_m_idx = article_indices[idx_in_articles + 1]
            end_pos = markers[next_m_idx]["start"]
        else:
            end_pos = len(full_text)

        article_content = full_text[start_pos:end_pos].strip()
        if not article_content:
            continue

        # Tìm Chương và Mục hiện tại nằm trước Điều này
        current_chapter = None
        current_section = None
        for prev_m in markers[:m_idx]:
            if prev_m["type"] == "CHAPTER":
                current_chapter = prev_m["title"]
                current_section = None # reset section khi sang chương mới
            elif prev_m["type"] == "SECTION":
                current_section = prev_m["title"]

        # Xây dựng Context Header chuẩn mực
        header_parts = []
        if document_name:
            header_parts.append(document_name)
        if current_chapter:
            header_parts.append(current_chapter)
        if current_section:
            header_parts.append(current_section)
        header_parts.append(art_marker["title"])
        
        context_header = f"[{' | '.join(header_parts)}]\n"
        art_page = get_page_for_pos(start_pos)

        # Nếu Điều ngắn gọn (<= max_chunk_size), giữ nguyên 1 chunk toàn vẹn
        if len(article_content) <= max_chunk_size:
            chunks.append({
                "text": context_header + article_content,
                "raw_text": article_content,
                "page_num": art_page,
                "section_title": art_marker["title"],
                "chapter_title": current_chapter
            })
        else:
            # Nếu Điều dài, tách theo từng Khoản nhưng giữ nguyên Context Header
            clauses = CLAUSE_BOUNDARY_REGEX.split(article_content)
            current_clause_group = []
            current_clause_len = 0
            
            for clause in clauses:
                clause = clause.strip()
                if not clause:
                    continue
                
                if current_clause_len + len(clause) + 1 > max_chunk_size and current_clause_group:
                    sub_text = "\n".join(current_clause_group)
                    chunks.append({
                        "text": context_header + sub_text,
                        "raw_text": sub_text,
                        "page_num": art_page,
                        "section_title": art_marker["title"],
                        "chapter_title": current_chapter
                    })
                    current_clause_group = [clause]
                    current_clause_len = len(clause)
                else:
                    current_clause_group.append(clause)
                    current_clause_len += len(clause) + 1

            if current_clause_group:
                sub_text = "\n".join(current_clause_group)
                chunks.append({
                    "text": context_header + sub_text,
                    "raw_text": sub_text,
                    "page_num": art_page,
                    "section_title": art_marker["title"],
                    "chapter_title": current_chapter
                })

    return chunks


def chunk_document_smart(
    data,
    document_name: str = "",
    chunk_size: int = 1000,
    chunk_overlap: int = 150
) -> List[Dict]:
    """
    Entrypoint thông minh cho việc cắt chunk tài liệu:
    1. Kiểm tra cấu trúc văn bản pháp lý/hành chính (Điều, Chương, Mục) -> Áp dụng Legal Chunking.
    2. Kiểm tra cấu trúc Markdown (#, ##, ###) -> Áp dụng Markdown Heading Chunking.
    3. Ngược lại -> Áp dụng Smart Sentence/Paragraph Chunking (không cắt ngang từ/câu).
    """
    # Chuẩn hóa đầu vào
    pages = []
    if isinstance(data, str):
        pages = [{"text": data, "page_num": 1}]
    elif isinstance(data, list):
        pages = data
    else:
        Log.warning(f"[Chunking] Unsupported data type: {type(data)}")
        return []

    # Ghép văn bản liên tục và ghi nhận mốc trang
    full_text = ""
    page_spans = []
    for p in pages:
        p_text = p.get("text", "")
        if not isinstance(p_text, str) or not p_text.strip():
            continue
        start_idx = len(full_text)
        full_text += p_text + "\n\n"
        end_idx = len(full_text)
        page_spans.append((start_idx, end_idx, p.get("page_num", 1)))

    if not full_text.strip():
        return []

    def get_page_for_pos(pos: int) -> int:
        for s_idx, e_idx, p_num in page_spans:
            if s_idx <= pos < e_idx:
                return p_num
        return page_spans[-1][2] if page_spans else 1

    # 1. Phát hiện văn bản hành chính / quy phạm pháp luật (có từ 2 Điều trở lên)
    article_matches = ARTICLE_REGEX.findall(full_text)
    if len(article_matches) >= 2:
        Log.info(f"[Chunking] 🏛️ Phát hiện cấu trúc pháp lý với {len(article_matches)} Điều trong '{document_name}'. Sử dụng Legal Section Chunker.")
        legal_chunks = _chunk_legal_articles(full_text, page_spans, document_name=document_name, max_chunk_size=chunk_size + 200)
        if legal_chunks:
            for idx, c in enumerate(legal_chunks):
                c["chunk_index"] = idx
            return legal_chunks

    # 2. Phát hiện cấu trúc Markdown Headings (có từ 2 heading trở lên)
    md_matches = list(MD_HEADING_REGEX.finditer(full_text))
    if len(md_matches) >= 2:
        Log.info(f"[Chunking] 📝 Phát hiện cấu trúc Markdown với {len(md_matches)} đề mục trong '{document_name}'.")
        chunks = []
        for i, m in enumerate(md_matches):
            start_pos = m.start()
            end_pos = md_matches[i+1].start() if i + 1 < len(md_matches) else len(full_text)
            section_content = full_text[start_pos:end_pos].strip()
            heading_title = m.group(2).strip()
            page_num = get_page_for_pos(start_pos)
            
            header = f"[{document_name} > {heading_title}]\n" if document_name else f"[{heading_title}]\n"
            if len(section_content) <= chunk_size + 200:
                chunks.append({
                    "text": header + section_content,
                    "raw_text": section_content,
                    "page_num": page_num,
                    "section_title": heading_title,
                    "chapter_title": None
                })
            else:
                sub_chunks = smart_split_by_sentences(section_content, max_chunk_size=chunk_size, chunk_overlap=chunk_overlap)
                for sc in sub_chunks:
                    chunks.append({
                        "text": header + sc,
                        "raw_text": sc,
                        "page_num": page_num,
                        "section_title": heading_title,
                        "chapter_title": None
                    })
        if chunks:
            for idx, c in enumerate(chunks):
                c["chunk_index"] = idx
            return chunks

    # 3. Fallback: Cắt thông minh theo đoạn văn & câu (Không bao giờ cắt giữa chừng từ hoặc câu)
    Log.info(f"[Chunking] 📄 Sử dụng Smart Paragraph Chunker cho '{document_name}'.")
    raw_sub_chunks = smart_split_by_sentences(full_text, max_chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = []
    
    current_search_pos = 0
    for idx, sc in enumerate(raw_sub_chunks):
        pos = full_text.find(sc[:50], current_search_pos)
        if pos == -1:
            pos = current_search_pos
        else:
            current_search_pos = pos
        
        page_num = get_page_for_pos(pos)
        header = f"[{document_name}]\n" if document_name else ""
        chunks.append({
            "text": header + sc,
            "raw_text": sc,
            "page_num": page_num,
            "chunk_index": idx,
            "section_title": None,
            "chapter_title": None
        })

    return chunks

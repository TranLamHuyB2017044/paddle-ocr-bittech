import re
from rapidfuzz import fuzz


class SmartExtractor:
    def __init__(self, config):
        """
        config = {
            "fieldName": {
                "keywords": [...],
                "keywords_threshold": 0.7,
                "value_regex": r"...",
                "extraction_mode": "same_line" | "next_line" | "auto" | "multiline",
                "max_lines": 3
            }
        }
        """
        self.config = config
        # Pre-collect all keywords to use as stop-words for multiline extraction
        self.all_keywords = []
        for f, rules in config.items():
            self.all_keywords.extend(rules.get("keywords", []))

    # ----------------------------------------------------------
    #                      KEYWORD MATCH
    # ----------------------------------------------------------
    def _keyword_score(self, text, keywords):
        """
        Fuzzy matching từng keyword → trả về score cao nhất.
        """
        text_lower = text.lower()
        best_score = 0
        
        for kw in keywords:
            score = fuzz.partial_ratio(text_lower, kw.lower()) / 100.0
            best_score = max(best_score, score)

        return best_score

    # ----------------------------------------------------------
    #                    MULTILINE EXTRACTION
    # ----------------------------------------------------------
    def _extract_multiline(self, lines, start_index, max_lines=3, stop_keywords=None):
        """
        Lấy text từ nhiều dòng tiếp theo, nối thành 1 chuỗi.
        Dừng nếu gặp dòng trống HOẶC dòng chứa keyword khác.
        """
        collected = []
        if stop_keywords is None: stop_keywords = []

        for j in range(start_index + 1, min(start_index + 1 + max_lines, len(lines))):
            line = lines[j].strip()
            if line == "":
                break
                
            # Check stop keywords (fuzzy or exact)
            is_stop = False
            line_lower = line.lower()
            for kw in stop_keywords:
                # Simple check: keyword in line (sufficient for stop condition)
                # But ensure keyword is long enough to be significant
                if len(kw) > 3 and kw.lower() in line_lower:
                    is_stop = True
                    break
            
            if is_stop:
                break
                
            collected.append(line)

        return " ".join(collected).strip()

    # ----------------------------------------------------------
    #                     SAME LINE EXTRACTION
    # ----------------------------------------------------------
    def _extract_same_line(self, line, value_regex):
        """
        Tách value ngay trên cùng dòng.
        """
        if value_regex:
            match = re.search(value_regex, line)
            if match:
                return match.group(0).strip()

        # fallback: lấy phần sau dấu ":" hoặc "-"
        if ":" in line:
            return line.split(":", 1)[1].strip()
        if "-" in line:
            parts = line.split("-", 1)
            if len(parts[0]) < 15:
                return parts[1].strip()

        return None

    # ----------------------------------------------------------
    #                   NEXT LINE EXTRACTION
    # ----------------------------------------------------------
    def _extract_next_line(self, lines, index, value_regex):
        if index + 1 >= len(lines):
            return None

        next_line = lines[index + 1].strip()

        if value_regex:
            match = re.search(value_regex, next_line)
            if match:
                return match.group(0).strip()

        return next_line if next_line else None

    # ----------------------------------------------------------
    #                     AUTO EXTRACTION
    # ----------------------------------------------------------
    def _extract_auto(self, lines, i, value_regex):
        """
        Tự đoán: Nếu value nằm trên cùng dòng → lấy same_line.
        Nếu không → lấy dòng dưới (next_line).
        """
        # thử same_line trước
        val = self._extract_same_line(lines[i], value_regex)
        if val:
            return val

        # thử next_line
        if i + 1 < len(lines):
            val = self._extract_same_line(lines[i + 1], value_regex)
            if val:
                return val

            return lines[i + 1].strip()

        return None

    # ----------------------------------------------------------
    #                       MAIN EXTRACTOR
    # ----------------------------------------------------------
    def extract(self, input_data):
        """
        Input: 
            input_data: List[str] (danh sách các dòng) HOẶC str (nguyên văn bản)
        Output: dict field → value
        """
        if isinstance(input_data, list):
            lines = [str(ln).strip() for ln in input_data if str(ln).strip()]
        elif isinstance(input_data, str):
            lines = [ln.strip() for ln in input_data.split("\n") if ln.strip()]
        else:
            return {}

        result = {field: None for field in self.config}

        for i, line in enumerate(lines):

            for field, rules in self.config.items():
                # 🛑 OPTIMIZATION: Nếu đã extract được rồi thì bỏ qua (Lấy giá trị đầu tiên tìm thấy)
                if result[field] is not None:
                    continue

                keywords = rules.get("keywords", [])
                threshold = rules.get("keywords_threshold", 0.7)
                value_regex = rules.get("value_regex")
                mode = rules.get("extraction_mode", "auto")

                # 1️⃣ Keyword matching
                score = self._keyword_score(line, keywords)
                if score < threshold:
                    continue

                # 2️⃣ Apply extraction mode
                if mode == "same_line":
                    extracted = self._extract_same_line(line, value_regex)

                elif mode == "next_line":
                    extracted = self._extract_next_line(lines, i, value_regex)

                elif mode == "multiline":
                    max_lines = rules.get("max_lines", 3)
                    # Use all known keywords as blockers
                    extracted = self._extract_multiline(lines, i, max_lines, stop_keywords=self.all_keywords)

                else:  # auto
                    extracted = self._extract_auto(lines, i, value_regex)

                # Save value
                if extracted:
                    # 🛡️ SANITY CHECK: Ensure extracted value is not another field's label
                    # Example: Nationality extracted as "Quê quán / Place of origin:"
                    is_valid = True
                    extracted_lower = extracted.lower()
                    for kw in self.all_keywords:
                        if len(kw) > 4 and kw in extracted_lower:
                            # Nếu giá trị chứa từ khóa của field khác (hoặc chính nó)
                            # -> Có thể là bắt nhầm tiêu đề
                            # Exception: Trừ trường hợp giá trị chứa từ khóa NHƯNG là địa chỉ dài? 
                            # (Ít xảy ra với keyword chuẩn như "ngày sinh", "họ và tên")
                            is_valid = False
                            break
                    
                    if is_valid:
                        result[field] = extracted

                    if is_valid:
                        result[field] = extracted

        # ----------------------------------------------------------
        # 3️⃣ GLOBAL REGEX FALLBACK (Cho trường hợp keyword bị miss/lệch dòng)
        # ----------------------------------------------------------
        full_text = "\n".join(lines)
        for field, rules in self.config.items():
            # Chỉ tìm nếu chưa có kết quả
            if result[field] is None:
                value_regex = rules.get("value_regex")
                is_global = rules.get("global_regex", False)
                
                if is_global and value_regex:
                    # Tìm regex trên toàn bộ văn bản (hỗ trợ multiline cho ^$)
                    match = re.search(value_regex, full_text, re.MULTILINE | re.IGNORECASE)
                    if match:
                        result[field] = match.group(0).strip()

        return result

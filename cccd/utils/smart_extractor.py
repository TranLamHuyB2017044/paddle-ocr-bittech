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
    def _extract_multiline(self, lines, start_index, max_lines=3):
        """
        Lấy text từ nhiều dòng tiếp theo, nối thành 1 chuỗi.
        Dừng nếu gặp dòng trống.
        """
        collected = []

        for j in range(start_index + 1, min(start_index + 1 + max_lines, len(lines))):
            line = lines[j].strip()
            if line == "":
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
                    extracted = self._extract_multiline(lines, i, max_lines)

                else:  # auto
                    extracted = self._extract_auto(lines, i, value_regex)

                # Save value
                if extracted:
                    result[field] = extracted

        return result

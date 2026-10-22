import pandas as pd
import numpy as np
import io
import re
from datetime import datetime
from typing import Union, BinaryIO, Dict, Any, List
from src.shared.utils.logger import Log

def clean_val(val, default="") -> str:
    """Xử lý giá trị null, NaN, NaT thành chuỗi sạch"""
    if pd.isna(val) or val is None:
        return default
    val_str = str(val).strip()
    if val_str.lower() in ("nan", "nat", "none", "null"):
        return default
    # Loại bỏ .0 nếu là số nguyên
    if re.match(r'^\d+\.0$', val_str):
        return val_str[:-2]
    return val_str

def parse_date_str(val) -> str:
    """Chuyển đổi các định dạng ngày sang DD/MM/YYYY hoặc YYYY-MM-DD"""
    if pd.isna(val) or val is None:
        return ""
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.strftime("%d/%m/%Y")
    val_str = clean_val(val)
    if not val_str:
        return ""
    # Thử parse các định dạng phổ biến
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(val_str.split()[0], fmt)
            return dt.strftime("%d/%m/%Y")
        except:
            pass
    return val_str

def convert_excel_to_markdown_string(file_input: Union[str, BinaryIO, bytes], sheet_name=0) -> str:
    """
    Đọc file Excel sổ văn bản đến và tự động chuyển đổi thành tài liệu Markdown có cấu trúc chuẩn
    (gồm Báo cáo thống kê, Bảng tổng hợp và Chi tiết từng công văn).
    """
    if isinstance(file_input, bytes):
        df = pd.read_excel(io.BytesIO(file_input), sheet_name=sheet_name)
    else:
        df = pd.read_excel(file_input, sheet_name=sheet_name)

    # Chuẩn hóa tên cột
    col_mapping = {}
    for col in df.columns:
        c_clean = str(col).strip().lower()
        if "số đến" in c_clean or "arrival" in c_clean:
            col_mapping[col] = "arrival_no"
        elif c_clean in ("sổ", "sổ văn bản", "book", "bookno"):
            col_mapping[col] = "book_no"
        elif "ký hiệu" in c_clean or "số vb" in c_clean or "documentno" in c_clean:
            col_mapping[col] = "document_no"
        elif "trích yếu" in c_clean or "tiêu đề" in c_clean or "title" in c_clean:
            col_mapping[col] = "title"
        elif "cơ quan" in c_clean or "đơn vị gửi" in c_clean or "sender" in c_clean:
            col_mapping[col] = "sender_org"
        elif "ban hành" in c_clean or "issuedate" in c_clean:
            col_mapping[col] = "issue_date"
        elif "ngày đến" in c_clean or "receivedate" in c_clean:
            col_mapping[col] = "receive_date"
        elif "hạn" in c_clean or "deadline" in c_clean:
            col_mapping[col] = "deadline"
        elif "khẩn" in c_clean or "priority" in c_clean:
            col_mapping[col] = "priority"
        elif "mật" in c_clean or "security" in c_clean:
            col_mapping[col] = "security"
        elif "lĩnh vực" in c_clean or "category" in c_clean:
            col_mapping[col] = "category"
        elif "trạng thái" in c_clean or "status" in c_clean:
            col_mapping[col] = "status"
        elif "đơn vị nhận" in c_clean or "đơn vị xử lý" in c_clean or "dept" in c_clean:
            col_mapping[col] = "dept"
        elif "người xử lý" in c_clean or "chủ trì" in c_clean or "cán bộ" in c_clean or "user" in c_clean:
            col_mapping[col] = "user"
        elif "ghi chú" in c_clean or "note" in c_clean:
            col_mapping[col] = "note"

    df_renamed = df.rename(columns=col_mapping)
    total_docs = len(df_renamed)

    records: List[Dict[str, Any]] = []
    for _, row in df_renamed.iterrows():
        records.append({
            "arrival_no": clean_val(row.get("arrival_no")),
            "book_no": clean_val(row.get("book_no"), "VP-2026"),
            "document_no": clean_val(row.get("document_no")),
            "title": clean_val(row.get("title")),
            "sender_org": clean_val(row.get("sender_org")),
            "issue_date": parse_date_str(row.get("issue_date")),
            "receive_date": parse_date_str(row.get("receive_date")),
            "deadline": parse_date_str(row.get("deadline")),
            "priority": clean_val(row.get("priority"), "Thường"),
            "security": clean_val(row.get("security"), "Thường"),
            "category": clean_val(row.get("category"), "Chưa phân loại"),
            "status": clean_val(row.get("status"), "Mới nhận"),
            "dept": clean_val(row.get("dept"), "Chưa phân luồng"),
            "user": clean_val(row.get("user"), "Chưa giao"),
            "note": clean_val(row.get("note")),
        })

    # =========================================================================
    # 1. TÍNH TOÁN BÁO CÁO THỐNG KÊ TỔNG HỢP (SUMMARY STATISTICS)
    # =========================================================================
    
    # Thống kê theo trạng thái
    status_counts = {}
    for r in records:
        st = r["status"]
        status_counts[st] = status_counts.get(st, 0) + 1

    # Thống kê theo độ khẩn
    priority_counts = {}
    for r in records:
        pr = r["priority"]
        priority_counts[pr] = priority_counts.get(pr, 0) + 1

    # Thống kê theo độ mật
    security_counts = {}
    for r in records:
        sc = r["security"]
        security_counts[sc] = security_counts.get(sc, 0) + 1

    # Thống kê theo phòng ban
    dept_counts = {}
    for r in records:
        dp = r["dept"]
        dept_counts[dp] = dept_counts.get(dp, 0) + 1

    # Thống kê theo lĩnh vực
    cat_counts = {}
    for r in records:
        ct = r["category"]
        cat_counts[ct] = cat_counts.get(ct, 0) + 1

    # Danh sách văn bản hỏa tốc, mới nhận, quá hạn
    hoa_toc_docs = [f"Số {r['arrival_no']} ({r['document_no']})" for r in records if "hỏa tốc" in r["priority"].lower()]
    moi_nhan_docs = [f"Số {r['arrival_no']} ({r['document_no']})" for r in records if "mới nhận" in r["status"].lower() or "mới tiếp nhận" in r["status"].lower()]
    qua_han_docs = [f"Số {r['arrival_no']} ({r['document_no']})" for r in records if "quá hạn" in r["status"].lower()]

    lines = []
    lines.append("# SỔ QUẢN LÝ VĂN BẢN ĐẾN (DỮ LIỆU TỔNG HỢP & CHI TIẾT TRA CỨU)\n")
    lines.append("> **Quy ước định danh văn bản trong hệ thống**:")
    lines.append("> - **Số đến (Số công văn đến)**: Là số thứ tự ghi sổ văn bản đến (ví dụ: Số 68, Số 67, Số 62...).")
    lines.append("> - **Số / Ký hiệu văn bản**: Là ký hiệu do cơ quan gửi ban hành (ví dụ: BG260819B40433, 157/CV-2026...).")
    lines.append("> - *Lưu ý tra cứu*: Khi người dùng hỏi 'công văn số X' (ví dụ công văn số 68) hoặc 'công văn Y' (ví dụ công văn BG260819B40433), cả hai cách gọi đều chỉ cùng một văn bản.\n")

    # MỤC 1
    lines.append("## 1. BÁO CÁO TỔNG HỢP DỮ LIỆU VĂN BẢN ĐẾN (SUMMARY STATISTICS)")
    lines.append("Mục này cung cấp dữ liệu tổng hợp và thống kê số liệu toàn bộ văn bản đến phục vụ trả lời các câu hỏi tổng quan, thống kê, báo cáo tình hình xử lý công văn:\n")

    lines.append("### 1.1. Thống kê tổng quan")
    lines.append(f"- **Tổng số lượng văn bản tiếp nhận**: **{total_docs} văn bản**.")
    lines.append("- **Sổ theo dõi chính**: Sổ Văn bản Văn phòng (Ký hiệu: `VP-2026`).\n")

    lines.append("### 1.2. Thống kê theo Trạng thái xử lý văn bản")
    lines.append("| Trạng thái xử lý | Số lượng văn bản | Tỷ lệ (%) |")
    lines.append("|:---|:---:|:---:|")
    for st, count in status_counts.items():
        pct = round((count / total_docs) * 100, 1) if total_docs > 0 else 0
        lines.append(f"| {st} | **{count}** | {pct}% |")
    lines.append(f"| **TỔNG CỘNG** | **{total_docs}** | **100%** |\n")

    lines.append("### 1.3. Thống kê theo Mức độ khẩn và Mức độ mật")
    lines.append("- **Mức độ khẩn**:")
    for pr, count in priority_counts.items():
        lines.append(f"  + {pr}: **{count}** văn bản")
    lines.append("- **Mức độ mật**:")
    for sc, count in security_counts.items():
        lines.append(f"  + {sc}: **{count}** văn bản")
    lines.append("")

    lines.append("### 1.4. Thống kê theo Phòng ban / Bộ phận thụ lý")
    lines.append("| Phòng ban / Đơn vị tiếp nhận | Số lượng văn bản |")
    lines.append("|:---|:---:|")
    for dp, count in dept_counts.items():
        lines.append(f"| {dp} | **{count}** |")
    lines.append("")

    lines.append("### 1.5. Thống kê theo Lĩnh vực văn bản")
    cat_str_list = [f"{ct} ({cnt})" for ct, cnt in cat_counts.items()]
    lines.append(f"- Các lĩnh vực công văn tiếp nhận: {', '.join(cat_str_list)}.\n")

    lines.append("### 1.6. Danh sách các văn bản cần lưu ý")
    lines.append(f"- **Văn bản Quá hạn ({len(qua_han_docs)} công văn)**: {', '.join(qua_han_docs) if qua_han_docs else 'Không có'}.")
    lines.append(f"- **Văn bản Mới nhận chưa xử lý ({len(moi_nhan_docs)} công văn)**: {', '.join(moi_nhan_docs) if moi_nhan_docs else 'Không có'}.")
    lines.append(f"- **Văn bản Hỏa tốc ({len(hoa_toc_docs)} công văn)**: {', '.join(hoa_toc_docs) if hoa_toc_docs else 'Không có'}.\n")

    lines.append("---\n")

    # MỤC 2: BẢNG TỔNG HỢP TRA CỨU
    lines.append("## 2. BẢNG TỔNG HỢP TRA CỨU CÔNG VĂN ĐẾN (THEO GIAO DIỆN HỆ THỐNG)")
    lines.append("| Số đến / Ký hiệu | Trích yếu nội dung | Ngày đến / Hạn xử lý | Trạng thái | Độ khẩn | Đơn vị / Người xử lý |")
    lines.append("|:---|:---|:---|:---:|:---:|:---|")

    for r in records:
        col1 = f"**Số {r['arrival_no']}**<br>({r['document_no']})"
        col2 = f"**{r['title']}**<br>*{r['sender_org']}*"
        
        date_parts = []
        if r["receive_date"]: date_parts.append(f"Đến: {r['receive_date']}")
        if r["deadline"]: date_parts.append(f"Hạn: {r['deadline']}")
        else: date_parts.append("Không đặt hạn")
        col3 = "<br>".join(date_parts)

        col4 = r["status"]
        col5 = r["priority"]
        col6 = f"{r['dept']} - Phụ trách: {r['user']}"
        lines.append(f"| {col1} | {col2} | {col3} | {col4} | {col5} | {col6} |")

    lines.append("\n---\n")

    # MỤC 3: CHI TIẾT TỪNG CÔNG VĂN
    lines.append("## 3. CHI TIẾT TỪNG CÔNG VĂN ĐẾN\n")
    for r in records:
        lines.append(f"### Công văn số {r['arrival_no']} | Số ký hiệu: {r['document_no']}")
        lines.append(f"- **Số đến (Số công văn đến)**: Số {r['arrival_no']} (Công văn số {r['arrival_no']}, Văn bản số {r['arrival_no']})")
        lines.append(f"- **Số ký hiệu văn bản**: {r['document_no']} (Công văn {r['document_no']}, Ký hiệu {r['document_no']})")
        lines.append(f"- **Tiêu đề (Trích yếu nội dung)**: {r['title']}")
        lines.append(f"- **Trạng thái hiện tại**: {r['status']}")
        lines.append(f"- **Mức độ khẩn**: {r['priority']} | **Mức độ mật**: {r['security']}")
        lines.append(f"- **Cơ quan ban hành / Đơn vị gửi**: {r['sender_org']}")
        lines.append(f"- **Lĩnh vực**: {r['category']}")
        lines.append(f"- **Sổ văn bản**: {r['book_no']}")
        
        receive_str = r['receive_date'] or "Chưa có"
        issue_str = r['issue_date'] or "Chưa có"
        lines.append(f"- **Ngày đến (Ngày nhận)**: {receive_str} | **Ngày ban hành**: {issue_str}")
        lines.append(f"- **Hạn xử lý (Thời hạn giải quyết)**: {r['deadline'] or 'Không đặt hạn'}")
        lines.append(f"- **Đơn vị xử lý**: {r['dept']}")
        lines.append(f"- **Người phụ trách / Người xử lý**: {r['user']}")
        if r["note"]:
            lines.append(f"- **Ghi chú**: {r['note']}")
        
        # Từ khóa tìm kiếm hỗ trợ LLM bắt đúng ngữ cảnh
        keywords = [
            f"Công văn số {r['arrival_no']}",
            f"Văn bản số {r['arrival_no']}",
            f"Số đến {r['arrival_no']}",
            f"Công văn {r['document_no']}",
            f"Ký hiệu {r['document_no']}",
            r['title'],
            r['sender_org']
        ]
        lines.append(f"- **Từ khóa tìm kiếm**: {', '.join([k for k in keywords if k])}\n")

    return "\n".join(lines)

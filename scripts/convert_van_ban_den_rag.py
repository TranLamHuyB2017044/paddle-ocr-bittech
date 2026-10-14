# -*- coding: utf-8 -*-
"""
Script chuẩn hóa file JSON export văn bản đến thành tài liệu Markdown tối ưu cho Chatbot RAG.
Đồng bộ định dạng hiển thị:
- Số đến / Số công văn: arrivalNo (ví dụ: Số 62, Công văn số 62)
- Số ký hiệu văn bản: documentNo (ví dụ: BG260819B404)
Đảm bảo khi hỏi "công văn số 62" hoặc "công văn BG260819B404" đều tìm về đúng 1 văn bản.
"""
import os
import re
import json
from collections import Counter

STATUS_MAP = {
    "MOI_NHAN": "Mới nhận",
    "DANG_XU_LY": "Đang xử lý",
    "CHO_Y_KIEN": "Chờ ý kiến",
    "CHO_KY": "Chờ ký",
    "DA_KY": "Đã ký",
    "HOAN_THANH": "Hoàn thành",
    "LUU_TRU": "Đã lưu trữ",
    "QUA_HAN": "Quá hạn"
}

PRIORITY_MAP = {
    "THUONG": "Thường",
    "KHAN": "Khẩn",
    "THUONG_KHAN": "Thượng khẩn",
    "HOA_TOC": "Hỏa tốc"
}

SECURITY_MAP = {
    "THUONG": "Thường",
    "MAT": "Mật",
    "TOI_MAT": "Tối mật",
    "TUYET_MAT": "Tuyệt mật"
}

def convert():
    input_path = os.path.join("docs", "van-ban-den-export.md")
    output_path = os.path.join("docs", "van-ban-den-rag.md")

    if not os.path.exists(input_path):
        print(f"Error: {input_path} does not exist!")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    json_match = re.search(r"```json\s*(\[.*?\])\s*```", content, re.DOTALL)
    if not json_match:
        print("Could not find json block in input file!")
        return

    records = json.loads(json_match.group(1))
    total_count = len(records)
    print(f"Found {total_count} records. Generating updated RAG documents with dual-index for arrivalNo and documentNo...")

    # Statistics Calculation
    status_counts = Counter(r.get("status") for r in records)
    priority_counts = Counter(r.get("priority") for r in records)
    security_counts = Counter(r.get("security") for r in records)
    dept_counts = Counter(r.get("currentDeptName") or "Chưa phân công" for r in records)
    user_counts = Counter(r.get("currentUserName") or "Chưa phân công" for r in records)
    category_counts = Counter(r.get("categoryName") or "Chưa phân loại" for r in records)
    
    receive_dates = [r.get("receiveDate") for r in records if r.get("receiveDate")]
    min_date = min(receive_dates) if receive_dates else "N/A"
    max_date = max(receive_dates) if receive_dates else "N/A"

    overdue_docs = [f"Số {r.get('arrivalNo')} ({r.get('documentNo')})" for r in records if r.get("status") == "QUA_HAN"]
    new_docs = [f"Số {r.get('arrivalNo')} ({r.get('documentNo')})" for r in records if r.get("status") == "MOI_NHAN"]

    lines = []
    lines.append("# SỔ QUẢN LÝ VĂN BẢN ĐẾN (DỮ LIỆU TỔNG HỢP & CHI TIẾT TRA CỨU)\n")
    lines.append("> **Quy ước định danh văn bản trong hệ thống**:")
    lines.append("> - **Số đến (Số công văn đến)**: Là số thứ tự ghi sổ văn bản đến (ví dụ: **Số 62**, **Số 61**, **Số 60**, **Số 58**...).")
    lines.append("> - **Số / Ký hiệu văn bản**: Là ký hiệu do cơ quan gửi ban hành (ví dụ: **BG260819B404**, **157/CV-2026**, **156/CV-2026**...).")
    lines.append("> - *Lưu ý tra cứu*: Khi người dùng hỏi 'công văn số X' (ví dụ công văn số 62) hoặc 'công văn Y' (ví dụ công văn BG260819B404), cả hai cách gọi đều chỉ cùng một văn bản.\n")

    # SECTION 1: SUMMARY STATISTICS (TỔNG HỢP DỮ LIỆU)
    lines.append("## 1. BÁO CÁO TỔNG HỢP DỮ LIỆU VĂN BẢN ĐẾN (SUMMARY STATISTICS)")
    lines.append("Mục này cung cấp dữ liệu tổng hợp và thống kê số liệu toàn bộ văn bản đến phục vụ trả lời các câu hỏi tổng hợp, thống kê, báo cáo tình hình xử lý công văn:\n")

    lines.append("### 1.1. Thống kê tổng quan")
    lines.append(f"- **Tổng số lượng văn bản tiếp nhận**: **{total_count} văn bản**.")
    lines.append(f"- **Khoảng thời gian tiếp nhận**: Từ ngày **{min_date}** đến ngày **{max_date}**.")
    lines.append("- **Sổ theo dõi chính**: Sổ Văn bản Văn phòng (Ký hiệu: `VP-2026`).\n")

    lines.append("### 1.2. Thống kê theo Trạng thái xử lý văn bản")
    lines.append("| Trạng thái xử lý | Mã trạng thái | Số lượng văn bản | Tỷ lệ (%) |")
    lines.append("|:---|:---:|:---:|:---:|")
    for st_code, st_vn in STATUS_MAP.items():
        cnt = status_counts.get(st_code, 0)
        pct = round(cnt / total_count * 100, 1) if total_count > 0 else 0
        lines.append(f"| {st_vn} | `{st_code}` | **{cnt}** | {pct}% |")
    lines.append(f"| **TỔNG CỘNG** | | **{total_count}** | **100%** |\n")

    lines.append("### 1.3. Thống kê theo Mức độ khẩn và Mức độ mật")
    lines.append("- **Mức độ khẩn**:")
    for pr_code, pr_vn in PRIORITY_MAP.items():
        lines.append(f"  + {pr_vn} (`{pr_code}`): **{priority_counts.get(pr_code, 0)}** văn bản")
    lines.append("- **Mức độ mật**:")
    for sc_code, sc_vn in SECURITY_MAP.items():
        lines.append(f"  + {sc_vn} (`{sc_code}`): **{security_counts.get(sc_code, 0)}** văn bản")
    lines.append("")

    lines.append("### 1.4. Thống kê theo Phòng ban / Bộ phận thụ lý")
    lines.append("| Phòng ban / Đơn vị tiếp nhận | Số lượng văn bản | Cán bộ phụ trách chính |")
    lines.append("|:---|:---:|:---|")
    dept_user_map = {
        "Địa chính – Xây dựng – Nông nghiệp – Môi trường": "Bùi Thị Hoa",
        "Văn hóa – Xã hội": "Huỳnh Văn Nam",
        "Ban CHQS xã": "Trương Văn Phúc",
        "Công an xã": "Phan Thị Oanh",
        "Tài chính – Kế toán": "Lý Thị Mai",
        "Tư pháp – Hộ tịch": "Dương Thị Kim",
        "Văn phòng – Thống kê": "Nguyễn Văn An",
        "Y tế": "Bộ phận Y tế",
        "Chưa phân công": "Chưa giao cán bộ"
    }
    for dept, cnt in dept_counts.most_common():
        user_name = dept_user_map.get(dept, "Chưa phân công")
        lines.append(f"| {dept} | **{cnt}** | {user_name} |")
    lines.append("")

    lines.append("### 1.5. Thống kê theo Lĩnh vực văn bản")
    cat_items = [f"{cat} ({cnt})" for cat, cnt in category_counts.most_common()]
    lines.append(f"- Các lĩnh vực công văn tiếp nhận: {', '.join(cat_items)}.\n")

    lines.append("### 1.6. Danh sách các văn bản cần lưu ý")
    lines.append(f"- **Văn bản Quá hạn ({len(overdue_docs)} công văn)**: {', '.join(overdue_docs) if overdue_docs else 'Không có'}.")
    lines.append(f"- **Văn bản Mới nhận chưa xử lý ({len(new_docs)} công văn)**: {', '.join(new_docs) if new_docs else 'Không có'}.")
    lines.append(f"- **Văn bản Hỏa tốc ({priority_counts.get('HOA_TOC', 0)} công văn)**: Bao gồm Số 56 (155/CV-2026), Số 44 (143/CV-2026), Số 32 (131/CV-2026), Số 20 (119/CV-2026), Số 8 (107/CV-2026), Số 3 (102/UBND-2026).\n")

    lines.append("---\n")

    # SECTION 2: BẢNG TRA CỨU TỔNG HỢP NHANH (GIỐNG GIAO DIỆN PHẦN MỀM)
    lines.append("## 2. BẢNG TỔNG HỢP TRA CỨU CÔNG VĂN ĐẾN (THEO GIAO DIỆN HỆ THỐNG)")
    lines.append("| Số đến / Ký hiệu | Trích yếu nội dung | Ngày đến / Hạn xử lý | Trạng thái | Độ khẩn | Đơn vị / Người xử lý |")
    lines.append("|:---|:---|:---|:---:|:---:|:---|")

    for r in records:
        arr_no = r.get("arrivalNo") or ""
        doc_no = r.get("documentNo") or "Chưa có số"
        title = (r.get("title") or "").replace("|", "-").replace("\n", " ").strip()
        status_raw = r.get("status") or ""
        status_vn = STATUS_MAP.get(status_raw, status_raw)
        priority_vn = PRIORITY_MAP.get(r.get("priority"), r.get("priority") or "Thường")
        sender = (r.get("senderOrg") or "").replace("|", "-").strip()
        dept = r.get("currentDeptName") or "Chưa phân công"
        rec_date = r.get("receiveDate") or ""
        deadline = r.get("deadline")
        deadline_str = f"Hạn: {deadline}" if deadline else "Không đặt hạn"
        
        assignees_chu_tri = []
        assignees_phoi_hop = []
        for a in r.get("assignees", []):
            if a.get("role") == "CHU_TRI":
                assignees_chu_tri.append(a.get("fullName"))
            else:
                assignees_phoi_hop.append(a.get("fullName"))
        
        user_display = []
        if dept != "Chưa phân công":
            user_display.append(dept)
        if assignees_chu_tri:
            user_display.append(f"Chủ trì: {', '.join(assignees_chu_tri)}")
        elif r.get("currentUserName"):
            user_display.append(f"Phụ trách: {r.get('currentUserName')}")
        if assignees_phoi_hop:
            user_display.append(f"Phối hợp: {', '.join(assignees_phoi_hop)}")
        
        user_str = " - ".join(user_display) if user_display else "Chưa phân công"
        
        col1 = f"**Số {arr_no}**<br>({doc_no})"
        col2 = f"**{title}**<br>*{sender}*"
        col3 = f"Đến: {rec_date}<br>{deadline_str}"
        lines.append(f"| {col1} | {col2} | {col3} | {status_vn} | {priority_vn} | {user_str} |")

    lines.append("\n---\n")

    # SECTION 3: CHI TIẾT TỪNG VĂN BẢN (DUAL KEY HEADINGS & EXPLICIT ALIASES)
    lines.append("## 3. CHI TIẾT TỪNG CÔNG VĂN ĐẾN\n")

    for r in records:
        arr_no = r.get("arrivalNo") or ""
        doc_no = r.get("documentNo") or "Chưa có số"
        book_no = r.get("bookNo") or "VP-2026"
        title = (r.get("title") or "Không có tiêu đề").strip()
        status_raw = r.get("status") or ""
        status_vn = STATUS_MAP.get(status_raw, status_raw)
        priority_vn = PRIORITY_MAP.get(r.get("priority"), r.get("priority") or "Thường")
        security_vn = SECURITY_MAP.get(r.get("security"), r.get("security") or "Thường")
        sender = (r.get("senderOrg") or "Không rõ").strip()
        category = r.get("categoryName") or "Chung"
        issue_date = r.get("issueDate") or "Chưa có"
        rec_date = r.get("receiveDate") or "Chưa có"
        deadline = r.get("deadline") or "Không đặt hạn"
        dept = r.get("currentDeptName") or "Chưa phân công"
        user = r.get("currentUserName") or "Chưa phân công"
        note = (r.get("note") or "Không có ghi chú").strip()
        
        assignees_chu_tri = []
        assignees_phoi_hop = []
        for a in r.get("assignees", []):
            if a.get("role") == "CHU_TRI":
                assignees_chu_tri.append(a.get("fullName"))
            else:
                assignees_phoi_hop.append(a.get("fullName"))
        
        chu_tri_str = ", ".join(assignees_chu_tri) if assignees_chu_tri else user
        phoi_hop_str = ", ".join(assignees_phoi_hop) if assignees_phoi_hop else "Không có"

        attach_list = [att.get("fileName") for att in r.get("attachments", []) if att.get("fileName")]
        attach_str = ", ".join(attach_list) if attach_list else "Không có"

        # Explicit card heading with both Số 62 and BG260819B404
        lines.append(f"### Công văn số {arr_no} | Số ký hiệu: {doc_no}")
        lines.append(f"- **Số đến (Số công văn đến)**: Số {arr_no} (Công văn số {arr_no}, Văn bản số {arr_no})")
        lines.append(f"- **Số ký hiệu văn bản**: {doc_no} (Công văn {doc_no}, Ký hiệu {doc_no})")
        lines.append(f"- **Tiêu đề (Trích yếu nội dung)**: {title}")
        lines.append(f"- **Trạng thái hiện tại**: {status_vn} ({status_raw})")
        lines.append(f"- **Mức độ khẩn**: {priority_vn} | **Mức độ mật**: {security_vn}")
        lines.append(f"- **Cơ quan ban hành / Đơn vị gửi**: {sender}")
        lines.append(f"- **Lĩnh vực**: {category}")
        lines.append(f"- **Sổ văn bản**: {book_no}")
        lines.append(f"- **Ngày đến (Ngày nhận)**: {rec_date} | **Ngày ban hành**: {issue_date}")
        lines.append(f"- **Hạn xử lý (Thời hạn giải quyết)**: {deadline}")
        lines.append(f"- **Đơn vị xử lý**: {dept}")
        lines.append(f"- **Người chủ trì xử lý**: {chu_tri_str}")
        lines.append(f"- **Người phối hợp xử lý**: {phoi_hop_str}")
        lines.append(f"- **Ghi chú**: {note}")
        lines.append(f"- **Tệp tin đính kèm**: {attach_str}")
        lines.append(f"- **Từ khóa tìm kiếm**: Công văn số {arr_no}, Văn bản số {arr_no}, Số đến {arr_no}, Công văn {doc_no}, Ký hiệu {doc_no}, {title}, {sender}")
        lines.append("")

    output_content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_content)

    print(f"Created {output_path} successfully with {len(records)} records ({len(output_content)} chars)!")

if __name__ == "__main__":
    convert()

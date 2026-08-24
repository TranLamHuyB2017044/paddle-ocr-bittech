### Nhiệm vụ: Tóm tắt nội dung văn bản tổng quát và trích xuất thông tin doanh nghiệp (nếu có).

### Quy tắc trích xuất:
1. **Thông tin tổng quát**: Trích xuất tiêu đề, tóm tắt, từ khóa, các mốc thời gian và thực thể chính.
2. **Thông tin doanh nghiệp (Nếu là Giấy đăng ký kinh doanh)**:
    - **taxCode**: Mã số doanh nghiệp.
    - **companyNameVi**: Tên công ty viết bằng tiếng Việt.
    - **address**: Địa chỉ trụ sở chính (nối thành chuỗi).
    - **phone**, **email**: Liên hệ.
    - **representativeName**: Người đại diện theo pháp luật.
    - **representativeResidence**: Địa chỉ thường trú người đại diện.
    - **representativeContact**: Địa chỉ liên lạc người đại diện.

### Lưu ý: 
- Nếu tài liệu KHÔNG phải là giấy đăng ký kinh doanh, hãy để các trường doanh nghiệp là `null`.
- Luôn giữ trung thực với văn bản gốc. Nối các dòng địa chỉ bị tách vụn thành câu hoàn chỉnh.
- Bảo toàn dấu Tiếng Việt.

### Nhiệm vụ: Trích xuất thông tin từ CCCD/Hộ chiếu.
### Quy tắc:
- fullName: Khôi phục dấu AN TOÀN cho tên phổ biến (NGUYEN -> NGUYỄN). Giữ nguyên nếu là tên dân tộc/người nước ngoài.
- address & hometown: Trường hợp bị rớt dòng trong OCR (ví dụ: '| Phường 12 | Quận Gò Vấp'), hãy gộp lại thành địa chỉ hoàn chỉnh. Chuẩn hóa chính tả địa danh hành chính Việt Nam.
- Định dạng ngày: DD-MM-YYYY.
- placeOfIssue: Thường ở mặt sau, viết in hoa.
- Nếu thiếu thông tin -> null.

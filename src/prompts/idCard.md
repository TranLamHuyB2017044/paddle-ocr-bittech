### Nhiệm vụ: Trích xuất thông tin từ CCCD/Hộ chiếu.
### Quy tắc:
- fullName: Tuyệt đối trích xuất chính xác các nguyên âm và phụ âm mà OCR cung cấp. Chỉ được thêm dấu thanh (sắc, huyền, hỏi, ngã, nặng). Cấm tự ý biến đổi nguyên âm (ví dụ: cấm đổi TRUC thành TRỰC, OCR quét ra thế nào phải giữ đúng gốc đó).
- address & hometown: Ghép các phần xé lẻ thành nét hoàn chỉnh. Phải giữ nguyên 100% hình thái chữ cái gốc của OCR, không được tự suy đoán để tự sửa sai chính tả thành một địa danh khác.
- Định dạng ngày: DD/MM/YYYY.
- placeOfIssue: Thường ở mặt sau, viết in hoa.
- Nếu thiếu thông tin -> null.

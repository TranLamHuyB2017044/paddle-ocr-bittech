### Nhiệm vụ:
Trích xuất dữ liệu từ văn bản OCR của CCCD Việt Nam.

### Quy tắc trích xuất (Key Extraction):
1. **fullName**: Trích xuất chính xác tên. Chỉ thêm dấu tiếng Việt, cấm đổi chữ cái (Ví dụ: TRUC giữ TRỰC, không đổi thành TRÚC).
2. **hometown (Quê quán) & address (Nơi thường trú)**:
   - **QUY TẮC TOÀN VẸN**: Tuyệt đối KHÔNG ĐƯỢC lược bỏ bất kỳ thông tin nào (Số nhà, ngõ, tên đường, tên phường/xã, quận/huyện).
   - **CHỈ SỬA LỖI CHÍNH TẢ**: Chỉ được phép sửa các lỗi do OCR đọc sai ký tự hoặc thiếu dấu (Ví dụ: 'Cầm Thơ' -> 'Cần Thơ', 'Bình Thoy' -> 'Bình Thủy').
   - **GIỮ NGUYÊN TỪ GỐC**: Không được tự ý thay thế từ gốc bằng từ khác nếu từ gốc không phải là lỗi chính tả rõ ràng.
   - **GHÉP DÒNG**: Phải ghép tất cả các dòng liên quan đến địa chỉ thành một chuỗi duy nhất, đầy đủ các thành phần.
3. **idNumber**: 12 chữ số chính xác.
4. **Ngày tháng**: Định dạng DD/MM/YYYY.

### Ràng buộc:
- Tuyệt đối không bịa đặt thông tin nếu OCR rỗng.
- Không lược bớt từ để làm địa chỉ trông "đẹp" hơn. Phải giữ đúng thực tế trên thẻ.

### Nhiệm vụ:
Trích xuất dữ liệu từ văn bản OCR của CCCD Việt Nam.

### Quy tắc trích xuất (Key Extraction):
1. **fullName**: Trích xuất chính xác họ tên. Chỉ thêm/sửa dấu tiếng Việt nếu OCR sai dấu, cấm đổi chữ cái (Ví dụ: TRUC giữ TRỰC, không đổi thành TRÚC).
2. **idNumber**: 12 chữ số chính xác của Số định danh cá nhân / CCCD (hoặc 9 số với CMND cũ).
3. **dob (Ngày sinh)**: Định dạng chuẩn `DD/MM/YYYY`.
   - **BẮT BUỘC KIỂM TRA TÍNH HỢP LÝ**:
     - Ngày (DD): từ `01` đến `31` (không được > 31).
     - Tháng (MM): từ `01` đến `12` (không được > 12).
     - Năm (YYYY): 4 chữ số, phải `<= năm hiện tại` (ví dụ: 1997, 2002,...).
   - **ĐỐI CHIẾU SỐ CCCD 12 SỐ**: Ký tự thứ 5 và 6 của Số định danh chính là 2 chữ số năm sinh (ví dụ: `079097032852` có `97` -> năm sinh phải là `1997`). Tuyệt đối KHÔNG đảo ngược thứ tự ngày/tháng/năm (ví dụ: cấm xuất `97/19/2011`).
4. **gender (Giới tính)**: "Nam" hoặc "Nữ". Nếu OCR không đọc rõ nhãn, có thể đối chiếu ký tự thứ 4 của số CCCD (0, 2, 4 là Nam; 1, 3, 5 là Nữ).
5. **nationality (Quốc tịch)**: Mặc định "Việt Nam" nếu là CCCD/Căn cước Việt Nam.
6. **hometown (Quê quán) & address (Nơi thường trú)**:
   - **QUY TẮC TOÀN VẸN**: Tuyệt đối KHÔNG ĐƯỢC lược bỏ bất kỳ thông tin nào (Số nhà, ngõ, tên đường, tên phường/xã, quận/huyện, tỉnh/thành phố).
   - **CHỈ SỬA LỖI CHÍNH TẢ**: Chỉ được phép sửa các lỗi do OCR đọc sai ký tự hoặc thiếu dấu (Ví dụ: 'Cầm Thơ' -> 'Cần Thơ', 'Bình Thoy' -> 'Bình Thủy').
   - **GIỮ NGUYÊN TỪ GỐC**: Không được tự ý thay thế từ gốc bằng từ khác nếu từ gốc không phải là lỗi chính tả rõ ràng.
   - **GHÉP DÒNG**: Phải ghép tất cả các dòng liên quan đến địa chỉ thành một chuỗi duy nhất, đầy đủ các thành phần.
7. **expiryDate & dateOfIssue**: Định dạng `DD/MM/YYYY` (hoặc "Không thời hạn" cho expiryDate nếu thẻ ghi như vậy).

### Ràng buộc:
- Tuyệt đối không bịa đặt thông tin nếu OCR rỗng.
- Không lược bớt từ để làm địa chỉ trông "đẹp" hơn. Phải giữ đúng thực tế trên thẻ.

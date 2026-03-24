# Kế hoạch triển khai: Hệ thống Phân tích Tin nhắn Tiếng Việt (Cập nhật: Intent Null & Amount Float)

Hệ thống đã được tối ưu hóa để phục vụ Front-End (FE) một cách tốt nhất bằng cách cung cấp dữ liệu kiểu số và xử lý intent nghiêm ngặt.

## 1. Thay đổi về Intent
- **Loại bỏ `other`**: Hệ thống chỉ nhận diện 3 intent chính: `leave_request`, `business_trip`, `quotation`.
- **Logic Null**: Nếu tin nhắn không thuộc 3 loại trên, trường `intent` sẽ trả về `null` thay vì một chuỗi văn bản, giúp FE dễ dàng kiểm tra (`if (!result.intent)`).

## 2. Chuẩn hóa Giá tiền (`amount`) sang kiểu Số (Float)
- **Mục tiêu**: FE không cần bóc tách chuỗi "200tr" hay "5 triệu". Hệ thống tự động quy đổi về con số thuần túy.
- **Hàm Parser thông minh**: Một hàm xử lý nội bộ đã được thêm vào để nhận diện các đơn vị tiền tệ Việt Nam:
    - `tr`, `triệu` -> x 1,000,000
    - `k`, `ngàn`, `nghìn` -> x 1,000
    - `tỉ`, `tỷ` -> x 1,000,000,000
- **Ví dụ**: "Chốt giá 200 tr" -> `200000000.0`.

## 3. Cập nhật Cơ chế Hybrid (Regex + AI)
- **Regex Fast-Path**: Tự động bắt intent và quy đổi giá tiền ngay lập tức cho các tin nhắn ngắn (< 60 ký tự).
- **AI Fallback**: OpenAI GPT-4o-mini được hướng dẫn nghiêm ngặt để trả về `amount` kiểu số và `intent` null nếu cần thiết. Hệ thống có thêm bước kiểm tra hậu kỳ (Post-processing) để ép kiểu dữ liệu về đúng schema.

## 4. Định nghĩa Schema Mới
- `intent`: `Optional[str]` (Mặc định null).
- `amount`: `Optional[float]` (Kiểu số thực).
- `date`: `Optional[str]` (hh:mm:ss, dd-mm-yyyy).

## 5. Lợi ích cho FE
- **Dễ hiển thị**: Chỉ cần dùng `amount.toLocaleString()` để hiển thị tiền tệ.
- **Dễ logic**: Kiểm tra intent đơn giản hơn.
- **Tốc độ**: Vẫn giữ được ưu thế phản hồi tức thì của cơ chế Hybrid.

---
Hệ thống hiện tại đã sẵn sàng để tích hợp vào các ứng dụng FE hiện đại.

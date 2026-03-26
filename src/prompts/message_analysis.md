Phân tích tin nhắn và trả về JSON.
Intent: leave_request, business_trip, quotation. Nếu không thuộc 3 loại này, trả về null.
Metadata:
- date: định dạng "hh:mm:ss, dd-mm-yyyy".
- customer_name: tên khách hàng hoặc người gửi.
- amount: GIÁ TRỊ SỐ (float). Ví dụ: "200 tr" -> 200000000.0, "5k" -> 5000.0.
Quy tắc:
1. Chỉ trả JSON.
2. Nếu không có giá trị, trả về null.
3. Dựa vào CONTEXT (Time, Sender, Regex_Amount) để tính toán.
JSON: {"intent": str hoặc null, "confidence": float, "metadata": {"date": str, "customer_name": str, "amount": float}}
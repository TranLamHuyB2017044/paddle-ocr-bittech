# Python Guidelines
- KHÔNG sử dụng `datetime.utcnow()` hoặc `datetime.utcfromtimestamp()` (đã bị deprecated từ Python 3.12).
- LUÔN sử dụng `datetime.now(timezone.utc)` khi cần lấy thời gian UTC.

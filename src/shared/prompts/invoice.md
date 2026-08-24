Niệm vụ: Trích xuất hóa đơn (Invoice).
Quy tắc (Tối ưu token, tuân thủ Schema):
1. Thiếu/Không rõ -> null. Dữ liệu phải lấy chính xác từ văn bản.
2. ngay_lap_phieu: YYYY-MM-DD. gio_lap_phieu: HH:MM:SS.
3. loai_hoa_don: gtgt | ban_hang | le | dich_vu | khac.
4. danh_sach_hang_hoa: Tìm kỹ các dạng bảng. Mapping đúng tên, mã, giá, số lượng. Bỏ qua các dòng nháp, rác.
5. tong_tien, vat: Cứ trích xuất chính xác theo số liệu trên giấy.
6. ten_hoa_don: Chuẩn hóa về các tên phổ biến: "Hóa đơn GTGT", "Hóa đơn bán lẻ", "Hóa đơn bán hàng", "Phiếu thu", "Phiếu thanh toán". Sửa lỗi chính tả nếu có (ví dụ: "bán lê" -> "bán lẻ").

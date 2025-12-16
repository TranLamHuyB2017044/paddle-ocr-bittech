from typing import Optional, Union, List
from pydantic import BaseModel, Field

class IdCard(BaseModel):
    fullName: Optional[str] = Field(description="Fullname/Họ và tên")
    idNumber: Optional[str] = Field(description="Số/Number/No")
    dob: Optional[str] = Field(description="Date of birth (DD-MM-YYYY)")
    gender: Optional[str] = Field(description="Gender (Nam/Nữ)")
    nationality: Optional[str] = Field(description="Nationality")
    hometown: Optional[str] = Field(description="Place of origin/Quê quán")
    address: Optional[str] = Field(description="Address/Nơi thường trú")
    expiryDate: Optional[str] = Field(description="Date of expiry (DD-MM-YYYY)")
    dateOfIssue: Optional[str] = Field(description="Date of issue (DD-MM-YYYY)")
    placeOfIssue: Optional[str] = Field(description="Place of issue")

class DriverLicense(BaseModel):
    fullName: Optional[str] = Field(description="Họ và tên")
    idNumber: Optional[str] = Field(description="Số giấy phép lái xe")
    dob: Optional[str] = Field(description="Ngày sinh (DD-MM-YYYY)")
    nationality: Optional[str] = Field(description="Nationality")
    rank: Optional[str] = Field(alias="class", description="Hạng bằng (A1, A2, B1, B2...)")
    expiryDate: Optional[str] = Field(description="Ngày hết hạn (DD-MM-YYYY)")
    dateOfIssue: Optional[str] = Field(description="Ngày cấp (DD-MM-YYYY)")
    dateOfBegining: Optional[str] = Field(description="Ngày trúng tuyển")


class InvoiceItem(BaseModel):
    ten_hang_hoa: Optional[str] = Field(description="Tên hàng hóa / dịch vụ")
    ma_hang: Optional[str] = Field(description="Mã hàng (nếu có)")
    don_vi_tinh: Optional[str] = Field(description="Đơn vị tính: cái, kg, giờ...")
    so_luong: Optional[float] = Field(description="Số lượng")
    don_gia: Optional[float] = Field(description="Đơn giá chưa thuế")
    thanh_tien: Optional[float] = Field(description="Thành tiền trước thuế")
    thue_suat: Optional[float] = Field(description="Thuế suất VAT (%)")
    tien_thue: Optional[float] = Field(description="Tiền thuế VAT")
    chiet_khau: Optional[float] = Field(description="Chiết khấu dòng hàng (nếu có)")


class Invoice(BaseModel):
    # =========================
    # 1. Nhận diện hóa đơn
    # =========================
    so_hoa_don: Optional[str] = Field(description="Số hóa đơn")
    ky_hieu_hoa_don: Optional[str] = Field(description="Ký hiệu hóa đơn")
    loai_hoa_don: Optional[str] = Field(
        description="Loại hóa đơn: gtgt | ban_hang | le | dich_vu | khac"
    )

    ngay_lap_phieu: Optional[str] = Field(
        description="Ngày lập hóa đơn (YYYY-MM-DD)"
    )
    gio_lap_phieu: Optional[str] = Field(
        description="Giờ lập hóa đơn (HH:MM:SS)"
    )

    # =========================
    # 2. Bên bán (Seller)
    # =========================
    ten_nguoi_ban: Optional[str] = Field(description="Tên người bán / đơn vị bán")
    ma_so_thue_nguoi_ban: Optional[str] = Field(description="MST người bán")
    dia_chi_nguoi_ban: Optional[str] = Field(description="Địa chỉ người bán")
    dien_thoai_nguoi_ban: Optional[str] = Field(description="SĐT người bán")
    so_tai_khoan: Optional[str] = Field(description="Số tài khoản ngân hàng")
    ten_ngan_hang: Optional[str] = Field(description="Tên ngân hàng")

    # =========================
    # 3. Bên mua (Buyer)
    # =========================
    ten_nguoi_mua: Optional[str] = Field(description="Tên người mua")
    ma_so_thue_nguoi_mua: Optional[str] = Field(description="MST người mua")
    dia_chi_nguoi_mua: Optional[str] = Field(description="Địa chỉ người mua")
    dien_thoai_nguoi_mua: Optional[str] = Field(description="SĐT người mua")

    # =========================
    # 4. Nội dung hóa đơn
    # =========================
    noi_dung_hoa_don: Optional[str] = Field(
        description="Nội dung hóa đơn / mô tả tổng quát"
    )

    danh_sach_hang_hoa: Optional[List[InvoiceItem]] = Field(
        description="Danh sách hàng hóa / dịch vụ"
    )

    # =========================
    # 5. Tổng tiền & thuế
    # =========================
    tong_tien_truoc_thue: Optional[float] = Field(
        description="Tổng tiền trước thuế"
    )
    tong_tien_thue: Optional[float] = Field(
        description="Tổng tiền thuế VAT"
    )
    tong_chiet_khau: Optional[float] = Field(
        description="Tổng chiết khấu (nếu có)"
    )
    tong_so_tien: Optional[float] = Field(
        description="Tổng số tiền thanh toán (sau thuế)"
    )
    tong_tien_bang_chu: Optional[str] = Field(
        description="Tổng tiền bằng chữ"
    )

    # =========================
    # 6. Thanh toán
    # =========================
    hinh_thuc_thanh_toan: Optional[str] = Field(
        description="Hình thức thanh toán: tiền mặt | chuyển khoản | ví"
    )
    trang_thai_thanh_toan: Optional[str] = Field(
        description="paid | unpaid | partial"
    )

    # =========================
    # 7. Thông tin bổ sung
    # =========================
    ghi_chu: Optional[str] = Field(description="Ghi chú")
    tham_chieu_hop_dong: Optional[str] = Field(description="Mã hợp đồng (nếu có)")

    # =========================
    # 8. Phục vụ OCR / AI
    # =========================
    do_tin_cay: Optional[float] = Field(
        description="Confidence score tổng (0–1)"
    )






class Document(BaseModel):
    title: Optional[str] = Field(description="Tiêu đề tài liệu")
    summary: Optional[str] = Field(description="Tóm tắt nội dung")
    keywords: list[str] = Field(default_factory=list, description="Từ khóa chính")
    dates: list[str] = Field(default_factory=list, description="Các mốc thời gian")
    entities: list[str] = Field(default_factory=list, description="Các thực thể (người, tổ chức)")

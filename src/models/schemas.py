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


class Invoice(BaseModel):
    # =========================
    # Header Information
    # =========================
    ten_hoa_don: Optional[str] = Field(description="Tên hóa đơn (Ví dụ: Hóa đơn GTGT, Phiếu thu...)")
    so_hoa_don: Optional[str] = Field(description="Số hóa đơn")
    ngay_lap_hoa_don: Optional[str] = Field(description="Ngày lập hóa đơn")
    
    # =========================
    # Customer / Buyer
    # =========================
    ten_khach_hang: Optional[str] = Field(description="Tên khách hàng / người mua")
    dia_chi_khach_hang: Optional[str] = Field(description="Địa chỉ khách hàng")
    
    # =========================
    # Seller (Optional but good to have)
    # =========================
    ten_nguoi_ban: Optional[str] = Field(description="Tên người bán / cửa hàng")
    dia_chi_nguoi_ban: Optional[str] = Field(description="Địa chỉ người bán")

    # =========================
    # Financials
    # =========================
    tong_tien: Optional[str] = Field(description="Tổng tiền thanh toán / Thành tiền")
    
    # =========================
    # Line Items (Simplified)
    # =========================
    danh_sach_san_pham: Optional[List[str]] = Field(
        default_factory=list,
        description="Danh sách sản phẩm/dịch vụ. Mỗi phần tử là một chuỗi text mô tả dòng hàng (Tên + SL + Giá)"
    )

class VehicleDocument(BaseModel):
    documentType: Optional[str] = Field(description="Loại giấy tờ nhận diện được, CHỈ ĐƯỢC CHỌN 1 TRONG 7 LOẠI SAU: REGISTRATION (Giấy đăng ký xe), INSPECTION (Giấy chứng nhận kiểm định / Đăng kiểm), CIVIL_INSURANCE (BH TNDS bắt buộc), VOLUNTARY_INSURANCE (BH vật chất xe tự nguyện), ROAD_FEE (Phí sử dụng đường bộ), TRANSPORT_LICENSE (Giấy phép kinh doanh vận tải / Phù hiệu), TRAINING_PERMIT (Giấy phép xe tập lái)")
    
    # Thông tin chung (Common Fields)
    plateNumber: Optional[str] = Field(description="Biển số xe (Plate Number)")
    documentNumber: Optional[str] = Field(description="Số seri / Số giấy chứng nhận / Số quản lý / Số biên lai / Số phù hiệu")
    dateOfIssue: Optional[str] = Field(description="Ngày cấp / Ngày nộp phí (DD-MM-YYYY)")
    effectiveDate: Optional[str] = Field(description="Ngày bắt đầu hiệu lực (DD-MM-YYYY)")
    expiryDate: Optional[str] = Field(description="Ngày hết hạn / Có giá trị đến (DD-MM-YYYY)")
    issuedBy: Optional[str] = Field(description="Nơi cấp / Đơn vị cấp / Công ty bảo hiểm / Cơ quan quản lý")
    
    # Thông tin chủ thể (Owner / Entity)
    ownerName: Optional[str] = Field(description="Tên chủ xe / Người được bảo hiểm / Tên doanh nghiệp / Tên cơ sở đào tạo")
    address: Optional[str] = Field(description="Địa chỉ")
    
    # Thông tin kỹ thuật xe (Vehicle Details)
    engineNumber: Optional[str] = Field(description="Số máy (Engine No)")
    chassisNumber: Optional[str] = Field(description="Số khung (Chassis No)")
    vehicleBrand: Optional[str] = Field(description="Nhãn hiệu (Brand)")
    vehicleType: Optional[str] = Field(description="Loại xe / Số chỗ ngồi / Tải trọng")
    color: Optional[str] = Field(description="Màu sơn")
    
    # Thông tin tiền phí (Financial Info)
    feeAmount: Optional[str] = Field(description="Số tiền phí / Phí bảo hiểm / Phí đường bộ")

    # Thông tin đặc thù khác (Specific Info)
    transportType: Optional[str] = Field(description="Loại hình kinh doanh vận tải (Ví dụ: Taxi, Hợp đồng, Tuyến cố định...)")
    route: Optional[str] = Field(description="Tuyến / Vùng hoạt động")
    teacherName: Optional[str] = Field(description="Tên giáo viên (Dành cho giấy phép xe tập lái)")


class Document(BaseModel):
    title: Optional[str] = Field(description="Tiêu đề tài liệu")
    summary: Optional[str] = Field(description="Tóm tắt nội dung")
    keywords: list[str] = Field(default_factory=list, description="Từ khóa chính")
    dates: list[str] = Field(default_factory=list, description="Các mốc thời gian")
    entities: list[str] = Field(default_factory=list, description="Các thực thể (người, tổ chức)")

class MenuItem(BaseModel):
    name: Optional[str] = Field(description="Tên sản phẩm/món ăn")
    price: Optional[str] = Field(description="Giá sản phẩm/món ăn")
    description: Optional[str] = Field(description="Mô tả sản phẩm, có thể null")
    thumbnail_url: Optional[str] = Field(description="URL hình ảnh sản phẩm (nếu có), có thể null")

class RestaurantMenu(BaseModel):
    business_name: Optional[str] = Field(description="Tên quán ăn/nhành hàng")
    business_info: Optional[str] = Field(description="Thông tin chung về quán (địa chỉ, SĐT, v.v.)")
    menu_items: List[MenuItem] = Field(default_factory=list, description="Danh sách các sản phẩm/món ăn từ menu")

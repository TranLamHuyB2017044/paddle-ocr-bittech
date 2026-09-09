from enum import Enum
from typing import Optional, Union, List
from pydantic import BaseModel, Field

class PriorityEnum(str, Enum):
    THUONG = "THUONG"
    KHAN = "KHAN"
    THUONG_KHAN = "THUONG_KHAN"
    HOA_TOC = "HOA_TOC"

class SecurityEnum(str, Enum):
    THUONG = "THUONG"
    MAT = "MAT"
    TOI_MAT = "TOI_MAT"
    TUYET_MAT = "TUYET_MAT"

class AdministrativeDocument(BaseModel):
    documentNo: Optional[str] = Field(None, description="Số/ký hiệu văn bản (Ví dụ: 123/UBND-VP)")
    senderOrg: Optional[str] = Field(None, description="Tên cơ quan / đơn vị ban hành văn bản")
    senderCode: Optional[str] = Field(None, description="Mã định danh cơ quan gửi (nếu có)")
    title: Optional[str] = Field(None, description="Trích yếu nội dung văn bản (phần V/v...)")
    issueDate: Optional[str] = Field(None, description="Ngày ban hành văn bản theo định dạng DD/MM/YYYY")
    receiveDate: Optional[str] = Field(None, description="Ngày nhận văn bản theo định dạng DD/MM/YYYY")
    deadline: Optional[str] = Field(None, description="Hạn xử lý văn bản theo định dạng DD/MM/YYYY (nếu có trong nội dung)")
    priority: PriorityEnum = Field(default=PriorityEnum.THUONG, description="Độ khẩn của văn bản")
    security: SecurityEnum = Field(default=SecurityEnum.THUONG, description="Độ mật của văn bản")
    category: Optional[str] = Field(None, description="Gợi ý lĩnh vực văn bản (ví dụ: Đất đai, Tài chính, Pháp chế,...)")
    requireReply: bool = Field(default=False, description="Có yêu cầu đơn vị nhận báo cáo / trả lời hay không")
    meetingAt: Optional[str] = Field(None, description="Thời gian họp nếu là Giấy mời (Định dạng DD-MM-YYYY HH:mm:ss)")
    note: Optional[str] = Field(None, description="Ghi chú thêm từ văn bản")

IncomingDocumentExtractResult = AdministrativeDocument

class BusinessRegistration(BaseModel):
    taxCode: Optional[str] = Field(description="Mã số doanh nghiệp")
    companyNameVi: Optional[str] = Field(description="Tên công ty viết bằng tiếng Việt")
    address: Optional[str] = Field(description="Địa chỉ trụ sở chính")
    phone: Optional[str] = Field(description="Điện thoại")
    email: Optional[str] = Field(description="Email")
    representativeName: Optional[str] = Field(description="Họ và tên người đại diện pháp luật")
    representativeResidence: Optional[str] = Field(description="Địa chỉ thường trú của người đại diện")
    representativeContact: Optional[str] = Field(description="Địa chỉ liên lạc của người đại diện")

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
    don_gia: Optional[str] = Field(description="Đơn giá chưa thuế (định dạng 100,000)")


class Invoice(BaseModel):
    ten_hoa_don: Optional[str] = Field(description="Tên hóa đơn (Ví dụ: Hóa đơn GTGT, Phiếu thu...)")
    so_hoa_don: Optional[str] = Field(description="Số hóa đơn")
    loai_hoa_don: Optional[str] = Field(
        description="Loại hóa đơn: gtgt | ban_hang | le | dich_vu | khac"
    )

    ngay_lap_phieu: Optional[str] = Field(
        description="Ngày lập hóa đơn (YYYY-MM-DD)"
    )
    gio_lap_phieu: Optional[str] = Field(
        description="Giờ lập hóa đơn (HH:MM:SS)"
    )

    ten_nguoi_ban: Optional[str] = Field(description="Tên người bán / đơn vị bán")
    dia_chi_nguoi_ban: Optional[str] = Field(description="Địa chỉ người bán")
    tong_tien: Optional[str] = Field(description="Tổng tiền thanh toán / Thành tiền (định dạng 100,000)")
    vat: Optional[str] = Field(description="VAT")
    danh_sach_hang_hoa: Optional[List[InvoiceItem]] = Field(
        description="Danh sách hàng hóa / dịch vụ"
    )

class VehicleDocument(BaseModel):
    documentType: Optional[str] = Field(description="Loại giấy tờ")
    plateNumber: Optional[str] = Field(description="Biển số xe")
    documentNumber: Optional[str] = Field(description="Số seri")
    dateOfIssue: Optional[str] = Field(description="Ngày cấp")
    effectiveDate: Optional[str] = Field(description="Ngày bắt đầu hiệu lực")
    expiryDate: Optional[str] = Field(description="Ngày hết hạn")
    issuedBy: Optional[str] = Field(description="Nơi cấp")
    ownerName: Optional[str] = Field(description="Tên chủ xe")
    address: Optional[str] = Field(description="Địa chỉ")
    engineNumber: Optional[str] = Field(description="Số máy")
    chassisNumber: Optional[str] = Field(description="Số khung")
    vehicleBrand: Optional[str] = Field(description="Nhãn hiệu")
    vehicleType: Optional[str] = Field(description="Loại xe")
    color: Optional[str] = Field(description="Màu sơn")
    feeAmount: Optional[str] = Field(description="Số tiền phí")
    transportType: Optional[str] = Field(description="Loại hình kinh doanh")
    route: Optional[str] = Field(description="Tuyến hoạt động")
    teacherName: Optional[str] = Field(description="Tên giáo viên")

Document = AdministrativeDocument

class MenuItem(BaseModel):
    category: Optional[str] = Field(description="Tên danh mục món ăn, có thể null")
    name: Optional[str] = Field(description="Tên sản phẩm/món ăn")
    price: Optional[str] = Field(description="Giá sản phẩm/món ăn")
    description: Optional[str] = Field(description="Mô tả sản phẩm, có thể null")
    thumbnail_url: Optional[str] = Field(description="URL hình ảnh sản phẩm (nếu có), có thể null")

class RestaurantMenu(BaseModel):
    business_name: Optional[str] = Field(description="Tên quán ăn/nhành hàng")
    business_info: Optional[str] = Field(description="Thông tin chung về quán (địa chỉ, SĐT, v.v.)")
    menu_items: List[MenuItem] = Field(default_factory=list, description="Danh sách các sản phẩm/món ăn từ menu")

# --- Schemas for Message Analysis ---
class MessageAnalysisRequest(BaseModel):
    message: str
    sender_name: Optional[str] = Field(None, description="Tên người gửi tin nhắn")

class MessageAnalysisMetadata(BaseModel):
    date: Optional[str] = Field(None, description="Ngày giờ liên quan")
    customer_name: Optional[str] = Field(None, description="Tên khách hàng nếu có")
    amount: Optional[float] = Field(None, description="Giá tiền hoặc giá trị báo giá")

class MessageAnalysis(BaseModel):
    intent: Optional[str] = Field(None, description="Ý định")
    confidence: float = Field(..., description="Độ tin cậy")
    metadata: MessageAnalysisMetadata = Field(..., description="Thông tin trích xuất")

# --- Schemas for Chatbot ---
class ChatbotUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="Tên chatbot")
    description: Optional[str] = Field(None, description="Mô tả chatbot")
    avatar_url: Optional[str] = Field(None, description="URL avatar chatbot")
    color: Optional[int] = Field(None, ge=0, le=4, description="Màu chatbot (0-4)")
    greeting: Optional[str] = Field(None, description="Lời chào chatbot")
    workspace_id: Optional[str] = Field(None, description="ID workspace liên kết")
    telegram_bot_token: Optional[str] = Field(None, description="Token của Telegram Bot")
    telegram_chat_id: Optional[str] = Field(None, description="Chat ID của Telegram để nhận thông báo")
    workflow_webhook_url: Optional[str] = Field(None, description="URL webhook cho workflow (n8n)")
    collect_contact_info: Optional[bool] = Field(None, description="Thu thập thông tin liên hệ của khách hàng khi không tìm thấy kết quả")
    domain: Optional[str] = Field(None, description="Lĩnh vực hoạt động của chatbot (ecommerce, ocop, customer_support, general, administrative_doc)")


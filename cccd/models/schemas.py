from typing import Optional, Union
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
    so_hoa_don: Optional[str] = Field(description="Số hóa đơn")
    noi_dung_hoa_don: Optional[str] = Field(description="Nội dung hóa đơn / Sản phẩm chính")
    tong_so_tien: Optional[float] = Field(description="Tổng số tiền thanh toán (number)")
    ngay_lap_phieu: Optional[str] = Field(description="Ngày lập phiếu (YYYY-MM-DD)")

class Document(BaseModel):
    title: Optional[str] = Field(description="Tiêu đề tài liệu")
    summary: Optional[str] = Field(description="Tóm tắt nội dung")
    keywords: list[str] = Field(default_factory=list, description="Từ khóa chính")
    dates: list[str] = Field(default_factory=list, description="Các mốc thời gian")
    entities: list[str] = Field(default_factory=list, description="Các thực thể (người, tổ chức)")

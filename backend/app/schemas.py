from datetime import date
from pydantic import BaseModel, Field, ConfigDict

class RegisterIn(BaseModel):
    role: str = Field(pattern="^(farmer|buyer)$")
    name: str = Field(min_length=2, max_length=120)
    password: str | None = Field(default=None, min_length=10, max_length=128)
    pin: str | None = Field(default=None, pattern=r"^\d{4}$")
    otp: str | None = None
    email: str | None = None
    phone: str | None = None
    language: str = "en"
    village: str = ""
    district: str = ""
    state: str = "Karnataka"
    business_name: str | None = None

class LoginIn(BaseModel):
    username: str
    password: str | None = None
    pin: str | None = Field(default=None, pattern=r"^\d{4}$")

class OtpIn(BaseModel):
    phone: str = Field(min_length=10, max_length=24)
    code: str | None = None

class RefreshIn(BaseModel):
    refresh_token: str

class ProductIn(BaseModel):
    crop: str = Field(min_length=2, max_length=80)
    category: str = "Vegetables"
    quantity_kg: float = Field(gt=0, le=1000000)
    price_per_kg: float = Field(gt=0, le=1000000)
    harvest_date: date
    pickup_date: date | None = None
    quality: str = "Good"
    organic: bool = False
    image_url: str | None = None
    village: str = ""
    district: str = ""
    state: str = "Karnataka"
    description: str = ""
    phone_visible: bool = True
    model_config = ConfigDict(extra="forbid")

class RequirementIn(BaseModel):
    crop: str = Field(min_length=2, max_length=80)
    quantity_kg: float = Field(gt=0)
    min_quantity_kg: float = 0
    max_price_per_kg: float | None = Field(default=None, gt=0)
    quality: str = "Any"
    pickup_by: date | None = None
    location: str = ""
    organic: bool = False

class EnquiryIn(BaseModel):
    product_id: int
    requested_quantity_kg: float = Field(gt=0)
    offered_price_per_kg: float | None = Field(default=None, gt=0)
    message: str = Field(default="", max_length=1500)

class StatusIn(BaseModel):
    status: str

class ProductPriceIn(BaseModel):
    price_per_kg: float = Field(gt=0, le=1000000)

class PriorityIn(BaseModel):
    priority: int = Field(ge=-10, le=10)

class PriceIn(BaseModel):
    crop: str
    state: str
    district: str = ""
    market: str
    minimum: float = Field(ge=0)
    maximum: float = Field(ge=0)
    modal: float = Field(ge=0)
    unit: str = "INR/quintal"
    market_date: date
    source: str

"""Health behavior checks that do not contact external providers."""
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, _otp_codes, _otp_verified, health, request_otp, verify_otp, register, login, products, update_product_price
from app.models import User, FarmerProfile, Product, MandiPrice
from app.security import hash_password
from app.schemas import LoginIn, OtpIn, RegisterIn, ProductPriceIn

def test_health_reports_unconfigured_live_integrations():
    body=health()
    assert body["status"] == "ok"
    assert "unavailable" in body["integrations"]["mandi"]


def test_farmer_can_register_and_sign_in_with_mobile_and_four_digit_pin():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    phone = "9000000001"
    try:
        assert "/api/auth/otp/request" in app.openapi()["paths"]
        sent = request_otp(OtpIn(phone=phone), None)
        code = sent["dev_otp"]
        assert verify_otp(OtpIn(phone=phone, code=code), None)["verified"] is True

        registered = register(RegisterIn(
            role="farmer", name="Demo Farmer", phone=phone,
            pin="4826", otp="verified", language="en",
        ), db, None)
        assert registered["user"]["role"] == "farmer"

        signed_in = login(LoginIn(username=phone, pin="4826"), db, None)
        assert signed_in["user"]["role"] == "farmer"

        formatted_signin = login(LoginIn(username=" 90000 00001 ", pin="4826"), db, None)
        assert formatted_signin["user"]["role"] == "farmer"
    finally:
        db.close()
        _otp_codes.pop(phone, None)
        _otp_verified.pop(phone, None)
        engine.dispose()


def test_farmer_otp_accepts_formatted_phone_and_whitespace_code():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    raw_phone = "+91 90000-00002"
    digits = "919000000002"
    try:
        sent = request_otp(OtpIn(phone=raw_phone), None)
        code = sent["dev_otp"]
        try:
            verify_otp(OtpIn(phone=raw_phone, code="000000"), None)
            assert False, "Expected HTTPException for wrong OTP"
        except Exception:
            pass
        assert verify_otp(OtpIn(phone=raw_phone, code=f" {code} "), None)["verified"] is True

        registered = register(RegisterIn(
            role="farmer", name="Formatted Farmer", phone=raw_phone,
            pin="1357", otp="verified", language="en", village="Gubbi", district="Tumakuru",
        ), db, None)
        assert registered["user"]["role"] == "farmer"
        assert registered["user"]["location"] == "Gubbi, Tumakuru, Karnataka"
        signed = login(LoginIn(username=raw_phone, pin="1357"), db, None)
        assert signed["user"]["role"] == "farmer"
        assert signed["user"]["location"] == "Gubbi, Tumakuru, Karnataka"
    finally:
        db.close()
        _otp_codes.pop(digits, None)
        _otp_verified.pop(digits, None)
        engine.dispose()


def test_products_prioritize_nearest_distance_and_mandi_comparison():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        farmer = User(name="Farm", phone="9111111111", role="farmer", password_hash=hash_password("2026"))
        db.add(farmer); db.flush()
        db.add(FarmerProfile(user_id=farmer.id, village="Gubbi", district="Tumakuru", state="Karnataka"))
        db.add(Product(farmer_id=farmer.id, crop="Tomato", quantity_kg=200, price_per_kg=18, harvest_date=date.today(), village="Gubbi", district="Tumakuru", state="Karnataka"))
        db.add(Product(farmer_id=farmer.id, crop="Potato", quantity_kg=200, price_per_kg=30, harvest_date=date.today(), village="Bannur", district="Mysuru", state="Karnataka"))
        db.add(MandiPrice(crop="Tomato", state="Karnataka", district="Tumakuru", market="Tumakuru APMC", minimum=2000, maximum=2600, modal=2300, unit="INR/quintal", market_date=date.today(), source="Sample Karnataka APMC Reference", is_sample=True))
        db.add(MandiPrice(crop="Potato", state="Karnataka", district="Mysuru", market="Bandipalya APMC, Mysuru", minimum=2000, maximum=2600, modal=2400, unit="INR/quintal", market_date=date.today(), source="Sample Karnataka APMC Reference", is_sample=True))
        db.commit()

        nearest = products(buyer_location="Mysuru, Karnataka", sort="nearest", page=1, limit=20, db=db)["items"]
        assert nearest[0]["crop"] == "Potato"
        assert nearest[0]["distance_km"] < nearest[1]["distance_km"]

        best_price = products(buyer_location="Mysuru, Karnataka", sort="best_price", page=1, limit=20, db=db)["items"]
        assert best_price[0]["crop"] == "Tomato"
        assert best_price[0]["mandi_ref"]["status"] == "below"
        assert best_price[0]["mandi_ref"]["modal_per_kg"] == 23.0

        below_only = products(below_mandi=True, page=1, limit=20, db=db)["items"]
        assert len(below_only) == 1 and below_only[0]["crop"] == "Tomato"

        updated = update_product_price(2, ProductPriceIn(price_per_kg=21.0), user=farmer, db=db)
        assert updated["price_per_kg"] == 21.0
        assert updated["mandi_ref"]["status"] == "below"
    finally:
        db.close()
        engine.dispose()

import os, re, time
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from .database import Base, engine, get_db
from . import models as m
from .schemas import RegisterIn, LoginIn, OtpIn, RefreshIn, ProductIn, RequirementIn, EnquiryIn, StatusIn, PriorityIn, PriceIn, ProductPriceIn
from .security import hash_password, verify_password, make_token, make_refresh_token, user_from_refresh, current_user, allow_roles
from .services import estimate_risk, match_score, product_dict, price_per_kg

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Harvest Bridge API", version="1.0.0", description="Urgency-first farmer and buyer marketplace. Risk estimates are planning guidance, not spoilage measurements.")
origins = [x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET","POST","PUT","PATCH","DELETE"], allow_headers=["Authorization","Content-Type"])
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
_auth_attempts={}
_otp_codes={}; _otp_verified={}
def auth_rate_limit(request:Request):
    """Simple per-process throttle. Use Redis/shared limits for multi-instance hosting."""
    now=time.time(); key=request.client.host if request.client else "unknown"
    window,count=_auth_attempts.get(key,(now,0))
    if now-window>600: window,count=now,0
    count+=1; _auth_attempts[key]=(window,count)
    if count>30: raise HTTPException(429,"Too many account requests. Try again in a few minutes.")

@app.get("/api/health")
def health(): return {"status":"ok","database":"configured","integrations":{"mandi":"credentials present; adapter not enabled" if os.getenv("AGMARKNET_API_URL") else "unavailable: configure official source","weather":"credentials present; adapter not enabled" if os.getenv("OPENWEATHER_API_KEY") else "unavailable: configure API key","images":"credentials present; Cloudinary adapter not enabled" if os.getenv("CLOUDINARY_CLOUD_NAME") else "local uploads fallback"}}

def user_location(user: m.User, db: Session) -> str:
    if user.role == "farmer":
        p = db.query(m.FarmerProfile).filter_by(user_id=user.id).first()
        if p:
            return ", ".join(x for x in (p.village, p.district, p.state) if x)
    elif user.role == "buyer":
        p = db.query(m.BuyerProfile).filter_by(user_id=user.id).first()
        if p and p.location:
            return p.location
    return ""

def profile_for(db, user, data):
    if user.role == "farmer":
        db.add(m.FarmerProfile(user_id=user.id, village=data.village, district=data.district, state=data.state))
    elif user.role == "buyer":
        buyer_loc = ", ".join(x.strip() for x in (data.district, data.state) if x and x.strip())
        db.add(m.BuyerProfile(user_id=user.id, business_name=data.business_name, location=buyer_loc))

@app.post("/api/auth/register")
def register(data: RegisterIn, db: Session=Depends(get_db), _rate=Depends(auth_rate_limit)):
    phone=re.sub(r"\D", "", data.phone or "") or None
    if data.role == "farmer":
        if not phone or len(phone)<10 or len(phone)>24 or not data.pin: raise HTTPException(422, "Farmers need a valid mobile number and four-digit PIN")
        verified_until=_otp_verified.get(phone, 0)
        if verified_until < time.time() or data.otp != "verified": raise HTTPException(400, "Verify your mobile number with OTP before creating the account")
    elif not data.email or not data.password:
        raise HTTPException(422, "Buyers need an email and password")
    if not data.email and not data.phone: raise HTTPException(422, "Provide an email or phone number")
    if data.email and db.query(m.User).filter(func.lower(m.User.email)==data.email.lower()).first(): raise HTTPException(409, "Email already registered")
    if phone and db.query(m.User).filter_by(phone=phone).first(): raise HTTPException(409, "Phone already registered")
    user=m.User(email=data.email.lower() if data.email else None, phone=phone, name=data.name, password_hash=hash_password(data.pin or data.password), role=data.role, language=data.language)
    db.add(user); db.flush(); profile_for(db,user,data); db.commit(); db.refresh(user)
    if data.role == "farmer" and phone:
        _otp_verified.pop(phone, None)
    return {"access_token":make_token(user),"refresh_token":make_refresh_token(user),"token_type":"bearer","user":{"id":user.id,"name":user.name,"role":user.role,"language":user.language,"location":user_location(user,db)}}

@app.post("/api/auth/login")
def login(data: LoginIn, db: Session=Depends(get_db), _rate=Depends(auth_rate_limit)):
    username_clean = data.username.strip()
    username_digits = re.sub(r"\D", "", username_clean)
    filters = [func.lower(m.User.email) == username_clean.lower(), m.User.phone == username_clean]
    if len(username_digits) >= 10:
        filters.append(m.User.phone == username_digits)
    user=db.query(m.User).filter(or_(*filters)).first()
    credential=data.pin if user and user.role=="farmer" else data.password
    if not user or not credential or not verify_password(credential,user.password_hash): raise HTTPException(401,"Mobile/PIN or email/password is incorrect")
    if not user.is_active: raise HTTPException(403,"Account is suspended")
    return {"access_token":make_token(user),"refresh_token":make_refresh_token(user),"token_type":"bearer","user":{"id":user.id,"name":user.name,"role":user.role,"language":user.language,"location":user_location(user,db)}}

@app.post("/api/auth/otp/request")
def request_otp(data: OtpIn, _rate=Depends(auth_rate_limit)):
    phone=re.sub(r"\D", "", data.phone)
    if len(phone)<10 or len(phone)>24: raise HTTPException(422,"Enter a valid mobile number")
    if os.getenv("ENVIRONMENT","development")!="development": raise HTTPException(503,"SMS delivery is not configured. Set up an approved SMS provider before enabling OTP outside local development.")
    code=f"{int.from_bytes(os.urandom(4),'big')%1000000:06d}"; _otp_codes[phone]=(code,time.time()+300)
    response={"message":"OTP sent when an SMS provider is configured. Development mode displays a temporary code here."}
    if os.getenv("ENVIRONMENT","development")=="development": response["dev_otp"]=code
    return response

@app.post("/api/auth/otp/verify")
def verify_otp(data: OtpIn, _rate=Depends(auth_rate_limit)):
    phone=re.sub(r"\D", "", data.phone)
    code=(data.code or "").strip()
    entry=_otp_codes.get(phone)
    if not entry or entry[1]<time.time():
        _otp_codes.pop(phone,None); raise HTTPException(400,"OTP is incorrect or expired; request a new code")
    if not code or entry[0]!=code:
        raise HTTPException(400,"OTP is incorrect or expired; request a new code")
    _otp_codes.pop(phone,None); _otp_verified[phone]=time.time()+600
    return {"verified":True}

@app.post("/api/auth/pin/recover")
def recover_pin(data: OtpIn, pin: str, db: Session=Depends(get_db), _rate=Depends(auth_rate_limit)):
    if not re.fullmatch(r"\d{4}",pin): raise HTTPException(422,"PIN must contain four digits")
    phone=re.sub(r"\D", "", data.phone)
    entry=_otp_codes.get(phone)
    if not data.code or not entry or entry[0]!=data.code or entry[1]<time.time():
        _otp_codes.pop(phone,None); raise HTTPException(400,"OTP is incorrect or expired; request a new code")
    user=db.query(m.User).filter_by(phone=phone,role="farmer").first()
    if not user: raise HTTPException(404,"No farmer account found for this mobile number")
    _otp_codes.pop(phone,None); user.password_hash=hash_password(pin); db.commit()
    return {"message":"PIN updated. Sign in with your new PIN."}

@app.post("/api/auth/logout")
def logout(user: m.User=Depends(current_user)):
    return {"message":"Signed out. Remove the access token from this device."}

@app.post("/api/auth/refresh")
def refresh(data:RefreshIn,db:Session=Depends(get_db)):
    user=user_from_refresh(data.refresh_token,db)
    return {"access_token":make_token(user),"refresh_token":make_refresh_token(user),"token_type":"bearer"}

@app.post("/api/auth/forgot-password")
def forgot_password(_rate=Depends(auth_rate_limit)): return {"message":"If the account exists, recovery instructions will be sent when email/SMS delivery is configured."}

@app.get("/api/me")
def me(user: m.User=Depends(current_user), db: Session=Depends(get_db)):
    return {"id":user.id,"name":user.name,"email":user.email,"phone":user.phone,"role":user.role,"language":user.language,"location":user_location(user,db)}

@app.get("/api/farmer/profile")
def farmer_profile(user: m.User=Depends(allow_roles("farmer")), db: Session=Depends(get_db)):
    p=db.query(m.FarmerProfile).filter_by(user_id=user.id).first(); return {"user":user.name,"phone":user.phone,"village":p.village,"district":p.district,"state":p.state,"show_phone":p.show_phone}

@app.put("/api/farmer/profile")
def update_farmer_profile(data: dict, user: m.User=Depends(allow_roles("farmer")), db: Session=Depends(get_db)):
    p=db.query(m.FarmerProfile).filter_by(user_id=user.id).first()
    for key in ("village","district","state","show_phone"):
        if key in data: setattr(p,key,data[key])
    if "language" in data and data["language"] in ("en","kn","hi"): user.language=data["language"]
    db.commit(); return {"message":"Profile updated"}

@app.get("/api/farmer/products")
def farmer_products(user: m.User=Depends(allow_roles("farmer")), db: Session=Depends(get_db)):
    return [product_dict(p,db) for p in db.query(m.Product).filter_by(farmer_id=user.id).order_by(m.Product.created_at.desc()).all()]

@app.post("/api/farmer/products")
def create_product(data: ProductIn, user: m.User=Depends(allow_roles("farmer")), db: Session=Depends(get_db)):
    p=m.Product(farmer_id=user.id,**data.model_dump()); db.add(p); db.commit(); db.refresh(p)
    return product_dict(p,db)

@app.put("/api/farmer/products/{product_id}")
def edit_product(product_id:int,data:ProductIn,user:m.User=Depends(allow_roles("farmer")),db:Session=Depends(get_db)):
    p=db.query(m.Product).filter_by(id=product_id,farmer_id=user.id).first()
    if not p: raise HTTPException(404,"Listing not found")
    for key,value in data.model_dump().items(): setattr(p,key,value)
    db.commit(); return product_dict(p,db)

@app.delete("/api/farmer/products/{product_id}")
def delete_product(product_id:int,user:m.User=Depends(allow_roles("farmer")),db:Session=Depends(get_db)):
    p=db.query(m.Product).filter_by(id=product_id,farmer_id=user.id).first()
    if not p: raise HTTPException(404,"Listing not found")
    db.delete(p); db.commit(); return {"message":"Listing removed"}

@app.post("/api/farmer/products/{product_id}/status")
def product_status(product_id:int,data:StatusIn,user:m.User=Depends(allow_roles("farmer")),db:Session=Depends(get_db)):
    if data.status not in ("active","paused","sold"): raise HTTPException(422,"Status must be active, paused or sold")
    p=db.query(m.Product).filter_by(id=product_id,farmer_id=user.id).first()
    if not p: raise HTTPException(404,"Listing not found")
    p.status=data.status; db.commit(); return product_dict(p,db)

@app.patch("/api/farmer/products/{product_id}/price")
def update_product_price(product_id:int,data:ProductPriceIn,user:m.User=Depends(allow_roles("farmer")),db:Session=Depends(get_db)):
    p=db.query(m.Product).filter_by(id=product_id,farmer_id=user.id).first()
    if not p: raise HTTPException(404,"Listing not found")
    p.price_per_kg=data.price_per_kg; db.commit(); db.refresh(p); return product_dict(p,db)

@app.post("/api/uploads/image")
def upload_image(file: UploadFile=File(...), user:m.User=Depends(current_user)):
    if file.content_type not in ("image/jpeg","image/png","image/webp"): raise HTTPException(415,"Use JPG, PNG or WebP")
    content=file.file.read(5*1024*1024+1)
    if len(content)>5*1024*1024: raise HTTPException(413,"Image must be 5 MB or smaller")
    valid={"image/jpeg":content.startswith(b"\xff\xd8\xff"),"image/png":content.startswith(b"\x89PNG\r\n\x1a\n"),"image/webp":len(content)>12 and content[:4]==b"RIFF" and content[8:12]==b"WEBP"}
    if not valid.get(file.content_type,False): raise HTTPException(415,"Image contents do not match the selected file type")
    ext={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}[file.content_type]
    name=re.sub(r"[^a-zA-Z0-9_]","_",(file.filename or "crop").rsplit(".",1)[0])[-60:]+ext
    path=f"uploads/{user.id}_{datetime.utcnow().timestamp():.0f}_{name}"
    with open(path,"wb") as f:f.write(content)
    return {"url":"/"+path,"storage":"local fallback"}

@app.get("/api/products")
def products(q:str|None=None, crop:str|None=None, district:str|None=None, organic:bool|None=None, urgent:bool=False,
             below_mandi:bool=False, buyer_location:str|None=None, sort:str="urgent",
             page:int=Query(1,ge=1), limit:int=Query(20,ge=1,le=100), db:Session=Depends(get_db)):
    query=db.query(m.Product).filter_by(status="active")
    if crop: query=query.filter(func.lower(m.Product.crop).contains(crop.lower()))
    if q: query=query.filter(or_(func.lower(m.Product.crop).contains(q.lower()),func.lower(m.Product.district).contains(q.lower()),func.lower(m.Product.village).contains(q.lower())))
    if district: query=query.filter(func.lower(m.Product.district).contains(district.lower()))
    if organic is not None: query=query.filter_by(organic=organic)
    items=query.all(); rows=[product_dict(p,db,buyer_location=buyer_location) for p in items]
    if urgent: rows=[x for x in rows if x["days_remaining"]<=3]
    if below_mandi: rows=[x for x in rows if x.get("mandi_ref") and x["mandi_ref"]["diff_per_kg"]<0]
    key={"price":"price_per_kg","risk":"risk_percent","newest":"id"}.get(sort)
    if key: rows.sort(key=lambda x:x[key],reverse=sort=="newest")
    elif sort=="nearest":
        rows.sort(key=lambda x:(x["distance_km"] is None, x["distance_km"] if x["distance_km"] is not None else 1e9, x["days_remaining"], -x["priority"]))
    elif sort=="best_price":
        def price_rank(x):
            ref=x.get("mandi_ref")
            if ref and ref.get("diff_percent") is not None:
                return (0, ref["diff_percent"], x["price_per_kg"])
            return (1, 0, x["price_per_kg"])
        rows.sort(key=price_rank)
    elif sort=="smart":
        def smart_rank(x):
            dist = x["distance_km"] if x["distance_km"] is not None else 250.0
            ref = x.get("mandi_ref")
            diff_pct = ref["diff_percent"] if ref and ref.get("diff_percent") is not None else 0.0
            return (round(dist * 0.6 + diff_pct * 1.2, 2), x["days_remaining"], -x["priority"])
        rows.sort(key=smart_rank)
    elif sort=="priority": rows.sort(key=lambda x:(x["priority"],-x["days_remaining"]),reverse=True)
    else: rows.sort(key=lambda x:(x["days_remaining"],-x["priority"]))
    total=len(rows); start=(page-1)*limit
    return {"items":rows[start:start+limit],"page":page,"limit":limit,"total":total}

@app.get("/api/products/urgent")
def urgent_products(db:Session=Depends(get_db)):
    return sorted([product_dict(p,db) for p in db.query(m.Product).filter_by(status="active").all()],key=lambda x:x["days_remaining"])[:100]

@app.get("/api/products/organic")
def organic_products(db:Session=Depends(get_db)):
    return [product_dict(p,db) for p in db.query(m.Product).filter_by(status="active",organic=True).all()]

@app.get("/api/products/{product_id}")
def product_detail(product_id:int,db:Session=Depends(get_db)):
    p=db.get(m.Product,product_id)
    if not p or p.status!="active": raise HTTPException(404,"Listing not found")
    return product_dict(p,db)

@app.get("/api/products/{product_id}/risk")
def risk(product_id:int,db:Session=Depends(get_db)):
    p=db.get(m.Product,product_id)
    if not p: raise HTTPException(404,"Listing not found")
    return estimate_risk(p)

@app.post("/api/products/{product_id}/risk/calculate")
def calculate_risk(product_id:int,user:m.User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.get(m.Product,product_id)
    if not p or (user.role=="farmer" and p.farmer_id!=user.id): raise HTTPException(404,"Listing not found")
    r=estimate_risk(p); db.add(m.ProductRiskAssessment(product_id=p.id,**{k:r[k] for k in ("risk_percent","days_remaining","status")},method="Crop planning window and harvest date; no sensor input")); db.commit(); return r

@app.get("/api/buyer/profile")
def buyer_profile(user:m.User=Depends(allow_roles("buyer")),db:Session=Depends(get_db)):
    p=db.query(m.BuyerProfile).filter_by(user_id=user.id).first(); return {"user":user.name,"business_name":p.business_name,"buyer_type":p.buyer_type,"location":p.location}

@app.post("/api/buyer/requirements")
def create_requirement(data:RequirementIn,user:m.User=Depends(allow_roles("buyer")),db:Session=Depends(get_db)):
    r=m.BuyerRequirement(buyer_id=user.id,**data.model_dump()); db.add(r); db.commit(); db.refresh(r); return {"id":r.id,**data.model_dump()}

@app.get("/api/buyer/requirements")
def get_requirements(user:m.User=Depends(allow_roles("buyer")),db:Session=Depends(get_db)):
    return [{"id":r.id,"crop":r.crop,"quantity_kg":r.quantity_kg,"min_quantity_kg":r.min_quantity_kg,"max_price_per_kg":r.max_price_per_kg,"location":r.location,"organic":r.organic,"active":r.active} for r in db.query(m.BuyerRequirement).filter_by(buyer_id=user.id).all()]

@app.put("/api/buyer/requirements/{requirement_id}")
def update_requirement(requirement_id:int,data:RequirementIn,user:m.User=Depends(allow_roles("buyer")),db:Session=Depends(get_db)):
    r=db.query(m.BuyerRequirement).filter_by(id=requirement_id,buyer_id=user.id).first()
    if not r: raise HTTPException(404,"Requirement not found")
    for k,v in data.model_dump().items():setattr(r,k,v)
    db.commit(); return {"id":r.id,**data.model_dump()}

@app.delete("/api/buyer/requirements/{requirement_id}")
def delete_requirement(requirement_id:int,user:m.User=Depends(allow_roles("buyer")),db:Session=Depends(get_db)):
    r=db.query(m.BuyerRequirement).filter_by(id=requirement_id,buyer_id=user.id).first()
    if not r: raise HTTPException(404,"Requirement not found")
    db.delete(r);db.commit();return {"message":"Requirement removed"}

@app.post("/api/matches/calculate")
def calculate_matches(requirement_id:int|None=None,user:m.User=Depends(allow_roles("buyer")),db:Session=Depends(get_db)):
    reqs=db.query(m.BuyerRequirement).filter_by(buyer_id=user.id,active=True)
    if requirement_id: reqs=reqs.filter_by(id=requirement_id)
    output=[]
    for r in reqs.all():
        for p in db.query(m.Product).filter_by(status="active",crop=r.crop).all():
            score,reasons=match_score(p,r); output.append({"requirement_id":r.id,"product":product_dict(p,db),"score":score,"reasons":reasons,"scoring":"Rule-based 100-point fit score; see reasons."})
    return sorted(output,key=lambda x:(-x["score"],x["product"]["days_remaining"]))

@app.get("/api/matches")
def matches(user:m.User=Depends(allow_roles("buyer")),db:Session=Depends(get_db)):
    return calculate_matches(None,user,db)

@app.post("/api/enquiries")
def create_enquiry(data:EnquiryIn,user:m.User=Depends(allow_roles("buyer")),db:Session=Depends(get_db)):
    p=db.get(m.Product,data.product_id)
    if not p or p.status!="active":raise HTTPException(404,"Listing not available")
    if data.requested_quantity_kg>p.quantity_kg:raise HTTPException(422,"Requested quantity exceeds available quantity")
    e=m.Enquiry(buyer_id=user.id,farmer_id=p.farmer_id,**data.model_dump());db.add(e);db.add(m.Notification(user_id=p.farmer_id,message=f"New enquiry for {p.crop}"));db.commit();db.refresh(e);return {"id":e.id,"status":e.status}

@app.get("/api/enquiries")
def enquiries(user:m.User=Depends(current_user),db:Session=Depends(get_db)):
    q=db.query(m.Enquiry)
    q=q.filter(m.Enquiry.farmer_id==user.id) if user.role=="farmer" else q.filter(m.Enquiry.buyer_id==user.id) if user.role=="buyer" else q
    return [{"id":e.id,"buyer_id":e.buyer_id,"farmer_id":e.farmer_id,"product_id":e.product_id,"quantity_kg":e.requested_quantity_kg,"offered_price_per_kg":e.offered_price_per_kg,"message":e.message,"status":e.status,"created_at":e.created_at.isoformat()} for e in q.order_by(m.Enquiry.created_at.desc()).all()]

@app.put("/api/enquiries/{enquiry_id}/status")
def set_enquiry_status(enquiry_id:int,data:StatusIn,user:m.User=Depends(current_user),db:Session=Depends(get_db)):
    valid={"pending","accepted","rejected","negotiating","deal confirmed","completed","cancelled"}
    if data.status not in valid:raise HTTPException(422,"Unknown enquiry status")
    e=db.get(m.Enquiry,enquiry_id)
    if not e or user.id not in (e.buyer_id,e.farmer_id) and user.role!="admin":raise HTTPException(404,"Enquiry not found")
    e.status=data.status
    if data.status=="deal confirmed":db.add(m.Transaction(enquiry_id=e.id,amount=(e.offered_price_per_kg or 0)*e.requested_quantity_kg))
    db.commit();return {"id":e.id,"status":e.status,"payment":"Not processed by Harvest Bridge"}

@app.get("/api/prices")
def prices(crop:str|None=None,db:Session=Depends(get_db)):
    q=db.query(m.MandiPrice)
    if crop:q=q.filter(func.lower(m.MandiPrice.crop)==crop.lower())
    return [{"crop":p.crop,"state":p.state,"district":p.district,"market":p.market,"minimum":p.minimum,"maximum":p.maximum,"modal":p.modal,"modal_per_kg":price_per_kg(p.modal,p.unit),"min_per_kg":price_per_kg(p.minimum,p.unit),"max_per_kg":price_per_kg(p.maximum,p.unit),"unit":p.unit,"market_date":str(p.market_date),"source":p.source,"sample":p.is_sample,"live":False} for p in q.order_by(m.MandiPrice.market_date.desc()).all()]

@app.get("/api/prices/crop/{crop_name}")
def price_crop(crop_name:str,db:Session=Depends(get_db)):return prices(crop_name,db)

@app.get("/api/prices/nearby")
def nearby_prices(state:str|None=None,db:Session=Depends(get_db)):
    q=db.query(m.MandiPrice)
    if state:q=q.filter(func.lower(m.MandiPrice.state)==state.lower())
    return [{"crop":p.crop,"market":p.market,"modal":p.modal,"unit":p.unit,"market_date":str(p.market_date),"source":p.source,"sample":p.is_sample} for p in q.all()]

@app.post("/api/admin/prices/import")
def import_price(data:PriceIn,user:m.User=Depends(allow_roles("admin")),db:Session=Depends(get_db)):
    if data.minimum>data.modal or data.modal>data.maximum:raise HTTPException(422,"Prices must satisfy minimum ≤ modal ≤ maximum")
    p=m.MandiPrice(**data.model_dump(),is_sample=False);db.add(p);db.add(m.AuditLog(actor_id=user.id,action="price_import",details=f"{data.crop}/{data.market}/{data.market_date}"));db.commit();return {"message":"Price recorded with provided source and market date"}

@app.get("/api/admin/dashboard")
def admin_dashboard(user:m.User=Depends(allow_roles("admin")),db:Session=Depends(get_db)):
    return {"farmers":db.query(m.User).filter_by(role="farmer").count(),"buyers":db.query(m.User).filter_by(role="buyer").count(),"active_listings":db.query(m.Product).filter_by(status="active").count(),"organic_listings":db.query(m.Product).filter_by(organic=True,status="active").count(),"enquiries":db.query(m.Enquiry).count(),"urgent_listings":sum(1 for p in db.query(m.Product).filter_by(status="active").all() if estimate_risk(p)["days_remaining"]<=2)}

@app.get("/api/admin/users")
def admin_users(user:m.User=Depends(allow_roles("admin")),db:Session=Depends(get_db)):
    return [{"id":u.id,"name":u.name,"role":u.role,"email":u.email,"phone":u.phone,"active":u.is_active} for u in db.query(m.User).all()]

@app.put("/api/admin/users/{user_id}/status")
def admin_user_status(user_id:int,data:StatusIn,user:m.User=Depends(allow_roles("admin")),db:Session=Depends(get_db)):
    target=db.get(m.User,user_id)
    if not target:raise HTTPException(404,"User not found")
    if data.status not in ("active","suspended"):raise HTTPException(422,"Status must be active or suspended")
    target.is_active=data.status=="active";db.add(m.AuditLog(actor_id=user.id,action="user_status",details=f"user={user_id} {data.status}"));db.commit();return {"id":target.id,"active":target.is_active}

@app.get("/api/admin/products")
def admin_products(user:m.User=Depends(allow_roles("admin")),db:Session=Depends(get_db)):
    return [product_dict(p,db) for p in db.query(m.Product).all()]

@app.put("/api/admin/products/{product_id}/priority")
def admin_priority(product_id:int,data:PriorityIn,user:m.User=Depends(allow_roles("admin")),db:Session=Depends(get_db)):
    p=db.get(m.Product,product_id)
    if not p:raise HTTPException(404,"Listing not found")
    p.priority=data.priority;db.add(m.AuditLog(actor_id=user.id,action="priority_update",details=f"product={product_id} priority={data.priority}"));db.commit();return {"id":p.id,"priority":p.priority,"reason":"Admin priority influences ranking among eligible listings only."}

@app.post("/api/admin/organic/verify")
def organic_verify(product_id:int,status:str,user:m.User=Depends(allow_roles("admin")),db:Session=Depends(get_db)):
    if status not in ("verified","rejected","pending"):raise HTTPException(422,"Invalid verification status")
    p=db.get(m.Product,product_id)
    if not p or not p.organic:raise HTTPException(404,"Organic listing not found")
    p.organic_status="Certified Organic" if status=="verified" else "Verification Pending" if status=="pending" else "Farmer-declared Organic"
    v=db.query(m.OrganicVerification).filter_by(product_id=product_id).first()
    if not v:v=m.OrganicVerification(product_id=product_id);db.add(v)
    v.status=status;v.reviewed_by=user.id;v.reviewed_at=datetime.utcnow();db.add(m.AuditLog(actor_id=user.id,action="organic_review",details=f"product={product_id} status={status}"));db.commit();return {"product_id":product_id,"status":status}

@app.get("/api/storage/{crop}")
def storage(crop:str):
    guidance={"tomato":"Keep shaded and avoid stacking damage.","potato":"Use cool, dark, ventilated storage.","onion":"Keep dry with good airflow.","beans":"Keep cool and handle gently."}
    return {"crop":crop,"guidance":guidance.get(crop.lower(),"Keep shaded, dry and well ventilated; check local crop guidance."),"temperature_range":"Not provided without validated local guidance","source":"General handling guidance; verify for your crop and conditions"}

@app.get("/api/weather")
def weather(location:str):
    if not os.getenv("OPENWEATHER_API_KEY"):return {"available":False,"location":location,"message":"Weather is unavailable until OPENWEATHER_API_KEY is configured."}
    return {"available":False,"location":location,"message":"Weather provider credentials exist, but live provider adapter is not enabled in this build."}

@app.get("/api/admin/health")
def admin_health(user:m.User=Depends(allow_roles("admin"))):return health()

@app.get("/api/notifications")
def notifications(user:m.User=Depends(current_user),db:Session=Depends(get_db)):
    return [{"id":n.id,"message":n.message,"read":n.read,"created_at":n.created_at.isoformat()} for n in db.query(m.Notification).filter_by(user_id=user.id).order_by(m.Notification.created_at.desc()).all()]

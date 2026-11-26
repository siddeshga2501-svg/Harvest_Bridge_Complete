import os
from datetime import date, timedelta
from app.database import Base, engine, SessionLocal
from app.models import User, FarmerProfile, BuyerProfile, AdminProfile, Product, BuyerRequirement, MandiPrice
from app.security import hash_password

SAMPLE_MANDI = [
    ("Tomato", "Karnataka", "Tumakuru", "Tumakuru APMC", 1900, 2600, 2300),
    ("Tomato", "Karnataka", "Bengaluru", "Yeshwanthpur APMC, Bengaluru", 2000, 2800, 2400),
    ("Onion", "Karnataka", "Mandya", "Mandya APMC", 2200, 3000, 2600),
    ("Potato", "Karnataka", "Mysuru", "Bandipalya APMC, Mysuru", 2000, 2700, 2400),
    ("Ragi", "Karnataka", "Bengaluru Rural", "Nelamangala APMC", 3400, 4200, 3800),
    ("Rice", "Karnataka", "Mandya", "Srirangapatna APMC", 3800, 4600, 4100),
    ("Maize", "Karnataka", "Mysuru", "Nanjangud APMC", 1800, 2400, 2100),
    ("Beans", "Karnataka", "Tumakuru", "Kunigal APMC", 4600, 5800, 5200),
    ("Chilli", "Karnataka", "Bengaluru Rural", "Doddaballapura APMC", 5200, 6800, 6000),
    ("Coconut", "Karnataka", "Tumakuru", "Tiptur APMC", 2600, 3300, 2900),
]

Base.metadata.create_all(bind=engine)
db=SessionLocal()
try:
    if db.query(User).count():
        print("Database already has users; seed skipped.")
    else:
        demo=[
          User(name="Ananya Demo Farm",email=None,phone="0000000001",role="farmer",password_hash=hash_password("2026"),language="en"),
          User(name="Kiran Demo Produce",email=None,phone="0000000002",role="farmer",password_hash=hash_password("2026"),language="kn"),
          User(name="Green Basket Demo",email="buyer@harvestbridge.demo",phone="0000000003",role="buyer",password_hash=hash_password("BuyerDemo!2026")),
          User(name="Market Link Demo",email="buyer2@harvestbridge.demo",phone="0000000004",role="buyer",password_hash=hash_password("BuyerDemo!2026")),
          User(name="Harvest Bridge Admin",email=os.getenv("ADMIN_EMAIL","admin@harvestbridge.demo"),role="admin",password_hash=hash_password(os.getenv("ADMIN_PASSWORD","HarvestDemo!2026"))),
          User(name="Cauvery Fresh Farm",email=None,phone="0000000005",role="farmer",password_hash=hash_password("2026"),language="kn"),
          User(name="Nandi Hills Growers",email=None,phone="0000000006",role="farmer",password_hash=hash_password("2026"),language="en"),
          User(name="Mysuru Mandi Hub",email="buyer3@harvestbridge.demo",phone="0000000007",role="buyer",password_hash=hash_password("BuyerDemo!2026")),
          User(name="Bengaluru Wholesale Co",email="buyer4@harvestbridge.demo",phone="0000000008",role="buyer",password_hash=hash_password("BuyerDemo!2026"))
        ]
        db.add_all(demo);db.flush()
        db.add_all([
          FarmerProfile(user_id=demo[0].id,village="Gubbi",district="Tumakuru",state="Karnataka"),
          FarmerProfile(user_id=demo[1].id,village="Maddur",district="Mandya",state="Karnataka"),
          FarmerProfile(user_id=demo[5].id,village="Bannur",district="Mysuru",state="Karnataka"),
          FarmerProfile(user_id=demo[6].id,village="Devanahalli",district="Bengaluru Rural",state="Karnataka"),
          BuyerProfile(user_id=demo[2].id,business_name="Green Basket Demo",location="Kyathsandra, Tumakuru, Karnataka"),
          BuyerProfile(user_id=demo[3].id,business_name="Market Link Demo",location="Srirangapatna, Mandya, Karnataka"),
          BuyerProfile(user_id=demo[7].id,business_name="Mysuru Mandi Hub",location="Bandipalya APMC, Mysuru, Karnataka"),
          BuyerProfile(user_id=demo[8].id,business_name="Bengaluru Wholesale Co",location="Yeshwanthpur APMC, Bengaluru, Karnataka")
        ])
        db.add(AdminProfile(user_id=demo[4].id))
        farmers=[demo[0].id, demo[1].id, demo[5].id, demo[6].id]
        crops=[
          ("Tomato",420,18,5,True,"Farmer-declared Organic",0,"Gubbi","Tumakuru"),
          ("Onion",900,24,9,False,"Conventional",1,"Maddur","Mandya"),
          ("Potato",650,21,4,False,"Conventional",2,"Bannur","Mysuru"),
          ("Ragi",1200,36,12,False,"Conventional",3,"Nelamangala","Bengaluru Rural"),
          ("Rice",800,42,7,False,"Conventional",1,"Srirangapatna","Mandya"),
          ("Maize",700,19,6,False,"Conventional",2,"Nanjangud","Mysuru"),
          ("Beans",160,48,2,True,"Verification Pending",0,"Kunigal","Tumakuru"),
          ("Chilli",250,55,8,False,"Conventional",3,"Doddaballapura","Bengaluru Rural"),
          ("Coconut",300,28,10,False,"Conventional",0,"Tiptur","Tumakuru")
        ]
        for crop,qty,price,age,organic,status,f_idx,village,district in crops:
            db.add(Product(farmer_id=farmers[f_idx],crop=crop,quantity_kg=qty,price_per_kg=price,harvest_date=date.today()-timedelta(days=age),pickup_date=date.today()+timedelta(days=2),organic=organic,organic_status=status,quality="Good",village=village,district=district,state="Karnataka",description="Fictional demonstration listing. Prices are seller-entered, not mandi data."))
        db.add_all([
          BuyerRequirement(buyer_id=demo[2].id,crop="Tomato",quantity_kg=300,min_quantity_kg=200,max_price_per_kg=25,quality="Good",location="Tumakuru"),
          BuyerRequirement(buyer_id=demo[3].id,crop="Beans",quantity_kg=100,min_quantity_kg=50,max_price_per_kg=60,organic=True,location="Mandya"),
          BuyerRequirement(buyer_id=demo[7].id,crop="Potato",quantity_kg=400,min_quantity_kg=150,max_price_per_kg=26,quality="Good",location="Mysuru"),
          BuyerRequirement(buyer_id=demo[8].id,crop="Ragi",quantity_kg=600,min_quantity_kg=300,max_price_per_kg=40,quality="Good",location="Bengaluru")
        ])
        for crop,state,district,market,low,high,modal in SAMPLE_MANDI:
            db.add(MandiPrice(crop=crop,state=state,district=district,market=market,minimum=low,maximum=high,modal=modal,unit="INR/quintal",market_date=date.today()-timedelta(days=1),source="Sample Karnataka APMC Reference",is_sample=True))
        db.commit();print("Demo accounts and fictional marketplace listings created.")
finally:
    db.close()

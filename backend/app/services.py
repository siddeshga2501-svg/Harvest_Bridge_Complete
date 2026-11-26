import math
import re
from datetime import date
from sqlalchemy import func
from .models import Product, BuyerRequirement, MandiPrice

# Illustrative planning windows, not measured spoilage. Administrators can extend this table.
SHELF_DAYS = {"tomato": 7, "onion": 35, "potato": 45, "ragi": 180, "rice": 180,
              "maize": 90, "beans": 5, "chilli": 14, "coconut": 30, "spinach": 3, "leafy greens": 3}

# Approximate locality centroids for distance prioritization across Karnataka hubs & nearby villages.
LOCALITY_COORDS = {
    "tumakuru": (13.3392, 77.1140), "tumkur": (13.3392, 77.1140), "tumukuru": (13.3392, 77.1140),
    "gubbi": (13.3119, 76.9408), "kunigal": (13.0258, 77.0249), "tiptur": (13.2563, 76.4777),
    "kyathsandra": (13.3168, 77.1520), "nagavalli": (13.2660, 77.0680), "sira": (13.7414, 76.9042),
    "koratagere": (13.5236, 77.2377), "turuvekere": (13.1625, 76.6669), "madhugiri": (13.6627, 77.2111),
    "mandya": (12.5218, 76.8951), "maddur": (12.5844, 77.0439), "srirangapatna": (12.4237, 76.6829),
    "pandavapura": (12.4942, 76.6708), "malavalli": (12.3853, 77.0587), "nagamangala": (12.8213, 76.7544),
    "krishnarajpet": (12.6606, 76.4910),
    "mysuru": (12.2958, 76.6394), "mysore": (12.2958, 76.6394), "bandipalya": (12.2496, 76.6656),
    "bannur": (12.3338, 76.8606), "nanjangud": (12.1190, 76.6820), "hunsur": (12.3065, 76.2882),
    "t narasipura": (12.2121, 76.9019), "periyapatna": (12.3364, 76.0987), "yelwal": (12.3578, 76.5442),
    "bengaluru": (12.9716, 77.5946), "bangalore": (12.9716, 77.5946), "bengaluru rural": (13.2473, 77.7136),
    "yeshwanthpur": (13.0285, 77.5409), "devanahalli": (13.2473, 77.7136), "nelamangala": (13.0992, 77.3937),
    "doddaballapura": (13.2957, 77.5378), "hoskote": (13.0707, 77.7982), "magadi": (12.9571, 77.2266),
    "ramanagara": (12.7150, 77.2813), "kanakapura": (12.5462, 77.4199), "channapatna": (12.6518, 77.2067),
    "yelahanka": (13.1007, 77.5963), "kengeri": (12.9177, 77.4833),
}

def resolve_coords(location_text: str | None) -> tuple[float, float] | None:
    """Resolve 'lat,lng' coordinates or a known Karnataka locality/district string."""
    if not location_text:
        return None
    text = location_text.strip()
    coord_match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", text)
    if coord_match:
        return float(coord_match.group(1)), float(coord_match.group(2))
    normalized = re.sub(r"[^a-z0-9,\s]", " ", text.lower())
    parts = [re.sub(r"\s+", " ", p).strip() for p in normalized.split(",") if p.strip()]
    for part in parts:
        if part in LOCALITY_COORDS:
            return LOCALITY_COORDS[part]
        for token in part.split():
            if token in LOCALITY_COORDS:
                return LOCALITY_COORDS[token]
    for key, coords in LOCALITY_COORDS.items():
        if key in normalized:
            return coords
    return None

def estimate_distance_km(origin_text: str | None, dest_text: str | None) -> float | None:
    """Calculate approximate Haversine distance in kilometers between two locations."""
    origin = resolve_coords(origin_text)
    dest = resolve_coords(dest_text)
    if not origin or not dest:
        return None
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, dest)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)

def price_per_kg(value: float, unit: str) -> float:
    """Convert mandi price units (e.g. INR/quintal) to INR per kg."""
    return round(value / 100.0, 2) if "quintal" in (unit or "").lower() else round(value, 2)

def mandi_comparison(product: Product, db) -> dict | None:
    """Find the closest matching dated mandi record for a crop and compare asking price."""
    if not db:
        return None
    records = (
        db.query(MandiPrice)
        .filter(func.lower(MandiPrice.crop) == product.crop.lower())
        .order_by(MandiPrice.market_date.desc(), MandiPrice.id.desc())
        .all()
    )
    if not records:
        return None
    p_dist = (product.district or "").strip().lower()
    p_state = (product.state or "").strip().lower()
    ref = next((r for r in records if p_dist and p_dist in (r.district or "").lower()), None)
    if not ref:
        ref = next((r for r in records if p_state and p_state == (r.state or "").lower()), records[0])
    modal_kg = price_per_kg(ref.modal, ref.unit)
    min_kg = price_per_kg(ref.minimum, ref.unit)
    max_kg = price_per_kg(ref.maximum, ref.unit)
    diff_kg = round(product.price_per_kg - modal_kg, 2)
    diff_pct = round((diff_kg / modal_kg) * 100, 1) if modal_kg > 0 else None
    status = "near"
    if diff_pct is not None:
        if diff_pct <= -5:
            status = "below"
        elif diff_pct > 5:
            status = "above"
    return {
        "market": ref.market,
        "district": ref.district,
        "modal_per_kg": modal_kg,
        "min_per_kg": min_kg,
        "max_per_kg": max_kg,
        "unit": ref.unit,
        "market_date": str(ref.market_date),
        "source": ref.source,
        "sample": ref.is_sample,
        "diff_per_kg": diff_kg,
        "diff_percent": diff_pct,
        "status": status,
    }

def estimate_risk(product: Product):
    shelf = SHELF_DAYS.get(product.crop.lower(), 10)
    elapsed = max(0, (date.today() - product.harvest_date).days)
    remaining = max(0, shelf - elapsed)
    risk = min(100, round(elapsed / shelf * 100))
    label = "Critical urgency" if remaining <= 1 else "High risk" if risk >= 70 else "Moderate risk" if risk >= 35 else "Low risk"
    return {"risk_percent": risk, "days_remaining": remaining, "status": label,
            "disclaimer": "Planning estimate based on crop and harvest date; it does not measure freshness or prove spoilage."}

def match_score(product: Product, requirement: BuyerRequirement):
    score, reasons = 20, ["Crop matches"]
    if product.quantity_kg >= requirement.min_quantity_kg:
        score += 15; reasons.append("Meets minimum quantity")
    elif product.quantity_kg >= requirement.quantity_kg * .5:
        score += 8; reasons.append("Part of requested quantity available")
    if requirement.location and requirement.location.lower() in f"{product.village} {product.district} {product.state}".lower():
        score += 15; reasons.append("Location matches")
    if requirement.max_price_per_kg is None or product.price_per_kg <= requirement.max_price_per_kg:
        score += 15; reasons.append("Within buyer price limit")
    if requirement.quality == "Any" or requirement.quality.lower() == product.quality.lower():
        score += 10; reasons.append("Quality preference matches")
    if not requirement.pickup_by or not product.pickup_date or product.pickup_date <= requirement.pickup_by:
        score += 10; reasons.append("Pickup date is suitable")
    if not requirement.organic or product.organic:
        score += 5; reasons.append("Organic preference matches")
    risk = estimate_risk(product)
    score += 10 if risk["days_remaining"] <= 2 else 5 if risk["days_remaining"] <= 5 else 0
    if risk["days_remaining"] <= 5: reasons.append("Urgent lot prioritized")
    return min(100, score), reasons

def product_dict(p: Product, db=None, buyer_location: str | None = None):
    from .models import User, FarmerProfile
    risk = estimate_risk(p)
    farmer = db.get(User, p.farmer_id) if db else None
    profile = db.query(FarmerProfile).filter_by(user_id=p.farmer_id).first() if db else None
    phone = farmer.phone if farmer and p.phone_visible and profile and profile.show_phone else None
    listing_place = ", ".join(x for x in (p.village, p.district, p.state) if x)
    distance_km = estimate_distance_km(buyer_location, listing_place) if buyer_location and listing_place else None
    mandi_ref = mandi_comparison(p, db)
    return {"id":p.id,"farmer_id":p.farmer_id,"farmer_name":farmer.name if farmer else "Farmer",
      "phone":phone,"crop":p.crop,"category":p.category,"quantity_kg":p.quantity_kg,"price_per_kg":p.price_per_kg,
      "harvest_date":str(p.harvest_date),"pickup_date":str(p.pickup_date) if p.pickup_date else None,"quality":p.quality,
      "organic":p.organic,"organic_status":p.organic_status,"image_url":p.image_url,"village":p.village,
      "district":p.district,"state":p.state,"description":p.description,"status":p.status,"priority":p.priority,
      "distance_km":distance_km,"mandi_ref":mandi_ref,**risk}

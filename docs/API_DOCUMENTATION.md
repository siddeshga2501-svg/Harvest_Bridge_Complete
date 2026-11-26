# Harvest Bridge API

Interactive OpenAPI documentation: `GET /docs`. Routes are under `/api`.

## Authentication

- `POST /api/auth/register`: farmer/buyer only; farmers register with mobile OTP verification + 4-digit PIN (plus village/district/state); buyers register with name, email, optional phone/district, and 10+ character password. Returns bearer JWT, refresh token, and user object including `location`.
- `POST /api/auth/login`: `{ "username": "email or phone", "password": "...", "pin": "4 digits for farmer" }`; returns bearer JWT, role, and `location`.
- `POST /api/auth/otp/request`, `POST /api/auth/otp/verify`, `POST /api/auth/pin/recover`: mobile OTP verification and PIN recovery.
- `POST /api/auth/logout`: stateless-token acknowledgement; client clears token locally.
- `POST /api/auth/refresh`: valid refresh JWT to fresh JWT.
- `POST /api/auth/forgot-password`: safe generic response; message delivery is not configured.
- `GET /api/me`: current account including resolved `location`.

Send `Authorization: Bearer <access_token>` for protected operations. Tokens expire per `ACCESS_TOKEN_MINUTES` (default 60). Admin is configured/seeded, never publicly registered.

## Marketplace and farmer

- `GET /api/products?q=&crop=&district=&organic=&urgent=&below_mandi=&buyer_location=&sort=&page=&limit=`; `sort` supports `urgent` (default), `nearest` (closest `distance_km` first), `best_price` (largest % below mandi modal first), `smart` (combined distance + price vs mandi), `price`, `risk`, `newest`, `priority`. Each item includes `distance_km` (when `buyer_location` resolves) and `mandi_ref` comparison when a dated mandi record exists.
- `GET /api/products/{id}`, `/urgent`, `/organic`.
- `GET/POST /api/farmer/products`; `PUT/DELETE /api/farmer/products/{id}`.
- `PATCH /api/farmer/products/{id}/price`: update asking `price_per_kg` and return refreshed `mandi_ref` comparison.
- `POST /api/farmer/products/{id}/status`: `active`, `paused`, `sold`.
- `POST /api/uploads/image`: authenticated JPG/PNG/WebP, up to 5 MB; local disk fallback.
- `GET /api/products/{id}/risk`, `POST .../risk/calculate`.
- `GET /api/storage/{crop}`: general guidance with source limitations.

## Buyer and matching

- `POST/GET /api/buyer/requirements`, `PUT/DELETE /api/buyer/requirements/{id}`.
- `GET /api/matches`, `POST /api/matches/calculate?requirement_id=`: deterministic score out of 100 and reason list.
- `POST /api/enquiries`: buyer enquiry with product, quantity, optional offer and message.
- `GET /api/enquiries`: own records; admin can inspect all.
- `PUT /api/enquiries/{id}/status`: participant/admin update. `deal confirmed` records an unpaid deal amount; it does not process payment.
- `GET /api/notifications`: current account notifications.

## Prices and admin

- `GET /api/prices?crop=`, `/api/prices/crop/{name}`, `/api/prices/nearby?state=` return stored records with source, market date, unit, `modal_per_kg`/`min_per_kg`/`max_per_kg` conversions, and sample flag.
- `POST /api/admin/prices/import`: admin dated record entry; verifies minimum ≤ modal ≤ maximum.
- `GET /api/admin/dashboard`, `/users`, `/products`; `PUT /api/admin/users/{id}/status`; `PUT /api/admin/products/{id}/priority`; `POST /api/admin/organic/verify?product_id=&status=`.
- `GET /api/health`: DB and optional integration config status. `GET /api/weather?location=` reports unavailable until live adapter is enabled.

Asking prices are INR/kg entered by sellers. Mandi prices preserve the source unit (default INR/quintal) and provide `/kg` conversions (`÷ 100` for quintals) for transparent comparison. Demo prices are seller-entered, and seeded APMC records are marked `sample: true`. Pydantic validates request data and SQLAlchemy parameterizes database queries.

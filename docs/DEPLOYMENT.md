# Deployment guide

## 1. PostgreSQL

Create managed PostgreSQL and copy its SQLAlchemy URL in `postgresql+psycopg://` form. Keep it only in backend environment settings. Apply schema with `alembic upgrade head` from `backend/`; optionally run `python seed.py` for demo accounts.

## 2. API on Render

Create a web service with root `backend`, build command `pip install -r requirements.txt`, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set `DATABASE_URL`, long random `SECRET_KEY`, exact `FRONTEND_ORIGINS`, and optional `ACCESS_TOKEN_MINUTES`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`. Health check `/api/health`; docs `/docs`. Local image uploads are not durable on ephemeral hosts; use durable configured storage before public uploads.

## 3. Frontend on Vercel

Set project root to `frontend`, framework Vite, build `npm run build`, and `VITE_API_URL` to the API HTTPS origin (no trailing slash). Keep secret provider keys out of frontend settings.

## 4. Optional integrations

Only use authorized credentials. Cloudinary variables are reserved for durable image storage; this release uses validated local uploads. `OPENWEATHER_API_KEY` is reported but a live weather adapter is not enabled. `AGMARKNET_API_URL` and `AGMARKNET_API_KEY` are configuration slots only; no live sync is claimed. Admin-imported prices must retain correct source and market date. SMS automation and payment processing are not connected. Phone links open the user's dialer when contact is shown, and the Google Maps distance button opens driving directions between the buyer/viewer locality and the farm locality.

Browser speech varies by browser; text entry is always available (Microsoft Edge includes online Kannada and Hindi speech voices out of the box).

## 5. Verify deployment

1. Open `/api/health`, verify DB readiness, then `/docs`.
2. Check `FRONTEND_ORIGINS` exactly matches the deployed website.
3. Confirm a non-admin receives 403 for admin endpoints.
4. Create a test listing, search as a buyer, send an enquiry and respond as farmer.
5. Verify source/date labels on every stored mandi record.
6. Remove demo users and rotate credentials before public use.

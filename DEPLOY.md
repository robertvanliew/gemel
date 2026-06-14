# Deploying GEMEL online

GEMEL is a stateful Python app: it serves the dashboard, reads live market data,
and **writes your journal to a SQLite database** (`gemel.db`). To host it so your
journal survives restarts, you need a platform with a **persistent volume**.

> **Why not Vercel?** Vercel runs serverless functions on a read-only, ephemeral
> filesystem — the journal can't be created or saved there, and the data libraries
> (pandas/pyarrow) exceed its size limit. It's the wrong tool for this app.
>
> **Why not Render's free tier?** Free Render services also have an ephemeral
> filesystem and **cannot attach a disk**, so your journal would reset on every
> restart. Render works only on a *paid* instance with a disk.

The journal can live in one of two places:

- **Postgres** — set `DATABASE_URL` and the server is stateless, so it runs on a
  **free** host (Render free tier + a free Neon database). This is Option A.
- **SQLite on a mounted volume** — set `DATA_DIR`; needs a paid host with a disk
  (Railway/Render paid). This is Option B.

No market-data key is required — it defaults to **yfinance**. Set Alpaca keys only
if you prefer that source (more reliable from a datacenter IP).

---

## Option A — Free: Render (free web service) + Neon (free Postgres)

Zero cost. The web service sleeps after ~15 min idle and takes ~1 min to wake on
the next visit, then it's fast — fine for a personal tool.

### 1. Create the free Postgres (Neon)
1. Sign up at **neon.tech** (free tier, no card).
2. Create a project → it gives you a **connection string** that looks like
   `postgresql://user:pass@ep-xxxx.neon.tech/dbname?sslmode=require`.
3. Copy it — that's your `DATABASE_URL`. (The app rewrites it to use the psycopg3
   driver automatically; just paste it as-is.)

### 2. Create the free web service (Render)
1. Sign in at **render.com** with GitHub.
2. **New → Web Service →** connect `robertvanliew/gemel`.
   - Render reads `render.yaml`/`Dockerfile`. Runtime **Docker**, plan **Free**.
3. **Environment →** add one variable:
   - `DATABASE_URL` = *(the Neon string from step 1)*
   - *(optional)* `ACCOUNT_SIZE = 35000`, or `DATA_SOURCE=alpaca` + Alpaca keys
4. **Create Web Service.** First build takes a few minutes (installing pandas/
   numpy). When it's live you get an `https://gemel-xxxx.onrender.com` URL.
5. Open it — the LIVE bar turns green once data loads. Trades now save to Neon and
   persist across restarts/redeploys. Every `git push` auto-deploys.

> No persistent disk is involved here, so Render's free tier is fine — the journal
> lives in Neon, not on the server's filesystem.

---

## Option B — Railway (~$5/mo, always-on, SQLite on a volume)

Railway's Hobby plan is $5/mo and includes $5 of usage credit; a 1 GB volume for
the journal costs only a few cents on top, well inside the credit.

1. Sign in at **railway.com** with GitHub.
2. **New Project → Deploy from GitHub repo →** pick `robertvanliew/gemel`.
   Railway detects the `Dockerfile` automatically.
3. Open the service → **Variables** and confirm/add:
   - `DATA_DIR = /data`  (the Dockerfile already sets this, but make it explicit)
   - *(optional)* `ACCOUNT_SIZE = 35000` to tune the 2% max-loss cap
   - *(optional)* `DATA_SOURCE = alpaca` + `ALPACA_API_KEY` + `ALPACA_SECRET_KEY`
     if you want Alpaca instead of yfinance
4. **Storage → Add Volume**, mount path **`/data`** (size 1 GB is plenty). This is
   what makes the journal persist.
5. **Settings → Networking → Generate Domain** to get a public `*.up.railway.app`
   URL. Railway provides `$PORT`; the Dockerfile already binds to it.
6. Deploy. Open the URL — the LIVE bar turns green once `/api/status` responds.

Redeploys on every `git push` to `master` are automatic.

## Option C — Render paid (always-on, SQLite on a disk)

1. **render.com → New → Web Service →** connect `robertvanliew/gemel`.
2. Runtime **Docker** (it reads the `Dockerfile`).
3. Choose a **paid** instance type (free tier can't keep a disk).
4. **Disks → Add Disk**, mount path **`/data`**, 1 GB.
5. **Environment →** add `DATA_DIR = /data`.
6. Create the service; Render gives you an `*.onrender.com` URL.

## Option D — Fly.io

`fly launch` (detects the Dockerfile) → `fly volumes create gemel_data --size 1`
→ in `fly.toml` add a `[mounts]` entry `source = "gemel_data"`,
`destination = "/data"` → `fly deploy`.

---

## Notes

- **Postgres vs SQLite:** when `DATABASE_URL` is set the app uses Postgres and
  ignores `DATA_DIR`; otherwise it uses a local SQLite file. Locally (and in the
  tests) nothing changes — no `DATABASE_URL`, plain SQLite.
- **yfinance from a datacenter IP** is occasionally rate-limited by Yahoo. If the
  hosted app shows stale/empty data, switch `DATA_SOURCE` to `alpaca` with keys.
- The hosted journal is separate from any local `gemel.db` you run via `run.bat`.
  There is no login — treat the public URL as semi-private.

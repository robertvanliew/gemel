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

The app reads `DATA_DIR` and stores `gemel.db` there. Point it at a mounted volume
and your trades persist. No secrets are required — it defaults to **yfinance** (no
API key). Set Alpaca keys only if you prefer that data source.

---

## Option A — Railway (recommended, ~$5/mo)

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

## Option B — Render (paid instance required for persistence)

1. **render.com → New → Web Service →** connect `robertvanliew/gemel`.
2. Runtime **Docker** (it reads the `Dockerfile`).
3. Choose a **paid** instance type (free tier can't keep a disk).
4. **Disks → Add Disk**, mount path **`/data`**, 1 GB.
5. **Environment →** add `DATA_DIR = /data`.
6. Create the service; Render gives you an `*.onrender.com` URL.

## Option C — Fly.io

`fly launch` (detects the Dockerfile) → `fly volumes create gemel_data --size 1`
→ in `fly.toml` add a `[mounts]` entry `source = "gemel_data"`,
`destination = "/data"` → `fly deploy`.

---

## Notes

- **A truly-free, persistent setup** is possible by swapping SQLite for a free
  managed Postgres (e.g. Neon/Supabase) and running the web service on a free
  tier — but that's extra wiring. Ask if you want that path.
- **yfinance from a datacenter IP** is occasionally rate-limited by Yahoo. If the
  hosted app shows stale/empty data, switch `DATA_SOURCE` to `alpaca` with keys.
- **Delete the failed Vercel project** so it stops trying (and failing) to build
  on every push.
- The journal on the server is separate from any local `gemel.db` you run via
  `run.bat`. There is no login — treat the public URL as semi-private.

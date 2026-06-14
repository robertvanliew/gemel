# GEMEL — container image for hosting the read-only dashboard + API.
# The journal DB lives on a mounted volume at /data (DATA_DIR) so saved trades
# survive restarts and redeploys.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

# Install Python deps. build-essential is a fallback for any package without a
# prebuilt wheel; it is purged afterward to keep the image small.
COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Persistent journal lives here — mount a volume at /data on your host.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# $PORT is injected by most hosts (Render/Railway/Fly); default 8000 locally.
CMD ["sh", "-c", "uvicorn gemel_server:app --host 0.0.0.0 --port ${PORT:-8000}"]

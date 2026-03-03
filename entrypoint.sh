#!/bin/sh
set -e

# Vänta tills DB är redo
python - <<'PY'
import os, time
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
engine = create_engine(url, pool_pre_ping=True)

for _ in range(40):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("DB is ready")
        break
    except Exception as e:
        print("Waiting for DB...", e)
        time.sleep(2)
else:
    raise SystemExit("DB not ready in time")
PY

# Skapa tabeller
python -c "from app.database.database import ensure_db; ensure_db()"

# Starta API
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
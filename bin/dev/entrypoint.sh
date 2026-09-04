#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
python - <<'PY'
import os, time
import psycopg

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
user = os.environ.get("POSTGRES_USER", "citypoint")
password = os.environ.get("POSTGRES_PASSWORD", "citypoint")
dbname = os.environ.get("POSTGRES_DB", "citypoint")

for attempt in range(60):
    try:
        with psycopg.connect(
            host=host, port=port, user=user, password=password, dbname=dbname
        ):
            print("PostgreSQL is ready")
            break
    except Exception as exc:
        print(f"PostgreSQL not ready ({attempt + 1}/60): {exc}")
        time.sleep(2)
else:
    raise SystemExit("PostgreSQL did not become ready")
PY

python manage.py makemigrations --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput || true

if [ "${SEED_DEMO:-1}" = "1" ]; then
  python manage.py seed_demo
fi

exec python manage.py runserver 0.0.0.0:8000

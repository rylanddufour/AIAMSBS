FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py /app/server.py
COPY init_db.sql /app/init_db.sql

# Prepare the data directory and ensure DB_PATH is a known, mountable location.
RUN mkdir -p /data

EXPOSE 8002

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8002"]

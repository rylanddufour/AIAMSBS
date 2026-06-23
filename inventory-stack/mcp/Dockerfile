FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py /app/server.py
COPY init_db.sql /app/init_db.sql

# Add nmap installation
RUN apt-get update && apt-get install -y --no-install-recommends nmap && apt-get clean && rm -rf /var/lib/apt/lists/*

EXPOSE 8001
EXPOSE 8002

# Use 0.0.0.0 to bind to all interfaces
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8001"]
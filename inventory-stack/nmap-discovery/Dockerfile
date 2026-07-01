FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install nmap binary for the discovery scan
RUN apt-get update && \
    apt-get install -y --no-install-recommends nmap && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY server.py /app/server.py

CMD ["python", "server.py", "--host", "127.0.0.1", "--port", "8003"]
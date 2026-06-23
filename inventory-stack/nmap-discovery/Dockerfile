FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install nmap
RUN apt-get update && \
    apt-get install -y nmap && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY server.py /app/server.py

EXPOSE 8002

# Use 0.0.0.0 to bind to all interfaces
CMD ["python", "server.py"]
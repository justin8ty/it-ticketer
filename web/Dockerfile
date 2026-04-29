FROM python:3.11-slim

WORKDIR /app

# System deps (optional: for better TLS / builds)
RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates   && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8080
CMD ["python", "main.py"]

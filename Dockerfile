# Stage 1: Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Installa dipendenze di sistema
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia e installa dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production stage  
FROM python:3.11-slim

WORKDIR /app

# Installa solo curl per runtime
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Crea utente non-root per sicurezza
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copia dipendenze installate
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copia codice applicazione e file .env
COPY app.py .

# Cambia ownership dei file
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 7860

# Usa Gunicorn per produzione
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "4", "--threads", "2", "--timeout", "120", "--worker-class", "gthread", "app:app"]

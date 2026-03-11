FROM python:3.11-slim

WORKDIR /app

# Minimal system deps — no build-essential needed without PyTorch
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# No model pre-download step — embeddings are API calls to Google
# Docker image: ~400MB. Cold start: instant.

COPY app.py analysis.py ingestion.py projects.py ./
COPY templates/ ./templates/

ENV PYTHONUNBUFFERED=1 \
    PORT=7860

EXPOSE 7860

# Hugging Face Spaces runs as non-root user 1000
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER 1000

CMD uvicorn app:app --host 0.0.0.0 --port ${PORT}

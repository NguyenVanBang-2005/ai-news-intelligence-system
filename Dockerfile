FROM python:3.12-slim

# Same default as Settings.embedding_model_name in app/core/config.py; override with
# --build-arg EMBEDDING_MODEL_NAME=... when .env uses another model.
ARG EMBEDDING_MODEL_NAME=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC HF_HOME=/opt/hf-cache
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image (own layer, before the app code, so code
# changes do not re-download it). compose.yaml sets HF_HUB_OFFLINE=1 at runtime.
RUN python -c "import sys; from sentence_transformers import SentenceTransformer; SentenceTransformer(sys.argv[1])" "$EMBEDDING_MODEL_NAME"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

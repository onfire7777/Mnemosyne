# Mnemosyne embedding + cross-encoder reranker service.
#
# Builds the REAL model path (FastAPI + torch + sentence-transformers). The
# service also runs without these deps via the stdlib fallback, but the image
# ships the production stack.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EMBEDDING_SERVICE_HOST=0.0.0.0 \
    EMBEDDING_SERVICE_PORT=8000 \
    EMBEDDING_SERVICE_DIMS=1024 \
    HF_HOME=/models

WORKDIR /app

COPY requirements.txt ./
# CPU wheel index: default aarch64/x86 torch wheels bundle multi-GB CUDA deps this
# CPU-only service never uses.
RUN pip install --upgrade pip \
    && pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY app.py selftest.py ./

EXPOSE 8000

# Hermetic, offline contract check at build time (forces deterministic fallback).
RUN EMBEDDING_SERVICE_FORCE_FALLBACK=1 python selftest.py

# Bake the real models into the image so the container can run on an
# egress-free network (read-only rootfs friendly; no runtime downloads).
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('BAAI/bge-small-en-v1.5'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')" \
    && chmod -R a+rX /models

# Non-root runtime (matches the hardened compose profile).
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin embedder
USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,os,sys; \
u='http://127.0.0.1:%s/health' % os.environ.get('EMBEDDING_SERVICE_PORT','8000'); \
sys.exit(0 if urllib.request.urlopen(u, timeout=5).status==200 else 1)"

CMD ["python", "app.py"]

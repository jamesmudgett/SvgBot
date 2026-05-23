# CPU-only backend image used by DigitalOcean App Platform (default deploy).
# StarVector is not installed here; it requires a CUDA GPU which App Platform
# does not provide. With STARVECTOR_ENABLED=false the orchestrator runs
# VTracer / VTracer-smooth / VTracer-mono only, which is fully CPU-capable.
#
# For GPU deploys (Droplet, GPU k8s) use docker/Dockerfile.cuda instead.

# Pinned to Bookworm (Debian 12) instead of the floating `-slim` tag, which
# now resolves to Trixie (Debian 13). Trixie renamed `libgdk-pixbuf2.0-0` to
# `libgdk-pixbuf-2.0-0`, breaking the apt install below. Bookworm is the
# Python project's default base through Dec 2028.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime libs: cairosvg / svglib / reportlab need cairo + pango + pixbuf.
# `libgdk-pixbuf2.0-0` is the Bookworm spelling (renamed to
# `libgdk-pixbuf-2.0-0` on Trixie, which is why we pin -bookworm above).
#
# Build deps: pycairo (pulled in transitively by svglib -> rlpycairo) has
# no Linux wheel on PyPI and must be source-built via meson. That needs a
# C toolchain (build-essential), the cairo development headers
# (libcairo2-dev), pkg-config for meson's cairo probe, and Python.h
# (python3-dev) for the pycairo extension module. Without these, pip
# fails at "Unknown compiler(s)" or "Package cairo was not found".
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0 \
        libgl1 libglib2.0-0 \
        build-essential libcairo2-dev pkg-config python3-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU-only torch FIRST from the PyTorch CPU index. requirements.txt
# pulls torch as a transitive dep; without this step pip resolves the default
# CUDA wheel (~2 GB) which both wastes build time and exceeds App Platform's
# image size limit.
RUN pip install --index-url https://download.pytorch.org/whl/cpu \
        "torch>=2.2.0" "torchvision>=0.17.0"

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

ENV PYTHONPATH=/app \
    STARVECTOR_ENABLED=false

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

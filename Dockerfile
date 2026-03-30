# ===============================
# Stage 1: Builder
# ===============================
FROM python:3.10-slim AS builder

WORKDIR /app

# Build dependencies (chỉ thứ cần)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements FIRST (để cache pip)
COPY requirements.txt .

# Upgrade pip once (không đổi version lib)
RUN pip install --upgrade pip setuptools wheel

# Install other deps
RUN pip install --no-cache-dir -r requirements.txt


# ===============================
# Stage 2: Runtime
# ===============================
FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/opt/venv/bin:$PATH"

# Runtime system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libreoffice-writer \
    libreoffice-java-common \
    default-jre \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Copy venv (cache tốt nhất)
COPY --from=builder /opt/venv /opt/venv

# Copy source code LAST (chỉ sửa code → build cực nhanh)
COPY src ./src
COPY app.py .
COPY run_worker.py .

# Create dirs & user
RUN mkdir -p uploads logs storage && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ || exit 1

CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--threads", "8", \
     "--timeout", "600", \
     "--keep-alive", "120", \
     "--worker-class", "gthread", \
     "--preload", \
     "--log-level", "info", \
     "app:app"]

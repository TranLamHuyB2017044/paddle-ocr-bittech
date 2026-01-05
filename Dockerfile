# ===============================
# Stage 1: Builder
# ===============================
FROM python:3.10-slim AS builder

WORKDIR /app

# Build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ wget \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first
COPY requirements.txt .

# Create virtual env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install CPU-only PyTorch
RUN pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu

# Install other deps
RUN pip install --no-cache-dir -r requirements.txt


# ===============================
# Stage 2: Runtime
# ===============================
FROM python:3.10-slim

WORKDIR /app

# Runtime env vars
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/opt/venv/bin:$PATH"

# Install Production System Libs
# 1. OCR libs (OpenCV, Paddle)
# 2. LibreOffice (The Doc/Docx Converter)
# 3. Fonts (Crucial for correct text rendering during conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    # LibreOffice Headless
    libreoffice-writer \
    libreoffice-java-common \
    default-jre \
    # Asian/Vietnam Fonts
    fonts-liberation \
    fontconfig \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY . .

# Create dirs & non-root user
RUN mkdir -p uploads logs storage && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ || exit 1

EXPOSE ${PORT}

# START APP
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "120", \
     "--worker-class", "gthread", \
     "--preload", \
     "app:app"]

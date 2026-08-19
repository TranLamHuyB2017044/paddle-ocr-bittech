# ===============================
# Stage 1: Builder (Giai đoạn build)
# ===============================
FROM python:3.10-slim AS builder

WORKDIR /app

# Cài đặt công cụ build cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl git \
    && rm -rf /var/lib/apt/lists/*

# Tạo môi trường ảo (venv)
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 1. Nâng cấp pip đầu tiên
RUN pip install --no-cache-dir --upgrade pip "setuptools<70.0.0" wheel

# 2. Cài đặt Torch & Torchvision CPU-only ĐẦU TIÊN (để tối ưu cache)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 3. Cài đặt các thư viện còn lại trong requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ===============================
# Stage 2: Runtime (Giai đoạn chạy)
# ===============================
FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/opt/venv/bin:$PATH"

# Cài đặt các thư viện hệ thống tối thiểu cần cho OpenCV và OCR chạy trên CPU
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libzbar0 \
    curl \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy môi trường venv đã build từ stage 1
COPY --from=builder /opt/venv /opt/venv

# Copy mã nguồn và public folder
COPY src ./src
COPY public ./public
COPY app.py .

# Thiết lập thư mục và user bảo mật
RUN mkdir -p uploads logs storage && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Pre-download ResNet18 weights to appuser's torch cache directory
RUN python -c "import torchvision.models as m; m.resnet18(weights=m.ResNet18_Weights.DEFAULT)"

# Bake photo models vào image
RUN python -c "from rembg import new_session; new_session('modnet'); from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_sc', allowed_modules=['detection'], providers=['CPUExecutionProvider'])"

EXPOSE ${PORT}

# Healthcheck giúp quản lý container trên VPS ổn định
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ || exit 1

CMD ["gunicorn", \
     "--config", "src/core/config/gunicorn.conf.py", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "600", \
     "--worker-class", "gthread", \
     "--preload", \
     "app:app"]

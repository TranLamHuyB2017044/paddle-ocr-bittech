# ============================================================
# Stage 1: Builder (Giai đoạn build và cài đặt thư viện)
# ============================================================
FROM python:3.10-slim AS builder

WORKDIR /app

# Cài đặt các công cụ biên dịch cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip "setuptools<70.0.0" wheel

# Cài đặt Torch & Torchvision bản CPU để giảm dung lượng
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Cài đặt các thư viện còn lại trong requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ============================================================
# Stage 2: Model Downloader (Tải trước toàn bộ AI Models)
# ============================================================
FROM builder AS model-downloader

WORKDIR /app

# Pre-download các model AI để cache vào build-stage (tránh tải lại khi code thay đổi hoặc chạy container)
# 1. Tải ResNet18
RUN python -c "import torchvision.models as m; m.resnet18(weights=m.ResNet18_Weights.DEFAULT)"

# 2. Tải InfiniFlow/deepdoc ONNX (cực kỳ quan trọng để chạy offline trên VPS)
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='InfiniFlow/deepdoc', local_dir='/app/onnx', local_dir_use_symlinks=False)"

# 3. Tải VietOCR Handwritten weight
RUN python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='DungHugging/vietocr-handwritten-finetune', filename='transformerocr.pth')"

# 4. Tải FastEmbed model (bge-small-en-v1.5) sử dụng cho RAG
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

RUN python -c "from vieneu import Vieneu; Vieneu()" || echo "Skip Vieneu preload"


# ============================================================
# Stage 3: Runtime (Giai đoạn chạy ứng dụng cuối cùng)
# ============================================================
FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/opt/venv/bin:$PATH"

# Cài đặt các thư viện hệ thống cần thiết cho OpenCV, zbar và ONNX
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libzbar0 \
    curl \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 1. Copy môi trường ảo đã build từ Stage 1
COPY --from=builder /opt/venv /opt/venv

# 2. Thiết lập thư mục chạy ứng dụng và bảo mật với user non-root
RUN mkdir -p uploads logs storage && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# 3. Copy cache của tất cả model đã tải từ Stage 2 sang cho appuser
COPY --from=model-downloader --chown=appuser:appuser /root/.cache /home/appuser/.cache

# 4. Copy mã nguồn dự án (khi đổi code, Docker chỉ build lại từ đây)
COPY src ./src
COPY public ./public
COPY app.py .
COPY run_worker.py .
COPY .licensekek ./.licensekek

# 5. Copy các model ONNX đã tải vào đúng đường dẫn mong đợi (/app/src/onnx) của code
COPY --from=model-downloader --chown=appuser:appuser /app/onnx /app/src/onnx

USER appuser

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ || exit 1

CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "600", \
     "--worker-class", "gthread", \
     "--preload", \
     "app:app"]

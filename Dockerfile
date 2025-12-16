# Multi-stage build for optimized production image
# Stage 1: Builder - Install dependencies
FROM python:3.12-slim AS builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install CPU-only PyTorch first (smaller size)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install other dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime - Minimal production image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Paddle/OCR optimizations
    FLAGS_eager_delete_tensor_gb=0.0 \
    FLAGS_fraction_of_gpu_memory_to_use=0.1

# Install only runtime dependencies (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    # For healthcheck
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p uploads logs && \
    # Set permissions
    chmod -R 755 /app && \
    # Create non-root user for security
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:$PORT/ || exit 1

# Expose port
EXPOSE $PORT

# Start command with optimized settings
# - 1 worker to save memory (ML models are heavy)
# - 4 threads for concurrency
# - Timeout increased for OCR processing
# - Preload app for faster response
# Note: wsgi.py contains the Flask app instance
CMD gunicorn \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --threads 4 \
    --timeout 120 \
    --worker-class gthread \
    --worker-tmp-dir /dev/shm \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --preload \
    wsgi:app

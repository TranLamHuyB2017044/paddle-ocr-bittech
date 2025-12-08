# Use Python 3.10 slim image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Set environment variables to optimize Python for containers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

# Install system dependencies required for OpenCV and PaddleOCR
# libgl1-mesa-glx: for OpenCV
# libgomp1: for PaddleOCR (OpenMP)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
# 1. Install CPU-only Torch first to reduce image size (avoids downloading 700MB+ CUDA version)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 2. Install other requirements
RUN pip install --no-cache-dir -r requirements.txt

# 3. Pre-download PaddleOCR models (optional but recommended to speed up boot)
# This prevents downloading model at runtime which might timeout on slow connections
# Note: You might want to add a script to trigger the download here if needed.

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# Expose port (Railway will override this, but good for documentation)
EXPOSE $PORT

# Start command
# Using 1 worker to save RAM (Paddle/Torch models are heavy). 
# Increase threads for concurrency.
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - app:app

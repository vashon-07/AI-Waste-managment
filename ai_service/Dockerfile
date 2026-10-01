# Hugging Face Docker Space - AI Waste Classifier Microservice
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Create a non-root user (Hugging Face Spaces runs as UID 1000)
RUN useradd -m -u 1000 user
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (using CPU-optimized PyTorch wheels for fast and lightweight builds)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# Copy application files
COPY app.py /app/app.py
COPY classifier.py /app/classifier.py

# Set proper ownership for Hugging Face non-root user
RUN chown -R user:user /app /home/user

# Switch to non-root user
USER user

# Hugging Face Spaces requires listening on port 7860
EXPOSE 7860

# Start FastAPI application with exactly one worker
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]

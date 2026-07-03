# OCR sidecar image — CUDA runtime + PaddleOCR. Build/deploy SEPARATELY from the web image
# (see docker-compose.yml `ocr` service). Keeps the GPU/CUDA bulk out of the web container.
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY ocr_server.py .

# Bind to loopback by default (safe under host networking); compose sets UVICORN_HOST=0.0.0.0 so
# the web app reaches it over the private bridge without the port ever being published to the host.
ENV UVICORN_HOST=127.0.0.1 UVICORN_PORT=8077
EXPOSE 8077
CMD ["python3", "-m", "uvicorn", "ocr_server:app"]

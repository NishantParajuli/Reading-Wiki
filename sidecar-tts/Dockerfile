# TTS sidecar image — CUDA runtime + OmniVoice. Build/deploy SEPARATELY from the web image
# (see docker-compose.yml `tts` service). Keeps the GPU/CUDA + torch bulk out of the web
# container, exactly like the OCR sidecar.
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Torch from the CUDA (cu128) wheel index — matches OmniVoice's recommended setup. Installed
# before the app deps so this heavy layer caches across rebuilds.
RUN pip3 install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 \
        --extra-index-url https://download.pytorch.org/whl/cu128

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY tts_server.py .
COPY voices ./voices

# Bind to loopback by default (safe under host networking); compose sets UVICORN_HOST=0.0.0.0 so
# the web app reaches it over the private bridge without the port ever being published to the host.
ENV UVICORN_HOST=127.0.0.1 UVICORN_PORT=8078
EXPOSE 8078
CMD ["python3", "-m", "uvicorn", "tts_server:app"]

FROM python:3.13-slim
WORKDIR /app
COPY proxy.py /app/proxy.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
EXPOSE 8899
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8899), timeout=2).close()"
CMD ["python", "/app/proxy.py"]

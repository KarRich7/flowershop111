FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    VK_PARSER_DOCKER=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends chromium chromium-driver ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .
ENTRYPOINT ["python", "docker_entry.py"]
CMD ["watch"]

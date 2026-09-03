# syntax=docker/dockerfile:1.6
# Plain Python: no CUDA, no PyTorch, no ffmpeg. Whisper used to run in this
# process and needed all three; transcription now happens on text-whisperer.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY modules/voice-assistant/backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# The build context is the repo root: the backend imports the shared clients in
# modules/llm and modules/stt, which live above its own directory.
COPY modules/voice-assistant/backend/app ./app
COPY modules/__init__.py ./modules/__init__.py
COPY modules/llm ./modules/llm
COPY modules/stt ./modules/stt

ENV HOST=0.0.0.0 \
    PORT=8001

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]

FROM python:3.11-slim

LABEL maintainer="Tactic Battle"
LABEL description="Napoleonic tactical battle simulator"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SDL_VIDEODRIVER=dummy
ENV SDL_AUDIODRIVER=dummy

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsdl2-2.0-0 \
    libsdl2-image-2.0-0 \
    libsdl2-mixer-2.0-0 \
    libsdl2-ttf-2.0-0 \
    python3-pygame \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pygame-ce==2.5.3

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]

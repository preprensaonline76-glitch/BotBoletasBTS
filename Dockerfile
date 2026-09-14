FROM python:3.12-bookworm

# ============================================================
# CONFIGURACIÓN
# ============================================================

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# ============================================================
# INSTALAR CHROMIUM + CHROMEDRIVER
# ============================================================

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    ca-certificates \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# DIRECTORIO DE TRABAJO
# ============================================================

WORKDIR /app

# ============================================================
# DEPENDENCIAS
# ============================================================

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================================
# BOT
# ============================================================

COPY bot.py .

# ============================================================
# INICIO
# ============================================================

CMD ["python", "-u", "bot.py"]

FROM python:3.12-bookworm

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# ============================================================
# CHROMIUM + CHROMEDRIVER
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
# DEPENDENCIAS PYTHON
# ============================================================

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ============================================================
# BOT
# ============================================================

COPY bot.py .


# ============================================================
# EJECUCIÓN
# ============================================================

CMD ["python", "-u", "bot.py"]

import os
import time
import random
import sys
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

# =========================
# 🔐 ENV
# =========================
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

URLS = [
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-sabado-3-octubre",
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-viernes-2-octubre"
]

# =========================
# 🧠 LOG
# =========================
def log(msg):
    print(msg)
    sys.stdout.flush()

# =========================
# 📲 TELEGRAM
# =========================
def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        log(f"Error Telegram: {e}")

def alerta_extrema(msg):
    # ráfaga corta y directa
    for _ in range(4):
        send_telegram(f"🚨 ALERTA 🚨\n{msg}")
        time.sleep(0.9)

# =========================
# ⚙️ DRIVER ULTRA LIGERO
# =========================
def crear_driver():
    options = Options()
    options.binary_location = "/usr/bin/chromium"

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # 🔥 reducir consumo
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--mute-audio")

    options.add_argument("user-agent=Mozilla/5.0")

    service = Service("/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=options)

driver = None

def iniciar_driver():
    global driver
    try:
        if driver:
            driver.quit()
    except:
        pass

    driver = crear_driver()
    driver.get("https://www.ticketmaster.co")
    time.sleep(2)

    log("✅ Driver listo")
    send_telegram("🚀 Bot activo")

# =========================
# 🧠 ESTADO
# =========================
estado_anterior = {url: None for url in URLS}
cooldown_alerta = {url: 0 for url in URLS}

# =========================
# 🔍 DETECCIÓN RÁPIDA
# =========================
def detectar_rapido(url):
    try:
        driver.get(url)
        time.sleep(random.uniform(1.2, 2.2))

        # selector directo
        elementos = driver.find_elements(By.CSS_SELECTOR, "button")

        for el in elementos:
            txt = el.text.lower()
            if any(x in txt for x in ["comprar", "buy", "tickets", "entradas"]):
                return True

        return False

    except Exception as e:
        log(f"⚠️ detectar_rapido error: {e}")
        if "tab crashed" in str(e).lower():
            iniciar_driver()
        return False

# =========================
# 🔁 CONFIRMACIÓN RÁPIDA
# =========================
def confirmar(url):
    try:
        time.sleep(random.uniform(0.6, 1.2))
        driver.refresh()
        time.sleep(random.uniform(1.0, 1.8))

        body = driver.page_source.lower()

        if any(x in body for x in ["agotado", "sold out", "no hay entradas"]):
            return False

        return True

    except Exception as e:
        log(f"⚠️ confirmar error: {e}")
        return True  # mejor alertar que perder oportunidad

# =========================
# 🔁 CICLO ÉLITE
# =========================
def ciclo():
    for url in URLS:
        disponible = detectar_rapido(url)

        if disponible:
            # ⏱️ evitar spam de alertas
            ahora = time.time()
            if ahora - cooldown_alerta[url] > 20:

                # 🔥 confirmación rápida (no bloquea demasiado)
                if confirmar(url):
                    log(f"🔥 DISPONIBLE {url}")
                    alerta_extrema(url)
                    cooldown_alerta[url] = ahora
                    estado_anterior[url] = "disponible"
                    continue

        # fallback estado
        try:
            body = driver.page_source.lower()
            if any(x in body for x in ["agotado", "sold out"]):
                estado = "agotado"
            else:
                estado = "desconocido"
        except:
            estado = "error"

        log(f"📊 {url} → {estado}")

        if estado != estado_anterior[url]:
            send_telegram(f"{estado.upper()}\n{url}")
            estado_anterior[url] = estado

# =========================
# 🚀 START
# =========================
log("🚀 MODO ÉLITE ACTIVADO")
iniciar_driver()

# =========================
# 🔁 LOOP
# =========================
while True:
    ciclo()

    # ⚡ ciclo agresivo pero humano
    espera = random.randint(15, 28)
    log(f"⏳ Esperando {espera}s\n")
    time.sleep(espera)
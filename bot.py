import os
import re
import time
import random
import threading
from datetime import datetime

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException,
    NoSuchElementException,
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

URLS = [
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-sabado-3-octubre",
    "https://www.ticketmaster.co/event/bts-world-tour-venta-general-viernes-2-octubre",
]

EVENTOS = {
    URLS[0]: "SÁBADO 3 DE OCTUBRE",
    URLS[1]: "VIERNES 2 DE OCTUBRE",
}

# Tiempo normal entre ciclos
ESPERA_MIN = 20
ESPERA_MAX = 30

# Heartbeat
HEARTBEAT_HORAS = 5
HEARTBEAT_SEGUNDOS = HEARTBEAT_HORAS * 60 * 60

# Navegación
TIMEOUT_PAGINA = 40
ESPERA_RENDER_MIN = 2
ESPERA_RENDER_MAX = 4

# Alertas de disponibilidad
COOLDOWN_DISPONIBILIDAD = 30

# Telegram
MAX_ERRORES_TELEGRAM = 10

# Bloqueos
ESPERA_BLOQUEO_1 = 120
ESPERA_BLOQUEO_2 = 300
ESPERA_BLOQUEO_3 = 600


# ============================================================
# ESTADO GLOBAL
# ============================================================

driver = None

inicio_bot = time.time()
ultimo_heartbeat = time.time()

ultimo_estado_valido = {
    url: None for url in URLS
}

estado_actual = {
    url: None for url in URLS
}

ultima_alerta = {
    url: 0 for url in URLS
}

racha_bloqueos = {
    url: 0 for url in URLS
}

estadisticas = {
    "ciclos": 0,
    "agotado": 0,
    "disponible": 0,
    "bloqueado": 0,
    "desconocido": 0,
    "errores": 0,
    "recuperaciones_chrome": 0,
    "alertas_disponibilidad": 0,
}

errores_telegram = 0

lock = threading.Lock()


# ============================================================
# UTILIDADES
# ============================================================

def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def tiempo_activo():
    segundos = int(time.time() - inicio_bot)

    dias = segundos // 86400
    segundos %= 86400

    horas = segundos // 3600
    segundos %= 3600

    minutos = segundos // 60
    segundos %= 60

    if dias > 0:
        return f"{dias}d {horas}h {minutos}m"

    return f"{horas}h {minutos}m {segundos}s"


def horas_activas():
    return (time.time() - inicio_bot) / 3600


def normalizar_texto(texto):
    if not texto:
        return ""

    texto = texto.lower()

    reemplazos = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
        "ñ": "n",
    }

    for original, reemplazo in reemplazos.items():
        texto = texto.replace(original, reemplazo)

    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def texto_visible(driver):
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        return body.text or ""
    except Exception:
        return ""


# ============================================================
# TELEGRAM
# ============================================================

def enviar_telegram(mensaje):
    global errores_telegram

    if not TOKEN or not CHAT_ID:
        print("Telegram no configurado: faltan TOKEN o CHAT_ID.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    datos = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "disable_web_page_preview": True,
    }

    try:
        respuesta = requests.post(
            url,
            data=datos,
            timeout=15
        )

        if respuesta.ok:
            errores_telegram = 0
            return True

        errores_telegram += 1

        if errores_telegram <= MAX_ERRORES_TELEGRAM:
            print(
                f"Error Telegram #{errores_telegram}: "
                f"{respuesta.status_code} {respuesta.text[:300]}"
            )

        return False

    except Exception as e:
        errores_telegram += 1

        if errores_telegram <= MAX_ERRORES_TELEGRAM:
            print(
                f"Error Telegram #{errores_telegram}: {e}"
            )

        return False


# ============================================================
# MENSAJE INICIAL
# ============================================================

def mensaje_inicio():
    mensaje = (
        "🚀 BOT INICIANDO\n\n"
        "✅ Railway conectado\n"
        "📡 Telegram conectado\n"
        "🔎 Preparando monitoreo...\n\n"
        f"🎫 Eventos configurados: {len(URLS)}"
    )

    enviar_telegram(mensaje)


# ============================================================
# HEARTBEAT
# ============================================================

def enviar_heartbeat():
    global ultimo_heartbeat

    if time.time() - ultimo_heartbeat < HEARTBEAT_SEGUNDOS:
        return

    ultimo_heartbeat = time.time()

    mensaje = (
        "💓 HEARTBEAT DEL BOT\n\n"
        "🟢 Railway: funcionando\n"
        "📡 Telegram: conectado\n"
        "🎫 Ticketmaster: monitoreando\n\n"
        f"⏱️ Tiempo activo: {tiempo_activo()}\n"
        f"🕐 Horas activo: {horas_activas():.2f} h\n\n"
        f"🔄 Ciclos: {estadisticas['ciclos']}\n"
        f"🔴 Agotado: {estadisticas['agotado']}\n"
        f"🟢 Disponible: {estadisticas['disponible']}\n"
        f"🛡️ Bloqueos: {estadisticas['bloqueado']}\n"
        f"❔ Desconocidos: {estadisticas['desconocido']}\n"
        f"⚠️ Errores: {estadisticas['errores']}\n"
        f"🔧 Recuperaciones Chrome: {estadisticas['recuperaciones_chrome']}\n"
        f"🚨 Alertas disponibilidad: {estadisticas['alertas_disponibilidad']}"
    )

    enviar_telegram(mensaje)


# ============================================================
# ALERTA DE DISPONIBILIDAD
# ============================================================

def alertar_disponibilidad(url, motivo):
    ahora_timestamp = time.time()

    if (
        ahora_timestamp - ultima_alerta[url]
        < COOLDOWN_DISPONIBILIDAD
    ):
        return

    ultima_alerta[url] = ahora_timestamp
    estadisticas["alertas_disponibilidad"] += 1

    evento = EVENTOS.get(url, "EVENTO DESCONOCIDO")

    mensaje = (
        "🚨🚨🚨 BOLETAS DISPONIBLES 🚨🚨🚨\n\n"
        f"🎤 BTS WORLD TOUR\n"
        f"📅 {evento}\n\n"
        f"🟢 Señal detectada: {motivo}\n\n"
        f"🎟️ ENTRA AHORA:\n"
        f"{url}"
    )

    enviar_telegram(mensaje)

    print(
        f"[{ahora()}] 🚨 DISPONIBILIDAD DETECTADA "
        f"({evento}) -> {motivo}"
    )


# ============================================================
# ALERTA DE BLOQUEO
# ============================================================

def alertar_bloqueo(url):
    if racha_bloqueos[url] != 1:
        return

    evento = EVENTOS.get(url, "EVENTO DESCONOCIDO")

    mensaje = (
        "🛡️ PROTECCIÓN / BLOQUEO DETECTADO\n\n"
        f"🎤 BTS WORLD TOUR\n"
        f"📅 {evento}\n\n"
        "⚠️ Ticketmaster está mostrando una señal "
        "de protección o verificación.\n\n"
        "🔄 El bot conservará el último estado válido "
        "y continuará intentando posteriormente."
    )

    enviar_telegram(mensaje)


# ============================================================
# SELENIUM / CHROME
# ============================================================

def cerrar_driver():
    global driver

    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass

    driver = None


def iniciar_driver(notificar=False):
    global driver

    cerrar_driver()

    opciones = Options()

    opciones.binary_location = "/usr/bin/chromium"

    opciones.add_argument("--headless=new")
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")
    opciones.add_argument("--disable-gpu")
    opciones.add_argument("--disable-software-rasterizer")
    opciones.add_argument("--disable-background-networking")
    opciones.add_argument("--disable-background-timer-throttling")
    opciones.add_argument("--disable-backgrounding-occluded-windows")
    opciones.add_argument("--disable-breakpad")
    opciones.add_argument("--disable-component-extensions-with-background-pages")
    opciones.add_argument("--disable-features=Translate,BackForwardCache")
    opciones.add_argument("--disable-hang-monitor")
    opciones.add_argument("--disable-ipc-flooding-protection")
    opciones.add_argument("--disable-popup-blocking")
    opciones.add_argument("--disable-prompt-on-repost")
    opciones.add_argument("--disable-renderer-backgrounding")
    opciones.add_argument("--disable-sync")
    opciones.add_argument("--metrics-recording-only")
    opciones.add_argument("--no-first-run")
    opciones.add_argument("--no-default-browser-check")
    opciones.add_argument("--password-store=basic")
    opciones.add_argument("--use-mock-keychain")
    opciones.add_argument("--window-size=1920,1080")

    opciones.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    opciones.page_load_strategy = "eager"

    try:
        driver = webdriver.Chrome(
            service=webdriver.ChromeService(
                executable_path="/usr/bin/chromedriver"
            ),
            options=opciones
        )

        driver.set_page_load_timeout(TIMEOUT_PAGINA)

        print(f"[{ahora()}] Chrome iniciado correctamente.")

        if notificar:
            enviar_telegram(
                "🚀 BOT ACTIVO\n\n"
                "Chrome iniciado correctamente."
            )

        return True

    except Exception as e:
        driver = None

        print(
            f"[{ahora()}] ❌ No se pudo iniciar Chrome: {e}"
        )

        return False


# ============================================================
# DETECCIÓN DE PROTECCIÓN
# ============================================================

def detectar_proteccion(texto):
    texto = normalizar_texto(texto)

    if not texto:
        return False

    frases_fuertes = [
        "verifica que eres humano",
        "verify you are human",
        "verifying you are human",
        "checking your browser",
        "checking your connection",
        "just a moment",
        "access denied",
        "too many requests",
        "unusual traffic",
        "security check",
        "security verification",
        "please wait while we verify",
        "please wait while we check",
        "ray id",
        "cloudflare",
        "captcha",
        "recaptcha",
        "are you a robot",
        "eres un robot",
        "actividad inusual",
        "actividad sospechosa",
        "proteccion contra bots",
    ]

    for frase in frases_fuertes:
        if frase in texto:
            return True

    combinaciones = [
        ("verifica", "humano"),
        ("verify", "human"),
        ("security", "check"),
        ("security", "verification"),
        ("please wait", "browser"),
        ("checking", "browser"),
        ("unusual", "traffic"),
        ("access", "denied"),
    ]

    for palabra1, palabra2 in combinaciones:
        if palabra1 in texto and palabra2 in texto:
            return True

    return False


# ============================================================
# PALABRAS DE ESTADO
# ============================================================

PALABRAS_AGOTADO = [
    "agotado",
    "agotada",
    "sold out",
    "soldout",
    "currently unavailable",
    "currently not available",
    "no disponible",
    "entradas agotadas",
    "boletas agotadas",
    "sin disponibilidad",
    "no hay disponibilidad",
    "unavailable",
]

PALABRAS_DISPONIBLE = [
    "disponible",
    "disponibles",
    "available",
    "availability",
    "hay entradas",
    "hay boletas",
    "entradas disponibles",
    "boletas disponibles",
]


# ============================================================
# DETECCIÓN DE PÁGINA DEL EVENTO
# ============================================================

def parece_pagina_evento(texto, html):
    texto_n = normalizar_texto(texto)
    html_n = normalizar_texto(html)

    senales = [
        "bts",
        "ticketmaster",
        "venta general",
        "octubre",
        "campin",
        "world tour",
    ]

    contador = 0

    for senal in senales:
        if senal in texto_n or senal in html_n:
            contador += 1

    return contador >= 2


# ============================================================
# DETECCIÓN DE AGOTADO EN TEXTO VISIBLE
# ============================================================

def detectar_agotado_texto(texto):
    texto_n = normalizar_texto(texto)

    for palabra in PALABRAS_AGOTADO:
        if palabra in texto_n:
            return True

    return False


# ============================================================
# DETECCIÓN DE AGOTADO EN HTML
# ============================================================

def detectar_agotado_html(html):
    html_n = normalizar_texto(html)

    for palabra in PALABRAS_AGOTADO:
        if palabra in html_n:
            return True

    return False


# ============================================================
# DETECTOR PRIORITARIO DEL BOTÓN DE COMPRA
# ============================================================

def detectar_boton_disponible_prioritario(driver):
    selectores = [
        "button",
        "a",
        "[role='button']",
    ]

    textos_fuertes = [
        "comprar",
        "compra",
        "comprar entradas",
        "comprar boletas",
        "seleccionar",
        "seleccionar entradas",
        "seleccionar asientos",
        "ver entradas",
        "ver boletas",
        "entradas",
        "boletas",
        "tickets",
        "buy tickets",
        "buy",
        "select seats",
        "select tickets",
        "get tickets",
    ]

    atributos_fuertes = [
        "aria-label",
        "title",
        "data-testid",
        "data-test",
    ]

    for selector in selectores:
        try:
            elementos = driver.find_elements(
                By.CSS_SELECTOR,
                selector
            )
        except Exception:
            continue

        for elemento in elementos:
            try:
                if not elemento.is_displayed():
                    continue
            except Exception:
                continue

            try:
                if not elemento.is_enabled():
                    continue
            except Exception:
                pass

            valores = []

            try:
                valores.append(elemento.text or "")
            except Exception:
                pass

            for atributo in atributos_fuertes:
                try:
                    valores.append(
                        elemento.get_attribute(atributo) or ""
                    )
                except Exception:
                    pass

            contenido = normalizar_texto(
                " ".join(valores)
            )

            if not contenido:
                continue

            for palabra in textos_fuertes:
                if palabra in contenido:
                    return True, palabra

    return False, None


# ============================================================
# DETECCIÓN GENÉRICA DE BOTONES
# ============================================================

def detectar_botones_compra(driver):
    palabras = [
        "comprar",
        "compra",
        "entradas",
        "boletas",
        "tickets",
        "buy",
        "select",
        "seleccionar",
        "reservar",
    ]

    selectores = [
        "button",
        "a",
        "[role='button']",
    ]

    for selector in selectores:
        try:
            elementos = driver.find_elements(
                By.CSS_SELECTOR,
                selector
            )
        except Exception:
            continue

        for elemento in elementos:
            try:
                if not elemento.is_displayed():
                    continue
            except Exception:
                continue

            try:
                texto = elemento.text or ""
            except Exception:
                texto = ""

            texto = normalizar_texto(texto)

            for palabra in palabras:
                if palabra in texto:
                    return True

    return False


# ============================================================
# DETECCIÓN DE ENLACES DE COMPRA
# ============================================================

def detectar_enlaces_compra(driver):
    palabras_href = [
        "checkout",
        "purchase",
        "buy",
        "ticket",
        "tickets",
        "entradas",
        "boletas",
        "select",
        "seat",
        "seats",
    ]

    try:
        enlaces = driver.find_elements(
            By.CSS_SELECTOR,
            "a[href]"
        )
    except Exception:
        return False

    for enlace in enlaces:
        try:
            if not enlace.is_displayed():
                continue
        except Exception:
            continue

        try:
            href = enlace.get_attribute("href") or ""
        except Exception:
            href = ""

        href = normalizar_texto(href)

        for palabra in palabras_href:
            if palabra in href:
                return True

    return False


# ============================================================
# DETECCIÓN PRINCIPAL DE DISPONIBILIDAD
# ============================================================

def detectar_disponibilidad(url):
    global driver

    if driver is None:
        if not iniciar_driver(notificar=False):
            return "error", "No se pudo iniciar Chrome"

    try:
        print(
            f"[{ahora()}] Consultando: "
            f"{EVENTOS.get(url, url)}"
        )

        driver.get(url)

        espera = random.uniform(
            ESPERA_RENDER_MIN,
            ESPERA_RENDER_MAX
        )

        time.sleep(espera)

        html = driver.page_source or ""
        visible = texto_visible(driver)

        print(
            f"[{ahora()}] Texto visible extraído: "
            f"{len(visible)} caracteres"
        )

        # ----------------------------------------------------
        # 1. PROTECCIÓN
        # ----------------------------------------------------

        if detectar_proteccion(visible):
            print(
                f"[{ahora()}] 🛡️ Protección detectada."
            )

            return "bloqueado", "Protección Ticketmaster"

        # ----------------------------------------------------
        # 2. AGOTADO EN TEXTO VISIBLE
        # ----------------------------------------------------

        if detectar_agotado_texto(visible):
            print(
                f"[{ahora()}] 🔴 AGOTADO detectado "
                f"en texto visible."
            )

            return "agotado", "Texto visible: AGOTADO"

        # ----------------------------------------------------
        # 3. VERIFICAR SI PARECE EVENTO
        # ----------------------------------------------------

        es_evento = parece_pagina_evento(
            visible,
            html
        )

        # ----------------------------------------------------
        # 4. AGOTADO EN HTML
        # ----------------------------------------------------

        if es_evento:
            if detectar_agotado_html(html):
                print(
                    f"[{ahora()}] 🔴 AGOTADO detectado "
                    f"en HTML de página de evento."
                )

                return "agotado", "HTML: AGOTADO"

        # ----------------------------------------------------
        # 5. BOTÓN DE COMPRA PRIORITARIO
        # ----------------------------------------------------

        boton_disponible, motivo_boton = (
            detectar_boton_disponible_prioritario(driver)
        )

        if boton_disponible:
            print(
                f"[{ahora()}] 🟢 BOTÓN DE COMPRA DETECTADO: "
                f"{motivo_boton}"
            )

            return (
                "disponible",
                f"Botón accionable: {motivo_boton}"
            )

        # ----------------------------------------------------
        # 6. TEXTO DE DISPONIBILIDAD
        # ----------------------------------------------------

        visible_normalizado = normalizar_texto(
            visible
        )

        for palabra in PALABRAS_DISPONIBLE:
            if palabra in visible_normalizado:
                print(
                    f"[{ahora()}] 🟢 Disponibilidad "
                    f"detectada por texto: {palabra}"
                )

                return (
                    "disponible",
                    f"Texto visible: {palabra}"
                )

        # ----------------------------------------------------
        # 7. BOTONES GENÉRICOS
        # ----------------------------------------------------

        if detectar_botones_compra(driver):
            print(
                f"[{ahora()}] 🟢 Posible botón de compra."
            )

            return (
                "disponible",
                "Botón de compra detectado"
            )

        # ----------------------------------------------------
        # 8. ENLACES DE COMPRA
        # ----------------------------------------------------

        if detectar_enlaces_compra(driver):
            print(
                f"[{ahora()}] 🟢 Posible enlace de compra."
            )

            return (
                "disponible",
                "Enlace de compra detectado"
            )

        # ----------------------------------------------------
        # 9. DESCONOCIDO
        # ----------------------------------------------------

        print(
            f"[{ahora()}] ❔ No se encontró señal clara."
        )

        return (
            "desconocido",
            "No se encontró señal clara"
        )

    except TimeoutException:
        print(
            f"[{ahora()}] ⚠️ Timeout cargando Ticketmaster."
        )

        return (
            "error",
            "Timeout de carga"
        )

    except WebDriverException as e:
        mensaje_error = str(e).lower()

        print(
            f"[{ahora()}] ⚠️ Error de Chrome/Selenium: "
            f"{e}"
        )

        errores_chrome = [
            "tab crashed",
            "session deleted",
            "disconnected",
            "chrome not reachable",
            "invalid session id",
            "target window already closed",
            "browser connection",
        ]

        es_error_chrome = any(
            palabra in mensaje_error
            for palabra in errores_chrome
        )

        if es_error_chrome:
            estadisticas["recuperaciones_chrome"] += 1

            print(
                f"[{ahora()}] 🔧 Recuperando Chrome "
                f"silenciosamente..."
            )

            iniciar_driver(notificar=False)

        return (
            "error",
            "Error de Chrome/Selenium"
        )

    except Exception as e:
        print(
            f"[{ahora()}] ❌ Error inesperado: {e}"
        )

        return (
            "error",
            str(e)[:200]
        )


# ============================================================
# PROCESAMIENTO DEL RESULTADO
# ============================================================

def procesar_resultado(url, estado, motivo):
    anterior = estado_actual.get(url)

    estado_actual[url] = estado

    evento = EVENTOS.get(url, "EVENTO")

    # --------------------------------------------------------
    # BLOQUEADO
    # --------------------------------------------------------

    if estado == "bloqueado":

        estadisticas["bloqueado"] += 1

        racha_bloqueos[url] += 1

        print(
            f"[{ahora()}] 🛡️ {evento}: BLOQUEADO "
            f"(racha {racha_bloqueos[url]})"
        )

        if racha_bloqueos[url] == 1:
            alertar_bloqueo(url)

        return

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if estado == "error":

        estadisticas["errores"] += 1

        print(
            f"[{ahora()}] ⚠️ {evento}: ERROR - {motivo}"
        )

        # El error no modifica el último estado válido.
        return

    # --------------------------------------------------------
    # DESCONOCIDO
    # --------------------------------------------------------

    if estado == "desconocido":

        estadisticas["desconocido"] += 1

        print(
            f"[{ahora()}] ❔ {evento}: DESCONOCIDO"
        )

        # No modifica el último estado válido.
        return

    # --------------------------------------------------------
    # RECUPERACIÓN DESPUÉS DE BLOQUEO
    # --------------------------------------------------------

    if racha_bloqueos[url] > 0:
        print(
            f"[{ahora()}] 🔄 {evento}: "
            f"Ticketmaster volvió a responder."
        )

        racha_bloqueos[url] = 0

    # --------------------------------------------------------
    # AGOTADO
    # --------------------------------------------------------

    if estado == "agotado":

        estadisticas["agotado"] += 1

        ultimo_estado_valido[url] = "agotado"

        if anterior != "agotado":
            print(
                f"[{ahora()}] 🔴 {evento}: AGOTADO"
            )
        else:
            print(
                f"[{ahora()}] 🔴 {evento}: "
                f"continúa AGOTADO"
            )

        return

    # --------------------------------------------------------
    # DISPONIBLE
    # --------------------------------------------------------

    if estado == "disponible":

        estadisticas["disponible"] += 1

        ultimo_estado_valido[url] = "disponible"

        print(
            f"[{ahora()}] 🟢 {evento}: "
            f"DISPONIBLE -> {motivo}"
        )

        # Alertar inmediatamente.
        # No exige doble confirmación.
        alertar_disponibilidad(
            url,
            motivo
        )

        return


# ============================================================
# TIEMPO DE ESPERA SEGÚN BLOQUEO
# ============================================================

def espera_por_bloqueo(url):
    racha = racha_bloqueos[url]

    if racha <= 1:
        return ESPERA_BLOQUEO_1

    if racha == 2:
        return ESPERA_BLOQUEO_2

    return ESPERA_BLOQUEO_3


# ============================================================
# RESUMEN DE CICLO
# ============================================================

def mostrar_resumen_ciclo():
    print()
    print("=" * 65)
    print(
        f"[{ahora()}] RESUMEN CICLO "
        f"{estadisticas['ciclos']}"
    )
    print("=" * 65)

    for url in URLS:
        evento = EVENTOS.get(url, url)

        estado = estado_actual.get(url)
        valido = ultimo_estado_valido.get(url)

        print(
            f"{evento}: "
            f"actual={estado} | "
            f"último válido={valido}"
        )

    print(
        f"Tiempo activo: {tiempo_activo()}"
    )

    print("=" * 65)
    print()


# ============================================================
# ESPERA INTERRUMPIBLE
# ============================================================

def esperar(segundos):
    inicio = time.time()

    while time.time() - inicio < segundos:

        enviar_heartbeat()

        restante = segundos - (
            time.time() - inicio
        )

        time.sleep(
            min(10, max(1, restante))
        )


# ============================================================
# BUCLE PRINCIPAL
# ============================================================

def main():

    global driver

    print("=" * 65)
    print("BOT DE MONITOREO TICKETMASTER - BTS")
    print("=" * 65)

    print(
        f"[{ahora()}] Iniciando bot..."
    )

    print(
        f"[{ahora()}] Eventos configurados: "
        f"{len(URLS)}"
    )

    if not TOKEN:
        print(
            f"[{ahora()}] ⚠️ Falta variable TOKEN."
        )

    if not CHAT_ID:
        print(
            f"[{ahora()}] ⚠️ Falta variable CHAT_ID."
        )

    # --------------------------------------------------------
    # INICIAR CHROME
    # --------------------------------------------------------

    if not iniciar_driver(notificar=False):

        enviar_telegram(
            "❌ ERROR AL INICIAR EL BOT\n\n"
            "No fue posible iniciar Chrome/Selenium "
            "en Railway."
        )

        # Intentar continuamente sin enviar BOT ACTIVO.
        while driver is None:

            esperar(30)

            if iniciar_driver(notificar=False):
                break

    # --------------------------------------------------------
    # MENSAJE DE INICIO
    # --------------------------------------------------------

    mensaje_inicio()

    print(
        f"[{ahora()}] Monitoreo iniciado."
    )

    # --------------------------------------------------------
    # BUCLE
    # --------------------------------------------------------

    while True:

        try:

            estadisticas["ciclos"] += 1

            print()
            print(
                "#" * 65
            )
            print(
                f"[{ahora()}] "
                f"INICIANDO CICLO "
                f"{estadisticas['ciclos']}"
            )
            print(
                "#" * 65
            )

            ciclo_tuvo_bloqueo = False

            # ------------------------------------------------
            # REVISAR CADA EVENTO
            # ------------------------------------------------

            for url in URLS:

                estado, motivo = detectar_disponibilidad(
                    url
                )

                procesar_resultado(
                    url,
                    estado,
                    motivo
                )

                if estado == "bloqueado":
                    ciclo_tuvo_bloqueo = True

                enviar_heartbeat()

            # ------------------------------------------------
            # RESUMEN
            # ------------------------------------------------

            mostrar_resumen_ciclo()

            # ------------------------------------------------
            # ESPERA
            # ------------------------------------------------

            if ciclo_tuvo_bloqueo:

                tiempos = [
                    espera_por_bloqueo(url)
                    for url in URLS
                    if racha_bloqueos[url] > 0
                ]

                espera = max(
                    tiempos
                ) if tiempos else ESPERA_BLOQUEO_1

                print(
                    f"[{ahora()}] 🛡️ Bloqueo activo. "
                    f"Esperando {espera} segundos."
                )

                esperar(espera)

            else:

                espera = random.randint(
                    ESPERA_MIN,
                    ESPERA_MAX
                )

                print(
                    f"[{ahora()}] ⏳ Próximo ciclo "
                    f"en {espera} segundos."
                )

                esperar(espera)

        except KeyboardInterrupt:

            print(
                f"[{ahora()}] Bot detenido manualmente."
            )

            cerrar_driver()

            break

        except Exception as e:

            estadisticas["errores"] += 1

            print(
                f"[{ahora()}] ❌ Error general "
                f"en el ciclo: {e}"
            )

            # No mandar BOT ACTIVO.
            # Recuperación silenciosa.
            if driver is None:

                print(
                    f"[{ahora()}] 🔧 "
                    "Intentando recuperar Chrome..."
                )

                iniciar_driver(
                    notificar=False
                )

            esperar(30)


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    main()

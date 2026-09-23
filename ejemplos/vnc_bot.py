"""
Bot VNC con verificador de clics en falso.

En cada revisión (pausa aleatoria entre ESPERA_MIN y ESPERA_MAX):
  1. VERDE en la franja      -> la acción está en curso: esperar
  2. dentro de la gracia     -> se acaba de hacer clic y el verde aún puede no
                                haber aparecido (tarda 1-2 s): esperar
  3. sin verde + hay CYAN    -> hacer clic en el cyan
                                (si el clic anterior nunca mostró verde, se
                                 registra como clic en falso)
  4. sin verde + sin cyan    -> cooldown: esperar a que aparezca el cyan

pip install vncdotool numpy
"""
import random
import time

import numpy as np
from vncdotool import api

# --- Conexión ---------------------------------------------------------------
SERVER = "localhost::5900"
PASSWORD = "123456"

# --- Objetivo (cyan) --------------------------------------------------------
name_Check = "Cyan"
COLOR_OBJETIVO = (0, 255, 255)   # RGB
ZONA = (6, 36, 1238, 801)        # (izq, arriba, der, abajo) donde se busca y se hace clic
TOLERANCIA = 5                   # diferencia máxima por canal (0 = exacto)
MIN_PIXELES = 15                 # menos que esto es ruido -> cuenta como "Not Found"
CELDA = 16                       # tamaño (px) de la cuadrícula para agrupar objetos

# --- Verificador (verde = acción en curso) ----------------------------------
name_Verde = "Accion"
VERDE = (6, 138, 53)             # RGB medido con el visor (también aparece 6,139,52)
VERDE_CAJA = (18, 101, 218, 124) # (x1, y1, x2, y2) bordes incluidos: la barra completa
VERDE_TOLERANCIA = 5             # cubre variaciones de tono de la barra
VERDE_MIN_PIXELES = 1            # con 1 píxel verde basta -> Found; 0 -> Not Found

# --- Tiempos ----------------------------------------------------------------
ESPERA_MIN, ESPERA_MAX = 1.8, 3.6   # pausa aleatoria entre revisiones
GRACIA_CLIC = 3.0                   # s tras un clic antes de juzgarlo (el verde tarda 1-2 s)


# ---------------------------------------------------------------------------
def capturar(client):
    """Pide un frame nuevo a la VM y lo devuelve como array numpy RGB (alto, ancho, 3)."""
    client.refreshScreen()
    return np.asarray(client.screen, dtype=np.uint8)


def pixeles_color(frame, caja, rgb, tolerancia):
    """Cantidad de píxeles de la caja (bordes incluidos) que coinciden con el color."""
    x1, y1, x2, y2 = caja
    zona = frame[y1:y2 + 1, x1:x2 + 1].astype(np.int16)
    ok = np.all(np.abs(zona - np.array(rgb, dtype=np.int16)) <= tolerancia, axis=-1)
    return int(ok.sum())


def is_action_running(frame):
    """Found mientras quede verde en la barra (acción en curso); Not Found si no hay nada de verde."""
    n = pixeles_color(frame, VERDE_CAJA, VERDE, VERDE_TOLERANCIA)
    return "Found" if n >= VERDE_MIN_PIXELES else "Not Found"


def buscar_color(frame):
    """Devuelve (x, y, n_pixeles) del centro del objeto cyan dentro de ZONA, o None."""
    px = frame.astype(np.int16)
    ox = oy = 0
    if ZONA:
        izq, arr, der, aba = ZONA
        px = px[arr:aba, izq:der]
        ox, oy = izq, arr

    mask = np.all(np.abs(px - np.array(COLOR_OBJETIVO, dtype=np.int16)) <= TOLERANCIA, axis=-1)
    if int(mask.sum()) < MIN_PIXELES:
        return None

    # Agrupa en celdas y toma la región con más píxeles del color
    # (si hay varios objetos, apunta al más grande, no al punto intermedio).
    h, w = mask.shape
    gh, gw = -(-h // CELDA), -(-w // CELDA)
    pad = np.zeros((gh * CELDA, gw * CELDA), dtype=np.int32)
    pad[:h, :w] = mask
    celdas = pad.reshape(gh, CELDA, gw, CELDA).sum(axis=(1, 3))
    vec = np.pad(celdas, 1)
    vec = sum(vec[1 + dy:1 + dy + gh, 1 + dx:1 + dx + gw]
              for dy in (-1, 0, 1) for dx in (-1, 0, 1))
    cy, cx = np.unravel_index(np.argmax(vec), vec.shape)

    y0, y1 = max(0, (cy - 1) * CELDA), min(h, (cy + 2) * CELDA)
    x0, x1 = max(0, (cx - 1) * CELDA), min(w, (cx + 2) * CELDA)
    ys, xs = np.nonzero(mask[y0:y1, x0:x1])
    ys, xs = ys + y0, xs + x0

    # Centro del objeto, ajustado al píxel del color más cercano (el clic cae sobre el color).
    my, mx = ys.mean(), xs.mean()
    i = np.argmin((ys - my) ** 2 + (xs - mx) ** 2)
    return int(xs[i]) + ox, int(ys[i]) + oy, len(xs)


def is_standing_on_(frame):
    return "Found" if buscar_color(frame) else "Not Found"


def hacer_clic(client, objetivo):
    x, y, n = objetivo
    client.mouseMove(x, y)
    client.mousePress(1)
    log(f"{name_Check}: CLIC en ({x}, {y})  [{n} px]")


def pausa():
    time.sleep(random.uniform(ESPERA_MIN, ESPERA_MAX))


def log(msg):
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


# ---------------------------------------------------------------------------
def main():
    client = api.connect(SERVER, password=PASSWORD)
    t_clic = None          # momento del último clic
    pendiente = False      # último clic aún sin confirmar con verde
    clics = confirmados = en_falso = 0
    estado_previo = None

    try:
        client.mouseMove(0, 0)  # inicializa el puntero (evita que falle el 1er clic)
        log(f"Bot iniciado. Verde {VERDE} en {VERDE_CAJA} | {name_Check} {COLOR_OBJETIVO} en {ZONA}. "
            "Ctrl+C para salir.")

        while True:
            frame = capturar(client)
            n_verde = pixeles_color(frame, VERDE_CAJA, VERDE, VERDE_TOLERANCIA)
            verde = n_verde >= VERDE_MIN_PIXELES
            en_gracia = t_clic is not None and time.monotonic() - t_clic < GRACIA_CLIC

            if verde:
                estado = "accion"
                if pendiente:
                    pendiente = False
                    confirmados += 1
                    log(f"{name_Verde}: Found [{n_verde} px verdes] -> clic confirmado")
            elif en_gracia:
                estado = "verificando"
            else:
                if pendiente:  # pasó la gracia y el verde nunca apareció
                    pendiente = False
                    en_falso += 1
                    log(f"{name_Verde}: Not Found [0 px verdes] tras {GRACIA_CLIC}s -> CLIC EN FALSO")

                objetivo = buscar_color(frame)
                if objetivo:
                    estado = "clic"
                    hacer_clic(client, objetivo)
                    t_clic, pendiente = time.monotonic(), True
                    clics += 1
                else:
                    estado = "cooldown"

            if estado != estado_previo and estado != "clic":
                log({
                    "accion": f"{name_Verde}: en curso (verde) -> esperando",
                    "verificando": f"{name_Verde}: verificando clic...",
                    "cooldown": f"{name_Check}: Not Found -> cooldown, esperando que aparezca",
                }[estado])
            estado_previo = estado
            pausa()
    except KeyboardInterrupt:
        print(f"\nFin. Clics: {clics} | confirmados: {confirmados} | en falso: {en_falso}")
    finally:
        api.shutdown()


if __name__ == "__main__":
    main()

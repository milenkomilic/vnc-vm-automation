"""
vncbot_base — núcleo reutilizable de la metodología Percibir -> Decidir -> Actuar -> Verificar.

Contiene:
  * Conexión VNC (vncdotool) con cierre garantizado.
  * Primitivas de percepción sobre el framebuffer RGB (P-01 a P-05, P-11, P-12).
  * Señales declarativas (Senal) evaluadas con caché por frame.
  * Motor de reglas por prioridad con verificación de acciones y watchdog (Bot).
  * Carga de la configuración desde YAML.

Uso:
    python vncbot_base.py bot.yaml

Dependencias: pip install vncdotool numpy pyyaml   (opcional: opencv-python para plantillas)
"""
from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass, field

import numpy as np
from vncdotool import api

RGB = tuple[int, int, int]
Caja = tuple[int, int, int, int]  # (x1, y1, x2, y2) con bordes INCLUIDOS, coordenadas de la VM


# ============================================================================
# Registro
# ============================================================================
def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


# ============================================================================
# Percepción (primitivas)
# ============================================================================
def capturar(client) -> np.ndarray:
    """P-01. Pide un frame nuevo y lo devuelve como array (alto, ancho, 3) uint8 en RGB."""
    client.refreshScreen()
    return np.asarray(client.screen, dtype=np.uint8)


def recortar(frame: np.ndarray, caja: Caja | None) -> tuple[np.ndarray, int, int]:
    """Recorta la caja (bordes incluidos). Devuelve (sub-array, offset_x, offset_y)."""
    if caja is None:
        return frame, 0, 0
    x1, y1, x2, y2 = caja
    return frame[y1:y2 + 1, x1:x2 + 1], x1, y1


def mascara(region: np.ndarray, rgb: RGB, tolerancia: int) -> np.ndarray:
    """Matriz booleana: True donde |pixel - rgb| <= tolerancia en los tres canales."""
    diff = np.abs(region.astype(np.int16) - np.array(rgb, dtype=np.int16))
    return np.all(diff <= tolerancia, axis=-1)


def contar(frame: np.ndarray, caja: Caja | None, rgb: RGB, tolerancia: int = 0) -> int:
    """P-03. Cantidad de píxeles del color dentro de la caja."""
    region, _, _ = recortar(frame, caja)
    return int(mascara(region, rgb, tolerancia).sum())


def presente(frame, caja, rgb, tolerancia=0, min_pixeles=1) -> bool:
    """P-02. True si hay al menos min_pixeles del color en la caja."""
    return contar(frame, caja, rgb, tolerancia) >= min_pixeles


def proporcion(frame, caja, rgb, tolerancia=0) -> float:
    """P-04. Fracción (0-1) de la caja cubierta por el color."""
    region, _, _ = recortar(frame, caja)
    return float(mascara(region, rgb, tolerancia).mean())


def buscar_objetivo(frame, zona, rgb, tolerancia=0, min_pixeles=15, celda=16):
    """
    P-05. Localiza el objeto más grande del color dentro de la zona.
    Devuelve (x, y, n_pixeles) con (x, y) sobre un píxel del color, o None.
    Algoritmo: máscara -> suma por celdas -> celda con más masa (con vecinas)
               -> centroide local -> píxel del color más cercano al centroide.
    """
    region, ox, oy = recortar(frame, zona)
    m = mascara(region, rgb, tolerancia)
    if int(m.sum()) < min_pixeles:
        return None
    h, w = m.shape
    gh, gw = -(-h // celda), -(-w // celda)
    pad = np.zeros((gh * celda, gw * celda), dtype=np.int32)
    pad[:h, :w] = m
    celdas = pad.reshape(gh, celda, gw, celda).sum(axis=(1, 3))
    v = np.pad(celdas, 1)
    v = sum(v[1 + dy:1 + dy + gh, 1 + dx:1 + dx + gw] for dy in (-1, 0, 1) for dx in (-1, 0, 1))
    cy, cx = np.unravel_index(np.argmax(v), v.shape)
    y0, y1 = max(0, (cy - 1) * celda), min(h, (cy + 2) * celda)
    x0, x1 = max(0, (cx - 1) * celda), min(w, (cx + 2) * celda)
    ys, xs = np.nonzero(m[y0:y1, x0:x1])
    ys, xs = ys + y0, xs + x0
    i = np.argmin((ys - ys.mean()) ** 2 + (xs - xs.mean()) ** 2)
    return int(xs[i]) + ox, int(ys[i]) + oy, int(len(xs))


def buscar_plantilla(frame, zona, plantilla: np.ndarray, umbral: float = 0.9):
    """
    P-11. Template matching (requiere opencv-python). Devuelve (x, y, score) del centro
    de la mejor coincidencia si score >= umbral, o None. 'plantilla' es RGB uint8.
    """
    import cv2
    region, ox, oy = recortar(frame, zona)
    res = cv2.matchTemplate(region, plantilla, cv2.TM_CCOEFF_NORMED)
    _, score, _, (mx, my) = cv2.minMaxLoc(res)
    if score < umbral:
        return None
    ph, pw = plantilla.shape[:2]
    return mx + pw // 2 + ox, my + ph // 2 + oy, float(score)


def esperar_estable(client, caja=None, quieto=1.0, timeout=30.0, intervalo=0.2, tolerancia=0) -> bool:
    """
    P-12. Bloquea hasta que la caja no cambie durante 'quieto' segundos (pantalla estable).
    Devuelve True si se estabilizó, False si venció el timeout.
    """
    inicio = time.monotonic()
    previo, desde = None, time.monotonic()
    while time.monotonic() - inicio < timeout:
        actual, _, _ = recortar(capturar(client), caja)
        if previo is None or np.abs(actual.astype(np.int16) - previo).max() > tolerancia:
            previo, desde = actual.astype(np.int16), time.monotonic()
        elif time.monotonic() - desde >= quieto:
            return True
        time.sleep(intervalo)
    return False


# ============================================================================
# Señales declarativas
# ============================================================================
@dataclass
class Senal:
    """
    Una pregunta sobre la pantalla con respuesta booleana (y, si es 'objetivo'/'plantilla',
    un punto donde actuar).
      tipo = presencia  -> contar(caja) >= min_pixeles
             proporcion -> proporcion(caja) >= umbral
             objetivo   -> buscar_objetivo(zona) no es None      (aporta punto de clic)
             plantilla  -> buscar_plantilla(zona) no es None     (aporta punto de clic)
    """
    nombre: str
    tipo: str
    caja: Caja | None = None
    color: RGB | None = None
    tolerancia: int = 0
    min_pixeles: int = 1
    umbral: float = 0.9
    celda: int = 16
    imagen: str | None = None
    _plantilla: np.ndarray | None = field(default=None, repr=False)

    def evaluar(self, frame: np.ndarray):
        """Devuelve (activa: bool, punto: (x, y) | None, detalle: int|float)."""
        if self.tipo == "presencia":
            n = contar(frame, self.caja, self.color, self.tolerancia)
            return n >= self.min_pixeles, None, n
        if self.tipo == "proporcion":
            p = proporcion(frame, self.caja, self.color, self.tolerancia)
            return p >= self.umbral, None, round(p, 3)
        if self.tipo == "objetivo":
            r = buscar_objetivo(frame, self.caja, self.color, self.tolerancia, self.min_pixeles, self.celda)
            return (True, r[:2], r[2]) if r else (False, None, 0)
        if self.tipo == "plantilla":
            if self._plantilla is None:
                from PIL import Image
                self._plantilla = np.asarray(Image.open(self.imagen).convert("RGB"), dtype=np.uint8)
            r = buscar_plantilla(frame, self.caja, self._plantilla, self.umbral)
            return (True, r[:2], round(r[2], 3)) if r else (False, None, 0)
        raise ValueError(f"Tipo de señal desconocido: {self.tipo}")


class Lectura:
    """Evalúa señales sobre UN frame, con caché (cada señal se calcula una vez por ciclo)."""

    def __init__(self, frame: np.ndarray, senales: dict[str, Senal]):
        self.frame, self.senales, self._cache = frame, senales, {}

    def __call__(self, nombre: str):
        if nombre not in self._cache:
            self._cache[nombre] = self.senales[nombre].evaluar(self.frame)
        return self._cache[nombre]

    def activa(self, nombre: str) -> bool:
        return self(nombre)[0]


# ============================================================================
# Motor de reglas
# ============================================================================
@dataclass
class Regla:
    """
    Se evalúan en orden; se ejecuta la PRIMERA cuya condición se cumple.
      si       : señales que deben estar activas (todas)
      si_no    : señales que deben estar inactivas (todas)
      hacer    : "esperar" | {"clic": <señal con punto>} | {"clic_en": [x, y]} | {"tecla": "enter"}
      confirmar: {"senal": <nombre>, "gracia": s}  -> verifica que la acción surtió efecto
    """
    nombre: str
    hacer: object = "esperar"
    si: list[str] = field(default_factory=list)
    si_no: list[str] = field(default_factory=list)
    confirmar: dict | None = None

    def aplica(self, lec: Lectura) -> bool:
        return all(lec.activa(s) for s in self.si) and not any(lec.activa(s) for s in self.si_no)


class Bot:
    def __init__(self, cfg: dict):
        con = cfg["conexion"]
        self.server, self.password = con["server"], con.get("password")
        ritmo = cfg.get("ritmo", {})
        self.pausa_min, self.pausa_max = ritmo.get("min", 1.8), ritmo.get("max", 3.6)
        self.watchdog = cfg.get("watchdog")  # s sin acciones antes de avisar (None = off)
        self.senales = {n: Senal(nombre=n, **_tuplas(d)) for n, d in cfg["senales"].items()}
        self.reglas = [Regla(**r) for r in cfg["reglas"]]
        self._validar()
        self.pendiente = None  # (regla, t_accion) de una acción esperando confirmación
        self.stats = {"acciones": 0, "confirmadas": 0, "en_falso": 0}

    def _validar(self):
        for r in self.reglas:
            usadas = r.si + r.si_no + ([r.confirmar["senal"]] if r.confirmar else [])
            if isinstance(r.hacer, dict) and "clic" in r.hacer:
                usadas.append(r.hacer["clic"])
            for s in usadas:
                if s not in self.senales:
                    raise ValueError(f"Regla '{r.nombre}' usa la señal inexistente '{s}'")

    # --- actuar -------------------------------------------------------------
    def _ejecutar(self, client, regla: Regla, lec: Lectura) -> bool:
        h = regla.hacer
        if h == "esperar":
            return False
        if "clic" in h:
            activa, punto, det = lec(h["clic"])
            if not activa or punto is None:
                return False
            client.mouseMove(*punto)
            client.mousePress(1)
            log(f"[{regla.nombre}] CLIC en {punto} ({h['clic']}: {det})")
        elif "clic_en" in h:
            client.mouseMove(*h["clic_en"])
            client.mousePress(1)
            log(f"[{regla.nombre}] CLIC en {tuple(h['clic_en'])}")
        elif "tecla" in h:
            client.keyPress(h["tecla"])
            log(f"[{regla.nombre}] TECLA {h['tecla']}")
        else:
            raise ValueError(f"Acción desconocida en '{regla.nombre}': {h}")
        return True

    # --- verificar ----------------------------------------------------------
    def _verificar(self, lec: Lectura) -> bool:
        """Devuelve True si hay que esperar (acción en período de gracia sin confirmar)."""
        if not self.pendiente:
            return False
        regla, t = self.pendiente
        senal, gracia = regla.confirmar["senal"], regla.confirmar.get("gracia", 3.0)
        activa, _, det = lec(senal)
        if activa:
            self.stats["confirmadas"] += 1
            log(f"[{regla.nombre}] confirmada ({senal}: {det})")
            self.pendiente = None
            return False
        if time.monotonic() - t < gracia:
            return True
        self.stats["en_falso"] += 1
        log(f"[{regla.nombre}] EN FALSO: '{senal}' no apareció en {gracia}s")
        self.pendiente = None
        return False

    # --- ciclo --------------------------------------------------------------
    def correr(self):
        client = api.connect(self.server, password=self.password)
        ultima_accion, estado_previo = time.monotonic(), None
        try:
            client.mouseMove(0, 0)  # inicializa el puntero (evita que falle el primer clic)
            log(f"Bot iniciado: {len(self.senales)} señales, {len(self.reglas)} reglas. Ctrl+C para salir.")
            while True:
                lec = Lectura(capturar(client), self.senales)
                if self._verificar(lec):
                    estado = "verificando"
                else:
                    regla = next((r for r in self.reglas if r.aplica(lec)), None)
                    estado = regla.nombre if regla else "(ninguna)"
                    if regla and self._ejecutar(client, regla, lec):
                        self.stats["acciones"] += 1
                        ultima_accion = time.monotonic()
                        if regla.confirmar:
                            self.pendiente = (regla, ultima_accion)
                if estado != estado_previo:
                    log(f"estado: {estado}")
                    estado_previo = estado
                if self.watchdog and time.monotonic() - ultima_accion > self.watchdog:
                    log(f"WATCHDOG: {self.watchdog}s sin acciones (estado '{estado}')")
                    ultima_accion = time.monotonic()
                time.sleep(random.uniform(self.pausa_min, self.pausa_max))
        except KeyboardInterrupt:
            print(f"\nFin. {self.stats}")
        finally:
            api.shutdown()


def _tuplas(d: dict) -> dict:
    """Convierte listas YAML a tuplas en caja/color."""
    return {k: (tuple(v) if k in ("caja", "color") and v is not None else v) for k, v in d.items()}


def cargar(ruta: str) -> Bot:
    import yaml
    with open(ruta, encoding="utf-8") as f:
        return Bot(yaml.safe_load(f))


if __name__ == "__main__":
    cargar(sys.argv[1] if len(sys.argv) > 1 else "bot.yaml").correr()

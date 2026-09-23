"""
escena_prueba — simulador para validar bots sin la VM real.

Dibuja en un servidor VNC de prueba (p. ej. Xtigervnc) una aplicación ficticia:
  * un objetivo cyan que aparece en posiciones distintas;
  * una barra de acción (verde sobre rojo oscuro) que se vacía al terminar la acción;
  * cooldown entre acciones;
  * el primer clic se ignora a propósito (simula un clic en falso).
Registra en consola cada evento y dónde cayó cada clic, para compararlo con el log del bot.

Uso (Linux):
    Xtigervnc :50 -geometry 1600x900 -depth 24 -rfbport 5900 -rfbauth ~/.vnc/passwd &
    DISPLAY=:50 python escena_prueba.py &
    python vncbot_base.py bot.yaml
"""
import time
import tkinter as tk

ANCHO, ALTO = 1600, 900
CYAN, VERDE, ROJO, FONDO = "#00FFFF", "#068A35", "#621414", "#222222"
BARRA = (18, 101, 219, 125)               # rectángulo tk (x2, y2 exclusivos)
POSICIONES = [(300, 300), (800, 500), (500, 200)]
RETRASO_ACCION, DURACION_ACCION, COOLDOWN = 1.5, 6.0, 5.0
IGNORAR_CLICS = {1}                       # números de clic que el "juego" ignora

T0 = time.time()


def evento(msg):
    print(f"{time.time() - T0:6.1f} [escena] {msg}", flush=True)


class Escena:
    def __init__(self, duracion=60):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry(f"{ANCHO}x{ALTO}+0+0")
        self.c = tk.Canvas(self.root, width=ANCHO, height=ALTO, bg=FONDO, highlightthickness=0)
        self.c.pack()
        self.obj = self.barra = None
        self.n_clic = self.n_obj = 0
        self.en_accion = False
        self.c.bind("<Button-1>", self.clic)
        self.root.after(1000, self.aparecer)
        self.root.after(int(duracion * 1000), self.root.destroy)

    def aparecer(self):
        x, y = POSICIONES[self.n_obj % len(POSICIONES)]
        self.n_obj += 1
        self.obj = self.c.create_oval(x, y, x + 70, y + 50, fill=CYAN, outline="")
        evento(f"objetivo APARECE en ({x + 35},{y + 25})")

    def clic(self, e):
        self.n_clic += 1
        sobre = self.obj is not None and self.obj in self.c.find_overlapping(e.x, e.y, e.x, e.y)
        lugar = "sobre objetivo" if sobre else "FUERA"
        if self.en_accion:
            evento(f"clic #{self.n_clic} ({e.x},{e.y}) DURANTE la acción  <-- error del bot")
        elif self.n_clic in IGNORAR_CLICS:
            evento(f"clic #{self.n_clic} ({e.x},{e.y}) {lugar} -> IGNORADO (clic en falso simulado)")
        elif sobre:
            evento(f"clic #{self.n_clic} ({e.x},{e.y}) {lugar} -> acción inicia en {RETRASO_ACCION}s")
            self.en_accion = True
            self.root.after(int(RETRASO_ACCION * 1000), self.iniciar_accion)
        else:
            evento(f"clic #{self.n_clic} ({e.x},{e.y}) {lugar}")

    def iniciar_accion(self):
        self.c.create_rectangle(*BARRA, fill=ROJO, outline="")
        self.barra = self.c.create_rectangle(*BARRA, fill=VERDE, outline="")
        evento("barra VERDE (acción en curso)")
        self.vaciar(BARRA[2] - BARRA[0], time.time())

    def vaciar(self, ancho_total, t_ini):
        restante = 1 - (time.time() - t_ini) / DURACION_ACCION
        if restante <= 0:
            return self.terminar()
        x1, y1, _, y2 = BARRA
        self.c.coords(self.barra, x1, y1, x1 + max(1, int(ancho_total * restante)), y2)
        self.root.after(200, self.vaciar, ancho_total, t_ini)

    def terminar(self):
        self.c.delete(self.barra)
        self.c.delete(self.obj)
        self.obj, self.en_accion = None, False
        evento(f"acción TERMINA, cooldown {COOLDOWN}s")
        self.root.after(int(COOLDOWN * 1000), self.aparecer)


if __name__ == "__main__":
    import sys
    Escena(float(sys.argv[1]) if len(sys.argv) > 1 else 60).root.mainloop()

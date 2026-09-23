"""
VISOR — se ejecuta en tu PC LOCAL. No se instala nada en la VM.

Abre una ventana con la pantalla de la VM (vía VNC). Al pasar el mouse
por encima, el título de la ventana muestra en vivo las coordenadas DE LA
VM y el color RGB de ese píxel; en el cmd solo se imprime al presionar F6.
Las coordenadas sirven directo para mouseMove() y para ZONA/BOX.

Teclas (con la ventana enfocada):
  F6   imprime en el cmd la posición y el color bajo el mouse
  F7   activa/desactiva mover el cursor real de la VM junto con el tuyo
  Esc  salir

pip install vncdotool pillow
"""
import queue
import threading
import time
import tkinter as tk

from PIL import ImageTk
from vncdotool import api

SERVER = "localhost::5900"
PASSWORD = "123456"
FPS_VISOR = 30            # refresco de la ventana
MOVER_CURSOR_VM = False   # F7 lo cambia en vivo


class Visor:
    def __init__(self):
        self.client = api.connect(SERVER, password=PASSWORD)
        self.frame = None                 # última captura (PIL RGB, resolución real)
        self.lock = threading.Lock()
        self.movimientos = queue.Queue()  # movimientos a enviar a la VM
        self.vivo = True
        self.mover = MOVER_CURSOR_VM
        self.pos = None
        self.ultimo = None
        self.marcas = 0

        threading.Thread(target=self._capturar, daemon=True).start()
        while self.frame is None:         # espera el primer frame
            time.sleep(0.05)

        self.root = tk.Tk()
        w, h = self.frame.size
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        # Si la VM es más grande que tu pantalla se muestra reducida,
        # pero las coordenadas y el color se leen siempre a tamaño real.
        self.escala = min(1.0, sw * 0.9 / w, sh * 0.85 / h)
        self.vw, self.vh = int(w * self.escala), int(h * self.escala)

        self.canvas = tk.Canvas(self.root, width=self.vw, height=self.vh,
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack()
        self.img_id = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: setattr(self, "pos", None))
        self.root.bind("<F6>", self._marcar)
        self.root.bind("<F7>", self._toggle_mover)
        self.root.bind("<Escape>", lambda e: self.cerrar())
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

        print(f"Visor abierto: VM {w}x{h}"
              + (f" (mostrada al {self.escala:.0%})" if self.escala < 1 else "")
              + ". Pasa el mouse sobre la ventana y presiona F6 para imprimir el píxel."
              + "  F7 mueve cursor VM, Esc sale.",
              flush=True)
        self._pintar()
        self.root.mainloop()

    # --- hilo único que habla con el servidor VNC
    def _capturar(self):
        while self.vivo:
            try:
                ultimo_mov = None
                while not self.movimientos.empty():
                    ultimo_mov = self.movimientos.get_nowait()
                if ultimo_mov:
                    self.client.mouseMove(*ultimo_mov)
                self.client.refreshScreen()
                with self.lock:
                    self.frame = self.client.screen.copy()
            except Exception as e:
                if self.vivo:
                    print("Error VNC:", e, flush=True)
                    time.sleep(1)

    # --- refresco de la ventana y lectura del color
    def _pintar(self):
        if not self.vivo:
            return
        with self.lock:
            frame = self.frame
        vista = frame if self.escala == 1 else frame.resize((self.vw, self.vh))
        self.tkimg = ImageTk.PhotoImage(vista)
        self.canvas.itemconfig(self.img_id, image=self.tkimg)

        if self.pos:
            x, y = self.pos
            if x < frame.width and y < frame.height:
                rgb = frame.getpixel((x, y))
                lectura = (x, y, rgb)
                if lectura != self.ultimo:          # solo el título se actualiza en vivo
                    self.ultimo = lectura
                    self.root.title(self._texto(*lectura))
        self.root.after(int(1000 / FPS_VISOR), self._pintar)

    @staticmethod
    def _texto(x, y, rgb):
        return f"VM  x={x:5d}  y={y:5d}   RGB={rgb}   #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

    def _on_motion(self, e):
        self.pos = (int(e.x / self.escala), int(e.y / self.escala))
        if self.mover:
            self.movimientos.put(self.pos)

    def _marcar(self, _e):
        """F6: imprime en el cmd la lectura del píxel bajo el mouse (frame más reciente)."""
        if not self.pos:
            print("F6: pon el mouse sobre la ventana del visor", flush=True)
            return
        with self.lock:
            frame = self.frame
        x, y = self.pos
        if x >= frame.width or y >= frame.height:
            return
        self.marcas += 1
        print(f"#{self.marcas:<3d} {self._texto(x, y, frame.getpixel((x, y)))}", flush=True)

    def _toggle_mover(self, _e):
        self.mover = not self.mover
        print(f"Mover cursor de la VM: {'ACTIVADO' if self.mover else 'desactivado'}", flush=True)

    def cerrar(self):
        self.vivo = False
        self.root.destroy()
        api.shutdown()  # detiene el hilo VNC y cierra la conexión


if __name__ == "__main__":
    Visor()

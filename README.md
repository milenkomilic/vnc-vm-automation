# Metodología de Bots por VNC

**Percibir → Decidir → Actuar → Verificar**

Metodología y código base para automatizar aplicaciones gráficas que corren dentro de una máquina virtual (VMware Workstation), controlándolas **desde afuera** mediante VNC, sin instalar nada dentro de la VM.

El bot observa la pantalla de la VM por VNC, detecta señales por color o por imagen, decide con reglas por prioridad, actúa con mouse o teclado y **verifica** que cada acción surtió efecto (detección de clics en falso con período de gracia).

## Estructura

```
vnc-bot-metodologia/
├── docs/
│   ├── Metodologia_Bots_VNC.md     # documentación completa (también para dar contexto a IAs)
│   ├── Metodologia_Bots_VNC.docx   # la misma documentación en Word
│   └── diagramas/                  # diagramas en PNG
├── vncbot/
│   ├── vncbot_base.py              # motor genérico: primitivas + señales + reglas + YAML
│   └── bot.yaml                    # ejemplo: bot "objetivo cyan con barra de confirmación"
├── herramientas/
│   ├── visor_vm.py                 # calibración: F6 imprime coordenadas de la VM y RGB
│   └── escena_prueba.py            # simulador para probar bots sin la VM real
├── ejemplos/
│   └── vnc_bot.py                  # versión autónoma del bot de ejemplo (sin YAML)
└── requirements.txt
```

## Inicio rápido

**1. Instalar dependencias**

```bash
pip install -r requirements.txt
```

**2. Habilitar VNC en la VM** (archivo `.vmx`, con la VM apagada)

```
RemoteDisplay.vnc.enabled = "TRUE"
RemoteDisplay.vnc.port = "5900"
RemoteDisplay.vnc.password = "tu_clave"
```

**3. Calibrar** colores y coordenadas con el visor (ajustar `SERVER` y `PASSWORD` al inicio del archivo):

```bash
python herramientas/visor_vm.py
```

Pasa el mouse sobre la ventana y presiona **F6** para imprimir `x`, `y` y `RGB` del píxel en coordenadas de la VM.

**4. Describir el bot** en un YAML (ver `vncbot/bot.yaml` y el Anexo B de la documentación).

**5. Ejecutar**

```bash
python vncbot/vncbot_base.py vncbot/bot.yaml
```

## Ejemplo de configuración

```yaml
senales:
  accion_en_curso: {tipo: presencia, caja: [18, 101, 218, 124], color: [6, 138, 53], tolerancia: 5}
  objetivo:        {tipo: objetivo,  caja: [6, 36, 1238, 801],  color: [0, 255, 255], tolerancia: 5, min_pixeles: 15}

reglas:                                   # se ejecuta la primera que aplica
  - {nombre: accion_en_curso, si: [accion_en_curso], hacer: esperar}
  - {nombre: clic_objetivo, si: [objetivo], hacer: {clic: objetivo},
     confirmar: {senal: accion_en_curso, gracia: 3.0}}
  - {nombre: cooldown, hacer: esperar}
```

## Documentación

La documentación completa está en [`docs/Metodologia_Bots_VNC.md`](docs/Metodologia_Bots_VNC.md):

- fundamentos de VNC/RFB, vncdotool y VMware;
- arquitectura y máquina de estados;
- catálogo de primitivas (P-01 a P-14) y tipos de señal (S-01 a S-04);
- metodología de desarrollo paso a paso;
- capacidades, limitaciones y estructuras futuras;
- buenas prácticas, lecciones aprendidas y tabla de diagnóstico;
- código completo en los anexos.

## Requisitos

- Python 3.10+
- VMware Workstation / Player / Fusion con VNC habilitado (ESXi 7+ no tiene VNC nativo)
- Opcional: `opencv-python` para señales por plantilla

## Uso responsable

Usar en aplicaciones propias, con autorización, o en entornos de prueba. Muchas aplicaciones y servicios en línea prohíben la automatización en sus términos de uso. VNC transmite sin cifrado: usarlo solo en `localhost`, en una red de gestión o sobre un túnel SSH.

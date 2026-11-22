# 🦖📺 T-Rex Bites

**Tu propio canal de televisión de los 2000, en casa.**

T-Rex Bites convierte cualquier computador viejo en una tele con canales,
horarios y programación propia. Tú subes los programas desde el teléfono y la
tele los va pasando sola, como un canal de verdad: prendes y ya hay algo dando.

- 📼 **Canales con horario**: dibujos en la mañana, películas en la tarde y
  "fin de transmisión" en la noche.
- 📱 **Se administra desde el teléfono o el PC** en `http://trexbites.local`:
  control remoto, subir videos, borrar programas y PIN de padres.
- 💿 **Se instala solo**: un USB, dos confirmaciones y listo. No hay que saber Linux.
- 🏠 **100 % local**: todo queda en el disco del equipo, sin internet ni cuentas.

> Funciona sobre [FieldStation42](https://github.com/shane-mason/FieldStation42),
> un simulador de TV abierta y cable hecho por Shane Mason. Ver [NOTICE.md](NOTICE.md).

---

## Instalar en un computador

### 1. Crear el USB (una sola vez)

En un computador con Linux (o WSL en Windows):

```bash
sudo apt install xorriso curl
./iso/build-iso.sh
```

Queda el archivo `iso/out/trexbites.iso`. Grábalo en un USB (de 2 GB o más) con
[balenaEtcher](https://etcher.balena.io/).

Opciones útiles al crear el USB:

```bash
# WiFi de la casa (para instalar sin cable de red)
TREX_WIFI_SSID="MiWifi" TREX_WIFI_PASSWORD="clave" ./iso/build-iso.sh

# Otro país o teclado (por defecto: Chile y teclado latinoamericano)
TREX_LOCALE=es_AR.UTF-8 TREX_TIMEZONE=America/Argentina/Buenos_Aires ./iso/build-iso.sh
TREX_LOCALE=es_ES.UTF-8 TREX_KEYMAP=es TREX_TIMEZONE=Europe/Madrid ./iso/build-iso.sh
```

### 2. Instalar

> ⚠️ **La instalación borra todo el disco del computador.**

1. Conecta el USB y el cable de red (o usa un USB creado con tu WiFi).
2. Prende el computador y elige arrancar desde el USB. Según la marca, hay que
   presionar **F12**, **F9**, **F2**, **Esc** o **Novo** (Lenovo) al encenderlo.
3. Elige **Instalar T-Rex Bites** y luego **Sí, borrar el disco e instalar**.
4. Espera de 15 a 40 minutos, según el equipo y la velocidad de internet. El
   computador se reinicia solo y aparece la tele.

### 3. Usar

Desde un teléfono o un PC conectado al mismo WiFi, abre **http://trexbites.local**.
El PIN de fábrica es **1234** y el panel te pide cambiarlo la primera vez.

Para tenerlo como app en el teléfono, en el navegador usa
**"Agregar a pantalla de inicio"**.

| Pestaña | Para qué |
|---|---|
| 🎮 **Control** | Control remoto: canal, volumen, guía y botones directos a cada canal |
| 📤 **Subir** | Subir videos a un canal y categoría (con barra de progreso) |
| 📚 **Programas** | Ver y borrar los videos de cada canal |
| 🗓 **Horarios** | **Hora de dormir** (apagado automático, "apagar hasta mañana", "1 hora extra") y **grilla semanal** de cada canal: eliges un pincel (categoría, fin de transmisión o apagado) y tocas las horas |
| ☰ **Más** | Crear y editar **canales** y sus categorías, **qué se vio** cada día, PIN y opciones avanzadas |

---

## ¿En qué computadores funciona?

| Equipo | ¿Funciona? |
|---|---|
| Notebooks y PCs de 64 bits (aprox. 2008 en adelante) | ✅ |
| Mini PCs (Intel NUC, Beelink, etc.) | ✅ |
| Mac con procesador Intel | ⚠️ En general sí; el WiFi puede fallar |
| CPUs muy antiguas sin SSE4.1 (Core 2, Atom de 1ª gen., AMD E-350) | ⚠️ Ver [docs/HARDWARE.md](docs/HARDWARE.md) |
| Raspberry Pi | 🔜 Planeado (otra imagen) |
| PCs de 32 bits, Mac M1/M2, tablets, celulares, Smart TV | ❌ (los celulares sirven como control remoto) |

Requisitos mínimos recomendados: 2 GB de RAM (4 GB ideal) y 32 GB de disco.

---

## Cómo está hecho

```
USB T-Rex Bites
 └─ Instalador de Debian 13 automático (iso/)
     └─ Debian mínimo, sin escritorio
         ├─ Arranca directo en la tele (usuario "tv", sin login)
         ├─ FieldStation42 + mpv  → la imagen en pantalla      (/opt/trexbites/fieldstation42)
         ├─ Panel web T-Rex Bites → http://trexbites.local    (/opt/trexbites/panel)
         └─ Videos en el disco local                          (/srv/trexbites/catalog)
```

| Carpeta | Qué hay |
|---|---|
| `iso/` | Generador del USB: instalación de Debian preconfigurada y menús de arranque |
| `system/` | Instalador que convierte un Debian mínimo en la tele, más los canales por defecto |
| `panel/` | Panel web (FastAPI + HTML) para el teléfono y el PC |
| `upstream/` | Versión exacta de FieldStation42 que se usa |
| `docs/` | Documentación adicional |

### Canales por defecto

| Canal | Tipo | Qué pasa |
|---|---|---|
| **3 · T-Rex TV** | Con horario | 7–10 h *Mañana*, 10–13 h *Dibujos*, 13–15 h *Educativos*, 15–18 h *Dibujos*, 18 h *Películas*, 20 h fin de transmisión |
| **5 · Dino Loop** | Repetición continua | Todos sus videos en loop, a cualquier hora |

Los horarios y canales se pueden cambiar en la consola avanzada de
FieldStation42 (`http://trexbites.local:4242`, enlazada desde Ajustes).

### Instalar en un Debian que ya tienes

```bash
git clone https://github.com/vanttacode/T-Rex-bites.git
sudo ./T-Rex-bites/system/install-trexbites.sh
```

### Desarrollo del panel

```bash
cd panel
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
# probar la interfaz sin tele (el control remoto dirá "La tele no responde")
mkdir -p /tmp/fs42 && cp -r ../system/defaults/confs /tmp/fs42/
TREXBITES_FS42_DIR=/tmp/fs42 TREXBITES_STATE=/tmp/fs42/panel.json uvicorn trexbites_panel.app:app --reload
```

---

## Estado

Primera versión (base). Ver [docs/ROADMAP.md](docs/ROADMAP.md) para lo que falta.

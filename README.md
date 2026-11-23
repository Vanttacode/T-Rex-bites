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

### 1. Descargar el USB (una sola vez)

1. Entra a la sección **[Releases](../../releases)** del repositorio y descarga
   `trexbites-vX.Y.Z.iso` (unos 1,6 GB).
2. Grábalo en un USB **de 4 GB o más** con [balenaEtcher](https://etcher.balena.io/)
   (Windows, Mac o Linux).

El USB **trae todo**: Debian, los drivers, FieldStation42, el panel y las librerías.
**El computador no necesita internet para instalarse.**

<details>
<summary>Crear el USB uno mismo (avanzado)</summary>

En Linux con Docker (o WSL en Windows), con internet y unos 4 GB libres:

```bash
sudo apt install xorriso curl docker.io
./iso/build-iso.sh
```

Queda `iso/out/trexbites.iso`. Opciones:

```bash
# Guardar el WiFi de la casa en la tele (¡no publiques un USB con tu clave!)
TREX_WIFI_SSID="MiWifi" TREX_WIFI_PASSWORD="clave" ./iso/build-iso.sh

# Otro país o teclado (por defecto: Chile y teclado latinoamericano)
TREX_LOCALE=es_AR.UTF-8 TREX_TIMEZONE=America/Argentina/Buenos_Aires ./iso/build-iso.sh
TREX_LOCALE=es_ES.UTF-8 TREX_KEYMAP=es TREX_TIMEZONE=Europe/Madrid ./iso/build-iso.sh

# USB pequeño (~800 MB) que descarga todo durante la instalación
TREX_OFFLINE=0 ./iso/build-iso.sh
```

Publicar una versión nueva: crear una etiqueta `vX.Y.Z` (`git tag v0.2.0 && git push --tags`).
GitHub Actions arma el USB y lo publica en Releases automáticamente.
</details>

### 2. Instalar

El USB ofrece dos formas de instalar:

| Opción del menú | Para qué |
|---|---|
| **Instalar T-Rex Bites** | Computador dedicado a la tele. ⚠️ **Borra todo el disco.** |
| **Instalar al lado de otro Linux** | Computador con Fedora, Ubuntu, etc. que quieres conservar. Usa solo el espacio sin asignar y no toca tu Linux; después un comando agrega T-Rex Bites a su menú. Ver [la guía](docs/INSTALAR-JUNTO-A-OTRO-SISTEMA.md). |
| **Instalar al lado de Windows** | Igual, junto a Windows; el menú de T-Rex Bites lista Windows. Ver [la guía](docs/INSTALAR-JUNTO-A-OTRO-SISTEMA.md). |

Pasos para un computador dedicado:

1. Conecta el USB. No hace falta internet ni cable de red.
2. Prende el computador y elige arrancar desde el USB. Según la marca, hay que
   presionar **F12**, **F9**, **F2**, **Esc** o **Novo** (Lenovo) al encenderlo.
3. Elige **Instalar T-Rex Bites** y luego **Sí, borrar el disco e instalar**.
4. Espera unos 15 a 30 minutos. El computador se reinicia solo y aparece la tele.
5. **Configura el WiFi.** La tele muestra *"Configura el WiFi de T-Rex Bites"* con tres formas:
   - **Con el teclado del computador:** elige tu red con las flechas, escribe la clave y Enter.
   - **Con cable de red:** se conecta solo.
   - **Con el teléfono** (si la tarjeta WiFi del computador puede crear su propia red):
   - La tele muestra *"Configura el WiFi de T-Rex Bites"*.
   - En tu teléfono, conéctate a la red WiFi **"T-Rex Bites Config"** (sin clave).
   - Se abre sola la página de configuración (si no, entra a `http://10.42.0.1`).
   - PIN **1234** → elige tu WiFi de casa → escribe su clave → **Conectar**.
   - Vuelve a conectar el teléfono a tu WiFi de casa y entra a `http://trexbites.local`.
     La tele muestra en pantalla su dirección por si `.local` no funciona.

   Si después cambias de router o de clave, la tele vuelve a abrir la red
   "T-Rex Bites Config" sola (sin dejar de pasar los canales), y repites el paso.
   Con cable de red no hace falta configurar nada.

### 3. Usar

Desde un teléfono o un PC conectado al mismo WiFi, abre **http://trexbites.local**.
El PIN de fábrica es **1234** y el panel te pide cambiarlo la primera vez.

Para tenerlo como app en el teléfono, en el navegador usa
**"Agregar a pantalla de inicio"**.

El panel tiene **4 secciones**: en el teléfono están abajo y en el computador en un menú lateral.

| Sección | Para qué |
|---|---|
| 🎮 **Control** | Control remoto: canal, volumen, guía y botones con el logo de cada canal |
| 📚 **Biblioteca** | Todos los videos en **categorías y programas**. Creas carpetas con **＋**, arrastras videos a una carpeta para subirlos, eliges varios para moverlos o borrarlos, e importas desde un pendrive |
| 📺 **Canales** | Una página por canal con 4 pestañas: **Programación** (qué pasa, o la línea de tiempo por hora), **Comerciales** (tandas, pautas y sus videos), **Apariencia** (logo, cortinillas y videos fijos) y **Ajustes** (nombre, número, PIN, duplicar, borrar). **＋ Nuevo canal** te guía en 3 pasos |
| ⚙️ **Ajustes** | WiFi, hora de dormir, estática, conversión y volumen, canal guía, respaldo, actualizaciones, qué se vio y PIN |

**Cómo se organiza (versión 0.6):**

- 📚 **Una biblioteca para toda la tele**, con categorías y programas, por ejemplo *Videos musicales → Oliver Tree* o *Dibujos animados → Bluey*. Subes un video una sola vez y lo usa cualquier canal.
- 📺 **Dos tipos de canal**, que eligen qué pasar de la biblioteca:
  - **🔁 Todo el día:** una o varias categorías o programas, al azar o en orden.
  - **🗓 Con horario:** bloques por hora en el editor de programación.
- Cada canal tiene **lo suyo**: logo, comerciales y pautas, cortinillas, videos fijos y PIN.
- En **Programas** eliges varios videos con casillas y los **mueves o borras juntos**.
- Al actualizar desde una versión anterior, tus videos se **mudan solos** a la biblioteca: se mueven en el mismo disco, sin copiar ni borrar nada.

**Otras funciones (desde la 0.5):**

- 📺 **Pautas comerciales** por bloque, y comerciales que salen solo en un **momento**: mañana, noche, un día o un mes.
- 📌 **Videos fijos** al empezar o terminar un bloque, y 🎬 **cortinillas** propias.
- 📡 **Estática** al cambiar de canal, y 🗒 **canal guía** estilo cable.
- 🔒 **Canales con PIN**.
- ⚙️ **Conversión automática** de videos pesados y 🔊 **volumen parejo**.
- 💾 **Importar desde pendrive** y **respaldo** de la configuración.
- 📱 **Ver un canal en otro aparato** en `http://trexbites.local/ver`.

### Programación por hora (en el computador)

En **Canales → un canal "Con horario" → Programación**, desde un computador:
una **línea de tiempo semanal** (días en filas, horas en columnas) donde cada
programa es un bloque de color.

- **Crear:** eliges un contenido en la paleta y arrastras sobre la línea de tiempo.
- **Mover / alargar:** arrastras el bloque (también a otro día) o sus bordes.
- **Cada bloque:** una o varias categorías (🎲 mezcla al azar), 🔁 capítulos en
  orden (sigue donde quedó), duración de los videos (cortos, episodios, películas)
  y estilo de la tanda de comerciales.
- **Herramientas:** copiar un día a otros, programación al azar, duplicar el canal
  (con los mismos videos o con videos propios), deshacer/rehacer y guardar (Ctrl+S).

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
         └─ Biblioteca de videos en el disco local            (/srv/trexbites/catalog/biblioteca)
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
| **3 · T-Rex TV** | 🗓 Con horario | 7–10 h *Mañana*, 10–13 h *Dibujos*, 13–15 h *Educativos*, 15–18 h *Películas* y *Dibujos*, 18 h *Películas*, 20 h fin de transmisión |
| **5 · Dino Loop** | 🔁 Todo el día | *Dibujos animados* al azar, a cualquier hora |

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

Versión 0.6 (beta). Ver [docs/ROADMAP.md](docs/ROADMAP.md) para lo que falta.

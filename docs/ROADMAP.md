# Hoja de ruta

## ✅ Fase 1: base (esta versión)

- USB instalador automático (Debian 13 + preseed, BIOS y UEFI) con confirmación
  antes de borrar el disco.
- Instalador del sistema: arranque directo a la tele, sin suspensión, `trexbites.local`.
- FieldStation42 fijado a una versión exacta.
- Canales por defecto: *T-Rex TV* (con horario y fin de transmisión) y *Dino Loop*.
- Videos de ejemplo con la dirección del panel, para que la tele nunca quede en negro.
- Panel web: PIN de padres, control remoto, subir videos (con progreso),
  biblioteca para borrar y espacio libre en disco.

## 🔜 Fase 2: primera prueba en hardware real

- [ ] Instalar en el notebook Lenovo y anotar qué falla (WiFi, video, sonido).
- [x] Mostrar en la tele la IP del equipo cuando `trexbites.local` no funcione.
- [x] Configurar y cambiar la red WiFi desde el teléfono (red "T-Rex Bites Config" + portal cautivo).
- [ ] Convertir automáticamente los videos pesados a un formato liviano
      (H.264 720p) para equipos lentos.

## 🎨 Fase 3: look de los 2000

- [x] Logo en la esquina (mosca de canal), propio por canal, y número de canal al cambiar.
- [x] Comerciales propios por canal: al final, repartidos o a la mitad del programa.
- [ ] Cortinillas y "bumpers" propios entre programas.
- [ ] Estática y sonido al cambiar de canal.
- [ ] Guía de programación con estilo cable de los 2000.
- [ ] Pantalla de "fin de transmisión" T-Rex.

## 👨‍👧 Fase 4: para padres

- [x] Editor de programación en el computador: línea de tiempo semanal con bloques, capítulos en orden, mezclas al azar, duración de videos, tandas por bloque, copiar días, programación al azar y duplicar canal.
- [ ] Bloques de media hora y programación por fecha (feriados, cumpleaños).
- [x] Hora de dormir: apagado automático con pantalla "¡A dormir!", "Apagar hasta mañana" y "1 hora extra".
- [x] Crear, renombrar, renumerar y borrar canales, con sus categorías.
- [x] Historial: qué pasó la tele cada día y cuántos minutos.
- [x] Botón "Actualizar T-Rex Bites" en el panel (desde GitHub Releases) y actualizaciones de seguridad automáticas.
- [ ] Límite diario de minutos (necesita un botón de encendido: control remoto físico).
- [ ] Ver el canal en vivo desde el navegador (otra tele de la casa).
- [ ] Imagen para Raspberry Pi.

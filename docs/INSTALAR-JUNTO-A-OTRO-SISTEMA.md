# Instalar T-Rex Bites al lado de otro sistema

Sirve para un computador que ya tiene Linux (o Windows) y que quieres **seguir
usando**. T-Rex Bites se instala en el **espacio libre sin particionar** del
disco y no toca las particiones que ya existen. Al prender el computador aparece
un menú para elegir:

```
  Debian GNU/Linux            ← T-Rex Bites (la tele)
  Opciones avanzadas
  Mi Linux (en /dev/sda1)     ← tu sistema de siempre
```

El menú espera 8 segundos y, si no eliges nada, arranca T-Rex Bites.

> ⚠️ **Antes de empezar, haz una copia de seguridad de tus archivos importantes.**
> El instalador no toca tus particiones, pero cambiar particiones de un disco
> siempre tiene riesgo (un corte de luz, un disco con fallas).

## 1. ¿Tu espacio libre está "sin particionar"?

Hay dos tipos de "espacio libre" y el instalador solo puede usar uno:

| Lo que ves | ¿Sirve tal cual? |
|---|---|
| **Espacio sin asignar** ("unallocated") fuera de tus particiones | ✅ Sí, el instalador lo usa directo |
| Espacio libre **dentro** de tu partición de Linux (lo que muestra el explorador de archivos o `df -h`) | ❌ Primero hay que **achicar** tu partición para liberarlo (paso 2) |

Para verlo, en tu Linux abre una terminal y ejecuta:

```bash
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT
sudo fdisk -l
```

O instala y abre **GParted** (`sudo apt install gparted`): el espacio sin
particionar aparece en gris como **"sin asignar"** / **"unallocated"**.

Lo más común es que tu terabyte libre esté **dentro** de tu partición, y entonces
hay que hacer el paso 2.

## 2. Liberar espacio (solo si no tienes espacio sin asignar)

Una partición en uso no se puede achicar, así que se hace desde un USB "vivo":

1. Descarga **GParted Live** (https://gparted.org/livecd.php) y grábalo en un USB
   con balenaEtcher.
2. Arranca el computador desde ese USB.
3. En GParted, clic derecho en tu partición de Linux (la grande, `ext4`) →
   **Redimensionar/Mover**.
4. Achícala dejando **al menos 100 GB libres a la derecha** (para T-Rex Bites y los
   videos; con 1 TB libre puedes dejarle 300–500 GB).
5. **Aplicar** (✓) y espera a que termine. Puede tardar.
6. Reinicia y comprueba que tu Linux sigue arrancando bien.

> Si tu Linux usa **LVM** o **cifrado** (por ejemplo, Ubuntu con "cifrar el disco"),
> achicar es más delicado: pide ayuda antes de hacerlo.

## 3. Instalar

1. Graba `trexbites.iso` en un USB y arranca desde él.
2. Elige **"Instalar al lado de otro sistema (usa el espacio libre)"**.
3. Baja a **"Sí, instalar T-Rex Bites en el espacio libre"** y Enter.
4. Espera de 15 a 30 minutos. Se reinicia solo.

Si el disco **no tiene espacio sin asignar**, el instalador se detiene y te
muestra un mensaje en vez de borrar algo: apaga el computador y haz el paso 2.

## Notas

- Si el computador tiene **más de un disco**, el instalador puede preguntarte
  cuál usar.
- El menú de arranque lo instala T-Rex Bites. Si alguna vez actualizas tu otro
  Linux y el menú cambia, los dos sistemas siguen ahí.
- Para que el computador arranque directo en tu otro sistema por defecto, se
  puede cambiar después (pide ayuda; es un cambio de una línea).

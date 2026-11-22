# Instalar T-Rex Bites al lado de otro sistema

Sirve para un computador que ya tiene Linux (o Windows) y que quieres **seguir
usando**. T-Rex Bites se instala en el **espacio libre sin particionar** del
disco y no toca las particiones que ya existen. Al prender el computador aparece
un menú para elegir entre T-Rex Bites y tu sistema de siempre.

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

> **Arranca el USB en el mismo modo que tu sistema.** Si tu Linux no tiene
> partición EFI (como un Fedora con una partición de 1 MiB al inicio), arranca el
> USB en modo **Legacy/BIOS**. Si tiene partición EFI (`/boot/efi`), en modo **UEFI**.
> En el menú de arranque del computador (F12, F9, Esc…) el USB suele aparecer dos
> veces: la entrada con "UEFI" es el modo UEFI y la otra es Legacy.

### Al lado de otro Linux (Fedora, Ubuntu, Mint…)

1. Graba `trexbites.iso` en un USB y arranca desde él.
2. Elige **"Instalar al lado de otro Linux"** → **"Sí, instalar T-Rex Bites en el espacio libre"**.
3. Espera de 15 a 30 minutos. Al terminar se reinicia y **arranca tu Linux como siempre**
   (el instalador no toca su menú de arranque, para no arriesgar tu sistema).
4. En tu Linux, abre una terminal y ejecuta:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Vanttacode/T-Rex-bites/main/system/agregar-al-menu.sh | sudo bash
   ```

   Busca la partición de T-Rex Bites y la agrega al menú de arranque de tu Linux.
   Para que **T-Rex Bites arranque por defecto** (útil si el computador queda al lado de la tele):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Vanttacode/T-Rex-bites/main/system/agregar-al-menu.sh | sudo bash -s -- --por-defecto
   ```

5. Reinicia: verás el menú 10 segundos con **"T-Rex Bites"** y tu Linux.

Para quitarlo del menú: el mismo comando con `--quitar`.

### Al lado de Windows

1. Arranca desde el USB y elige **"Instalar al lado de Windows"** → **"Sí"**.
2. Al reiniciar aparece el menú de T-Rex Bites con Windows en la lista
   (espera 8 segundos y, si no eliges nada, arranca T-Rex Bites).

## Notas

- Si el computador tiene **más de un disco**, el instalador puede preguntarte
  cuál usar.
- Al lado de otro Linux, el menú es el de **tu** Linux: sus actualizaciones no
  borran la entrada de T-Rex Bites, y las de T-Rex Bites tampoco la rompen
  (apunta a `/vmlinuz`, que siempre es su kernel actual).
- Al lado de Windows, el menú es el de T-Rex Bites.

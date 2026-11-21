#!/usr/bin/env bash
# Builds iso/out/trexbites.iso: the official Debian 13 netinst image plus an
# automatic install of T-Rex Bites. Write it to a USB stick (balenaEtcher,
# Raspberry Pi Imager, or dd) and boot any 64-bit PC from it.
#
# Needs: bash, curl, xorriso, sha256sum   (Debian/Ubuntu: sudo apt install xorriso curl)
#
# Optional settings (environment variables):
#   TREX_LOCALE=es_CL.UTF-8      language and country of the installed system
#   TREX_KEYMAP=latam            keyboard layout (es = Spain, latam = Latin America, us)
#   TREX_TIMEZONE=America/Santiago
#   TREX_TV_PASSWORD=trexbites   password of the "tv" maintenance account
#   TREX_WIFI_SSID / TREX_WIFI_PASSWORD
#                                home WiFi, so the install works without a cable
#   DEBIAN_ISO=/path/to/debian-13.x-amd64-netinst.iso   use an already downloaded image
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ISO_DIR="$REPO/iso"
WORK="$ISO_DIR/build"
OUT="$ISO_DIR/out"
DEBIAN_CD_URL="${DEBIAN_CD_URL:-https://cdimage.debian.org/debian-cd/current/amd64/iso-cd}"

LOCALE="${TREX_LOCALE:-es_CL.UTF-8}"
KEYMAP="${TREX_KEYMAP:-latam}"
TIMEZONE="${TREX_TIMEZONE:-America/Santiago}"
TV_PASSWORD="${TREX_TV_PASSWORD:-trexbites}"
WIFI_SSID="${TREX_WIFI_SSID:-}"
WIFI_PASSWORD="${TREX_WIFI_PASSWORD:-}"

for cmd in curl xorriso sha256sum; do
    command -v "$cmd" >/dev/null || { echo "Falta '$cmd'. Instálalo (ej: sudo apt install xorriso curl)." >&2; exit 1; }
done

mkdir -p "$WORK" "$OUT"

# ---------------------------------------------------------------------------
# 1. Official Debian netinst image, verified against Debian's checksums
if [ -n "${DEBIAN_ISO:-}" ]; then
    BASE_ISO="$DEBIAN_ISO"
else
    echo ">>> Buscando la última imagen netinst de Debian"
    curl -fsSL "$DEBIAN_CD_URL/SHA256SUMS" -o "$WORK/SHA256SUMS"
    ISO_NAME=$(grep -oE 'debian-[0-9.]+-amd64-netinst\.iso' "$WORK/SHA256SUMS" | head -n1)
    [ -n "$ISO_NAME" ] || { echo "No encontré la imagen netinst en $DEBIAN_CD_URL" >&2; exit 1; }
    BASE_ISO="$WORK/$ISO_NAME"
    if [ ! -f "$BASE_ISO" ]; then
        echo ">>> Descargando $ISO_NAME"
        curl -fL --retry 4 "$DEBIAN_CD_URL/$ISO_NAME" -o "$BASE_ISO.part"
        mv "$BASE_ISO.part" "$BASE_ISO"
    fi
    echo ">>> Verificando la descarga"
    (cd "$WORK" && grep " $ISO_NAME\$" SHA256SUMS | sha256sum -c -)
fi

# ---------------------------------------------------------------------------
# 2. T-Rex Bites files that go on the USB stick
STAGE="$WORK/stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/trexbites/payload/panel"
cp -r "$REPO/upstream" "$REPO/system" "$STAGE/trexbites/payload/"
cp -r "$REPO/panel/trexbites_panel" "$REPO/panel/static" "$REPO/panel/requirements.txt" "$STAGE/trexbites/payload/panel/"
find "$STAGE" -name '__pycache__' -prune -exec rm -rf {} +

# values are written into a shell/preseed file: refuse characters that would break it
for value in "$LOCALE" "$KEYMAP" "$TIMEZONE" "$TV_PASSWORD" "$WIFI_SSID" "$WIFI_PASSWORD"; do
    if printf '%s' "$value" | grep -q '[@|\\"'"'"'$`]'; then
        echo "Los valores de configuración no pueden contener @ | \\ \" ' \$ o \`" >&2
        exit 1
    fi
done

WIFI_LINES="# no WiFi configured at build time"
if [ -n "$WIFI_SSID" ]; then
    WIFI_LINES="d-i netcfg/wireless_essid string $WIFI_SSID
d-i netcfg/wireless_essid_again string $WIFI_SSID
d-i netcfg/wireless_security_type select wpa
d-i netcfg/wireless_wpa string $WIFI_PASSWORD"
fi

fill() {
    local src="$1" dst="$2"
    local kernel_args="auto=true priority=critical preseed/file=/cdrom/trexbites/preseed.cfg locale=$LOCALE keyboard-configuration/xkb-keymap=$KEYMAP vga=788 --- quiet"
    awk -v wifi="$WIFI_LINES" '{ if ($0 == "@WIFI_LINES@") print wifi; else print }' "$src" \
        | sed -e "s|@LOCALE@|$LOCALE|g" -e "s|@KEYMAP@|$KEYMAP|g" -e "s|@TIMEZONE@|$TIMEZONE|g" \
              -e "s|@TV_PASSWORD@|$TV_PASSWORD|g" -e "s|@KERNEL_ARGS@|$kernel_args|g" > "$dst"
}

fill "$ISO_DIR/preseed.cfg.in" "$STAGE/trexbites/preseed.cfg"
fill "$ISO_DIR/isolinux.cfg.in" "$STAGE/isolinux.cfg"
fill "$ISO_DIR/trexbites-confirm.cfg.in" "$STAGE/trexbites-confirm.cfg"
fill "$ISO_DIR/trexbites-style.cfg.in" "$STAGE/trexbites-style.cfg"
fill "$ISO_DIR/grub.cfg.in" "$STAGE/grub.cfg"

# ---------------------------------------------------------------------------
# 3. New image: same boot setup as Debian's (BIOS + UEFI, USB-bootable),
#    with our files and boot menus added
OUT_ISO="$OUT/trexbites.iso"
rm -f "$OUT_ISO"
echo ">>> Creando $OUT_ISO"
xorriso -indev "$BASE_ISO" -outdev "$OUT_ISO" \
    -map "$STAGE/trexbites" /trexbites \
    -map "$STAGE/isolinux.cfg" /isolinux/isolinux.cfg \
    -map "$STAGE/trexbites-confirm.cfg" /isolinux/trexbites-confirm.cfg \
    -map "$STAGE/trexbites-style.cfg" /isolinux/trexbites-style.cfg \
    -map "$STAGE/grub.cfg" /boot/grub/grub.cfg \
    -boot_image any replay

(cd "$OUT" && sha256sum trexbites.iso > trexbites.iso.sha256)
echo
echo "Listo: $OUT_ISO"
echo "Grábalo en un USB con balenaEtcher (o: sudo dd if=$OUT_ISO of=/dev/sdX bs=4M status=progress)"

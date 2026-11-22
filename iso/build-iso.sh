#!/usr/bin/env bash
# Builds iso/out/trexbites.iso: the official Debian 13 netinst image plus an
# automatic install of T-Rex Bites. Write it to a USB stick (balenaEtcher,
# Raspberry Pi Imager, or dd) and boot any 64-bit PC from it.
#
# By default the USB carries everything (Debian packages, Python libraries and
# FieldStation42), so the computer needs NO internet to install. Building it
# needs Docker, internet and about 4 GB of free disk.
#
# Needs: bash, curl, xorriso, sha256sum, docker
#        (Debian/Ubuntu: sudo apt install xorriso curl docker.io)
#
# Optional settings (environment variables):
#   TREX_OFFLINE=1               0 = small USB that downloads everything while installing
#   TREX_LOCALE=es_CL.UTF-8      language and country of the installed system
#   TREX_KEYMAP=latam            keyboard layout (es = Spain, latam = Latin America, us)
#   TREX_TIMEZONE=America/Santiago
#   TREX_TV_PASSWORD=trexbites   password of the "tv" maintenance account
#   TREX_WIFI_SSID / TREX_WIFI_PASSWORD
#                                home WiFi, saved on the TV (never put these in a public build)
#   DEBIAN_ISO=/path/to/debian-13.x-amd64-netinst.iso   use an already downloaded image
#   OFFLINE_PAYLOAD=/path        use an offline bundle built before (see build-offline-payload.sh)
#   EXTRA_CA_CERT=/path/ca.crt   extra HTTPS certificate for networks that inspect traffic
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ISO_DIR="$REPO/iso"
WORK="$ISO_DIR/build"
OUT="$ISO_DIR/out"
DEBIAN_CD_URL="${DEBIAN_CD_URL:-https://cdimage.debian.org/debian-cd/current/amd64/iso-cd}"

OFFLINE="${TREX_OFFLINE:-1}"
LOCALE="${TREX_LOCALE:-es_CL.UTF-8}"
KEYMAP="${TREX_KEYMAP:-latam}"
TIMEZONE="${TREX_TIMEZONE:-America/Santiago}"
TV_PASSWORD="${TREX_TV_PASSWORD:-trexbites}"
WIFI_SSID="${TREX_WIFI_SSID:-}"
WIFI_PASSWORD="${TREX_WIFI_PASSWORD:-}"

NEEDED=(curl xorriso sha256sum)
if [ "$OFFLINE" = 1 ] && [ -z "${OFFLINE_PAYLOAD:-}" ]; then
    NEEDED+=(docker)
fi
for cmd in "${NEEDED[@]}"; do
    command -v "$cmd" >/dev/null || { echo "Falta '$cmd'. Instálalo (ej: sudo apt install xorriso curl docker.io)." >&2; exit 1; }
done

# values are written into shell and preseed files: refuse characters that would break them
for value in "$LOCALE" "$KEYMAP" "$TIMEZONE" "$TV_PASSWORD" "$WIFI_SSID" "$WIFI_PASSWORD"; do
    if printf '%s' "$value" | grep -q '[@|\\"'"'"'$`]'; then
        echo "Los valores de configuración no pueden contener @ | \\ \" ' \$ o \`" >&2
        exit 1
    fi
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
# 2. Offline bundle: every package and library, built inside Debian 13
if [ "$OFFLINE" = 1 ]; then
    if [ -n "${OFFLINE_PAYLOAD:-}" ]; then
        PAYLOAD_DIR="$OFFLINE_PAYLOAD"
    else
        PAYLOAD_DIR="$WORK/offline"
        mkdir -p "$PAYLOAD_DIR"
        echo ">>> Armando el paquete sin internet (10-20 minutos la primera vez)"
        DOCKER_ARGS=(--rm -v "$REPO:/src:ro" -v "$PAYLOAD_DIR:/out")
        if [ -n "${EXTRA_CA_CERT:-}" ]; then
            DOCKER_ARGS+=(-v "$EXTRA_CA_CERT:/extra-ca.crt:ro")
        fi
        docker run "${DOCKER_ARGS[@]}" debian:trixie /src/iso/build-offline-payload.sh /src /out
    fi
    for item in repo/Packages.gz wheels fieldstation42.tar.gz; do
        [ -e "$PAYLOAD_DIR/$item" ] || { echo "El paquete sin internet está incompleto: falta $item" >&2; exit 1; }
    done
fi

# ---------------------------------------------------------------------------
# 3. T-Rex Bites files that go on the USB stick
STAGE="$WORK/stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/trexbites/payload/panel"
cp -r "$REPO/upstream" "$REPO/system" "$STAGE/trexbites/payload/"
cp -r "$REPO/panel/trexbites_panel" "$REPO/panel/static" "$REPO/panel/requirements.txt" "$STAGE/trexbites/payload/panel/"
find "$STAGE" -name '__pycache__' -prune -exec rm -rf {} +
if [ "$OFFLINE" = 1 ]; then
    mkdir -p "$STAGE/trexbites/payload/offline"
    cp -r "$PAYLOAD_DIR/repo" "$PAYLOAD_DIR/wheels" "$PAYLOAD_DIR/fieldstation42.tar.gz" \
        "$STAGE/trexbites/payload/offline/"
    [ -f "$PAYLOAD_DIR/FIELDSTATION42-LICENSE.txt" ] && cp "$PAYLOAD_DIR/FIELDSTATION42-LICENSE.txt" "$STAGE/trexbites/"
fi
cp "$REPO/NOTICE.md" "$STAGE/trexbites/"

if [ "$OFFLINE" = 1 ]; then
    # the Debian installer never touches the network: everything comes from the USB
    NETWORK_LINES="d-i netcfg/enable boolean false
d-i netcfg/get_hostname string trexbites
d-i netcfg/get_domain string
d-i netcfg/hostname string trexbites
d-i hw-detect/load_firmware boolean true
d-i clock-setup/ntp boolean false
d-i apt-setup/use_mirror boolean false
d-i apt-setup/no_mirror boolean true
d-i apt-setup/services-select multiselect"
    PACKAGE_LINES="d-i pkgsel/upgrade select none
d-i pkgsel/update-policy select none"
    if [ -n "$WIFI_SSID" ]; then
        # saved on the installed system, where NetworkManager uses it
        printf "WIFI_SSID='%s'\nWIFI_PASSWORD='%s'\n" "$WIFI_SSID" "$WIFI_PASSWORD" > "$STAGE/trexbites/payload/wifi.conf"
    fi
else
    NETWORK_LINES="d-i netcfg/choose_interface select auto
d-i netcfg/get_hostname string trexbites
d-i netcfg/get_domain string
d-i netcfg/hostname string trexbites
d-i hw-detect/load_firmware boolean true
d-i clock-setup/ntp boolean true
d-i mirror/country string manual
d-i mirror/http/hostname string deb.debian.org
d-i mirror/http/directory string /debian
d-i mirror/http/proxy string"
    if [ -n "$WIFI_SSID" ]; then
        NETWORK_LINES="$NETWORK_LINES
d-i netcfg/wireless_essid string $WIFI_SSID
d-i netcfg/wireless_essid_again string $WIFI_SSID
d-i netcfg/wireless_security_type select wpa
d-i netcfg/wireless_wpa string $WIFI_PASSWORD"
    fi
    PACKAGE_LINES="d-i pkgsel/include string sudo ca-certificates git
d-i pkgsel/upgrade select full-upgrade"
fi

fill() {
    local src="$1" dst="$2"
    local kernel_args="auto=true priority=critical preseed/file=/cdrom/trexbites/preseed.cfg locale=$LOCALE keyboard-configuration/xkb-keymap=$KEYMAP vga=788 --- quiet"
    awk -v net="$NETWORK_LINES" -v pkg="$PACKAGE_LINES" '
        $0 == "@NETWORK_LINES@" { print net; next }
        $0 == "@PACKAGE_LINES@" { print pkg; next }
        { print }' "$src" \
        | sed -e "s|@LOCALE@|$LOCALE|g" -e "s|@KEYMAP@|$KEYMAP|g" -e "s|@TIMEZONE@|$TIMEZONE|g" \
              -e "s|@TV_PASSWORD@|$TV_PASSWORD|g" -e "s|@KERNEL_ARGS@|$kernel_args|g" > "$dst"
}

fill "$ISO_DIR/preseed.cfg.in" "$STAGE/trexbites/preseed.cfg"
fill "$ISO_DIR/isolinux.cfg.in" "$STAGE/isolinux.cfg"
fill "$ISO_DIR/trexbites-confirm.cfg.in" "$STAGE/trexbites-confirm.cfg"
fill "$ISO_DIR/trexbites-style.cfg.in" "$STAGE/trexbites-style.cfg"
fill "$ISO_DIR/grub.cfg.in" "$STAGE/grub.cfg"

# ---------------------------------------------------------------------------
# 4. New image: same boot setup as Debian's (BIOS + UEFI, USB-bootable),
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
echo "Listo: $OUT_ISO ($(du -h "$OUT_ISO" | cut -f1))"
echo "Grábalo en un USB con balenaEtcher (o: sudo dd if=$OUT_ISO of=/dev/sdX bs=4M status=progress)"

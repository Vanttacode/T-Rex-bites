#!/usr/bin/env bash
# T-Rex Bites installer: turns a minimal Debian 13 (trixie) into a TV channel box.
#
# It runs automatically from the T-Rex Bites USB installer, and can also be run
# by hand on an existing minimal Debian:   sudo ./system/install-trexbites.sh
#
# It is safe to run again: it never overwrites channels, videos or the PIN.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../upstream/fieldstation42.conf
source "$SRC_DIR/upstream/fieldstation42.conf"

TV_USER=tv
TV_HOME=/home/$TV_USER
PREFIX=/opt/trexbites
FS42_DIR=$PREFIX/fieldstation42
PANEL_DIR=$PREFIX/panel
MEDIA_DIR=/srv/trexbites
STATE_DIR=/var/lib/trexbites
LOG=/var/log/trexbites-install.log
HOSTNAME_TV=trexbites

if [ "$(id -u)" -ne 0 ]; then
    echo "Este instalador necesita ejecutarse como administrador (sudo)." >&2
    exit 1
fi

exec > >(tee -a "$LOG") 2>&1
echo "=== T-Rex Bites: instalación iniciada $(date) ==="

# systemd is not running inside the installer's chroot: only enable units there
if [ -d /run/systemd/system ] && ! systemd-detect-virt --chroot -q 2>/dev/null; then
    LIVE_SYSTEMD=1
else
    LIVE_SYSTEMD=0
fi

as_tv() { runuser -u "$TV_USER" -- "$@"; }
step() { echo; echo ">>> $*"; }

# ---------------------------------------------------------------------------
step "Activando repositorios de firmware (drivers de WiFi y video)"
if [ -f /etc/apt/sources.list ]; then
    sed -i -E '/^deb(-src)? .*debian/ { / non-free-firmware/! s/$/ non-free-firmware/ }' /etc/apt/sources.list
fi
for f in /etc/apt/sources.list.d/*.sources; do
    [ -f "$f" ] || continue
    sed -i -E '/^Components:/ { / non-free-firmware/! s/$/ non-free-firmware/ }' "$f"
done

export DEBIAN_FRONTEND=noninteractive
apt-get update

step "Instalando paquetes del sistema"
apt-get install -y --no-install-recommends \
    ca-certificates git sudo curl \
    python3 python3-venv python3-pip python3-dev build-essential \
    mpv ffmpeg fonts-dejavu-core \
    xserver-xorg-core xserver-xorg-video-all xserver-xorg-input-all xinit x11-xserver-utils \
    libxcb-cursor0 libgl1 libegl1 libxkbcommon-x11-0 \
    dbus-user-session pipewire pipewire-pulse wireplumber \
    network-manager avahi-daemon libnss-mdns \
    mesa-va-drivers mesa-vdpau-drivers

# hardware support: install whatever exists in this Debian release, skip the rest
for pkg in firmware-linux-free firmware-misc-nonfree firmware-realtek firmware-iwlwifi \
           firmware-atheros firmware-brcm80211 firmware-libertas firmware-amd-graphics \
           firmware-intel-graphics firmware-intel-sound firmware-sof-signed \
           intel-media-va-driver i965-va-driver; do
    apt-get install -y --no-install-recommends "$pkg" || echo "(aviso) no se pudo instalar $pkg, sigo"
done

# ---------------------------------------------------------------------------
step "Creando el usuario de la tele ($TV_USER)"
if ! id "$TV_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$TV_USER"
fi
for grp in audio video input render; do
    getent group "$grp" >/dev/null && usermod -aG "$grp" "$TV_USER"
done

mkdir -p "$PREFIX" "$MEDIA_DIR/catalog" "$MEDIA_DIR/.uploads" "$STATE_DIR"
chown "$TV_USER:$TV_USER" "$PREFIX" "$MEDIA_DIR" "$MEDIA_DIR/catalog" "$MEDIA_DIR/.uploads" "$STATE_DIR"

# ---------------------------------------------------------------------------
step "Descargando FieldStation42 (motor de la tele) en la versión $FS42_COMMIT"
if [ ! -d "$FS42_DIR/.git" ]; then
    as_tv git clone "$FS42_REPO" "$FS42_DIR"
fi
as_tv git -C "$FS42_DIR" fetch --quiet origin
as_tv git -C "$FS42_DIR" -c advice.detachedHead=false checkout --quiet "$FS42_COMMIT"

# videos live on /srv so the engine can be reinstalled without touching them
if [ ! -e "$FS42_DIR/catalog" ]; then
    as_tv ln -s "$MEDIA_DIR/catalog" "$FS42_DIR/catalog"
fi

step "Configurando canales"
as_tv mkdir -p "$FS42_DIR/confs"
has_channels=0
for conf in "$FS42_DIR"/confs/*.json; do
    if [ -f "$conf" ] && [ "$(basename "$conf")" != main_config.json ]; then
        has_channels=1
    fi
done
if [ "$has_channels" = 0 ]; then
    install -o "$TV_USER" -g "$TV_USER" -m 644 "$SRC_DIR"/system/defaults/confs/*.json "$FS42_DIR/confs/"
fi
if [ ! -f "$FS42_DIR/confs/main_config.json" ]; then
    API_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
    cat > "$FS42_DIR/confs/main_config.json" <<EOF
{
  "server_host": "0.0.0.0",
  "server_port": 4242,
  "api_key": "$API_KEY",
  "schedule_agent": {"trigger_add_at": "day", "amount_to_add": "week"}
}
EOF
    chown "$TV_USER:$TV_USER" "$FS42_DIR/confs/main_config.json"
    chmod 600 "$FS42_DIR/confs/main_config.json"
fi

step "Instalando FieldStation42 (esto puede tardar varios minutos)"
# its installer asks to press Enter; with no keyboard input it just continues
as_tv bash -c "cd '$FS42_DIR' && TERM=dumb bash install.sh </dev/null"
if [ ! -x "$FS42_DIR/env/bin/python3" ]; then
    echo "ERROR: FieldStation42 no quedó instalado (falta env/bin/python3)." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
step "Creando videos de ejemplo en los canales vacíos"
FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
while IFS= read -r folder; do
    [ -n "$folder" ] || continue
    as_tv mkdir -p "$folder"
    if [ -z "$(find "$folder" -maxdepth 1 -type f -print -quit)" ]; then
        label=$(basename "$folder")
        as_tv ffmpeg -hide_banner -loglevel error -y \
            -f lavfi -i "smptebars=size=1280x720:rate=25" \
            -f lavfi -i "sine=frequency=440:sample_rate=48000" \
            -t 120 \
            -vf "drawtext=fontfile=$FONT:text='T-REX BITES':fontsize=96:fontcolor=white:borderw=6:x=(w-tw)/2:y=h/2-140,drawtext=fontfile=$FONT:text='Sube tus programas desde el telefono':fontsize=42:fontcolor=white:borderw=4:x=(w-tw)/2:y=h/2,drawtext=fontfile=$FONT:text='http\://trexbites.local':fontsize=54:fontcolor=yellow:borderw=4:x=(w-tw)/2:y=h/2+80,drawtext=fontfile=$FONT:text='$label':fontsize=32:fontcolor=white:borderw=3:x=(w-tw)/2:y=h-80" \
            -af "volume=0.05" \
            -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest \
            "$folder/_bienvenida_trexbites.mp4"
    fi
done < <(python3 -I "$SRC_DIR/panel/trexbites_panel/channels.py" --confs "$FS42_DIR/confs" --fs42 "$FS42_DIR" --print-dirs)

step "Preparando la programación inicial"
as_tv bash -c "cd '$FS42_DIR' && env/bin/python3 station_42.py --rebuild_catalog && env/bin/python3 station_42.py --add_week" \
    || echo "(aviso) la programación inicial no se pudo crear; la tele la creará al encenderse"

# ---------------------------------------------------------------------------
step "Instalando el panel web"
mkdir -p "$PANEL_DIR"
cp -r "$SRC_DIR/panel/trexbites_panel" "$SRC_DIR/panel/static" "$SRC_DIR/panel/requirements.txt" "$PANEL_DIR/"
chown -R "$TV_USER:$TV_USER" "$PANEL_DIR"
as_tv python3 -m venv "$PANEL_DIR/env"
as_tv "$PANEL_DIR/env/bin/pip" install --quiet --upgrade pip
as_tv "$PANEL_DIR/env/bin/pip" install --quiet -r "$PANEL_DIR/requirements.txt"

# ---------------------------------------------------------------------------
step "Configurando el arranque directo a la tele"
cp -r "$SRC_DIR/system/rootfs/." /
install -d -o "$TV_USER" -g "$TV_USER" "$TV_HOME/.config/systemd/user"
cp -r "$SRC_DIR/system/home/tv/." "$TV_HOME/"
chmod +x "$TV_HOME/.xinitrc"
chown -R "$TV_USER:$TV_USER" "$TV_HOME"

# the TV starts when the tv user's screen session starts
install -d -o "$TV_USER" -g "$TV_USER" "$TV_HOME/.config/systemd/user/trexbites-x11.target.wants"
ln -sfn ../fs42.service "$TV_HOME/.config/systemd/user/trexbites-x11.target.wants/fs42.service"
chown -h "$TV_USER:$TV_USER" "$TV_HOME/.config/systemd/user/trexbites-x11.target.wants/fs42.service"

# never sleep: it's a TV
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

step "Nombre en la red: $HOSTNAME_TV.local"
echo "$HOSTNAME_TV" > /etc/hostname
if grep -q '^127.0.1.1' /etc/hosts; then
    sed -i -E "s/^127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME_TV/" /etc/hosts
else
    printf '127.0.1.1\t%s\n' "$HOSTNAME_TV" >> /etc/hosts
fi

step "Arranque silencioso"
if [ -f /etc/default/grub ]; then
    sed -i -E 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=1/' /etc/default/grub
    sed -i -E 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3"/' /etc/default/grub
    update-grub || true
fi

systemctl enable avahi-daemon.service NetworkManager.service trexbites-panel.service
systemctl enable trexbites-firstboot.service
systemctl set-default multi-user.target

touch "$STATE_DIR/installed"
echo
echo "=== T-Rex Bites quedó instalado $(date) ==="
echo "Reinicia el equipo. Luego abre http://$HOSTNAME_TV.local desde tu teléfono (PIN 1234)."

if [ "$LIVE_SYSTEMD" = 1 ]; then
    systemctl daemon-reload
    systemctl restart avahi-daemon.service trexbites-panel.service || true
fi

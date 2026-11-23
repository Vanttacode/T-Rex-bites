#!/usr/bin/env bash
# T-Rex Bites installer: turns a minimal Debian 13 (trixie) into a TV channel box.
#
# It runs automatically from the T-Rex Bites USB installer, and can also be run
# by hand on an existing minimal Debian:   sudo ./system/install-trexbites.sh
#
# It is safe to run again: it never overwrites channels, videos or the PIN.
#
# Two modes:
#   offline  the USB built by iso/build-iso.sh carries every package, Python
#            library and FieldStation42 itself in ../offline: no internet needed
#   online   anything else (for example a git clone): downloads what it needs
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
OFFLINE_DIR=$SRC_DIR/offline
OFFLINE_LIST=/etc/apt/sources.list.d/trexbites-offline.list

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
read_list() { grep -v -E '^\s*(#|$)' "$SRC_DIR/system/$1"; }

if [ -d "$OFFLINE_DIR/repo" ] && [ -d "$OFFLINE_DIR/wheels" ]; then
    OFFLINE=1
    echo "Modo sin internet: todo se instala desde el USB."
else
    OFFLINE=0
    echo "Modo con internet: se descarga lo necesario."
fi

# ---------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
mapfile -t PACKAGES < <(read_list packages.txt)
mapfile -t OPTIONAL_PACKAGES < <(read_list packages-optional.txt)

if [ "$OFFLINE" = 1 ]; then
    step "Usando los paquetes incluidos en el USB"
    chmod -R a+rX "$OFFLINE_DIR"
    echo "deb [trusted=yes] file:$OFFLINE_DIR/repo ./" > "$OFFLINE_LIST"
    # only the USB's packages: the network may not exist yet
    APT=(apt-get -o "Dir::Etc::SourceList=$OFFLINE_LIST" -o "Dir::Etc::SourceParts=-")
    "${APT[@]}" update

    # where future updates come from, once the TV has internet
    if ! grep -qsE '^deb ' /etc/apt/sources.list && ! ls /etc/apt/sources.list.d/*.sources >/dev/null 2>&1; then
        cat > /etc/apt/sources.list <<'SOURCES'
deb http://deb.debian.org/debian trixie main non-free-firmware
deb http://deb.debian.org/debian trixie-updates main non-free-firmware
deb http://security.debian.org/debian-security trixie-security main non-free-firmware
SOURCES
    fi
else
    step "Activando repositorios de firmware (drivers de WiFi y video)"
    if [ -f /etc/apt/sources.list ]; then
        sed -i -E '/^deb(-src)? .*debian/ { / non-free-firmware/! s/$/ non-free-firmware/ }' /etc/apt/sources.list
    fi
    for f in /etc/apt/sources.list.d/*.sources; do
        [ -f "$f" ] || continue
        sed -i -E '/^Components:/ { / non-free-firmware/! s/$/ non-free-firmware/ }' "$f"
    done
    # a TV installed from the USB without internet still lists the USB ("cdrom")
    # as a package source: apt fails on it once the USB is gone
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
        [ -f "$f" ] && sed -i -E 's|^(deb(-src)? +cdrom:)|# \1|' "$f"
    done
    if ! grep -qsE '^deb ' /etc/apt/sources.list /etc/apt/sources.list.d/*.list \
        && ! ls /etc/apt/sources.list.d/*.sources >/dev/null 2>&1; then
        cat > /etc/apt/sources.list <<'SOURCES'
deb http://deb.debian.org/debian trixie main non-free-firmware
deb http://deb.debian.org/debian trixie-updates main non-free-firmware
deb http://security.debian.org/debian-security trixie-security main non-free-firmware
SOURCES
    fi
    APT=(apt-get)
    # one broken source must not stop an update: what's already installed keeps working
    "${APT[@]}" update || echo "(aviso) apt-get update tuvo errores, sigo con lo que hay"
    mapfile -t -O "${#PACKAGES[@]}" PACKAGES < <(read_list packages-build.txt)
fi

step "Instalando paquetes del sistema"
if ! "${APT[@]}" install -y --no-install-recommends "${PACKAGES[@]}"; then
    # install them one by one, so one missing package doesn't block the rest
    echo "(aviso) instalación en bloque falló; pruebo paquete por paquete"
    "${APT[@]}" -f install -y || true
    missing=()
    for pkg in "${PACKAGES[@]}"; do
        "${APT[@]}" install -y --no-install-recommends "$pkg" || missing+=("$pkg")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        echo "(aviso) no se pudieron instalar: ${missing[*]}"
        # without these the TV can't work at all
        for pkg in python3 python3-venv mpv ffmpeg; do
            dpkg -s "$pkg" >/dev/null 2>&1 || { echo "ERROR: falta $pkg" >&2; exit 1; }
        done
    fi
fi

# hardware support: install whatever exists, skip the rest
for pkg in "${OPTIONAL_PACKAGES[@]}"; do
    "${APT[@]}" install -y --no-install-recommends "$pkg" || echo "(aviso) no se pudo instalar $pkg, sigo"
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
FS42_MARK="$FS42_DIR/.trexbites-commit"
as_tv mkdir -p "$FS42_DIR"
if [ "$(cat "$FS42_MARK" 2>/dev/null)" = "$FS42_COMMIT" ]; then
    step "FieldStation42 (motor de la tele) ya está en la versión $FS42_COMMIT"
elif [ "$OFFLINE" = 1 ]; then
    step "Copiando FieldStation42 (motor de la tele) desde el USB"
    # confs/ and runtime/ hold the person's settings: never overwritten
    as_tv tar -xzf "$OFFLINE_DIR/fieldstation42.tar.gz" -C "$FS42_DIR" --exclude=./confs --exclude=./runtime
    echo "$FS42_COMMIT" | as_tv tee "$FS42_MARK" >/dev/null
else
    step "Descargando FieldStation42 (motor de la tele) en la versión $FS42_COMMIT"
    FS42_TGZ=$(mktemp)
    curl -fsSL --retry 4 "${FS42_REPO%.git}/archive/$FS42_COMMIT.tar.gz" -o "$FS42_TGZ"
    as_tv tar -xzf "$FS42_TGZ" -C "$FS42_DIR" --strip-components=1 \
        --exclude='*/confs' --exclude='*/runtime'
    rm -f "$FS42_TGZ"
    echo "$FS42_COMMIT" | as_tv tee "$FS42_MARK" >/dev/null
fi

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
LIBRARY_DIR=$MEDIA_DIR/catalog/biblioteca
as_tv mkdir -p "$LIBRARY_DIR"
if [ "$has_channels" = 0 ]; then
    install -o "$TV_USER" -g "$TV_USER" -m 644 "$SRC_DIR"/system/defaults/confs/*.json "$FS42_DIR/confs/"
    if [ ! -f "$LIBRARY_DIR/.trexbites.json" ]; then
        install -o "$TV_USER" -g "$TV_USER" -m 644 "$SRC_DIR/system/defaults/biblioteca.json" "$LIBRARY_DIR/.trexbites.json"
    fi
fi
# channel helpers run straight from the source tree
trex_py() { (cd "$SRC_DIR/panel" && python3 -m "$@"); }
# channels made before the shared library (v0.5 and earlier) move into it;
# their videos are moved on the same disk, never copied or deleted
trex_py trexbites_panel.migrate --confs "$FS42_DIR/confs" --fs42 "$FS42_DIR"
chown -R "$TV_USER:$TV_USER" "$FS42_DIR/confs" "$LIBRARY_DIR"
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
if [ "$OFFLINE" = 1 ]; then
    # FieldStation42's own installer downloads its Python libraries one by one:
    # these pip settings make it take them from the USB instead
    as_tv env PIP_NO_INDEX=1 PIP_FIND_LINKS="$OFFLINE_DIR/wheels" \
        bash -c "cd '$FS42_DIR' && TERM=dumb bash install.sh </dev/null"
else
    as_tv bash -c "cd '$FS42_DIR' && TERM=dumb bash install.sh </dev/null"
fi
if [ ! -x "$FS42_DIR/env/bin/python3" ]; then
    echo "ERROR: FieldStation42 no quedó instalado (falta env/bin/python3)." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
step "Creando el video de ejemplo y la pantalla de \"¡A dormir!\""
FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
MEDIA_ASSETS=$PREFIX/media
mkdir -p "$MEDIA_ASSETS"
PLACEHOLDER=$MEDIA_ASSETS/_bienvenida_trexbites.mp4
if [ ! -f "$PLACEHOLDER" ]; then
    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i "smptebars=size=1280x720:rate=25" \
        -f lavfi -i "sine=frequency=440:sample_rate=48000" \
        -t 120 \
        -vf "drawtext=fontfile=$FONT:text='T-REX BITES':fontsize=96:fontcolor=white:borderw=6:x=(w-tw)/2:y=h/2-140,drawtext=fontfile=$FONT:text='Sube tus programas desde el telefono':fontsize=42:fontcolor=white:borderw=4:x=(w-tw)/2:y=h/2,drawtext=fontfile=$FONT:text='http\://trexbites.local':fontsize=54:fontcolor=yellow:borderw=4:x=(w-tw)/2:y=h/2+80" \
        -af "volume=0.05" \
        -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest \
        "$PLACEHOLDER"
fi
if [ ! -f "$MEDIA_ASSETS/a_dormir.png" ]; then
    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i "color=c=0x12142b:size=1280x720" -frames:v 1 \
        -vf "drawtext=fontfile=$FONT:text='zzz...':fontsize=72:fontcolor=0xa9abc9:x=(w-tw)/2:y=h/2-190,drawtext=fontfile=$FONT:text='¡A dormir!':fontsize=120:fontcolor=0xff8a1f:borderw=6:x=(w-tw)/2:y=h/2-90,drawtext=fontfile=$FONT:text='T-Rex TV vuelve mañana':fontsize=48:fontcolor=white:x=(w-tw)/2:y=h/2+80" \
        "$MEDIA_ASSETS/a_dormir.png"
fi
if [ ! -f "$MEDIA_ASSETS/configurar_wifi.png" ]; then
    # shown on the first start, until the WiFi is set up from a phone
    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i "color=c=0x12142b:size=1280x720" -frames:v 1 \
        -vf "drawtext=fontfile=$FONT:text='Configura el WiFi de T-Rex Bites':fontsize=56:fontcolor=0xff8a1f:x=(w-tw)/2:y=70,\
drawtext=fontfile=$FONT:text='1.  En tu teléfono, conéctate a la red WiFi\:':fontsize=38:fontcolor=white:x=110:y=200,\
drawtext=fontfile=$FONT:text='T-Rex Bites Config':fontsize=72:fontcolor=0x4cd964:x=(w-tw)/2:y=265,\
drawtext=fontfile=$FONT:text='2.  Se abre sola la página de configuración':fontsize=38:fontcolor=white:x=110:y=400,\
drawtext=fontfile=$FONT:text='(si no se abre, entra a http\://10.42.0.1)':fontsize=30:fontcolor=0xa9abc9:x=160:y=450,\
drawtext=fontfile=$FONT:text='3.  PIN 1234, elige tu WiFi y escribe su clave':fontsize=38:fontcolor=white:x=110:y=530,\
drawtext=fontfile=$FONT:text='Después la tele empieza sola':fontsize=32:fontcolor=0xa9abc9:x=(w-tw)/2:y=640" \
        "$MEDIA_ASSETS/configurar_wifi.png"
fi
IDENT=$MEDIA_ASSETS/_ident_trexbites.mp4
if [ ! -f "$IDENT" ]; then
    # short station ident that fills the gaps between programs
    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i "color=c=0x12142b:size=1280x720:rate=25" \
        -f lavfi -i "sine=frequency=660:sample_rate=48000" \
        -t 10 \
        -vf "drawtext=fontfile=$FONT:text='T-REX TV':fontsize=140:fontcolor=0xff8a1f:borderw=8:x=(w-tw)/2:y=h/2-110,drawtext=fontfile=$FONT:text='Ya volvemos...':fontsize=56:fontcolor=white:x=(w-tw)/2:y=h/2+70" \
        -af "volume=0.03" \
        -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest \
        "$IDENT"
fi
chmod 644 "$PLACEHOLDER" "$MEDIA_ASSETS/a_dormir.png" "$MEDIA_ASSETS/configurar_wifi.png" "$IDENT"

# FieldStation42 needs at least one video per category: empty folders get the sample clip
while IFS= read -r folder; do
    [ -n "$folder" ] || continue
    as_tv mkdir -p "$folder"
    # a category whose videos are all in program subfolders is not empty
    if [ -z "$(find "$folder" -type f ! -name '.*' -print -quit)" ]; then
        as_tv cp "$PLACEHOLDER" "$folder/_bienvenida_trexbites.mp4"
    fi
done < <(trex_py trexbites_panel.channels --confs "$FS42_DIR/confs" --fs42 "$FS42_DIR" --print-dirs)

# scheduled channels fill the gaps between programs with short clips
while IFS= read -r folder; do
    [ -n "$folder" ] || continue
    as_tv mkdir -p "$folder"
    if [ -z "$(find "$folder" -maxdepth 1 -type f -print -quit)" ]; then
        as_tv cp "$IDENT" "$folder/_ident_trexbites.mp4"
    fi
done < <(trex_py trexbites_panel.channels --confs "$FS42_DIR/confs" --fs42 "$FS42_DIR" --print-bump-dirs)

step "Preparando la programación inicial"
as_tv bash -c "cd '$FS42_DIR' && env/bin/python3 station_42.py --rebuild_catalog && env/bin/python3 station_42.py --add_week" \
    || echo "(aviso) la programación inicial no se pudo crear; la tele la creará al encenderse"

# ---------------------------------------------------------------------------
step "Instalando el panel web"
mkdir -p "$PANEL_DIR"
cp -r "$SRC_DIR/panel/trexbites_panel" "$SRC_DIR/panel/static" "$SRC_DIR/panel/requirements.txt" "$PANEL_DIR/"
chown -R "$TV_USER:$TV_USER" "$PANEL_DIR"
as_tv python3 -m venv "$PANEL_DIR/env"
if [ "$OFFLINE" = 1 ]; then
    as_tv "$PANEL_DIR/env/bin/pip" install --quiet --no-index --find-links "$OFFLINE_DIR/wheels" \
        -r "$PANEL_DIR/requirements.txt"
else
    as_tv "$PANEL_DIR/env/bin/pip" install --quiet --upgrade pip
    as_tv "$PANEL_DIR/env/bin/pip" install --quiet -r "$PANEL_DIR/requirements.txt"
fi

# ---------------------------------------------------------------------------
step "Instalando las actualizaciones a distancia"
install -m 644 "$SRC_DIR/VERSION" "$PREFIX/VERSION" 2>/dev/null || echo "0.0.0" > "$PREFIX/VERSION"
install -d "$PREFIX/bin"
install -m 755 "$SRC_DIR/system/trexbites-update.sh" "$PREFIX/bin/trexbites-update"
install -m 644 "$SRC_DIR/upstream/trexbites.conf" "$PREFIX/trexbites.conf"

# ---------------------------------------------------------------------------
step "Configurando el arranque directo a la tele"
cp -r "$SRC_DIR/system/rootfs/." /
install -d -o "$TV_USER" -g "$TV_USER" "$TV_HOME/.config/systemd/user"
cp -r "$SRC_DIR/system/home/tv/." "$TV_HOME/"
chmod +x "$TV_HOME/.xinitrc"
chown -R "$TV_USER:$TV_USER" "$TV_HOME"

# channel logos and the channel banner are drawn by FieldStation42's OSD;
# osd/osd.json is the person's own file, so it is only written the first time
if [ ! -f "$FS42_DIR/osd/osd.json" ]; then
    install -o "$TV_USER" -g "$TV_USER" -m 644 "$SRC_DIR/system/defaults/osd.json" "$FS42_DIR/osd/osd.json"
fi
# transparent background, so only the logo shows over the video
install -m 644 "$SRC_DIR/panel/static/logo-trexbites.png" "$PREFIX/media/logo_trexbites.png"
install -d -o "$TV_USER" -g "$TV_USER" "$TV_HOME/.config/systemd/user/fs42.service.wants"
ln -sfn ../fs42-osd.service "$TV_HOME/.config/systemd/user/fs42.service.wants/fs42-osd.service"
chown -h "$TV_USER:$TV_USER" "$TV_HOME/.config/systemd/user/fs42.service.wants/fs42-osd.service"

# the TV starts when the tv user's screen session starts
install -d -o "$TV_USER" -g "$TV_USER" "$TV_HOME/.config/systemd/user/trexbites-x11.target.wants"
ln -sfn ../fs42.service "$TV_HOME/.config/systemd/user/trexbites-x11.target.wants/fs42.service"
chown -h "$TV_USER:$TV_USER" "$TV_HOME/.config/systemd/user/trexbites-x11.target.wants/fs42.service"

# keep the tv user's services manager running even before the screen session
# starts, so the panel can always switch between the TV and "¡A dormir!"
mkdir -p /var/lib/systemd/linger
touch "/var/lib/systemd/linger/$TV_USER"

# never sleep: it's a TV
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

step "Nombre en la red: $HOSTNAME_TV.local"
echo "$HOSTNAME_TV" > /etc/hostname
if grep -q '^127.0.1.1' /etc/hosts; then
    sed -i -E "s/^127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME_TV/" /etc/hosts
else
    printf '127.0.1.1\t%s\n' "$HOSTNAME_TV" >> /etc/hosts
fi

step "Enlaces fijos al kernel"
if ! grep -qs '^do_symlinks *= *yes' /etc/kernel-img.conf; then
    sed -i '/^do_symlinks/d' /etc/kernel-img.conf 2>/dev/null || true
    echo "do_symlinks = yes" >> /etc/kernel-img.conf
fi
LATEST_KERNEL=$(find /boot -maxdepth 1 -name 'vmlinuz-*' | sort -V | tail -n 1)
if [ -n "$LATEST_KERNEL" ]; then
    KVER=${LATEST_KERNEL#/boot/vmlinuz-}
    ln -sfn "boot/vmlinuz-$KVER" /vmlinuz
    [ -e "/boot/initrd.img-$KVER" ] && ln -sfn "boot/initrd.img-$KVER" /initrd.img
fi

step "Menú de arranque"
if [ -f /etc/default/grub ]; then
    sed -i -E 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3"/' /etc/default/grub
    # list other systems on the disk (a Linux or Windows installed before) in the menu
    if grep -q '^#\?GRUB_DISABLE_OS_PROBER' /etc/default/grub; then
        sed -i -E 's/^#?GRUB_DISABLE_OS_PROBER=.*/GRUB_DISABLE_OS_PROBER=false/' /etc/default/grub
    else
        echo 'GRUB_DISABLE_OS_PROBER=false' >> /etc/default/grub
    fi
    if command -v os-prober >/dev/null && [ -n "$(os-prober 2>/dev/null)" ]; then
        # shared computer: show the menu long enough to pick the other system
        echo "Encontré otro sistema en el disco: queda en el menú de arranque."
        sed -i -E 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=8/' /etc/default/grub
        sed -i -E 's/^#?GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=menu/' /etc/default/grub
    else
        # T-Rex Bites alone: straight to the TV
        sed -i -E 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=1/' /etc/default/grub
    fi
    update-grub || true
fi

systemctl enable avahi-daemon.service NetworkManager.service trexbites-panel.service
systemctl enable trexbites-firstboot.service
systemctl set-default multi-user.target

# home WiFi given when the USB was built (only for USBs made at home)
if [ -f "$SRC_DIR/wifi.conf" ]; then
    step "Guardando la red WiFi de la casa"
    # shellcheck source=/dev/null
    . "$SRC_DIR/wifi.conf"
    install -d -m 700 /etc/NetworkManager/system-connections
    NM_FILE=/etc/NetworkManager/system-connections/trexbites-casa.nmconnection
    (
        umask 077
        cat > "$NM_FILE" <<WIFI
[connection]
id=Casa
type=wifi
autoconnect=true

[wifi]
mode=infrastructure
ssid=$WIFI_SSID

[wifi-security]
key-mgmt=wpa-psk
psk=$WIFI_PASSWORD

[ipv4]
method=auto

[ipv6]
method=auto
WIFI
    )
    chmod 600 "$NM_FILE"
fi

touch "$STATE_DIR/installed"

if [ "$OFFLINE" = 1 ]; then
    # the USB copy is no longer needed: frees about 1 GB for videos
    rm -f "$OFFLINE_LIST"
    rm -rf "$OFFLINE_DIR"
fi
echo
echo "=== T-Rex Bites quedó instalado $(date) ==="
echo "Reinicia el equipo. Luego abre http://$HOSTNAME_TV.local desde tu teléfono (PIN 1234)."

if [ "$LIVE_SYSTEMD" = 1 ]; then
    systemctl daemon-reload
    systemctl restart avahi-daemon.service trexbites-panel.service || true
    # the tv user's own services (player, logo, bedtime screen)
    systemctl --user --machine="$TV_USER@" daemon-reload 2>/dev/null || true
    if systemctl --user --machine="$TV_USER@" is-active --quiet fs42.service 2>/dev/null; then
        systemctl --user --machine="$TV_USER@" restart fs42.service || true
    fi
fi

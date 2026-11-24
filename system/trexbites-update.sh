#!/usr/bin/env bash
# T-Rex Bites updater, installed as /opt/trexbites/bin/trexbites-update.
#
#   trexbites-update check   say whether a newer version exists (no changes)
#   trexbites-update apply   download it from GitHub Releases and install it
#
# The panel starts "apply" through trexbites-update.service (as root). Videos,
# channels, schedules, PIN, WiFi and history are never touched: the installer
# only replaces program files. If the install fails, the previous panel and
# installer come back.
set -euo pipefail

PREFIX=/opt/trexbites
INSTALLER_DIR=/opt/trexbites-installer
STATE_DIR=/var/lib/trexbites
STATE=$STATE_DIR/update.json
LOG=/var/log/trexbites-update.log
# shellcheck source=../upstream/trexbites.conf
source "$PREFIX/trexbites.conf"

CURRENT=$(tr -d '[:space:]' < "$PREFIX/VERSION" 2>/dev/null || echo "0.0.0")

state() {  # state <status> <message> [version]
    python3 - "$STATE" "$1" "$2" "${3:-}" "$CURRENT" <<'PY'
import json, sys, time
path, status, message, version, current = sys.argv[1:6]
json.dump({"status": status, "message": message, "version": version,
           "current": current, "time": int(time.time())}, open(path, "w"))
PY
}

# newest published release: "<tag> <bundle url> <sha256 url>"
latest_release() {
    curl -fsSL --retry 3 "https://api.github.com/repos/$TREX_REPO/releases?per_page=10" | python3 -c '
import json, sys
for rel in json.load(sys.stdin):
    if rel.get("draft"):
        continue
    tag = rel["tag_name"]
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    bundle = f"trexbites-update-{tag}.tar.gz"
    if bundle in assets and bundle + ".sha256" in assets:
        print(tag, assets[bundle], assets[bundle + ".sha256"])
        break
'
}

is_newer() {  # is_newer <candidate> <current>: version order, "1.0" > "1.0-beta"
    python3 - "$1" "$2" <<'PY'
import re, sys
def key(v):
    v = v.lstrip("v")
    main, _, pre = v.partition("-")
    nums = [int(x) for x in re.findall(r"\d+", main)][:3] + [0, 0, 0]
    return nums[:3] + [0 if pre else 1, pre]
sys.exit(0 if key(sys.argv[1]) > key(sys.argv[2]) else 1)
PY
}

cmd=${1:-check}
mkdir -p "$STATE_DIR"

release=$(latest_release || true)
if [ -z "$release" ]; then
    state error "No se pudo consultar GitHub. ¿La tele tiene internet?"
    exit 1
fi
read -r TAG BUNDLE_URL SUM_URL <<< "$release"

if ! is_newer "$TAG" "$CURRENT"; then
    state current "Ya tienes la última versión ($CURRENT)." "$TAG"
    echo "Ya está al día ($CURRENT)."
    exit 0
fi

if [ "$cmd" = check ]; then
    state available "Hay una versión nueva: $TAG" "$TAG"
    echo "Disponible: $TAG"
    exit 0
fi
[ "$cmd" = apply ] || { echo "uso: trexbites-update check|apply" >&2; exit 2; }

exec >> "$LOG" 2>&1
echo "=== Actualización a $TAG ($(date)) ==="
state running "Descargando $TAG…" "$TAG"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
curl -fsSL --retry 4 "$BUNDLE_URL" -o "$WORK/bundle.tar.gz"
curl -fsSL --retry 4 "$SUM_URL" -o "$WORK/bundle.sha256"
EXPECTED=$(awk '{print $1}' "$WORK/bundle.sha256")
ACTUAL=$(sha256sum "$WORK/bundle.tar.gz" | awk '{print $1}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
    state error "La descarga llegó dañada. Inténtalo de nuevo." "$TAG"
    exit 1
fi
mkdir "$WORK/new"
tar -xzf "$WORK/bundle.tar.gz" -C "$WORK/new"
[ -x "$WORK/new/system/install-trexbites.sh" ] || { state error "Paquete de actualización inválido." "$TAG"; exit 1; }

state running "Instalando $TAG (la tele puede reiniciarse un momento)…" "$TAG"
BACKUP=$WORK/backup
mkdir -p "$BACKUP"
cp -a "$PREFIX/panel" "$BACKUP/panel"
[ -d "$INSTALLER_DIR" ] && cp -a "$INSTALLER_DIR" "$BACKUP/installer"

rm -rf "$INSTALLER_DIR"
cp -a "$WORK/new" "$INSTALLER_DIR"
if "$INSTALLER_DIR/system/install-trexbites.sh"; then
    CURRENT=$(tr -d '[:space:]' < "$PREFIX/VERSION")
    state "done" "Actualizada a $TAG." "$TAG"
    echo "=== Listo: $TAG ==="
else
    echo "!!! Falló la instalación: vuelvo a la versión anterior"
    rm -rf "$PREFIX/panel" "$INSTALLER_DIR"
    cp -a "$BACKUP/panel" "$PREFIX/panel"
    [ -d "$BACKUP/installer" ] && cp -a "$BACKUP/installer" "$INSTALLER_DIR"
    systemctl restart trexbites-panel.service || true
    state error "La actualización falló y se volvió a la versión anterior. Detalle en $LOG" "$TAG"
    exit 1
fi

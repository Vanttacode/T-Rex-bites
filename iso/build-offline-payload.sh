#!/usr/bin/env bash
# Collects everything T-Rex Bites installs, so the USB works with no internet:
#   repo/                     Debian packages (and all their dependencies) + index
#   wheels/                   Python libraries, already compiled
#   fieldstation42.tar.gz     FieldStation42 at the pinned commit
#
# Runs INSIDE a Debian 13 (trixie) amd64 container, so packages and compiled
# libraries match the installed system exactly. build-iso.sh starts it with:
#   docker run --rm -v "$REPO:/src:ro" -v "$OUT:/out" debian:trixie /src/iso/build-offline-payload.sh /src /out
set -euo pipefail

SRC=${1:?usage: build-offline-payload.sh <repo dir> <output dir>}
OUT=${2:?usage: build-offline-payload.sh <repo dir> <output dir>}
# shellcheck source=../upstream/fieldstation42.conf
source "$SRC/upstream/fieldstation42.conf"

read_list() { grep -v -E '^\s*(#|$)' "$SRC/system/$1"; }

export DEBIAN_FRONTEND=noninteractive
mkdir -p "$OUT/repo" "$OUT/wheels"

# networks that inspect HTTPS (some offices and build machines) can mount their
# certificate at /extra-ca.crt; GitHub Actions does not need it
if [ -f /extra-ca.crt ]; then
    mkdir -p /usr/local/share/ca-certificates
    cp /extra-ca.crt /usr/local/share/ca-certificates/extra-ca.crt
    export PIP_CERT=/etc/ssl/certs/ca-certificates.crt GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt
fi

echo ">>> Preparando Debian (con firmware no libre)"
for f in /etc/apt/sources.list.d/*.sources; do
    sed -i -E '/^Components:/ { / non-free-firmware/! s/$/ non-free-firmware/ }' "$f"
done
apt-get update -q
apt-get install -y -q --no-install-recommends \
    ca-certificates git dpkg-dev python3 python3-venv python3-pip python3-dev build-essential >/dev/null
[ -f /extra-ca.crt ] && update-ca-certificates >/dev/null

# ---------------------------------------------------------------------------
echo ">>> Calculando paquetes y dependencias"
mapfile -t WANTED < <(read_list packages.txt; read_list packages-optional.txt)
AVAILABLE=()
for pkg in "${WANTED[@]}"; do
    if apt-cache show "$pkg" >/dev/null 2>&1; then
        AVAILABLE+=("$pkg")
    else
        echo "(aviso) $pkg no existe en esta versión de Debian, se omite"
    fi
done
# the whole dependency tree, including packages the base system already has:
# then the USB never depends on what the installed system happens to have
apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts \
        --no-breaks --no-replaces --no-enhances "${AVAILABLE[@]}" \
    | grep -E '^[a-z0-9]' | sort -u > "$OUT/packages.all"
# skip virtual package names (they have no .deb of their own)
: > "$OUT/packages.real"
while IFS= read -r pkg; do
    if apt-cache show --no-all-versions "$pkg" >/dev/null 2>&1; then
        echo "$pkg" >> "$OUT/packages.real"
    fi
done < "$OUT/packages.all"
echo "    $(wc -l < "$OUT/packages.real") paquetes"

echo ">>> Descargando paquetes"
# a rerun only downloads what is missing
: > "$OUT/packages.missing"
while IFS= read -r pkg; do
    compgen -G "$OUT/repo/${pkg}_*.deb" >/dev/null || echo "$pkg" >> "$OUT/packages.missing"
done < "$OUT/packages.real"
if [ -s "$OUT/packages.missing" ]; then
    (cd "$OUT/repo" && xargs -a "$OUT/packages.missing" -n 40 apt-get download -q -o APT::Sandbox::User=root)
fi
rm -f "$OUT/packages.missing"
(cd "$OUT/repo" && dpkg-scanpackages --multiversion . /dev/null > Packages 2>/dev/null && gzip -9kf Packages)
rm -f "$OUT/packages.all"

# ---------------------------------------------------------------------------
echo ">>> Descargando FieldStation42 ($FS42_COMMIT)"
FS42_SRC=$(mktemp -d)
git -C "$FS42_SRC" init -q
git -C "$FS42_SRC" fetch -q --depth 1 "$FS42_REPO" "$FS42_COMMIT"
git -C "$FS42_SRC" archive --format=tar.gz -o "$OUT/fieldstation42.tar.gz" --prefix=./ FETCH_HEAD
# keep its license next to the copy, as MPL-2.0 asks
git -C "$FS42_SRC" show FETCH_HEAD:LICENSE > "$OUT/FIELDSTATION42-LICENSE.txt"

echo ">>> Compilando las librerías de Python"
python3 -m venv /tmp/wheelbuild
/tmp/wheelbuild/bin/pip install -q --upgrade pip wheel
git -C "$FS42_SRC" show FETCH_HEAD:install/requirements.in > /tmp/fs42-requirements.in
/tmp/wheelbuild/bin/pip wheel -q -w "$OUT/wheels" \
    -r /tmp/fs42-requirements.in -r "$SRC/panel/requirements.txt" pip setuptools wheel

echo ">>> Resumen"
du -sh "$OUT/repo" "$OUT/wheels" "$OUT/fieldstation42.tar.gz"

#!/usr/bin/env bash
# Adds T-Rex Bites to the boot menu of another Linux on the same computer
# (Fedora, Ubuntu, Mint, Debian...). Use it after installing T-Rex Bites with
# the USB option "Instalar al lado de otro Linux", which leaves that Linux's
# boot menu untouched.
#
# Run it in the OTHER Linux:
#   curl -fsSL https://raw.githubusercontent.com/Vanttacode/T-Rex-bites/main/system/agregar-al-menu.sh | sudo bash
#
# Options (after "bash -s --" when piping, or directly when running the file):
#   --por-defecto   start T-Rex Bites when nobody picks an option in the menu
#   --quitar        remove T-Rex Bites from the menu again
#
# It only adds one small menu file (/etc/grub.d/08_trexbites) and shows the
# menu for 10 seconds; it never changes partitions or the other system's files.
set -euo pipefail

ENTRY_FILE=/etc/grub.d/08_trexbites
TITLE="T-Rex Bites"
MAKE_DEFAULT=0
REMOVE=0
for arg in "$@"; do
    case "$arg" in
        --por-defecto) MAKE_DEFAULT=1 ;;
        --quitar) REMOVE=1 ;;
        *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Ejecútalo con sudo." >&2
    exit 1
fi

if command -v grub2-mkconfig >/dev/null; then
    MKCONFIG=(grub2-mkconfig -o /boot/grub2/grub.cfg)   # Fedora, RHEL, openSUSE
elif command -v update-grub >/dev/null; then
    MKCONFIG=(update-grub)                              # Debian, Ubuntu, Mint
elif command -v grub-mkconfig >/dev/null; then
    MKCONFIG=(grub-mkconfig -o /boot/grub/grub.cfg)     # Arch and others
else
    echo "No encontré GRUB en este Linux; este script solo sirve con GRUB." >&2
    exit 1
fi

regenerate() {
    echo ">>> Actualizando el menú de arranque"
    "${MKCONFIG[@]}"
}

if [ "$REMOVE" = 1 ]; then
    rm -f "$ENTRY_FILE"
    regenerate
    echo "Listo: T-Rex Bites ya no aparece en el menú (su partición sigue en el disco)."
    exit 0
fi

# ---------------------------------------------------------------------------
echo ">>> Buscando la partición de T-Rex Bites"
MNT=$(mktemp -d)
cleanup() { mountpoint -q "$MNT" && umount "$MNT"; rmdir "$MNT"; }
trap cleanup EXIT

FOUND_UUID=""
while read -r dev fstype uuid; do
    [ "$fstype" = ext4 ] || continue
    [ -n "$uuid" ] || continue
    # partitions in use by this Linux are skipped
    if findmnt -rn -S "$dev" >/dev/null; then
        continue
    fi
    if mount -o ro "$dev" "$MNT" 2>/dev/null; then
        if [ -d "$MNT/opt/trexbites" ] || grep -qx trexbites "$MNT/etc/hostname" 2>/dev/null; then
            if [ -e "$MNT/vmlinuz" ] && [ -e "$MNT/initrd.img" ]; then
                FOUND_UUID=$uuid
                echo "    Encontrada en $dev"
            else
                echo "(aviso) $dev parece T-Rex Bites pero no tiene /vmlinuz; ¿terminó la instalación?" >&2
            fi
        fi
        umount "$MNT"
    fi
    [ -n "$FOUND_UUID" ] && break
done < <(lsblk -rnpo NAME,FSTYPE,UUID)

if [ -z "$FOUND_UUID" ]; then
    echo "No encontré T-Rex Bites en este computador." >&2
    echo "Instálalo primero desde el USB con \"Instalar al lado de otro Linux\"." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
echo ">>> Agregando \"$TITLE\" al menú"
# /vmlinuz and /initrd.img always point to T-Rex Bites' current kernel, so this
# entry keeps working after its updates without running this script again
cat > "$ENTRY_FILE" <<EOF
#!/bin/sh
# Added by T-Rex Bites (agregar-al-menu.sh). Remove with: agregar-al-menu.sh --quitar
cat <<'MENU'
menuentry '$TITLE' --class debian --class gnu-linux --id trexbites {
    insmod part_gpt
    insmod part_msdos
    insmod ext2
    search --no-floppy --fs-uuid --set=root $FOUND_UUID
    linux /vmlinuz root=UUID=$FOUND_UUID ro quiet loglevel=3
    initrd /initrd.img
}
MENU
EOF
chmod 755 "$ENTRY_FILE"

# show the menu instead of hiding it (Fedora hides it by default)
if [ -f /etc/default/grub ]; then
    sed -i -E 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=10/' /etc/default/grub
    grep -q '^GRUB_TIMEOUT=' /etc/default/grub || echo 'GRUB_TIMEOUT=10' >> /etc/default/grub
    if grep -q '^GRUB_TIMEOUT_STYLE=' /etc/default/grub; then
        sed -i -E 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=menu/' /etc/default/grub
    else
        echo 'GRUB_TIMEOUT_STYLE=menu' >> /etc/default/grub
    fi
fi
if command -v grub2-editenv >/dev/null; then
    grub2-editenv - unset menu_auto_hide || true
fi

if [ "$MAKE_DEFAULT" = 1 ]; then
    sed -i -E 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=trexbites/' /etc/default/grub
    grep -q '^GRUB_DEFAULT=' /etc/default/grub || echo 'GRUB_DEFAULT=trexbites' >> /etc/default/grub
    if command -v grub2-set-default >/dev/null; then
        grub2-set-default trexbites || true
    fi
    # Fedora makes every new kernel the default; keep T-Rex Bites instead
    if [ -f /etc/sysconfig/kernel ]; then
        sed -i -E 's/^UPDATEDEFAULT=.*/UPDATEDEFAULT=no/' /etc/sysconfig/kernel
    fi
fi

regenerate
echo
echo "Listo. Al reiniciar verás el menú durante 10 segundos con \"$TITLE\"."
if [ "$MAKE_DEFAULT" = 1 ]; then
    echo "Si no eliges nada, arranca T-Rex Bites."
else
    echo "Si no eliges nada, arranca este Linux como siempre."
    echo "(Para que arranque T-Rex Bites por defecto: vuelve a ejecutarlo con --por-defecto)"
fi

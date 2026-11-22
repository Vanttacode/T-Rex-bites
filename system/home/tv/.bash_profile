# shellcheck shell=bash
# T-Rex Bites: on the first screen, start the TV picture right away.
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor >/dev/null 2>&1
fi

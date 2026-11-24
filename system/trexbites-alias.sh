#!/usr/bin/env bash
# Announces a second name for the TV on the home network (mDNS), so phones
# open the remote at http://control.local while trexbites.local stays the
# full panel. Installed as /opt/trexbites/bin/trexbites-alias.
set -u
NAME=${1:-control.local}

current_ip() {
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}'
}

while true; do
    addr=$(current_ip)
    if [ -z "$addr" ]; then
        sleep 10   # no network yet
        continue
    fi
    avahi-publish -a -R "$NAME" "$addr" &
    pid=$!
    # republish when the address changes (new WiFi, new router) or avahi restarts
    while sleep 20; do
        if [ "$(current_ip)" != "$addr" ] || ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
    done
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
done

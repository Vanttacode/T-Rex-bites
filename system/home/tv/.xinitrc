#!/bin/sh
# T-Rex Bites X session: black screen, no screensaver, then hand over to the
# systemd user services that run the TV.
xsetroot -solid black
xset s off
xset s noblank
xset -dpms

systemctl --user import-environment DISPLAY XAUTHORITY
systemctl --user start trexbites-x11.target

# keep X running; the TV itself is fs42.service
while true; do sleep 3600; done

#!/usr/bin/env python3
"""WiFi setup on the TV screen itself, with the keyboard or the mouse.

Shown by trexbites-setup.service while the box has never been connected to a
network. Next to it, the phone method ("T-Rex Bites Config") keeps working
when the WiFi chip can create that network; this screen says so only then.

Standard library + Tkinter only: it runs with the system's python3.
"""

import json
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trexbites_panel.wifi import WifiManager, validate  # noqa: E402

STATE_DIR = Path(os.environ.get("TREXBITES_STATE_DIR", "/var/lib/trexbites"))
STATUS_FILE = STATE_DIR / "wifi-status.json"
BUSY_FILE = STATE_DIR / "wifi-busy"

BG = "#12142b"
PANEL = "#1f2347"
TEXT = "#f3f1e8"
MUTED = "#a9abc9"
ACCENT = "#ff8a1f"
GREEN = "#4cd964"
RED = "#ff5a5a"


def read_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def mark_busy():
    """Tell the panel not to switch the WiFi card to the setup network now."""
    try:
        BUSY_FILE.write_text(str(time.time()))
    except OSError:
        pass


def clear_busy():
    try:
        BUSY_FILE.unlink()
    except OSError:
        pass


def bars(signal):
    n = 4 if signal >= 75 else 3 if signal >= 50 else 2 if signal >= 25 else 1
    return ("▂▄▆█"[:n]).ljust(4, "·")


class SetupScreen:

    def __init__(self, root):
        self.root = root
        self.wifi = WifiManager()
        self.networks = []
        self.working = False

        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        scale = max(0.6, min(w / 1280, h / 720))
        f = lambda size, bold=False: ("DejaVu Sans", int(size * scale), "bold" if bold else "normal")  # noqa: E731

        root.title("T-Rex Bites - WiFi")
        root.configure(bg=BG)
        # there is no window manager: cover the screen ourselves
        root.geometry(f"{w}x{h}+0+0")
        root.attributes("-fullscreen", True)

        tk.Label(root, text="Configura el WiFi de T-Rex Bites", font=f(34, True),
                 fg=ACCENT, bg=BG).pack(pady=(int(24 * scale), int(8 * scale)))
        self.subtitle = tk.Label(root, text="", font=f(17), fg=MUTED, bg=BG)
        self.subtitle.pack()

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=int(40 * scale), pady=int(16 * scale))

        # ---- keyboard / mouse ----
        left = tk.Frame(body, bg=PANEL, padx=int(20 * scale), pady=int(16 * scale))
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="⌨  Con el teclado", font=f(22, True), fg=TEXT, bg=PANEL).pack(anchor="w")
        tk.Label(left, text="1. Elige tu red con las flechas ↑ ↓ y aprieta Enter",
                 font=f(15), fg=MUTED, bg=PANEL).pack(anchor="w", pady=(4, 6))
        self.listbox = tk.Listbox(left, font=f(20), height=7, bg=BG, fg=TEXT,
                                  selectbackground=ACCENT, selectforeground="#241200",
                                  highlightthickness=2, highlightcolor=ACCENT,
                                  activestyle="none", borderwidth=0)
        self.listbox.pack(fill="both", expand=True)
        tk.Label(left, text="2. Escribe la clave del WiFi y aprieta Enter",
                 font=f(15), fg=MUTED, bg=PANEL).pack(anchor="w", pady=(10, 4))
        row = tk.Frame(left, bg=PANEL)
        row.pack(fill="x")
        self.password = tk.Entry(row, font=f(20), show="•", bg=BG, fg=TEXT,
                                 insertbackground=TEXT, highlightthickness=2,
                                 highlightcolor=ACCENT, borderwidth=0)
        self.password.pack(side="left", fill="x", expand=True, ipady=int(6 * scale))
        self.show_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="Ver clave", variable=self.show_var, command=self._toggle_show,
                       font=f(14), fg=MUTED, bg=PANEL, selectcolor=BG,
                       activebackground=PANEL, activeforeground=TEXT).pack(side="left", padx=8)
        buttons = tk.Frame(left, bg=PANEL)
        buttons.pack(fill="x", pady=(10, 0))
        self.connect_btn = tk.Button(buttons, text="Conectar", font=f(18, True), command=self.connect,
                                     bg=ACCENT, fg="#241200", activebackground="#ffa04a",
                                     borderwidth=0, padx=20, pady=6)
        self.connect_btn.pack(side="left")
        tk.Button(buttons, text="Buscar redes (F5)", font=f(15), command=self.scan,
                  bg="#2a2f5c", fg=TEXT, activebackground="#343a70", borderwidth=0,
                  padx=14, pady=6).pack(side="left", padx=10)
        self.status = tk.Label(left, text="", font=f(17, True), fg=MUTED, bg=PANEL,
                               wraplength=int(620 * scale), justify="left")
        self.status.pack(anchor="w", pady=(12, 0))

        # ---- phone / cable ----
        right = tk.Frame(body, bg=BG, padx=int(24 * scale))
        right.pack(side="left", fill="both")
        self.phone_title = tk.Label(right, text="📱  Con el teléfono", font=f(22, True), fg=TEXT, bg=BG)
        self.phone_text = tk.Label(right, text="", font=f(16), fg=MUTED, bg=BG,
                                   justify="left", wraplength=int(420 * scale))
        self.phone_title.pack(anchor="w")
        self.phone_text.pack(anchor="w", pady=(6, 24))
        tk.Label(right, text="🔌  Con cable de red", font=f(22, True), fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(right, text="Conecta un cable al router y espera unos segundos: no hay que configurar nada.",
                 font=f(16), fg=MUTED, bg=BG, justify="left", wraplength=int(420 * scale)).pack(anchor="w", pady=6)

        self.listbox.bind("<Return>", lambda e: self.password.focus_set())
        self.listbox.bind("<Double-Button-1>", lambda e: self.password.focus_set())
        self.password.bind("<Return>", lambda e: self.connect())
        root.bind("<F5>", lambda e: self.scan())

        cached = read_status().get("networks") or []
        if cached:
            self._show_networks(cached)
        else:
            self.scan()
        self._refresh_phone()
        self.listbox.focus_set()
        root.after(300, root.focus_force)

    # ---------- helpers ----------

    def _toggle_show(self):
        self.password.configure(show="" if self.show_var.get() else "•")

    def _set_status(self, text, color=MUTED):
        self.status.configure(text=text, fg=color)

    def _show_networks(self, networks):
        self.networks = networks
        self.listbox.delete(0, "end")
        for net in networks:
            lock = "  🔒" if net.get("secure") else ""
            self.listbox.insert("end", f"  {bars(net.get('signal', 0))}   {net['ssid']}{lock}")
        if networks:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self.listbox.activate(0)
            self._set_status("")
        else:
            self._set_status("No se encontraron redes. Aprieta F5 para buscar de nuevo.", RED)

    def _refresh_phone(self):
        status = read_status()
        if status.get("hotspot"):
            self.phone_text.configure(text=(
                f"1. Conéctate a la red WiFi \"{status.get('hotspot_ssid', 'T-Rex Bites Config')}\"\n"
                f"2. Se abre sola la página (si no: http://{status.get('hotspot_ip', '10.42.0.1')})\n"
                "3. PIN 1234 y elige tu WiFi"))
            self.subtitle.configure(text="Elige una forma: con el teclado, con el teléfono o con cable")
        else:
            self.phone_text.configure(text=(
                "La tarjeta WiFi de este computador no pudo crear la red de configuración. "
                "Usa el teclado o un cable."
                if status.get("hotspot_error") else
                "Preparando la red \"T-Rex Bites Config\"… (puede tardar un minuto)"))
            self.subtitle.configure(text="Elige una forma: con el teclado o con cable")
        self.root.after(5000, self._refresh_phone)

    def _run(self, work, done):
        def worker():
            mark_busy()
            try:
                result = work()
            except Exception as e:  # shown on screen, never a crash
                result = e
            finally:
                clear_busy()
            self.root.after(0, lambda: done(result))
        self.working = True
        threading.Thread(target=worker, daemon=True).start()

    # ---------- actions ----------

    def scan(self):
        if self.working:
            return
        self._set_status("🔎 Buscando redes…")

        def work():
            # the card can't search while it is the setup network
            if read_status().get("hotspot"):
                self.wifi.stop_hotspot()
            return self.wifi.scan()

        def done(result):
            self.working = False
            if isinstance(result, Exception):
                self._set_status(f"No se pudo buscar redes: {result}", RED)
            else:
                self._show_networks(result)
                self.listbox.focus_set()

        self._run(work, done)

    def connect(self):
        if self.working:
            return
        selected = self.listbox.curselection()
        if not selected:
            self._set_status("Primero elige tu red en la lista.", RED)
            self.listbox.focus_set()
            return
        net = self.networks[selected[0]]
        password = self.password.get()
        if net.get("secure") and not password:
            self._set_status("Escribe la clave del WiFi.", RED)
            self.password.focus_set()
            return
        try:
            ssid, password = validate(net["ssid"], password if net.get("secure") else "")
        except ValueError as e:
            self._set_status(str(e), RED)
            self.password.focus_set()
            return
        self._set_status(f"⏳ Conectando a \"{ssid}\"…")
        self.connect_btn.configure(state="disabled")

        def work():
            self.wifi.connect(ssid, password)
            return self.wifi.last_error

        def done(error):
            self.working = False
            self.connect_btn.configure(state="normal")
            if error:
                self._set_status(f"❌ {error}", RED)
                self.password.focus_set()
            else:
                self._set_status(f"✅ ¡Conectada a \"{ssid}\"! La tele empieza en unos segundos.\n"
                                 "Desde tu teléfono, en tu WiFi: http://trexbites.local", GREEN)

        self._run(work, done)


def main():
    root = tk.Tk()
    SetupScreen(root)
    root.mainloop()


if __name__ == "__main__":
    main()

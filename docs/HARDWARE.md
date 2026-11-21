# Hardware compatible

T-Rex Bites se instala en **computadores de 64 bits (x86-64)**. El USB incluye
los drivers (firmware) de WiFi, video y sonido de las marcas más comunes:
Intel, Realtek, Atheros, Broadcom y AMD.

## Cómo saber si un computador sirve

- **Tiene 64 bits:** casi todo lo fabricado desde ~2008. Si en BIOS/UEFI aparece
  "UEFI", es de 64 bits.
- **RAM:** mínimo 2 GB; con 4 GB funciona holgado.
- **Disco:** mínimo 32 GB. Cada hora de video ocupa entre 0,5 y 2 GB.

## CPUs muy antiguas (Core 2, primeros Atom, AMD E-350/G-T48E)

FieldStation42 usa librerías (por ejemplo, Qt/PySide6) que hoy se compilan para
procesadores con **SSE4.1**. En CPUs más antiguas la tele puede cerrarse sola
con el error `Illegal instruction`. Para comprobarlo, con el equipo ya instalado,
presiona `Ctrl+Alt+F2`, entra como `tv` y ejecuta:

```bash
grep -o -w 'sse4_1' /proc/cpuinfo | head -1
```

Si no aparece `sse4_1`, revisa la guía de FieldStation42
[RUNNING_ON_OLD_CPUS.md](https://github.com/shane-mason/FieldStation42/blob/main/docs/RUNNING_ON_OLD_CPUS.md).

## Arrancar desde el USB

| Marca | Tecla al encender |
|---|---|
| Lenovo | F12 (o el botón **Novo**, un agujerito al costado) |
| HP | F9 (o Esc y luego F9) |
| Dell | F12 |
| Acer | F12 (a veces hay que activarlo en BIOS con F2) |
| Asus | Esc o F8 |
| Mac Intel | Mantener **Option ⌥** |

Si el computador tiene **Secure Boot** y no arranca el USB, desactívalo en la
BIOS/UEFI.

## Usar un notebook conectado a la tele

Se puede cerrar la tapa: T-Rex Bites ignora la tapa y nunca se suspende.
Conecta el notebook a la tele por HDMI.

## Cuenta de mantenimiento

El sistema tiene un usuario `tv` con contraseña `trexbites` (o la que se definió
al crear el USB con `TREX_TV_PASSWORD`). Solo se usa desde el teclado del equipo
(`Ctrl+Alt+F2`). No hay acceso remoto por SSH.

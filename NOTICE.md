# Avisos de terceros

## FieldStation42

T-Rex Bites usa [FieldStation42](https://github.com/shane-mason/FieldStation42),
creado por Shane Mason, como motor de la tele: programación, canales y reproducción.

- Licencia: **Mozilla Public License 2.0** (https://mozilla.org/MPL/2.0/)
- Este repositorio **no copia** su código. El instalador descarga la versión exacta
  indicada en `upstream/fieldstation42.conf` desde su repositorio oficial, sin modificarla.
- El USB de instalación sin internet **incluye una copia sin modificar** de esa versión
  (`fieldstation42.tar.gz`), junto con su licencia (`FIELDSTATION42-LICENSE.txt`).
  Su código fuente está en https://github.com/shane-mason/FieldStation42.
- Si en el futuro se modifican archivos de FieldStation42, esos archivos deben
  seguir bajo MPL-2.0 y publicarse con su código fuente, como exige esa licencia.

Si te gusta el proyecto, puedes apoyar a su autor en
[Patreon](https://www.patreon.com/cw/FieldStation42).

## Debian

El USB de instalación se construye a partir de la imagen oficial *netinst* de
[Debian](https://www.debian.org/), que se descarga y verifica con las sumas
SHA256 publicadas por Debian, e incluye paquetes binarios oficiales de Debian 13
sin modificar. Debian y sus paquetes mantienen sus propias licencias (muchas GPL);
su código fuente está disponible en https://sources.debian.org y
https://snapshot.debian.org.

## Librerías de Python

El USB incluye librerías de Python descargadas de PyPI (por ejemplo PySide6/Qt
bajo LGPL, FastAPI, Pillow), sin modificar, con sus licencias dentro de cada paquete.

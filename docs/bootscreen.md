# Pantalla de arranque: PI ZERO

Implementa el handoff C · Terminal de 480×320 con VT323. LISTO permanece en pantalla; la UI de monitoreo queda para después. La estación se ejecuta como demo en segundo plano, sin sensores reales, pantalla ni HTTP.

El renderer ahora sigue la especificación v2: INICIANDO, barra de 23 bloques y animaciones A1–A6. El hilo de comprobaciones y la configuración de red no cambian.

## Comprobaciones reales

- Sistema: `basic.target` activo; las etapas Wi-Fi, servicios y app se comprueban por separado.
- Wi-Fi: IPv4 global y ruta por defecto en `wlan0`; no usa Internet ni prueba la API remota.
- Servicios: `ssh.service` y `avahi-daemon.service` activos.
- App: `pi-sensor-station.service` activo. Usa `Type=notify`; Python envía READY=1 después de su primera adquisición simulada e inicialización.

Los pasos avanzan en orden. Un paso anterior que deja de estar listo antes de LISTO devuelve el avance a ese paso. Cada timeout cuenta desde que el paso está en curso. Al vencer muestra error, cuenta de 8 a 0 y vuelve a comprobar; el uptime no se reinicia. Una vez en LISTO, el tiempo queda congelado y la imagen permanece.

El timeout predeterminado es 60 s. `basic.target` representa la base del sistema; usar `multi-user.target` duplicaba la espera de la app, que forma parte de la etapa siguiente.

## Archivos instalados en la Raspberry

| Ruta | Función |
| --- | --- |
| `/opt/bootscreen/bootscreen/` | Renderer, lógica, sondeos y fuente local |
| `/opt/bootscreen/bootscreen/assets/VT323-Regular.ttf` | Fuente del handoff; sin descarga al arrancar |
| `/opt/bootscreen/station/pi_sensor_station/` | Estación para la demo de inicialización |
| `/usr/local/bin/bootscreen` | CLI del servicio y pruebas |
| `/etc/bootscreen/config.toml` | Configuración activa |
| `/opt/bootscreen.bak-20261025/` | Copia previa a v2 del paquete, TOML, unidad y launcher |
| `/opt/bootscreen.bak-20261025/rollback.sh` | Revierte solo v2 y vuelve a iniciar el servicio |
| `/etc/systemd/system/bootscreen.service` | Servicio temprano, WantedBy=sysinit.target; cede y termina al reclamar la pantalla el monitor |
| `/etc/systemd/system/pi-sensor-station.service` | Demo sin pantalla ni HTTP |
| `/run/bootscreen/status.json` | Estado, IP, uptime de primer cuadro y de LISTO |
| `/usr/local/sbin/bootscreen-rollback` | Restaura la instalación anterior |
| `/var/lib/bootscreen/backups/<fecha>/rollback.sh` | Rollback conservado junto a las copias |

El handoff original también está copiado a `/home/zero/bootscreen-handoff/`. Las capturas de referencia del repositorio están en `design/bootscreen-reference/`.

## Configuración

```toml
[display]
framebuffer = "/dev/fb1"

[animations]
enabled = true
blink = true
dots = true
step_flash = true
ready_intro = false
error_strip = true
max_fps = 5

[runtime]
interface = "wlan0"
retry_seconds = 8
poll_seconds = 1.0
check_timeout = 1.0

[[steps]]
label = "Sistema"
kind = "systemd"
units = ["basic.target"]
timeout = 60
error_title = "ERROR"

[[steps]]
label = "Wi-Fi"
kind = "network"
timeout = 60
error_title = "SIN WI-FI"

[[steps]]
label = "Servicios"
kind = "systemd"
units = ["ssh.service", "avahi-daemon.service"]
timeout = 60
error_title = "ERROR"

[[steps]]
label = "App"
kind = "systemd"
units = ["pi-sensor-station.service"]
timeout = 60
error_title = "ERROR"
```

Cada paso acepta `kind = "systemd"` con `units`, `network`, `command` con un array `command`, o `tcp` con `host` y `port`. Los comandos se ejecutan como argv, sin shell. Usa comandos locales y rápidos; cada ejecución tiene el límite `check_timeout`. Una etapa desactivada con `enabled = false` se marca `[--]`, nunca como una comprobación exitosa.

## Instalación

La Pi probada tiene Python 3.13 y Pillow 11.1. No se necesita numpy ni pip global. En otra Pi instala `python3-pil` con apt antes de usar el instalador. El instalador requiere Python 3.11 o posterior por TOML.

```bash
sudo python3 deploy/bootscreen/install.py --with-demo-app
sudo systemctl start pi-sensor-station.service
sudo systemctl start bootscreen.service
```

El instalador guarda copias antes de cambiar archivos, deja un rollback y habilita los servicios. No reinicia y no cambia red ni SSH. En esta instalación el backup original quedó en `/var/lib/bootscreen/backups/20261025-211205/`.

`bootscreen.service` tiene DefaultDependencies=no, Type=simple, sin Before= ni dependencia de network-online.target. Espera a local-fs y udev; si el framebuffer todavía no existe, espera dentro de su proceso sin bloquear basic.target ni multi-user.target. Mantiene prioridad baja.

## Pruebas y uso

```bash
# Sin pantalla, sensores ni acceso a red:
PYTHONPATH=src python3 -m bootscreen --output /tmp/boot-previews
PYTHONPATH=src python3 -m unittest discover -s tests -v

# En la Raspberry instalada:
sudo bootscreen --demo
sudo bootscreen --state error
sudo bootscreen --state ready --duration 8
sudo bootscreen --frame iniciando-puntos-2
sudo journalctl -u bootscreen.service -b --no-pager
cat /run/bootscreen/status.json
```

`--demo` recorre el inicio normal, muestra un fallo simulado de App con reintento y recupera a LISTO; tarda unos 20 s. `--frame` acepta los nombres de `design/bootscreen-reference/anim/` sin la extensión PNG. `--state` fuerza una pantalla por cuatro segundos. Las pruebas toman el bloqueo exclusivo, guardan los bytes previos del framebuffer y los restauran al terminar; no paran ni cambian el servicio real y no realizan comprobaciones reales durante `--demo`.

## Cesión de la pantalla al monitor

`bootscreen` y la vista de monitoreo comparten `/run/bootscreen/screen.lock`. Antes de su primer dibujo, la estación toma el bloqueo y crea `monitor-active` dentro de `/run/bootscreen`. El bootscreen comprueba esa marca dentro del mismo bloqueo; al encontrarla deja de escribir y sale correctamente. Así el monitor queda como único escritor y la última imagen de arranque no puede reaparecer sobre sus lecturas. `RuntimeDirectoryPreserve=yes` conserva el directorio mientras corre el monitor; la unidad de la estación tiene permiso de escritura sobre él. Al terminar la estación, su manejador `atexit` retira la marca.

La transferencia se ejecuta cuando la estación produce el primer cuadro. El bootscreen puede quedar activo hasta ese momento; después debe verse `bootscreen.service` como `inactive` y `pi-sensor-station.service` como `active`. Si se detiene la estación, la vista de arranque no se reactiva automáticamente.

Las animaciones de estado estable respetan `max_fps`. La entrada LISTO quedó desactivada por medición: el render de cuadro completo del Pi Zero tardaba cientos de milisegundos y 16 niveles de barra en 0,9 s requerirían hasta 18 actualizaciones/s; además, el área del título cruza más de 140 filas y la transferencia SPI tiene un mínimo teórico de unos 68 ms. Por eso LISTO aparece completa de golpe y luego solo parpadea el cursor. `enabled = false` fija puntos, cursores y franja encendidos, sin destellos ni entrada animada.

`deploy/bootscreen/live_test.py` simula el fallo de un sondeo mediante un archivo temporal, observa la cuenta regresiva y la recuperación. Se ejecuta con el daemon real detenido y la estación headless activa. No cambia la configuración real, Wi-Fi ni SSH:

```bash
sudo python3 deploy/bootscreen/live_test.py
```

El renderer entrega rectángulos por elemento. El servicio compara y convierte únicamente sus filas, agrupa filas consecutivas y evita cuadros iguales. El bucle deriva fases de `time.monotonic()` y duerme hasta la siguiente fase de animación, el reloj o la comprobación de estado.

## Consola y período blanco

El instalador conserva ambas consolas de rescate (`console=serial0,115200` y `console=tty1`) y los parámetros de raíz. Añade `quiet loglevel=3 logo.nologo vt.global_cursor_default=0 consoleblank=0 fbcon=map:0`, elimina `splash` y establece `disable_splash=1` en config.txt. La consola se reserva para fb0; no se vincula a la LCD fb1.

Estas opciones no apagan la retroiluminación ni permiten dibujar antes de que el driver registre fb1. No hay un control de backlight expuesto en este equipo. La primera parte blanca requiere estudiar la carga anterior del controlador o el hardware, fuera de estos cambios.

## Medidas previas al reinicio

| Medición | Resultado |
| --- | --- |
| Arranque de referencia | 156,357 s |
| Registro inicial de fb1 | 58,376 s |
| IPv4 y ruta Wi-Fi listas | Aproximadamente 152 s |
| Primera imagen, incluyendo imports del renderer | 1,471 s |
| Render completo, por estado | 0,156–0,272 s |
| Conversión completa RGB565 | 0,065–0,074 s |
| Copia al framebuffer, completa o por filas | 0,004–0,010 s |
| Actualización optimizada del reloj | Promedio 0,0877 s; 15 filas |
| Memoria máxima del benchmark de cuatro pantallas | 22,33 MiB |

Los cuatro volcados del framebuffer coincidieron exactamente con los bytes RGB565 generados. El renderer conserva la estética del handoff; las diferencias RGB respecto a sus capturas son de aproximadamente 3,2–5,1% de píxeles, principalmente bordes del texto. Las pruebas admiten hasta un 6% para conservar el comportamiento del renderer suministrado.

## Arranque medido después de instalar

En el primer reinicio, antes de cambiar la etapa Sistema a `basic.target`, systemd informó 11,543 s de kernel y 171,001 s de espacio de usuario, 182,544 s en total. El primer cuadro se escribió a los 64,460 s; LISTO apareció a los 180,060 s con IPv4 `192.168.100.17`. `multi-user.target` se alcanzó a los 167,745 s. Esta medición incluye la etapa Sistema con su timeout agotado y recuperación.

Con `basic.target`, el segundo reinicio tomó 184,383 s (11,514 s de kernel + 172,869 s de espacio de usuario). El primer cuadro apareció a los 65,170 s y LISTO a los 182,150 s, con los cuatro pasos activos y sin activar el estado de error. La diferencia de 1,8 s entre arranques es menor que la variación observada en los servicios de red; el bootscreen no agrega una dependencia que retrase los targets.

Con la animación A5 desactivada, el proceso quedó en LISTO con `192.168.100.17` y los cuatro pasos activos. La última medición en reposo dio 1,22 s de CPU en 20 s (6,1% de un núcleo) y 23,6 MiB de RSS. El refresco final solo toca el cursor de la IP; el renderer parcial y el framebuffer conservan el resto del cuadro. Este consumo es mayor que la medición previa de 0,05 s/20 s, así que conviene volver a medirlo tras los próximos cambios de estado y en un arranque frío.

Con la nueva escritura por rectángulos, `bootscreen --demo` completó sus 20 s: 40 cuadros, 4.098 filas afectadas en total, 0,140 s de media por cuadro (0,084 s de render y 0,056 s en framebuffer), 0,0029 s de media en llamadas `pwrite` y 7,77 s de CPU acumulada. Es una secuencia de animación activa; no representa el consumo en LISTO. `--frame listo-barra-mitad` también finalizó y restauró la pantalla. Después de ambas pruebas, `bootscreen.service` siguió activo y el estado volvió a LISTO.

Antes de v2, al escribir bytes de la imagen que ya estaba en pantalla, `pwrite` de 320 filas tardó una media de 1,862 ms (mediana 0,846 ms; máximo 10,873 ms, 30 muestras); 60 filas tardaron 0,390 ms (mediana 0,119 ms; máximo 2,896 ms, 50 muestras). Son tiempos de la llamada al kernel: no confirman cuándo termina la transferencia física SPI. En v2, `--demo` registra también filas actualizadas, tiempo total de render y escritura y CPU del proceso al terminar.

La escritura devuelve el control antes de que el driver termine necesariamente la transferencia SPI. Estos tiempos de copia no representan confirmación física de refresco. Una imagen completa contiene 307.200 bytes: a 16 MHz, su transmisión requiere como mínimo unos 0,154 s de reloj, más comandos y pausas del driver.

## Revertir

```bash
# Solo quitar la pantalla de arranque del inicio:
sudo systemctl disable --now bootscreen.service

# Restaurar todo lo gestionado por esta instalación, incluida la demo headless:
sudo /usr/local/sbin/bootscreen-rollback
# Alternativa, backup original:
sudo /var/lib/bootscreen/backups/20261025-211205/rollback.sh
# Volver únicamente de v2 a la instalación anterior, si se desea:
sudo /opt/bootscreen.bak-20261025/rollback.sh
```

El rollback restaura config.txt, cmdline.txt y cualquier unidad existente desde sus copias; elimina únicamente archivos nuevos de esta instalación cuyo contenido coincide con el instalado. Conserva backups y archivos nuevos que alguien haya modificado posteriormente. No reinicia por su cuenta. Los cambios de parámetros del kernel se aplican en el siguiente reinicio.

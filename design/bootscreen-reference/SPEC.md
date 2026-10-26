# Especificación visual v2: pantalla de arranque "C · Terminal" (480 × 320)

Cambios respecto a la v1: el título anterior pasa a **"INICIANDO"**, la barra de progreso avanza en
**bloques enteros** y se agregan **animaciones** (sección "Animaciones"). Todo lo demás sigue igual.

Fuente de verdad visual: las capturas en `reference/` y `reference/anim/`. Esta especificación da los
valores exactos; si algo no coincide con las capturas, mandan las capturas. Medidas en píxeles reales
de la pantalla (480 de ancho × 320 de alto).

## Tipografía y colores

| Rol | Valor |
|---|---|
| Fuente única | `assets/VT323-Regular.ttf` (SIL OFL 1.1, Peter Hull). Sin negrita, sin cursiva |
| Fondo | `#050805` (5, 8, 5) |
| Verde fósforo (texto principal, barra) | `#4DFF88` (77, 255, 136) |
| Verde apagado (pasos pendientes) | `#3FA865` (63, 168, 101) |
| Naranja (solo en error) | `#FF8A4C` (255, 138, 76) |

Texto solo en ASCII + letras con tilde. Usar guion normal `-` ("Wi-Fi", "SIN WI-FI"), porque VT323 no
tiene el guion no separable (U+2011). Los títulos van en MAYÚSCULAS.

## Estructura común (pantallas 1, 2 y 4)

Columna vertical con padding: arriba 18, lados 24, abajo 22. Cuatro bloques repartidos con espacio
uniforme entre ellos (equivalente a `justify-content: space-between`):

1. **Encabezado** (alto 26 px, texto 26 px, interlineado 1.0). Izquierda: `PI ZERO`. Derecha: tiempo
   transcurrido desde el encendido en `mm:ss` (ej. `00:23`).
2. **Título** (78 px, interlineado 0.9, espaciado +0.02 em, mayúsculas) seguido a 4 px de un **cursor de
   bloque** de 26 × 54 px (su borde inferior queda 1 px sobre la línea base del título).
3. **Lista de pasos** (texto 30 px, interlineado 1.05, una línea por paso). Cada línea: marcador de
   4 caracteres, 18 px de separación y el nombre del paso, alineados en columna.
   - `[OK]` hecho: verde. `[..]` en curso: verde. `[  ]` pendiente: verde apagado (dos espacios).
   - `[!!]` falló: fila resaltada (pantalla 4).
4. **Zona inferior**: barra de progreso (pantallas 1 y 2) o línea de reintento (pantalla 4).

### Barra de progreso (por bloques)

Caja de 432 × 22 px, borde de 2 px verde, 3 px de espacio interior (zona útil 422 px, que empieza en
x = 29). Dentro hay **23 bloques** de 14 px de ancho y 4 px de separación (el bloque *i* empieza en
x = 29 + 18·i). Bloques llenos: `n = round(progreso × 23)`, con
`progreso = (pasos OK + 0.5 si hay un paso en curso) / total de pasos`. Con 4 pasos: paso 2 en curso →
9 bloques; paso 4 en curso → 20 bloques. Después de los bloques llenos va el **bloque líder** (el
bloque n+1), que parpadea (ver animaciones). No hay bloque líder cuando n = 23.

## Pantallas

| # | Archivo de referencia | Título | Pasos | Zona inferior | Colores |
|---|---|---|---|---|---|
| 1 | `01-iniciando.png` | `INICIANDO` + 3 puntos animados | Sistema OK · Wi-Fi en curso · Servicios y App pendientes | 9 bloques + líder | verde |
| 2 | `02-casi-listo.png` | `CASI LISTO` (sin puntos) | los tres primeros OK · App en curso | 20 bloques + líder | verde |
| 3 | `03-listo.png` | `LISTO` | (sin lista) | barra llena + IP | verde |
| 4 | `04-error.png` | título de error del paso, ej. `SIN WI-FI` | Sistema OK · Wi-Fi falló · resto pendiente | `> reintentando en 8 s` | naranja |

"CASI LISTO" se usa cuando el último paso está en curso y todos los anteriores están OK. "INICIANDO" es
el título en cualquier otro momento del arranque normal (si aparece un título anterior en el código, la
configuración o los tests, cámbialo).

### Pantalla 3 · Listo

Tres bloques con espacio uniforme: encabezado, palabra, barra + IP.

- Encabezado como el resto, pero a la derecha `[OK] mm:ss` con el tiempo total del arranque (queda fijo).
- Palabra `LISTO`: 205 px, interlineado 0.74, espaciado +0.01 em, verde, a todo el ancho.
- Barra de 22 px **llena y sólida** (sin bloques), mismo borde de 2 px.
- 14 px debajo, la IP en 34 px: `> 192.168.1.42` y un cursor de bloque de 16 × 28 px que parpadea.
  La IP es la real del equipo (interfaz Wi-Fi); si no hay, mostrar el hostname.

### Pantalla 4 · Error

- Todo lo verde pasa a naranja (encabezado, título, línea de reintento), salvo los pasos que ya estaban
  OK, que se quedan verdes.
- La fila del paso que falló es una franja naranja de lado a lado (x = 18 a 462, alto 31.5 px) con texto
  en el color del fondo: `[!!] Wi-Fi - sin respuesta`.
- Zona inferior (texto 30 px, naranja): `> reintentando en N s`, cuenta regresiva desde 8. Al llegar a 0 se
  reintenta el paso; si se recupera, la pantalla vuelve a la secuencia normal.
- Título de error por paso (editable en configuración): Wi-Fi → `SIN WI-FI`; otros → `ERROR`
  (máximo 10 caracteres a 78 px).

## Animaciones

Todas son discretas (saltos, sin degradados ni fundidos), pensadas para pocos cuadros por segundo.
Cada una debe poder apagarse por configuración. Los tiempos se calculan con un reloj monotónico (no
acumulando retrasos). Entre pantallas los cambios son instantáneos.

| # | Animación | Dónde | Comportamiento exacto |
|---|---|---|---|
| A1 | Parpadeo 1 Hz | cursor del título, cursor de la IP, marcador `[..]`, bloque líder | 0.5 s visible, 0.5 s oculto; todos en la misma fase. Con el elemento oculto no se dibuja nada (fondo) |
| A2 | Puntos de "INICIANDO" | pantalla 1 | Tras el texto hay 3 posiciones reservadas para puntos. Ciclo de 1.6 s: 0 puntos, 1, 2, 3 puntos, 0.4 s cada uno (2.5 cuadros por segundo). El cursor **no se mueve** (queda tras los 3 puntos reservados). Solo en `INICIANDO`, no en `CASI LISTO` ni en error |
| A3 | Bloque líder | barra de pantallas 1 y 2 | El bloque siguiente al último lleno parpadea con A1. Sirve para saber que el equipo no está colgado aunque un paso tarde |
| A4 | Destello de paso | fila del paso que pasa a OK | En el instante en que el paso queda OK, su fila se pinta invertida (fondo verde de x = 18 a 462, texto color fondo) durante 0.35 s y luego vuelve a normal con `[OK]`. En ese mismo cuadro la barra salta a su nueva cantidad de bloques |
| A5 | Entrada de LISTO | pantalla 3, una sola vez al entrar | (1) Barrido del título de izquierda a derecha en 5 pasos de 0.15 s: se muestra 0, 20, 40, 60, 80 y 100 % del ancho útil (432 px). (2) Al mismo tiempo la barra se llena en 16 pasos iguales durante 0.9 s. (3) La IP (y su cursor) aparece de golpe a los 0.95 s. Después solo parpadea el cursor de la IP |
| A6 | Franja de error | fila `[!!]` de la pantalla 4 | Ciclo de 1.2 s: 0.72 s encendida (fondo naranja, texto oscuro) y 0.48 s apagada (sin fondo, texto naranja) |

Los cuadros clave están en `reference/anim/`:

| Archivo | Muestra |
|---|---|
| `iniciando-puntos-0..3.png` | A2: 0 a 3 puntos visibles |
| `iniciando-lider-apagado.png` | A1/A3: fase "oculto" del parpadeo (cursor, `[..]` y bloque líder apagados) |
| `destello-fila.png` | A4: fila `Sistema` invertida (generado con el renderer, sin captura del diseño) |
| `listo-barrido-0..5.png` | A5: barrido del título (0 a 100 %), barra vacía y sin IP |
| `listo-barra-mitad.png` | A5: título completo y barra a la mitad |
| `error-franja-apagada.png` | A6: fase "apagada" de la franja |

### Presupuesto de dibujo (pantalla SPI)

Mientras la pantalla está estable, lo único que cambia son pocas zonas pequeñas: puntos y cursor del título
(2.5 cuadros/s como máximo), marcador `[..]` y bloque líder (1 Hz), el contador `mm:ss` (1 Hz), la franja
de error (cambios cada ~0.5 s) y el cursor de la IP (1 Hz). Solo la entrada de LISTO (A5) redibuja zonas
grandes: unos 22 cuadros en 0.95 s, una sola vez. `render(screen, regions=dict)` en `src/bootscreen_render.py`
entrega los rectángulos de cada elemento (`time`, `title`, `dots`, `cursor`, `lead`, `bar`, `ip`,
`marker0..3`, `row0..3`, `retry`) para escribir al framebuffer solo las filas afectadas
(`write_fb_rows`). Si una animación no cabe en el presupuesto medido, se desactiva por configuración y se
informa; no se baja la calidad del resto.

## Renderer de referencia

`src/bootscreen_render.py` (v2) dibuja las pantallas con Pillow replicando estas medidas y expone cada
fase de animación como un campo de `Screen` (`dots`, `flash_row`, `reveal`, `sweep`, `show_ip`, `strip_on`,
`cursor_on`, `blink_on`). Difiere de las capturas en ~3 % de píxeles por el suavizado de bordes del texto.
`python3 src/bootscreen_render.py --preview ./out` genera las pantallas y los cuadros de `anim/` para comparar.

#!/usr/bin/env python3
"""Renderer de la pantalla de arranque (480x320) para Raspberry Pi Zero. v2

Dibuja las pantallas del diseno "C - Terminal" con Pillow y puede convertir la
imagen a RGB565 para escribirla directo al framebuffer.

Novedades v2 (ver SPEC.md, seccion "Animaciones"):
  * Titulo "INICIANDO" con puntos animados (campo `dots`, 0 a 3).
  * Barra de progreso en bloques enteros (23 bloques) + bloque lider parpadeante.
  * Destello de la fila cuando un paso pasa a OK (campo `flash_row`).
  * Pantalla LISTO: barrido del titulo (`reveal` 0..5), llenado de la barra
    (`sweep` 0..1) y aparicion de la IP (`show_ip`).
  * Error: la franja naranja parpadea (`strip_on`).
  * render(screen, regions=dict) devuelve ademas los rectangulos de cada
    elemento animado, para actualizar solo esas filas del framebuffer.

Uso rapido (en cualquier maquina con Pillow):
    python3 bootscreen_render.py --preview ./out
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

W, H = 480, 320
PAD_T, PAD_X, PAD_B = 18, 24, 22

BG = (5, 8, 5)            # #050805
FG = (77, 255, 136)       # #4DFF88  verde fosforo
DIM = (63, 168, 101)      # #3FA865  pasos pendientes
ERR = (255, 138, 76)      # #FF8A4C  error

FONT_PATH = os.environ.get(
    "BOOTSCREEN_FONT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "VT323-Regular.ttf"),
)

OK, ACTIVE, PENDING, FAILED, SKIPPED = "ok", "active", "pending", "failed", "skipped"
MARK = {OK: "[OK]", ACTIVE: "[..]", PENDING: "[  ]", FAILED: "[!!]", SKIPPED: "[--]"}

BAR_BLOCKS = 23          # bloques de 14 px con 4 px de separacion dentro de la barra
Rect = Tuple[int, int, int, int]   # x0, y0, x1, y1 (x1/y1 exclusivos)


@dataclass
class Step:
    label: str                 # "Sistema", "Wi-Fi", "Servicios", "App"
    status: str = PENDING      # ok | active | pending | failed
    detail: str = ""           # texto extra en error, p. ej. "sin respuesta"
    error_title: str = "ERROR"  # titulo grande si este paso falla, p. ej. "SIN WI-FI"


@dataclass
class Screen:
    steps: List[Step]
    elapsed: int = 0                 # segundos desde el arranque
    ip: str = ""                     # solo en "listo"
    retry_in: Optional[int] = None   # segundos para reintentar (error)
    # ---- fases de animacion (cada una se avanza desde el bucle del servicio) ----
    cursor_on: bool = True           # cursores de bloque, 1 Hz
    blink_on: bool = True            # marcador [..] y bloque lider, 1 Hz (misma fase)
    dots: int = 3                    # puntos visibles tras INICIANDO: 0, 1, 2, 3 (cada 0.4 s)
    flash_row: Optional[int] = None  # indice de fila destellando (0.35 s tras pasar a OK)
    flash_rows: Tuple[int, ...] = () # filas que pasan a OK en el mismo sondeo
    reveal: int = 5                  # LISTO: barrido del titulo, 0..5 (pasos de 0.15 s)
    sweep: float = 1.0               # LISTO: llenado de la barra, 0..1 (en pasos de 1/16)
    show_ip: bool = True             # LISTO: la IP aparece a los 0.95 s
    strip_on: bool = True            # ERROR: franja naranja encendida/apagada (1.2 s)

    # ---- estado derivado ----
    @property
    def mode(self) -> str:
        if any(s.status == FAILED for s in self.steps):
            return "error"
        if all(s.status in (OK, SKIPPED) for s in self.steps):
            return "ready"
        return "boot"

    @property
    def progress(self) -> float:
        n = len(self.steps)
        done = sum(1 for s in self.steps if s.status in (OK, SKIPPED))
        act = sum(1 for s in self.steps if s.status in (ACTIVE, FAILED))
        return min(1.0, (done + 0.5 * min(act, 1)) / n)

    @property
    def casi_listo(self) -> bool:
        last = self.steps[-1]
        return last.status == ACTIVE and all(s.status in (OK, SKIPPED) for s in self.steps[:-1])

    @property
    def title(self) -> str:
        if self.mode == "ready":
            return "LISTO"
        if self.mode == "error":
            bad = next(s for s in self.steps if s.status == FAILED)
            return bad.error_title.upper()
        return "CASI LISTO" if self.casi_listo else "INICIANDO"


# ------------------------------------------------------------------ helpers
_fonts: dict = {}


def font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT_PATH, size)
    return _fonts[size]


def text_width(txt: str, size: int, spacing: float = 0.0) -> float:
    f = font(size)
    return sum(f.getlength(c) + spacing * size for c in txt)


def draw_text(d: ImageDraw.ImageDraw, x: float, top: float, txt: str, size: int,
              line_height: float, fill, spacing: float = 0.0) -> float:
    """Dibuja texto replicando la caja de linea de CSS. Devuelve la linea base."""
    f = font(size)
    asc, desc = f.getmetrics()
    box = line_height * size
    baseline = top + (box - (asc + desc)) / 2 + asc
    cx = x
    for c in txt:
        d.text((cx, baseline), c, font=f, fill=fill, anchor="ls")
        cx += f.getlength(c) + spacing * size
    return baseline


def space_between(heights: List[float]) -> List[float]:
    """Posiciones y de bloques en columna flex con justify-content: space-between."""
    free = (H - PAD_T - PAD_B) - sum(heights)
    gap = free / (len(heights) - 1)
    ys, y = [], float(PAD_T)
    for h in heights:
        ys.append(y)
        y += h + gap
    return ys


def rect(x0, y0, x1, y1) -> Rect:
    return (int(x0), int(y0), int(x1) + 1, int(y1) + 1)


def draw_header(d, y, right_text: str, color, reg: dict):
    draw_text(d, PAD_X, y, "PI ZERO", 26, 1.0, color)
    tw = text_width(right_text, 26)
    draw_text(d, W - PAD_X - tw, y, right_text, 26, 1.0, color)
    reg["time"] = rect(W - PAD_X - tw - 2, y, W - PAD_X + 2, y + 26)


def draw_bar_blocks(d, y, n_fill: int, lead_on: bool, color, reg: dict):
    """Barra de progreso: borde 2 px, 3 px de espacio, bloques de 14 px cada 18 px."""
    d.rectangle([PAD_X, y, W - PAD_X - 1, y + 21], outline=color, width=2)
    ix0, iy0, iy1 = PAD_X + 5, y + 5, y + 21 - 5
    for i in range(n_fill):
        x = ix0 + i * 18
        d.rectangle([x, iy0, x + 13, iy1], fill=color)
    if lead_on and n_fill < BAR_BLOCKS:
        x = ix0 + n_fill * 18
        d.rectangle([x, iy0, x + 13, iy1], fill=color)
    reg["bar"] = rect(PAD_X, y, W - PAD_X - 1, y + 21)
    reg["lead"] = rect(ix0 + n_fill * 18, iy0, ix0 + n_fill * 18 + 13, iy1)


def mmss(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


# ------------------------------------------------------------------ pantallas
def render(s: Screen, regions: Optional[Dict[str, Rect]] = None) -> Image.Image:
    """Dibuja la pantalla. Si se pasa `regions`, se rellena con los rectangulos
    de los elementos animados (time, title, dots, cursor, lead, bar, ip, marker0..3,
    row0..3) para poder escribir solo esas filas al framebuffer."""
    reg: Dict[str, Rect] = regions if regions is not None else {}
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    mode = s.mode
    accent = ERR if mode == "error" else FG

    # ---------------------------------------------------------------- LISTO
    if mode == "ready":
        ys = space_between([26, 205 * 0.74, 22 + 14 + 34])
        draw_header(d, ys[0], f"[OK] {mmss(s.elapsed)}", FG, reg)

        # titulo en una capa aparte para poder recortarlo (barrido de izquierda a derecha)
        layer = Image.new("RGB", (W, H), BG)
        draw_text(ImageDraw.Draw(layer), PAD_X, ys[1], "LISTO", 205, 0.74, FG, spacing=0.01)
        vis_x = PAD_X + round((W - 2 * PAD_X) * s.reveal / 5)
        if vis_x > PAD_X:                  # solo la franja del titulo (no pisa encabezado ni barra)
            top_band, bot_band = int(ys[1]) - 10, int(ys[2]) - 10
            img.paste(layer.crop((0, top_band, vis_x, bot_band)), (0, top_band))
        reg["title"] = rect(PAD_X, ys[1] - 20, W - PAD_X, ys[1] + 205 * 0.74 + 20)

        # barra solida que se llena de izquierda a derecha (16 pasos)
        by = ys[2]
        d.rectangle([PAD_X, by, W - PAD_X - 1, by + 21], outline=FG, width=2)
        ix0, ix1 = PAD_X + 5, W - PAD_X - 5
        fill_end = ix0 + (ix1 - ix0) * s.sweep
        if fill_end > ix0:
            d.rectangle([ix0, by + 5, fill_end - 1, by + 16], fill=FG)
        reg["bar"] = rect(PAD_X, by, W - PAD_X - 1, by + 21)

        if s.show_ip:
            ty = by + 22 + 14
            base = draw_text(d, PAD_X, ty, "> " + s.ip, 34, 1.0, FG)
            cx = PAD_X + text_width("> " + s.ip, 34) + 10
            if s.cursor_on:
                d.rectangle([cx, base - 22, cx + 15, base + 5], fill=FG)
            reg["ip"] = rect(PAD_X, ty, W - PAD_X, ty + 34)
            reg["cursor"] = rect(cx, base - 22, cx + 15, base + 5)
        return img

    # ------------------------------------------------------- BOOT / ERROR
    log_h = len(s.steps) * 30 * 1.05
    bottom_h = 30 if mode == "error" else 22
    ys = space_between([26, 78 * 0.9, log_h, bottom_h])
    draw_header(d, ys[0], mmss(s.elapsed), accent, reg)

    # titulo (+ puntos animados solo en INICIANDO) + cursor de bloque
    title = s.title
    base = draw_text(d, PAD_X, ys[1], title, 78, 0.9, accent, spacing=0.02)
    cx = PAD_X + text_width(title, 78, 0.02)
    if title == "INICIANDO":
        adv = font(78).getlength(".") + 0.02 * 78
        for i in range(max(0, min(3, s.dots))):
            draw_text(d, cx + i * adv, ys[1], ".", 78, 0.9, accent)
        reg["dots"] = rect(cx, base - 54, cx + 3 * adv, base + 4)
        cx += 3 * adv                      # el cursor queda fijo tras los 3 puntos reservados
    cx += 4
    if s.cursor_on:
        d.rectangle([cx, base - 54, cx + 25, base - 1], fill=accent)
    reg["cursor"] = rect(cx, base - 54, cx + 25, base - 1)
    reg["title"] = rect(PAD_X, ys[1], W - PAD_X, ys[1] + 78 * 0.9)

    # lista de pasos
    marker_w = text_width("[OK]", 30)
    for i, st in enumerate(s.steps):
        top = ys[2] + i * 30 * 1.05
        row_h = 30 * 1.05
        reg[f"row{i}"] = rect(PAD_X - 6, top, W - PAD_X + 6 - 1, top + row_h - 1)
        reg[f"marker{i}"] = rect(PAD_X, top, PAD_X + marker_w, top + row_h - 1)
        label = st.label
        mark = MARK[st.status]
        color = {OK: FG, ACTIVE: FG, PENDING: DIM, FAILED: BG, SKIPPED: DIM}[st.status]
        if st.status == SKIPPED:
            label = f"{st.label} - desactivada"
        elif st.status == FAILED and st.detail:
            label = f"{st.label} - {st.detail}"
        if st.status == OK and mode == "error":
            color = FG                                   # los pasos OK siguen verdes en error
        inverted = False
        if st.status == FAILED:
            inverted = s.strip_on                         # franja naranja que parpadea
            color = BG if s.strip_on else ERR
        if s.flash_row == i or i in s.flash_rows:
            inverted, color = True, BG                    # destello al pasar a [OK]
        if inverted:
            d.rectangle([PAD_X - 6, top, W - PAD_X + 6 - 1, top + row_h - 1], fill=accent)
        if st.status == ACTIVE and not s.blink_on:
            pass                                          # marcador oculto en la fase "off"
        else:
            draw_text(d, PAD_X, top, mark, 30, 1.05, color)
        draw_text(d, PAD_X + marker_w + 18, top, label, 30, 1.05, color)

    # zona inferior
    if mode == "error":
        retry = f"> reintentando en {s.retry_in} s" if s.retry_in is not None else "> reintentando"
        draw_text(d, PAD_X, ys[3], retry, 30, 1.0, ERR)
        reg["retry"] = rect(PAD_X, ys[3], W - PAD_X, ys[3] + 30)
    else:
        n_fill = min(BAR_BLOCKS, round(s.progress * BAR_BLOCKS))
        draw_bar_blocks(d, ys[3], n_fill, s.blink_on, FG, reg)
    return img


def _layout_regions(s: Screen) -> Dict[str, Rect]:
    """Return the screen-space bounds for every independently updated item."""
    reg = {}
    if s.mode == "ready":
        ys = space_between([26, 205 * 0.74, 22 + 14 + 34])
        right = f"[OK] {mmss(s.elapsed)}"
        tw = text_width(right, 26)
        reg["time"] = rect(W - PAD_X - tw - 2, ys[0], W - PAD_X + 2, ys[0] + 26)
        reg["title"] = rect(PAD_X, ys[1] - 20, W - PAD_X, ys[1] + 205 * 0.74 + 20)
        by = ys[2]
        reg["bar"] = rect(PAD_X, by, W - PAD_X - 1, by + 21)
        ty = by + 22 + 14
        reg["ip"] = rect(PAD_X, ty, W - PAD_X, ty + 34)
        base = ty + (34 - sum(font(34).getmetrics())) / 2 + font(34).getmetrics()[0]
        cx = PAD_X + text_width("> " + s.ip, 34) + 10
        reg["cursor"] = rect(cx, base - 22, cx + 15, base + 5)
        return reg

    log_h = len(s.steps) * 30 * 1.05
    bottom_h = 30 if s.mode == "error" else 22
    ys = space_between([26, 78 * 0.9, log_h, bottom_h])
    right = mmss(s.elapsed)
    tw = text_width(right, 26)
    reg["time"] = rect(W - PAD_X - tw - 2, ys[0], W - PAD_X + 2, ys[0] + 26)
    title_base = ys[1] + (78 * 0.9 - sum(font(78).getmetrics())) / 2 + font(78).getmetrics()[0]
    cursor_x = PAD_X + text_width(s.title, 78, 0.02)
    if s.title == "INICIANDO":
        advance = font(78).getlength(".") + 0.02 * 78
        dots_x = cursor_x
        cursor_x += 3 * advance
        reg["dots"] = rect(dots_x, title_base - 54, dots_x + 3 * advance, title_base + 4)
    cursor_x += 4
    reg["cursor"] = rect(cursor_x, title_base - 54, cursor_x + 25, title_base - 1)
    reg["title"] = rect(PAD_X, ys[1], W - PAD_X, ys[1] + 78 * 0.9)
    marker_w = text_width("[OK]", 30)
    for i in range(len(s.steps)):
        top = ys[2] + i * 30 * 1.05
        row_h = 30 * 1.05
        reg[f"row{i}"] = rect(PAD_X - 6, top, W - PAD_X + 6 - 1, top + row_h - 1)
        reg[f"marker{i}"] = rect(PAD_X, top, PAD_X + marker_w, top + row_h - 1)
    by = ys[3]
    if s.mode == "error":
        reg["retry"] = rect(PAD_X, by, W - PAD_X, by + 30)
    else:
        n_fill = min(BAR_BLOCKS, round(s.progress * BAR_BLOCKS))
        ix0, iy0 = PAD_X + 5, by + 5
        reg["bar"] = rect(PAD_X, by, W - PAD_X - 1, by + 21)
        reg["lead"] = rect(ix0 + n_fill * 18, iy0, ix0 + n_fill * 18 + 13, by + 16)
    return reg


@lru_cache(maxsize=32)
def _cached_layout(step_values, elapsed, ip):
    return _layout_regions(Screen([Step(*step) for step in step_values], elapsed=elapsed, ip=ip))


def layout_regions(s: Screen) -> Dict[str, Rect]:
    steps = tuple((step.label, step.status, step.detail, step.error_title) for step in s.steps)
    return _cached_layout(steps, s.elapsed, s.ip)


def render_partial(s: Screen, previous: Image.Image, only, regions=None, *, in_place=False) -> Image.Image:
    """Redraw named regions over a prior frame, leaving all other pixels intact."""
    reg = regions if regions is not None else layout_regions(s)
    dirty = set(only)
    img = previous if in_place else previous.copy()
    d = ImageDraw.Draw(img)
    mode = s.mode
    accent = ERR if mode == "error" else FG
    if "time" in dirty:
        bottom_height = 30 if mode == "error" else 22
        header_y = (space_between([26, 205 * 0.74, 22 + 14 + 34])[0] if mode == "ready"
                    else space_between([26, 78 * 0.9, len(s.steps) * 30 * 1.05, bottom_height])[0])
        img.paste(BG, (PAD_X, int(header_y), W - PAD_X, int(header_y + 26) + 1))
        d = ImageDraw.Draw(img)
        draw_header(d, header_y, f"[OK] {mmss(s.elapsed)}" if mode == "ready" else mmss(s.elapsed), accent, {})

    if mode == "ready":
        ys = space_between([26, 205 * 0.74, 22 + 14 + 34])
        if "title" in dirty:
            top_band, bot_band = int(ys[1]) - 10, int(ys[2]) - 10
            img.paste(BG, (0, top_band, W, bot_band))
            layer = Image.new("RGB", (W, H), BG)
            draw_text(ImageDraw.Draw(layer), PAD_X, ys[1], "LISTO", 205, 0.74, FG, spacing=0.01)
            vis_x = PAD_X + round((W - 2 * PAD_X) * s.reveal / 5)
            if vis_x > PAD_X:
                img.paste(layer.crop((0, top_band, vis_x, bot_band)), (0, top_band))
            d = ImageDraw.Draw(img)
        if "bar" in dirty:
            x0, y0, x1, y1 = reg["bar"]
            img.paste(BG, (x0, y0, x1, y1))
            d = ImageDraw.Draw(img)
            by = ys[2]
            d.rectangle([PAD_X, by, W - PAD_X - 1, by + 21], outline=FG, width=2)
            ix0, ix1 = PAD_X + 5, W - PAD_X - 5
            fill_end = ix0 + (ix1 - ix0) * s.sweep
            if fill_end > ix0:
                d.rectangle([ix0, by + 5, fill_end - 1, by + 16], fill=FG)
        if "ip" in dirty or "cursor" in dirty:
            x0, y0, x1, y1 = reg["ip"]
            if "ip" in dirty:
                img.paste(BG, (x0, y0, x1, y1))
            else:
                x0, y0, x1, y1 = reg["cursor"]
                img.paste(BG, (x0, y0, x1, y1))
            d = ImageDraw.Draw(img)
            if "ip" in dirty and s.show_ip:
                by = ys[2]
                ty = by + 22 + 14
                base = draw_text(d, PAD_X, ty, "> " + s.ip, 34, 1.0, FG)
                cx = PAD_X + text_width("> " + s.ip, 34) + 10
                if s.cursor_on and s.show_ip:
                    d.rectangle([cx, base - 22, cx + 15, base + 5], fill=FG)
            elif s.cursor_on and s.show_ip:
                x0, y0, x1, y1 = reg["cursor"]
                d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=FG)
        return img

    log_h = len(s.steps) * 30 * 1.05
    bottom_h = 30 if mode == "error" else 22
    ys = space_between([26, 78 * 0.9, log_h, bottom_h])
    title = s.title
    if "title" in dirty:
        x0, y0, x1, y1 = reg["title"]
        img.paste(BG, (x0, y0, x1, y1))
        d = ImageDraw.Draw(img)
        base = draw_text(d, PAD_X, ys[1], title, 78, 0.9, accent, spacing=0.02)
        cursor_x = PAD_X + text_width(title, 78, 0.02)
        if title == "INICIANDO":
            advance = font(78).getlength(".") + 0.02 * 78
            for i in range(max(0, min(3, s.dots))):
                draw_text(d, cursor_x + i * advance, ys[1], ".", 78, 0.9, accent)
            cursor_x += 3 * advance
        cursor_x += 4
        if s.cursor_on:
            d.rectangle([cursor_x, base - 54, cursor_x + 25, base - 1], fill=accent)
    elif "dots" in dirty and title == "INICIANDO":
        x0, y0, x1, y1 = reg["dots"]
        img.paste(BG, (x0, y0, x1, y1))
        d = ImageDraw.Draw(img)
        advance = font(78).getlength(".") + 0.02 * 78
        base = ys[1] + (78 * 0.9 - sum(font(78).getmetrics())) / 2 + font(78).getmetrics()[0]
        dots_x = PAD_X + text_width("INICIANDO", 78, 0.02)
        for i in range(max(0, min(3, s.dots))):
            draw_text(d, dots_x + i * advance, ys[1], ".", 78, 0.9, accent)
    if "cursor" in dirty and "title" not in dirty:
        x0, y0, x1, y1 = reg["cursor"]
        img.paste(BG, (x0, y0, x1, y1))
        if s.cursor_on:
            ImageDraw.Draw(img).rectangle([x0, y0, x1 - 1, y1 - 1], fill=accent)

    marker_w = text_width("[OK]", 30)
    for i, st in enumerate(s.steps):
        if f"row{i}" not in dirty and f"marker{i}" not in dirty:
            continue
        row = f"row{i}" in dirty
        area = reg[f"row{i}"] if row else reg[f"marker{i}"]
        x0, y0, x1, y1 = area
        img.paste(BG, (x0, y0, x1, y1))
        d = ImageDraw.Draw(img)
        top = ys[2] + i * 30 * 1.05
        color = {OK: FG, ACTIVE: FG, PENDING: DIM, FAILED: BG, SKIPPED: DIM}[st.status]
        label = f"{st.label} - desactivada" if st.status == SKIPPED else st.label
        if st.status == FAILED and st.detail:
            label = f"{st.label} - {st.detail}"
        if st.status == OK and mode == "error":
            color = FG
        inverted = False
        if st.status == FAILED:
            inverted, color = s.strip_on, BG if s.strip_on else ERR
        if s.flash_row == i or i in s.flash_rows:
            inverted, color = True, BG
        if inverted and row:
            d.rectangle([PAD_X - 6, top, W - PAD_X + 6 - 1, top + 30 * 1.05 - 1], fill=accent)
        if row:
            if st.status != ACTIVE or s.blink_on:
                draw_text(d, PAD_X, top, MARK[st.status], 30, 1.05, color)
            draw_text(d, PAD_X + marker_w + 18, top, label, 30, 1.05, color)
        elif st.status != ACTIVE or s.blink_on:
            draw_text(d, PAD_X, top, MARK[st.status], 30, 1.05, color)

    if "bar" in dirty:
        x0, y0, x1, y1 = reg["bar"]
        img.paste(BG, (x0, y0, x1, y1))
        d = ImageDraw.Draw(img)
        draw_bar_blocks(d, ys[3], min(BAR_BLOCKS, round(s.progress * BAR_BLOCKS)), s.blink_on, FG, {})
    elif "lead" in dirty:
        x0, y0, x1, y1 = reg["lead"]
        img.paste(BG, (x0, y0, x1, y1))
        if s.blink_on and round(s.progress * BAR_BLOCKS) < BAR_BLOCKS:
            ImageDraw.Draw(img).rectangle([x0, y0, x1 - 1, y1 - 1], fill=FG)
    if "retry" in dirty:
        x0, y0, x1, y1 = reg["retry"]
        img.paste(BG, (x0, y0, x1, y1))
        retry = f"> reintentando en {s.retry_in} s" if s.retry_in is not None else "> reintentando"
        draw_text(ImageDraw.Draw(img), PAD_X, ys[3], retry, 30, 1.0, ERR)
    return img


class CachedRenderer:
    """Memoize identical frames; animation phases remain explicit in Screen."""

    def __init__(self):
        self._cached = lru_cache(maxsize=32)(self._render_key)

    @staticmethod
    def _render_key(key):
        steps, values = key
        return render(Screen([Step(*step) for step in steps], **dict(values)))

    def __call__(self, screen):
        values = tuple((name, getattr(screen, name)) for name in
                       ("elapsed", "ip", "retry_in", "cursor_on", "blink_on", "dots",
                        "flash_row", "flash_rows", "reveal", "sweep", "show_ip", "strip_on"))
        steps = tuple((s.label, s.status, s.detail, s.error_title) for s in screen.steps)
        return self._cached((steps, values)).copy()


# ------------------------------------------------------------------ framebuffer
def to_rgb565(img: Image.Image) -> bytes:
    """Fast RGB888 to little-endian RGB565 using Pillow's C channel operations."""
    from PIL import ImageChops

    red, green, blue = img.convert("RGB").split()
    high = ImageChops.add(red.point(lambda x: x & 0xF8), green.point(lambda x: x >> 5))
    low = ImageChops.add(green.point(lambda x: (x & 0x1C) << 3), blue.point(lambda x: x >> 3))
    out = bytearray(img.width * img.height * 2)
    out[0::2], out[1::2] = low.tobytes(), high.tobytes()
    return bytes(out)


def write_fb(img: Image.Image, dev: str = "/dev/fb1") -> None:
    with open(dev, "wb") as fb:
        fb.write(to_rgb565(img))


def write_fb_rows(img: Image.Image, y0: int, y1: int, dev: str = "/dev/fb1") -> None:
    """Escribe solo las filas [y0, y1) (ancho completo). Util para animaciones baratas."""
    data = to_rgb565(img.crop((0, y0, W, y1)))
    with open(dev, "r+b") as fb:
        fb.seek(y0 * W * 2)
        fb.write(data)


# ------------------------------------------------------------------ demo / preview
def _steps(*st, wifi_detail=""):
    names = ["Sistema", "Wi-Fi", "Servicios", "App"]
    titles = ["ERROR", "SIN WI-FI", "ERROR", "ERROR"]
    return [Step(n, s, wifi_detail if (n == "Wi-Fi" and s == FAILED) else "", t)
            for n, s, t in zip(names, st, titles)]


def demo_screens() -> dict:
    """Pantallas estaticas de referencia (animaciones en su estado 'normal')."""
    return {
        "01-iniciando": Screen(_steps(OK, ACTIVE, PENDING, PENDING), elapsed=23),
        "02-casi-listo": Screen(_steps(OK, OK, OK, ACTIVE), elapsed=36),
        "03-listo": Screen(_steps(OK, OK, OK, OK), elapsed=38, ip="192.168.1.42"),
        "04-error": Screen(_steps(OK, FAILED, PENDING, PENDING, wifi_detail="sin respuesta"),
                           elapsed=51, retry_in=8),
    }


def demo_frames() -> dict:
    """Cuadros clave de cada animacion (para comparar con reference/anim/)."""
    boot = lambda **k: Screen(_steps(OK, ACTIVE, PENDING, PENDING), elapsed=23, **k)
    ready = lambda **k: Screen(_steps(OK, OK, OK, OK), elapsed=38, ip="192.168.1.42", **k)
    out = {}
    for k in range(4):
        out[f"iniciando-puntos-{k}"] = boot(dots=k)
    out["iniciando-lider-apagado"] = boot(blink_on=False, cursor_on=False)
    for k in range(6):
        out[f"listo-barrido-{k}"] = ready(reveal=k, sweep=0.0, show_ip=False)
    out["listo-barra-mitad"] = ready(reveal=5, sweep=0.5, show_ip=False)
    out["destello-fila"] = Screen(_steps(OK, ACTIVE, PENDING, PENDING), elapsed=3, flash_row=0)
    err = lambda **k: Screen(_steps(OK, FAILED, PENDING, PENDING, wifi_detail="sin respuesta"),
                             elapsed=51, retry_in=8, **k)
    out["error-franja-apagada"] = err(strip_on=False)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", metavar="DIR", help="guarda las pantallas y los cuadros clave como PNG en DIR")
    ap.add_argument("--fb", metavar="DEV", help="escribe una pantalla al framebuffer, p. ej. /dev/fb1")
    ap.add_argument("--state", default="01-iniciando", help="pantalla para --fb")
    a = ap.parse_args()
    if a.preview:
        os.makedirs(os.path.join(a.preview, "anim"), exist_ok=True)
        for name, s in demo_screens().items():
            render(s).save(os.path.join(a.preview, name + ".png"))
        for name, s in demo_frames().items():
            render(s).save(os.path.join(a.preview, "anim", name + ".png"))
        print("PNG guardados en", a.preview)
    if a.fb:
        write_fb(render(demo_screens()[a.state]), a.fb)
    if not (a.preview or a.fb):
        ap.print_help(sys.stderr)

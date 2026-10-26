"""Tokens visuales de la pantalla de monitoreo (480x320). Tema: Alto contraste. Disposición A.
Todos los colores son PLANOS (sin alfa). Fuente de verdad: referencia/monitoreo_referencia_v2_480x320.html
"""

W, H = 480, 320

def _mix(a, b, t):
    """Mezcla a*t + b*(1-t) entre dos '#RRGGBB'. Igual que mixHex() del HTML."""
    ch = lambda h, i: int(h[1 + i * 2:3 + i * 2], 16)
    return "#" + "".join("%02X" % round(ch(a, i) * t + ch(b, i) * (1 - t)) for i in range(3))

C = {
    "bg": "#000000", "panel": "#0D0D0D", "panel_line": "#5A5A5A", "track": "#2E2E2E",
    "text": "#FFFFFF", "text2": "#F2F2F2", "muted": "#D0D0D0",
    "ok": "#3DE07F",            # óptimo, API ok, logo, barra "en rango"
    "ember": "#FF6A2B",         # temperatura del aire (SHT31)
    "dew": "#2FC8FF",           # humedad (SHT31)
    "sub": "#C792FF",           # temperatura del sustrato (DS18B20)
    "honey": "#FFD60A",         # alta, API caída
    "mist": "#80CBFF",          # baja
    "danger": "#FF5252",        # sin sensor
    "nodata": "#A8A8A8", "nodata_line": "#808080",
    "stem": "#F2F2F2",          # pie del hongo del logo
    "on": "#000000",            # texto/ícono sobre chips rellenos
    "zone": "#2FA15D",          # marca de zona objetivo (arco del dial r=84 y barrita de la tira)
}
C["band"] = _mix(C["ok"], C["panel"], 0.2)   # banda objetivo del gráfico (#173724)

# Fuentes (ver fuentes/*.ttf). Tamaños en px = tamaño de Pillow (ImageFont.truetype(size=px)).
FONTS = {
    "h1":        ("Fraunces-600.ttf", 21),          # "Monitoreo"
    "reloj":     ("BarlowCondensed-500.ttf", 24),   # tracking +0.04em
    "h2":        ("Barlow-600.ttf", 13),            # TEMPERATURA/HUMEDAD/SUSTRATO, MAYÚSCULAS, tracking +0.10em
    "chip":      ("Barlow-700.ttf", 12),            # tracking +0.06em (+0.02em en SIN DATO/SIN SENSOR)
    "num":       ("BarlowCondensed-600.ttf", 46),   # valor del dial (disposición A)
    "unidad":    ("Barlow-600.ttf", 14),
    "sensor":    ("Barlow-600.ttf", 12),            # tracking +0.04em
    "escala":    ("Barlow-400.ttf", 12),
    "nota":      ("Barlow-500.ttf", 13),
    "objetivo":  ("Barlow-400.ttf", 13),            # el rango va en Barlow-600, color text2
    "t_nota":    ("Barlow-500.ttf", 12),            # nota de la tira de sustrato
    "t_valor":   ("BarlowCondensed-600.ttf", 28),   # valor de la tira (unidad Barlow-600 13)
    "d_stats_l": ("Barlow-400.ttf", 12),
    "d_stats_v": ("BarlowCondensed-600.ttf", 18),
    "d_ejes":    ("Barlow-400.ttf", 12),
    "d_inr":     ("Barlow-400.ttf", 13),            # el porcentaje va en Barlow-600, color text2
    "sys":       ("Barlow-500.ttf", 13),
    "api_err":   ("Barlow-600.ttf", 13),
}

# ---- Dial: caja de 200x154 en unidades de diseño, escalada por k (A: k = 0.8 -> 160x123) ----
DIAL = {
    "k": 0.8, "box": (200, 154), "center": (100, 90),
    "r_prog": 72, "w_prog": 14,       # arco de progreso y pista (extremos redondeados)
    "r_zone": 84, "w_zone": 4,        # marca de zona objetivo
    "start_deg": 135, "sweep_deg": 270,   # convención de Pillow.arc: horario desde las 3 en punto, eje y hacia abajo
    "knob_r": 9, "knob_stroke": 3,    # relleno text, borde panel (también escalan con k)
    "center_top": 40,                 # (x k) distancia desde la caja al número
    "label_y": 138,                   # (x k) etiquetas de escala
    "label_x": {"t": (58, 58), "h": (62, 56)},   # (x k) desde el borde izq. de la caja y desde el der.
}

# ---- Layout (px de pantalla; el detalle completo está en medidas.json) ----
LAYOUT = {
    "header_h": 44, "gap": 8, "side": 8,
    "panel": {"y": 44, "h": 220, "w": 228, "x": (8, 244), "radius": 16, "pad": (10, 14, 12, 14)},   # arriba, der, abajo, izq
    "strip": {"y": 272, "h": 40, "x": 8, "w": 464, "radius": 14, "pad": (0, 12, 0, 14), "gap": 12,
              "col1_w": 122, "value_w": 72, "chip_h": 26,
              "gauge": {"h": 22, "inset": 7, "zone_h": 4, "track_y": 10, "track_h": 8, "knob": 14, "knob_border": 3}},
    "dcard": {"y": 44, "h": 234, "w": (150, 148, 150), "x": (8, 166, 322), "radius": 16, "pad": (10, 8, 12, 8),
              "chart": {"svg": (130, 80), "plot_x": (26, 128), "plot_y": (4, 76), "ylab_w": 23, "xlab_y": 82, "block_h": 96}},
    "sys": {"x": 8, "y": 286, "w": 464, "h": 26, "radius": 13, "pad_x": 12, "dot": 9},
    "dots": {"y": 313, "dot": 5, "dot_on_w": 14, "gap": 5},
}

# ---- Rangos y escalas por defecto (configurables) ----
DEFAULT_CONFIG = {
    "temp": {"min": 22.0, "max": 24.0, "scale_min": 16, "scale_max": 32},   # °C · aire del microclima (SHT31)
    "hum":  {"min": 85.0, "max": 92.0, "scale_min": 60, "scale_max": 100},  # %  · aire del microclima (SHT31)
    # PROVISIONAL: confirmar con el cultivador. Rango objetivo de temperatura del sustrato (DS18B20).
    "sub":  {"min": 21.0, "max": 25.0, "scale_min": 14, "scale_max": 34},   # °C
}

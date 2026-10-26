"""Lógica de estados pura (sin hardware ni dibujo). Igual a la del HTML de referencia v2.
Python 3.9+. Probada en test_estado.py.

Magnitudes (cada una depende de UN solo sensor; NO hay respaldo cruzado, miden cosas distintas):
  't' temperatura del aire / microclima  <- SHT31
  'h' humedad del aire / microclima      <- SHT31
  's' temperatura del sustrato           <- DS18B20
"""
DEFAULT_CONFIG = {
    "temp": {"min": 22.0, "max": 24.0, "scale_min": 16, "scale_max": 32},
    "hum": {"min": 85.0, "max": 92.0, "scale_min": 60, "scale_max": 100},
    "sub": {"min": 21.0, "max": 25.0, "scale_min": 14, "scale_max": 34},
}

OK, NODATA, DISC = "ok", "nodata", "disc"        # estado de un sensor
SENSOR = {"t": "sht31", "h": "sht31", "s": "ds18b20"}
NAME = {"ds18b20": "DS18B20", "sht31": "SHT31"}
CFG_KEY = {"t": "temp", "h": "hum", "s": "sub"}
DECIMALS = {"t": True, "h": False, "s": True}     # 23,0 °C · 88 % · 23,5 °C
UNIT = {"t": "°C", "h": "%", "s": "°C"}

# Texto del chip por estado del panel. icon = id de iconos/chip_*.svg (None = solo texto)
CHIP = {
    "ok":     ("ÓPTIMA", "optima"),
    "high":   ("ALTA", "alta"),
    "low":    ("BAJA", "baja"),
    "nodata": ("SIN DATO", None),
    "disc":   ("SIN SENSOR", None),
}

def level(v, lo, hi):
    return "low" if v < lo else ("high" if v > hi else "ok")

def fmt1(n):  # 23.0 -> "23,0"
    return ("%.1f" % n).replace(".", ",")

def fmt(k, v):
    return fmt1(v) if DECIMALS[k] else str(int(round(v)))

def note(lv, delta, decimals):
    if lv == "ok":
        return "Dentro del objetivo"
    d = fmt1(delta) if decimals else str(int(round(delta)))
    return ("+%s sobre el máximo" if lv == "high" else "−%s bajo el mínimo") % d   # menos = U+2212

def view_model(k, sensors, values, cfg=DEFAULT_CONFIG):
    """k: 't'|'h'|'s'. sensors: {'sht31': 'ok'|'nodata'|'disc', 'ds18b20': ...}. values: {'t': float|None, 'h': ..., 's': ...}.
    Devuelve lo que el dibujo necesita."""
    sens = SENSOR[k]; c = cfg[CFG_KEY[k]]; st = sensors[sens]
    v = values.get(k)
    if st == OK and v is None:           # sensor 'ok' pero sin valor: tratar como sin lectura
        st = NODATA
    if st != OK:
        return {"st": st, "num": "—", "tag": NAME[sens], "frac": None,
                "note": NAME[sens] + " desconectado" if st == DISC else "Sin lectura válida"}
    lv = level(v, c["min"], c["max"])
    delta = v - c["max"] if lv == "high" else c["min"] - v
    span = c["scale_max"] - c["scale_min"]
    return {"st": lv, "num": fmt(k, v), "tag": NAME[sens], "v": v,
            "frac": min(1.0, max(0.0, (v - c["scale_min"]) / span)),
            "note": note(lv, delta, DECIMALS[k])}

def range_text(k, cfg=DEFAULT_CONFIG):
    c = cfg[CFG_KEY[k]]
    f = (lambda x: ("%g" % x)) 
    return "%s – %s %s" % (f(c["min"]), f(c["max"]), UNIT[k])      # "22 – 24 °C" (con U+2013 y espacios)

def strip_note(vm, cfg=DEFAULT_CONFIG):
    """Segunda línea de la tira de sustrato: objetivo si está óptimo; si no, la nota del estado."""
    return "Obj. " + range_text("s", cfg) if vm["st"] == "ok" else vm["note"]

def zone_fracs(k, cfg=DEFAULT_CONFIG):
    """Extremos (0..1) de la marca de zona objetivo sobre el dial / la tira."""
    c = cfg[CFG_KEY[k]]; span = c["scale_max"] - c["scale_min"]
    cl = lambda x: min(1.0, max(0.0, (x - c["scale_min"]) / span))
    return cl(c["min"]), cl(c["max"])

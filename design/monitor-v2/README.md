# Monitor UI v2 handoff

This folder preserves the supplied visual source of truth:

- `reference/monitoreo_referencia_v2_480x320.html`: interactive reference.
- `reference/v2_*.png`: layout reference sheets.
- `golden/`: 30 expected screenshots (15 states on each page).
- `medidas.json`: layout measurements.

The implementation is in `src/pi_sensor_station/render_v2.py`; it uses the bundled v2 fonts and tokens and writes Pillow images to the existing RGB565 framebuffer path.

Regenerate scenario images with:

```bash
.venv/bin/python -m pi_sensor_station.preview --render-golden /tmp/monitor-v2
```

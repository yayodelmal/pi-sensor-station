# Monitor UI v2 handoff

This folder archives the supplied visual handoff. The running application uses only its Inicio page; the touch navigation, Resumen page and history charts are not implemented.

- `reference/monitoreo_referencia_v2_480x320.html`: interactive reference.
- `reference/v2_*.png`: layout reference sheets.
- `golden/`: supplied reference screenshots, including the archived Resumen page.
- `medidas.json`: layout measurements.

The single-page implementation is in `src/pi_sensor_station/render_v2.py`; it uses the bundled v2 fonts and writes Pillow images to the existing RGB565 framebuffer path.

Regenerate scenario images with:

```bash
.venv/bin/python -m pi_sensor_station.preview --render-golden /tmp/monitor-v2
```

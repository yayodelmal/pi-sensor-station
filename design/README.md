# Display reference

`monitoreo-reference.html` is the user-supplied Claude Design reference with the requested high-contrast palette applied. Open it with `#bare&static&t=17:28` for the fixed 480×320 optimal scenario. The source file in Downloads is unchanged.

`monitor-preview.png` is the Pillow implementation with the same scenario and clock. Regenerate it with `python -m pi_sensor_station.preview --output /tmp/station-previews` and copy `optimal.png` here.

The native renderer preserves the palette, geometry, fonts, sensor source selection and status rules. Intentional adaptations: no decorative animation, explicit pending/disabled HTTP states, `API sin envío` for failed delivery (HTTP rejection does not prove disconnection), and a DEMO marker in simulated operation. There is no browser running on the Pi.

The default high-contrast palette is centralized in `src/pi_sensor_station/colores.py`, including target bands and sensor error states. Both the display and generated preview gallery use it.

import argparse
import copy
import json
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .config import Config
from .framebuffer import Framebuffer
from .probes import Probes, Snapshot
from .render import (ACTIVE, FAILED, OK, PENDING, Screen, Step, demo_frames,
                     demo_screens, layout_regions, render, render_partial)
from .state import AnimationPlan, Controller

LOG = logging.getLogger("bootscreen")


def uptime():
    return float(Path("/proc/uptime").read_text().split()[0])


def process_started_at():
    fields = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[19]) / os.sysconf("SC_CLK_TCK")


def atomic_status(controller, now, first_frame=None):
    path = Path("/run/bootscreen/status.json")
    path.parent.mkdir(mode=0o775, parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    screen = controller.screen(now)
    temp.write_text(json.dumps({"mode": screen.mode, "elapsed": screen.elapsed,
                                "steps": [asdict(step) for step in screen.steps],
                                "ip": screen.ip, "retry_in": screen.retry_in,
                                "ready_at": controller.ready_at, "first_frame_at": first_frame}))
    os.replace(temp, path)


def changed_regions(previous, current, all_regions):
    """Element names whose pixel rows can have changed between two frames."""
    if previous is None or previous.mode != current.mode:
        return None
    dirty = set()
    if previous.elapsed != current.elapsed:
        dirty.add("time")
    if previous.title != current.title:
        dirty.update(("title", "cursor", "dots"))
    if previous.cursor_on != current.cursor_on:
        dirty.add("cursor")
    if previous.blink_on != current.blink_on:
        dirty.update(f"marker{i}" for i, step in enumerate(current.steps) if step.status == ACTIVE)
        if current.mode == "boot":
            dirty.add("lead")
    if previous.dots != current.dots:
        dirty.add("dots")
    if previous.flash_rows != current.flash_rows:
        dirty.update(f"row{i}" for i in set(previous.flash_rows) | set(current.flash_rows))
    if previous.reveal != current.reveal:
        dirty.add("title")
    if previous.sweep != current.sweep:
        dirty.add("bar")
    if previous.show_ip != current.show_ip or previous.ip != current.ip:
        dirty.update(("ip", "cursor"))
    if previous.strip_on != current.strip_on:
        dirty.update(f"row{i}" for i, step in enumerate(current.steps) if step.status == FAILED)
    if previous.retry_in != current.retry_in:
        dirty.add("retry")
    for i, (old, new) in enumerate(zip(previous.steps, current.steps)):
        if old != new:
            dirty.update((f"row{i}", f"marker{i}"))
            if old.status != new.status:
                dirty.update(("bar", "lead"))
    return {name: all_regions[name] for name in dirty if name in all_regions}


def frame_key(screen):
    return (screen.mode, screen.title, screen.elapsed, screen.ip, screen.retry_in,
            screen.cursor_on, screen.blink_on, screen.dots, screen.flash_rows,
            screen.reveal, screen.sweep, screen.show_ip, screen.strip_on,
            tuple((s.label, s.status, s.detail, s.error_title) for s in screen.steps))


def demo_screen(elapsed):
    names = ("Sistema", "Wi-Fi", "Servicios", "App")
    if elapsed < 3:
        statuses = (OK, ACTIVE, PENDING, PENDING)
    elif elapsed < 6:
        statuses = (OK, OK, ACTIVE, PENDING)
    elif elapsed < 9:
        statuses = (OK, OK, OK, ACTIVE)
    elif elapsed < 17:
        statuses = (OK, OK, OK, FAILED)
    else:
        statuses = (OK, OK, OK, OK)
    steps = [Step(name, status, "sin respuesta" if status == FAILED else "",
                  "SIN WI-FI" if name == "Wi-Fi" else "ERROR")
             for name, status in zip(names, statuses)]
    retry = max(0, 8 - int(elapsed - 9)) if 9 <= elapsed < 17 else None
    return Screen(steps, elapsed=int(elapsed), ip="192.168.100.17", retry_in=retry)


def main():
    parser = argparse.ArgumentParser(description="Early framebuffer boot progress for 480x320 ILI9486")
    parser.add_argument("--config", default="/etc/bootscreen/config.toml")
    parser.add_argument("--demo", action="store_true", help="simulate the whole boot, including an error and recovery")
    parser.add_argument("--state", choices=("boot", "almost", "ready", "error"))
    parser.add_argument("--frame", choices=tuple(demo_frames()), help="show a named animation reference frame")
    parser.add_argument("--duration", type=float, default=4, help="seconds to hold --state or --frame")
    parser.add_argument("--output", type=Path, help="render reference previews without touching the display")
    args = parser.parse_args()
    if sum((args.demo, args.state is not None, args.frame is not None)) > 1:
        parser.error("Choose one of --demo, --state or --frame")
    if args.duration <= 0 or not args.duration < float("inf"):
        parser.error("--duration must be finite and positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "anim").mkdir(exist_ok=True)
        for name, state in demo_screens().items():
            render(state).save(args.output / (name + ".png"))
        for name, state in demo_frames().items():
            render(state).save(args.output / "anim" / (name + ".png"))
        return 0
    try:
        config = Config.load(args.config)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    initial = process_started_at()
    device = Path(config.framebuffer)
    while not device.exists() and not stop.wait(0.1):
        pass
    if stop.is_set():
        return 0
    framebuffer = Framebuffer(config.framebuffer)
    demo_preview = None
    try:
        if args.demo:
            demo_preview = framebuffer.preview()
            demo_preview.__enter__()
        if args.frame:
            state = demo_frames()[args.frame]
            with framebuffer.preview():
                framebuffer.draw(render(state), force=True, leased=True)
                stop.wait(args.duration)
            return 0
        if args.state:
            state = demo_screens()[{"boot": "01-iniciando", "almost": "02-casi-listo",
                                    "ready": "03-listo", "error": "04-error"}[args.state]]
            with framebuffer.preview():
                framebuffer.draw(render(state), force=True, leased=True)
                stop.wait(args.duration)
            return 0

        controller = Controller(config)
        animator = AnimationPlan(config)
        probes = Probes(config)
        probe_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bootscreen-probes")
        probe_future = None
        next_poll = 0.0
        previous_state = None
        previous_key = None
        previous_image = None
        last_draw = None
        first_frame = None
        demo_started = time.monotonic()
        demo_frames_written = demo_rows_written = 0
        demo_draw_seconds = demo_write_seconds = 0.0
        demo_peak_draw_seconds = demo_peak_write_seconds = 0.0
        demo_render_seconds = demo_fb_seconds = 0.0
        while not stop.is_set():
            mono = time.monotonic()
            now = uptime()
            if args.demo:
                demo_elapsed = mono - demo_started
                screen = demo_screen(demo_elapsed)
                if demo_elapsed >= 20:
                    break
            else:
                if controller.ready_at is None and probe_future is not None and probe_future.done():
                    try:
                        snapshot = probe_future.result()
                    except Exception:
                        LOG.exception("readiness probe failed")
                        snapshot = Snapshot()
                    probe_future = None
                    after = uptime()
                    previous_index, previous_retry = controller.index, controller.retry_until
                    controller.update(after, snapshot)
                    next_poll = time.monotonic() + config.poll_seconds
                    atomic_status(controller, after, first_frame)
                    if (previous_index, previous_retry) != (controller.index, controller.retry_until):
                        LOG.info("steps=%s retry_until=%s", [(s.label, s.status) for s in controller.screen(after).steps], controller.retry_until)
                    if controller.ready_at is not None:
                        LOG.info("ready uptime=%.3fs ip=%s", controller.ready_at, controller.screen(after).ip)
                if controller.ready_at is None and probe_future is None and mono >= next_poll:
                    probe_future = probe_executor.submit(probes.sample)
                screen = controller.screen(now)
            animator.update(screen, mono)
            key = frame_key(screen)
            if key != previous_key:
                began = time.monotonic()
                regions = layout_regions(screen)
                selected = changed_regions(previous_state, screen, regions)
                if selected is None:
                    image = render(screen)
                else:
                    image = render_partial(screen, previous_image, selected, regions, in_place=True)
                rendered_at = time.monotonic()
                elapsed_write = framebuffer.draw(image, force=selected is None,
                                                  leased=args.demo, regions=selected,
                                                  stop_if_monitor=not args.demo)
                if elapsed_write is not None:
                    previous_key = key
                    previous_state = copy.deepcopy(screen)
                    previous_image = image
                    last_draw = time.monotonic()
                    if args.demo:
                        demo_frames_written += 1
                        demo_rows_written += framebuffer.rows_written
                        frame_seconds = time.monotonic() - began
                        demo_draw_seconds += frame_seconds
                        demo_render_seconds += rendered_at - began
                        demo_fb_seconds += frame_seconds - (rendered_at - began)
                        demo_write_seconds += framebuffer.last_write_seconds
                        demo_peak_draw_seconds = max(demo_peak_draw_seconds, frame_seconds)
                        demo_peak_write_seconds = max(demo_peak_write_seconds, framebuffer.last_write_seconds)
                    if first_frame is None:
                        first_frame = uptime()
                        LOG.info("first_frame uptime=%.3fs service_elapsed=%.3fs render_convert_write=%.3fs write=%.6fs rows=%d",
                                 first_frame, first_frame - initial, time.monotonic() - began,
                                 framebuffer.last_write_seconds, framebuffer.rows_written)
                elif not args.demo and framebuffer.monitor_owner_path.exists():
                    LOG.info("display_handoff monitor_active=true")
                    break
            if args.demo:
                next_delay = animator.next_delay(screen, time.monotonic(), uptime(), last_draw=last_draw)
            else:
                next_delay = animator.next_delay(screen, time.monotonic(), uptime(),
                                                 next_poll if controller.ready_at is None and probe_future is None else None,
                                                 last_draw)
            stop.wait(next_delay)
    finally:
        if "probe_executor" in locals():
            probe_executor.shutdown(wait=True, cancel_futures=True)
        if demo_preview is not None:
            LOG.info("demo_metrics frames=%d rows=%d mean_frame=%.6fs peak_frame=%.6fs mean_render=%.6fs mean_fb=%.6fs mean_pwrite=%.6fs peak_pwrite=%.6fs cpu=%.3fs",
                     demo_frames_written, demo_rows_written,
                     demo_draw_seconds / max(1, demo_frames_written), demo_peak_draw_seconds,
                     demo_render_seconds / max(1, demo_frames_written),
                     demo_fb_seconds / max(1, demo_frames_written),
                     demo_write_seconds / max(1, demo_frames_written), demo_peak_write_seconds,
                     time.process_time())
            demo_preview.__exit__(None, None, None)
        framebuffer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

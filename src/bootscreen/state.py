import math
import socket
import time

from .render import ACTIVE, FAILED, OK, PENDING, SKIPPED, Screen, Step


class AnimationPlan:
    """Animation phases derived from monotonic deadlines, never accumulated ticks."""

    def __init__(self, config, started=None):
        self.config = config.animations
        self.started = started if started is not None else time.monotonic()
        self.previous_statuses = None
        self.previous_mode = None
        self.flash_until = {}
        self.ready_started = None
        self.error_started = None

    def update(self, screen, now):
        cfg = self.config
        active = cfg.enabled
        statuses = tuple(step.status for step in screen.steps)
        mode = screen.mode
        if self.previous_statuses is not None and active and cfg.step_flash:
            for i, (old, new) in enumerate(zip(self.previous_statuses, statuses)):
                if old != OK and new == OK:
                    self.flash_until[i] = now + 0.35
        if mode == "ready" and self.previous_mode != "ready":
            self.ready_started = now
        elif mode != "ready":
            self.ready_started = None
        if mode == "error" and self.previous_mode != "error":
            self.error_started = now
        elif mode != "error":
            self.error_started = None
        self.previous_statuses = statuses
        self.previous_mode = mode

        blink = active and cfg.blink and ((now - self.started) % 1.0 < 0.5)
        screen.cursor_on = blink if active and cfg.blink else True
        screen.blink_on = screen.cursor_on
        screen.dots = int((now - self.started) / 0.32) % 4 if active and cfg.dots else 3
        screen.flash_rows = tuple(i for i, until in self.flash_until.items() if active and cfg.step_flash and now < until)
        screen.flash_row = screen.flash_rows[0] if screen.flash_rows else None
        if mode == "ready" and active and cfg.ready_intro:
            age = max(0.0, now - (self.ready_started if self.ready_started is not None else now))
            screen.reveal = min(5, int(age / 0.15))
            screen.sweep = 1.0 if age + 1e-9 >= 0.9 else int(age / (0.9 / 16)) / 16
            screen.show_ip = age >= 0.95
        else:
            screen.reveal, screen.sweep, screen.show_ip = 5, 1.0, True
        if mode == "error" and active and cfg.error_strip:
            age = max(0.0, now - (self.error_started if self.error_started is not None else now))
            screen.strip_on = age % 1.2 < 0.72
        else:
            screen.strip_on = True
        return screen

    def next_delay(self, screen, now, uptime_now, next_poll=None, last_draw=None):
        """Seconds until the next visual/check event, with a sleep when idle."""
        cfg = self.config
        cap = 1.0 / cfg.max_fps if cfg.enabled else 1.0
        deadlines = [now + (1.0 - uptime_now % 1.0)]
        if next_poll is not None:
            # Poll deadlines use the same monotonic clock as animation events.
            deadlines.append(max(now, next_poll))
        active = cfg.enabled
        if active and cfg.blink:
            phase = (now - self.started) % 1.0
            deadlines.append(now + (0.5 - phase if phase < 0.5 else 1.0 - phase))
        if active and cfg.dots and screen.title == "INICIANDO":
            phase = (now - self.started) % 0.32
            deadlines.append(now + 0.32 - phase)
        if active and screen.mode == "ready" and cfg.ready_intro and self.ready_started is not None:
            age = max(0.0, now - self.ready_started)
            for interval, total in ((0.15, 5), (0.9 / 16, 16)):
                step = int(age / interval)
                if step < total:
                    deadlines.append(self.ready_started + (step + 1) * interval)
            if age < 0.95:
                deadlines.append(self.ready_started + 0.95)
            # The short one-time intro has 16 bar steps in 0.9 s; those scheduled
            # partial-row updates intentionally exceed the steady-state FPS cap.
            return max(0.005, min(deadlines) - now)
        if active and screen.mode == "error" and cfg.error_strip and self.error_started is not None:
            age = max(0.0, now - self.error_started) % 1.2
            deadlines.append(now + (0.72 - age if age < 0.72 else 1.2 - age))
        for until in self.flash_until.values():
            if now < until:
                deadlines.append(until)
        deadline = min(deadlines)
        if active and last_draw is not None:
            deadline = max(deadline, last_draw + cap)
        return max(0.005, deadline - now)


class Controller:
    def __init__(self, config):
        self.config = config
        self.index = 0
        self.started = None
        self.retry_until = None
        self.zero_shown = False
        self.ready_at = None
        self.last_snapshot = None

    def update(self, now, snapshot):
        if self.ready_at is not None:
            return
        self.last_snapshot = snapshot
        # Previously passed checks can regress before LISTO; restart at that step.
        for i in range(self.index):
            if not snapshot.ready(self.config.steps[i]):
                self.index, self.started, self.retry_until = i, now, None
                self.zero_shown = False
                break
        while self.index < len(self.config.steps):
            step = self.config.steps[self.index]
            if self.started is None:
                self.started = now
            if self.retry_until is not None:
                if now < self.retry_until:
                    return
                if not self.zero_shown:
                    self.zero_shown = True
                    return
                self.retry_until, self.started = None, now
                self.zero_shown = False
            if snapshot.ready(step):
                self.index += 1
                self.started = now
                continue
            if now - self.started >= step.timeout:
                self.retry_until = now + self.config.retry_seconds
                self.zero_shown = False
            return
        self.ready_at = now

    def screen(self, now):
        steps = []
        for i, check in enumerate(self.config.steps):
            status = SKIPPED if not check.enabled else OK if i < self.index else PENDING
            if i == self.index and check.enabled:
                status = FAILED if self.retry_until is not None else ACTIVE
            steps.append(Step(check.label, status, "sin respuesta" if status == FAILED else "", check.error_title))
        retry = None if self.retry_until is None else max(0, math.ceil(self.retry_until - now))
        blink_on = not self.config.blink or now % 1 < 0.5
        return Screen(steps, elapsed=int(self.ready_at if self.ready_at is not None else now),
                      ip=(self.last_snapshot.ip if self.last_snapshot else "") or socket.gethostname(),
                      retry_in=retry, cursor_on=blink_on, blink_on=blink_on)

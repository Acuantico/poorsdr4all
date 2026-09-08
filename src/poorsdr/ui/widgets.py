import contextlib
import tkinter as tk

import numpy as np

from poorsdr.ui.theme import THEME_COLORS


class DialControl(tk.Canvas):
    def __init__(self, parent, from_, to_, command, initial=0, size=90, step=1):
        super().__init__(parent, width=size, height=size, bg=THEME_COLORS["panel_bg"], highlightthickness=0)
        self.from_ = float(from_)
        self.to_ = float(to_)
        self.min_value = min(self.from_, self.to_)
        self.max_value = max(self.from_, self.to_)
        self.command = command
        self.size = size
        self.step = float(step)
        self.min_angle = -135.0
        self.max_angle = 135.0
        self.value = float(initial)
        self._center = (size / 2.0, size / 2.0)
        self._radius = size * 0.35
        self._indicator = None
        self._value_text = None
        self._drag_start_y = None
        self._drag_start_value = None
        self._enabled = True
        self._draw()
        self.set(self.value)
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", self._on_wheel)
        self.bind("<Button-5>", self._on_wheel)

    def _draw(self):
        cx, cy = self._center
        r = self._radius
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=THEME_COLORS["panel_bg"], outline=THEME_COLORS["border"], width=2)
        self._indicator = self.create_line(cx, cy, cx, cy - r, fill=THEME_COLORS["accent"], width=3)
        readout_pt = max(6, round(self.size * 0.11))
        self._value_text = self.create_text(cx, cy + (self.size * 0.18), text="", fill=THEME_COLORS["text_primary"], font=("Segoe UI", readout_pt, "bold"))
        self.tag_raise(self._indicator)

    def _angle_to_value(self, angle):
        angle = max(self.min_angle, min(self.max_angle, angle))
        ratio = ((-angle) - self.min_angle) / (self.max_angle - self.min_angle)
        return self.from_ + ratio * (self.to_ - self.from_)

    def _value_to_angle(self, value):
        value = max(self.min_value, min(self.max_value, value))
        ratio = (value - self.from_) / (self.to_ - self.from_)
        return self.min_angle + ratio * (self.max_angle - self.min_angle)

    def _update_indicator(self):
        if not self._indicator:
            return
        cx, cy = self._center
        angle = np.deg2rad(self._value_to_angle(self.value))
        x = cx + self._radius * np.cos(angle)
        y = cy + self._radius * np.sin(angle)
        self.coords(self._indicator, cx, cy, x, y)
        if self._value_text:
            self.itemconfig(self._value_text, text=f"{int(round(self.value))}")

    def _set_value(self, value):
        self.value = max(self.min_value, min(self.max_value, float(value)))
        self._update_indicator()
        if self.command:
            self.command(self.value)

    def set(self, value):
        self._set_value(value)

    def set_silent(self, value):
        """Como :meth:`set`, pero sin disparar ``command``.

        Para reflejar un valor que ya viene aplicado desde otro origen (p. ej.
        el servidor web) sin reenviarlo de vuelta al servicio — evitaría un
        ida-y-vuelta redundante con el propio origen del cambio.
        """
        self.value = max(self.min_value, min(self.max_value, float(value)))
        self._update_indicator()

    def set_accent(self, color: str):
        """Tiñe el indicador del dial con el color del tema."""
        if self._indicator:
            with contextlib.suppress(tk.TclError):
                self.itemconfig(self._indicator, fill=color)

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self.configure(cursor="" if self._enabled else "arrow")
        fg = THEME_COLORS["text_primary"] if self._enabled else THEME_COLORS["text_muted"]
        if self._value_text:
            self.itemconfig(self._value_text, fill=fg)

    def _on_click(self, event):
        if not self._enabled:
            return "break"
        self._drag_start_y = event.y
        self._drag_start_value = self.value
        self._set_from_event(event)

    def _on_drag(self, event):
        if not self._enabled:
            return "break"
        if self._drag_start_y is None or self._drag_start_value is None:
            self._set_from_event(event)
            return
        pixel_range = max(1.0, self.size * 1.5)
        value_range = self.to_ - self.from_
        delta_pixels = self._drag_start_y - event.y
        new_value = self._drag_start_value + (delta_pixels / pixel_range) * value_range
        self._set_value(new_value)

    def _set_from_event(self, event):
        if not self._enabled:
            return "break"
        cx, cy = self._center
        dx = event.x - cx
        dy = event.y - cy
        angle = np.degrees(np.arctan2(dy, dx))
        self._set_value(self._angle_to_value(angle))

    def _on_wheel(self, event):
        if not self._enabled:
            return "break"
        event_num = getattr(event, "num", None)
        if event_num == 4:
            delta = 1
        elif event_num == 5:
            delta = -1
        else:
            delta = 1 if getattr(event, "delta", 0) > 0 else -1
        self._set_value(self.value + delta * self.step)
        return "break"

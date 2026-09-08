from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Callable


def _should_suppress_portaudio_probe_noise() -> bool:
    if sys.platform.startswith("win"):
        return False
    return os.environ.get("POORSDR_DEBUG_ALSA", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }


@contextmanager
def suppress_portaudio_probe_noise():
    if not _should_suppress_portaudio_probe_noise():
        yield
        return

    try:
        stderr_fd = sys.stderr.fileno()
    except Exception:
        stderr_fd = 2

    saved_fd = None
    null_fd = None
    try:
        try:
            sys.stderr.flush()
        except Exception:
            pass
        saved_fd = os.dup(stderr_fd)
        null_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null_fd, stderr_fd)
        yield
    finally:
        if saved_fd is not None:
            os.dup2(saved_fd, stderr_fd)
            os.close(saved_fd)
        if null_fd is not None:
            os.close(null_fd)


def probe_portaudio(call: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    with suppress_portaudio_probe_noise():
        return call(*args, **kwargs)


def create_pyaudio(pyaudio_module: Any) -> Any:
    return probe_portaudio(pyaudio_module.PyAudio)

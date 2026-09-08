from __future__ import annotations

from typing import Callable, Iterable

import socket


def build_viewer_launcher_env(
    *,
    base_env: dict,
    config_path: str,
    geometry: str,
    is_valid_geometry_fn: Callable[[str], bool],
    state_path: str | None = None,
) -> dict:
    env = dict(base_env or {})
    env["OWRX_CONFIG_PATH"] = str(config_path or "")
    if state_path:
        env["POORSDR_WATERFALL_STATE_PATH"] = str(state_path)
    if is_valid_geometry_fn(str(geometry or "")):
        env["OWRX_FORCE_GEOMETRY"] = str(geometry)
    env.setdefault("GDK_BACKEND", "x11")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def allocate_loopback_port(socket_module=socket) -> int | None:
    try:
        with socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])
    except Exception:
        return None


def build_viewer_launch_args(
    *,
    helper_python: str,
    helper_path: str,
    url: str,
    width: int,
    height: int,
    viewer_port: int | None,
    control_host: str = "127.0.0.1",
    control_port: int | None = None,
) -> list[str]:
    return [
        str(helper_python or ""),
        str(helper_path or ""),
        str(url or ""),
        str(int(width or 0)),
        str(int(height or 0)),
        str(viewer_port or ""),
        str(control_host or "127.0.0.1"),
        str(control_port or ""),
    ]


def format_env_log_lines(*, prefix: str, env: dict, keys: Iterable[str]) -> list[str]:
    lines: list[str] = []
    for key in keys:
        lines.append(f"{prefix} env {key}={env.get(key, '')}\n")
    return lines


def resolve_launch_size(
    *,
    geometry: str,
    is_valid_geometry_fn: Callable[[str], bool],
    parse_geometry_fn: Callable[[str], tuple[int, int, int, int] | None],
    fallback_width: int,
    fallback_height: int,
    min_width: int = 0,
    min_height: int = 0,
) -> tuple[int, int]:
    parsed = parse_geometry_fn(geometry) if is_valid_geometry_fn(geometry) else None
    if parsed:
        width, height, _x, _y = parsed
    else:
        width = int(fallback_width or 0)
        height = int(fallback_height or 0)
    width = max(int(min_width or 0), int(width))
    height = max(int(min_height or 0), int(height))
    return width, height


def open_viewer_process_log(
    *,
    log_path: str,
    prefix: str,
    helper_python: str,
    env: dict,
    env_keys: Iterable[str],
    open_fn=open,
):
    handle = open_fn(log_path, "w", encoding="utf-8")
    handle.write(f"{prefix} python: {helper_python}\n")
    for line in format_env_log_lines(prefix=prefix, env=env, keys=env_keys):
        handle.write(line)
    handle.flush()
    return handle


def spawn_viewer_process(
    *,
    launch_args: list[str],
    cwd: str,
    env: dict,
    stdout_handle,
    stderr_value,
    popen_fn,
    start_new_session: bool = True,
):
    return popen_fn(
        launch_args,
        cwd=cwd,
        env=env,
        stdout=stdout_handle,
        stderr=stderr_value,
        start_new_session=bool(start_new_session),
    )


def close_log_handle(handle) -> None:
    if not handle:
        return
    try:
        handle.close()
    except Exception:
        pass

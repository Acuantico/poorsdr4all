"""Dispositivos de la VPN para la pestaña "VPN" de Ajustes.

Debajo de los campos de la pestaña (activar, puerto, dirección pública, LAN):
lista de dispositivos autorizados con su estado, alta con QR para la app
WireGuard, baja, y qué hay que reenviar en el router. Los dispositivos se
guardan al momento en ``vpn.json`` (no esperan a "Guardar") y, si el túnel está
en marcha, se aplican en caliente. Toda la lógica está en ``_vendor/vpn.py``.
"""

from __future__ import annotations

import contextlib
import os
import threading
import tkinter as tk
from functools import partial
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Any

from poorsdr.i18n.settings_labels import field_label
from poorsdr.ui.settings import style as sstyle

if TYPE_CHECKING:
    from poorsdr.config.model import AppConfig

REFRESH_MS = 3000


def _vpn() -> Any:
    import vpn  # _vendor/vpn.py (en sys.path al arrancar la app)

    return vpn


class VpnDevicesPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, cfg: AppConfig) -> None:
        super().__init__(master)
        self._cfg = cfg
        self._lang = cfg.ui.language
        self._status: dict[str, dict] = {}
        self._timer: str | None = None
        try:
            self._mod = _vpn()
        except Exception as exc:  # noqa: BLE001 - falta cryptography u otra pieza
            ttk.Label(self, text=f"VPN: {exc}", style="Muted.TLabel").grid(sticky="w")
            self._mod = None
            return

        self._list = ttk.LabelFrame(self, text=self._t("label_vpn_devices"), padding=8)
        self._list.grid(row=0, column=0, sticky="ew", pady=(8, 4))
        self.columnconfigure(0, weight=1)
        self._info = ttk.Label(self, style="Muted.TLabel", justify="left", wraplength=560)
        self._info.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self._render()
        self._refresh_info()
        if not self._mod.endpoint_for(cfg.web.vpn_endpoint):
            threading.Thread(target=self._detect_endpoint, daemon=True).start()
        self._schedule()

    def _t(self, key: str, **kwargs: object) -> str:
        return field_label(key, self._lang, **kwargs)

    # -- lista ------------------------------------------------------------ #
    def _render(self) -> None:
        for child in self._list.winfo_children():
            child.destroy()
        peers = self._mod.load().get("peers", [])
        if not peers:
            ttk.Label(self._list, text=self._t("label_vpn_no_devices"), style="Muted.TLabel").grid(
                row=0, column=0, columnspan=4, sticky="w"
            )
        for row, peer in enumerate(peers):
            ttk.Label(self._list, text=peer.get("name", "")).grid(row=row, column=0, sticky="w", padx=(0, 10))
            ttk.Label(self._list, text=peer.get("ip", ""), style="Muted.TLabel").grid(
                row=row, column=1, sticky="w", padx=(0, 10)
            )
            ttk.Label(self._list, text=self._state_text(peer), style="Muted.TLabel").grid(
                row=row, column=2, sticky="w", padx=(0, 10)
            )
            ttk.Button(self._list, text="QR", command=partial(self._show_qr, peer)).grid(
                row=row, column=3, padx=2, pady=1
            )
            ttk.Button(
                self._list, text=self._t("label_vpn_remove"), command=partial(self._remove, peer)
            ).grid(row=row, column=4, padx=2, pady=1)
        ttk.Button(self._list, text=self._t("label_vpn_add"), command=self._add).grid(
            row=max(1, len(peers)), column=0, columnspan=5, sticky="w", pady=(8, 0)
        )

    def _state_text(self, peer: dict) -> str:
        info = self._status.get(peer.get("public_key", ""))
        if not self._mod.get_manager().running:
            return ""
        if info and info.get("connected"):
            return self._t("label_vpn_connected")
        return self._t("label_vpn_not_connected")

    def _refresh_info(self) -> None:
        mod, web = self._mod, self._cfg.web
        manager = mod.get_manager()
        lines = []
        if manager.running:
            lines.append(self._t("label_vpn_running", url=mod.access_url(web.port)))
        elif manager.error:
            lines.append(self._t("label_vpn_error", error=manager.error))
        else:
            lines.append(self._t("label_vpn_stopped"))
        endpoint = mod.endpoint_for(web.vpn_endpoint)
        lines.append(self._t("label_vpn_endpoint_now", endpoint=endpoint or "…"))
        if endpoint and mod.is_shared_or_private(endpoint.rsplit(":", 1)[0].strip("[]")):
            lines.append(self._t("label_vpn_cgnat"))
        lines.append(self._t("label_vpn_router", port=web.vpn_port, ip=" / ".join(mod.lan_addresses()) or "?"))
        self._info.configure(text="\n".join(lines))

    def _schedule(self) -> None:
        self._timer = self.after(REFRESH_MS, self._tick)

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        manager = self._mod.get_manager()
        if manager.running:
            def poll() -> None:
                status = manager.device_status(wait=1.0)
                self.after(0, lambda: self._apply_status(status))

            threading.Thread(target=poll, daemon=True).start()
        else:
            self._refresh_info()
        self._schedule()

    def _apply_status(self, status: dict[str, dict]) -> None:
        if not self.winfo_exists():
            return
        self._status = status
        self._render()
        self._refresh_info()

    def _detect_endpoint(self) -> None:
        public = self._mod.detect_public_ip()
        if public:
            data = self._mod.load()
            data["detected_endpoint"] = public
            self._mod.save(data)
            self.after(0, self._refresh_info)

    def destroy(self) -> None:
        if self._timer is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._timer)
        super().destroy()

    # -- acciones ----------------------------------------------------------- #
    def _add(self) -> None:
        name = simpledialog.askstring(
            self._t("label_vpn_add"), self._t("label_vpn_device_name"), parent=self
        )
        if name is None:
            return
        try:
            peer = self._mod.add_device(name)
        except ValueError as exc:
            messagebox.showerror("VPN", str(exc), parent=self)
            return
        self._render()
        self._show_qr(peer)

    def _remove(self, peer: dict) -> None:
        if not messagebox.askyesno(
            "VPN", self._t("label_vpn_remove_confirm", name=peer.get("name", "")), parent=self
        ):
            return
        self._mod.remove_device(peer.get("public_key", ""))
        self._render()

    def _client_text(self, peer: dict) -> str:
        web = self._cfg.web
        return self._mod.client_config(peer, self._mod.endpoint_for(web.vpn_endpoint), web.vpn_port)

    def _show_qr(self, peer: dict) -> None:
        text = self._client_text(peer)
        top = tk.Toplevel(self)
        top.title(f"VPN — {peer.get('name', '')}")
        top.configure(bg=sstyle.PANEL)
        top.transient(self.winfo_toplevel())
        try:
            import segno  # _vendor/segno

            qr = segno.make_qr(text, error="m")
            matrix = [list(row) for row in qr.matrix]
        except Exception as exc:  # noqa: BLE001
            matrix = []
            ttk.Label(top, text=f"QR: {exc}", style="Muted.TLabel").pack(padx=12, pady=8)
        if matrix:
            quiet = 4
            modules = len(matrix) + 2 * quiet
            # Que quepa también en la pantalla de 7" (800x480) con los textos.
            scale = max(2, min(6, (top.winfo_screenheight() - 190) // modules))
            size = modules * scale
            canvas = tk.Canvas(top, width=size, height=size, bg="#ffffff", highlightthickness=0)
            for y, row in enumerate(matrix):
                for x, dark in enumerate(row):
                    if dark:
                        x0, y0 = (x + quiet) * scale, (y + quiet) * scale
                        canvas.create_rectangle(x0, y0, x0 + scale, y0 + scale, fill="#000000", width=0)
            canvas.pack(padx=12, pady=(12, 6))
        ttk.Label(
            top, justify="left", wraplength=420,
            text=self._t("label_vpn_qr_steps", url=self._mod.access_url(self._cfg.web.port)),
        ).pack(padx=12, pady=(0, 6))
        bar = ttk.Frame(top)
        bar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(bar, text=self._t("label_vpn_save_conf"), command=lambda: self._save_conf(peer, text, top)).pack(
            side="left"
        )
        ttk.Button(bar, text=self._t("label_close"), command=top.destroy).pack(side="right")

    def _save_conf(self, peer: dict, text: str, parent: tk.Misc) -> None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in peer.get("name", "movil")) or "movil"
        path = filedialog.asksaveasfilename(
            parent=parent, defaultextension=".conf", initialfile=f"poorsdr-{safe}.conf",
            filetypes=[("WireGuard", "*.conf")],
        )
        if path:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(text)
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)  # lleva la clave privada del dispositivo


__all__ = ["VpnDevicesPanel"]

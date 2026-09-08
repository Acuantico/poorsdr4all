"""core.theme: paletas, acento por fondo y colormap de la cascada."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from poorsdr.core import theme  # noqa: E402


class ThemeTests(unittest.TestCase):
    def test_accent_per_background(self):
        self.assertEqual(theme.accent_for_background("back.png"), "#7b8794")  # executive (acero suave)
        self.assertEqual(theme.accent_for_background("back1.jpg"), "#36f715")  # acid jungle
        self.assertEqual(theme.accent_for_background("back2.jpg"), "#0314ec")  # mizuno night
        self.assertEqual(theme.accent_for_background("desconocido"), "#f10a0a")  # fallback devil power

    def test_label_roundtrip(self):
        for label, file in theme.THEME_OPTIONS.items():
            self.assertEqual(theme.theme_label(file), label)
            self.assertEqual(theme.background_for_label(label), file)
        self.assertEqual(theme.background_for_label("nope"), "back.jpg")

    def test_executive_theme_renamed_from_classic(self):
        # Linaje de nombres del tema de back.png: Gris -> Classic -> Executive.
        self.assertEqual(theme.THEME_OPTIONS["Executive"], "back.png")
        self.assertNotIn("Gris", theme.THEME_OPTIONS)
        self.assertNotIn("Classic", theme.THEME_OPTIONS)
        self.assertEqual(theme.theme_label("back.png"), "Executive")

    def test_cascada_colors_gradient(self):
        stops = theme.cascada_colors("#1e90ff")
        self.assertEqual(len(stops), 9)
        self.assertEqual(stops[0], (0.0, "#0b0f14"))
        self.assertEqual(stops[-1][0], 1.0)
        # posiciones monótonas crecientes
        positions = [p for p, _ in stops]
        self.assertEqual(positions, sorted(positions))
        # todos los colores son #rrggbb
        for _pos, color in stops:
            self.assertRegex(color, r"^#[0-9a-f]{6}$")

    def test_cascada_colors_uses_accent(self):
        red = theme.cascada_colors("#ff0000")
        blue = theme.cascada_colors("#0000ff")
        self.assertNotEqual(red[-1][1], blue[-1][1])  # el tramo alto depende del acento

    def test_cascada_colors_for_background_classic_ignores_accent(self):
        # Excepción única del tema Classic: la cascada usa siempre el mismo
        # degradado fijo estilo SDR#, sin importar qué acento le pases.
        acero = theme.cascada_colors_for_background("back.png", "#7b8794")
        otro_acento = theme.cascada_colors_for_background("back.png", "#ff0000")
        self.assertEqual(acero, otro_acento)
        self.assertEqual(acero, theme.CLASSIC_CASCADA_COLORS)

    def test_cascada_colors_for_background_other_themes_use_accent(self):
        rojo = theme.cascada_colors_for_background("back.jpg", "#f10a0a")
        self.assertEqual(rojo, theme.cascada_colors("#f10a0a"))
        self.assertNotEqual(rojo, theme.CLASSIC_CASCADA_COLORS)


class SettingsThemeFieldTests(unittest.TestCase):
    def test_build_config_maps_theme_label_to_file(self):
        from poorsdr.config.model import AppConfig
        from poorsdr.ui.settings.form import ALL_FIELDS, build_config, get_value

        cfg = build_config(AppConfig(), {("ui", "background_image"): "Acid Jungle"})
        self.assertEqual(cfg.ui.background_image, "back1.jpg")
        # get_value muestra la etiqueta
        theme_field = next(f for f in ALL_FIELDS if f.attr == "background_image")
        self.assertEqual(get_value(cfg, theme_field), "Acid Jungle")


if __name__ == "__main__":
    unittest.main()

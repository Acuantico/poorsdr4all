"""poorsdr.i18n: textos y helper t()."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT / "src" / "poorsdr" / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from poorsdr import i18n  # noqa: E402


class I18nTests(unittest.TestCase):
    def test_languages(self):
        self.assertEqual(
            set(i18n.LANGUAGES),
            {"es", "en", "fr", "de", "it", "pt", "tr", "pl", "ru", "gl", "ca", "eu"},
        )
        self.assertEqual(i18n.DEFAULT_LANG, "es")

    def test_new_languages_have_full_translations(self):
        # Todas las claves de "es" deben existir en los idiomas añadidos (sin
        # depender del fallback de t()): comprobación directa de completitud.
        expected_keys = set(i18n.idiomas["es"])
        for lang in ("tr", "pl", "ru", "gl", "ca", "eu"):
            with self.subTest(lang=lang):
                self.assertEqual(set(i18n.idiomas[lang]), expected_keys)

    def test_translations_fallback(self):
        self.assertEqual(i18n.translations("es")["ptt"], "PTT")
        self.assertEqual(i18n.translations("zz"), i18n.translations("es"))

    def test_t(self):
        self.assertEqual(i18n.t("settings", "es"), "Ajustes")
        self.assertEqual(i18n.t("settings", "en"), "Settings")
        # clave ausente en el idioma → cae a es
        self.assertEqual(i18n.t("ptt", "fr"), i18n.idiomas["fr"].get("ptt", i18n.idiomas["es"]["ptt"]))
        # clave inexistente → default o la propia clave
        self.assertEqual(i18n.t("no_existe", "es"), "no_existe")
        self.assertEqual(i18n.t("no_existe", "es", default="X"), "X")


if __name__ == "__main__":
    unittest.main()

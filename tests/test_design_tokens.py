"""Один источник дизайна: токены CSS и ресурсы Android собираются из
design/tokens.json и design/mark.svg (design/build.py).

Тест ловит правку руками в сгенерированном файле и забытую сборку после
правки источника: иначе веб и Android однажды разошлись бы снова.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _build():
    spec = importlib.util.spec_from_file_location("design_build", ROOT / "design" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_files_match_tokens():
    stale = [str(path.relative_to(ROOT)) for path in _build().stale()]
    assert stale == [], "запустите python design/build.py: " + ", ".join(stale)


def test_android_and_web_share_colors():
    build = _build()
    res = ROOT / "mobile/android/app/src/main/res"
    colors = (res / "values/colors.xml").read_text(encoding="utf-8")
    css = (ROOT / "apps/web/static/web/app/app.css").read_text(encoding="utf-8")
    accent = build.TOKENS["client"]["accent"]
    assert f'<color name="accent">{accent.upper()}</color>' in colors
    assert f"--accent: {accent};" in css


def test_mark_parses_into_closed_outlines():
    polygons = _build().polygons()
    assert len(polygons) == 2  # кузов и задний фонарь
    assert all(len(p) > 20 for p in polygons)  # кривые разбиты, а не пропущены

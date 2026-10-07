"""Сборка дизайна из одного источника: токены и иконки.

    python design/build.py           # токены (CSS, Android) и иконки
    python design/build.py --check   # только сверка токенов: код 1, если разошлись

Источник — `design/tokens.json` и `design/mark.svg`. Пишет:

* `apps/web/static/web/css/app.css` — шкалы (шрифт, насыщенность,
  скругления, отступы, движение) в блоке между метками `design-tokens`;
* `apps/web/static/web/app/app.css` — цвета клиентской темы в таком же блоке;
* `mobile/android/.../values/colors.xml` и `dimens.xml` — целиком;
* иконки: iPhone (apple-touch-icon, иконки манифеста) и Android
  (адаптивная: фон и знак, монохромная, старые квадратные и круглые,
  заставка, знак для экрана «нет связи»).

Иконкам нужен Pillow (`pip install pillow`) — только здесь, проекту он не
нужен. Сверка (`--check`) работает без него: её гоняет CI, а PNG от версии
Pillow побайтно не повторяются, и сверять их бессмысленно.

Почему не cairo и не браузер: в знаке только команды M, C, L, Z, и
растеризация кривых Безье — полсотни строк; тянуть системную библиотеку
или Chromium ради четырёх картинок — лишняя хрупкость.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "design"
TOKENS = json.loads((DESIGN / "tokens.json").read_text(encoding="utf-8"))

APP_CSS = ROOT / "apps/web/static/web/css/app.css"
CLIENT_CSS = ROOT / "apps/web/static/web/app/app.css"
ANDROID_RES = ROOT / "mobile/android/app/src/main/res"
WEB_ICONS = ROOT / "apps/web/static/web/app/icons"

START = (
    "/* design-tokens: начало — сгенерировано design/build.py из design/tokens.json, "
    "руками не править */"
)
END = "/* design-tokens: конец */"


# ---------------------------------------------------------------- токены
def _name(prefix: str, key: str) -> str:
    return f"--{prefix}-{key}" if key else f"--{prefix}"


def scales_css() -> str:
    scale = TOKENS["scale"]
    lines = []
    for group in ("fs", "fw", "radius", "space", "dur"):
        lines += [f"  {_name(group, key)}: {value};" for key, value in scale[group].items()]
    lines.append(f"  --ease: {scale['ease']};")
    return "\n".join(lines)


def client_css() -> str:
    return "\n".join(
        f"  --{key}: {value};" for key, value in TOKENS["client"].items() if not key.startswith("_")
    )


def replace_block(text: str, body: str, path: Path) -> str:
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"{path}: нет меток design-tokens — куда писать, неизвестно")
    return pattern.sub(lambda _: f"{START}\n{body}\n  {END}", text, count=1)


def android_colors() -> str:
    client = TOKENS["client"]
    rows = "\n".join(
        f'    <color name="{name}">{client[token].upper()}</color>'
        for name, token in TOKENS["android"]["colors"].items()
        if not name.startswith("_")
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Сгенерировано design/build.py из design/tokens.json — руками не править.\n"
        "     Цвета — те же, что у веб-приложения /app/: оболочка показывает его\n"
        "     экраны, а своё (заставка, «нет связи») должно выглядеть так же. -->\n"
        f"<resources>\n{rows}\n</resources>\n"
    )


def android_dimens() -> str:
    scale = TOKENS["scale"]
    rows = []
    for name, (group, key, unit) in TOKENS["android"]["dimens"].items():
        value = scale[group][key].removesuffix("px")
        rows.append(f'    <dimen name="{name}">{value}{unit}</dimen>')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Сгенерировано design/build.py из шкал design/tokens.json — руками не править. -->\n"
        "<resources>\n" + "\n".join(rows) + "\n</resources>\n"
    )


def text_outputs() -> dict[Path, str]:
    return {
        APP_CSS: replace_block(APP_CSS.read_text(encoding="utf-8"), scales_css(), APP_CSS),
        CLIENT_CSS: replace_block(CLIENT_CSS.read_text(encoding="utf-8"), client_css(), CLIENT_CSS),
        ANDROID_RES / "values/colors.xml": android_colors(),
        ANDROID_RES / "values/dimens.xml": android_dimens(),
        ANDROID_RES / "drawable/ic_mark.xml": vector_mark("@color/accent"),
        ANDROID_RES / "drawable/ic_launcher_monochrome.xml": vector_monochrome(),
    }


def stale() -> list[Path]:
    """Файлы, которые разошлись с источником."""
    return [
        path for path, content in text_outputs().items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]


# ------------------------------------------------------------------ знак
VIEW_W, VIEW_H = 1483, 326


def mark_paths() -> list[str]:
    svg = (DESIGN / "mark.svg").read_text(encoding="utf-8")
    return re.findall(r'<path d="([^"]+)"', svg)


def vector_mark(fill: str) -> str:
    """Знак вектором — экран «нет связи». Без свечения: VectorDrawable его не умеет."""
    paths = "\n".join(
        f'    <path android:fillColor="{fill}" android:pathData="{d}" />' for d in mark_paths()
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Сгенерировано design/build.py из design/mark.svg — руками не править. -->\n"
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="128dp" android:height="28dp"\n'
        f'    android:viewportWidth="{VIEW_W}" android:viewportHeight="{VIEW_H}">\n'
        f"{paths}\n</vector>\n"
    )


# Доля ширины, которую знак занимает в иконке. Подобрано по виду, а не
# по формуле: силуэт вытянут (4,5 : 1), и «вписать в безопасную зону» по
# диагонали дало бы мелкую полоску.
WIDTH_FULL = 0.76  # iPhone и квадратные иконки: на всю иконку
WIDTH_MASKABLE = 0.62  # маскируемая иконка манифеста: видно круг 80 %
ADAPTIVE_WIDTH_DP = 62  # Android: слой 108 dp, видно круг 66–72 dp
SPLASH_WIDTH_DP = 140  # заставка Android 12+: 240 dp, видно круг 160 dp


def vector_monochrome() -> str:
    """Монохромная иконка Android 13+: тот же знак, система красит сама."""
    scale = ADAPTIVE_WIDTH_DP / VIEW_W
    tx = (108 - VIEW_W * scale) / 2
    ty = (108 - VIEW_H * scale) / 2
    paths = "\n".join(
        f'        <path android:fillColor="#FFFFFFFF" android:pathData="{d}" />'
        for d in mark_paths()
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Сгенерировано design/build.py из design/mark.svg — руками не править.\n"
        "     Знак по центру слоя 108 dp и шириной, как у цветной иконки. -->\n"
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="108dp" android:height="108dp"\n'
        '    android:viewportWidth="108" android:viewportHeight="108">\n'
        f'    <group android:translateX="{tx:.3f}" android:translateY="{ty:.3f}"\n'
        f'        android:scaleX="{scale:.6f}" android:scaleY="{scale:.6f}">\n'
        f"{paths}\n    </group>\n</vector>\n"
    )


def _bezier(p0, p1, p2, p3, steps=24):
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        yield (
            mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1],
        )


def polygons() -> list[list[tuple[float, float]]]:
    """Контуры знака ломаными — кривые разбиты на короткие отрезки."""
    result = []
    for d in mark_paths():
        tokens = re.findall(r"[MCLZ]|-?\d*\.?\d+(?:e-?\d+)?", d)
        i, current, poly = 0, (0.0, 0.0), []
        while i < len(tokens):
            cmd = tokens[i]
            i += 1
            if cmd == "M":
                current = (float(tokens[i]), float(tokens[i + 1]))
                i += 2
                poly = [current]
            elif cmd == "L":
                current = (float(tokens[i]), float(tokens[i + 1]))
                i += 2
                poly.append(current)
            elif cmd == "C":
                pts = [(float(tokens[i + k]), float(tokens[i + k + 1])) for k in (0, 2, 4)]
                i += 6
                poly.extend(_bezier(current, *pts))
                current = pts[2]
            elif cmd == "Z":
                result.append(poly)
                poly = []
        if poly:
            result.append(poly)
    return result


# ---------------------------------------------------------------- иконки
def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))


def render_mark(
    size: int, width_ratio: float, *, background: bool, rounded: str = "", halo: float = 1.0
):
    """Знак со свечением на квадрате `size`. Без фона — для слоя Android.

    `halo` — сила дальнего синего ореола: на заставке Android видно только
    круг, и полный ореол обрезался бы по нему заметным диском.
    """
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    colors = TOKENS["client"]
    ss = 4  # рисуем крупнее и уменьшаем — сглаженные края без cairo
    big = size * ss
    scale = big * width_ratio / VIEW_W
    ox = (big - VIEW_W * scale) / 2
    oy = (big - VIEW_H * scale) / 2

    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    for poly in polygons():
        draw.polygon([(ox + x * scale, oy + y * scale) for x, y in poly], fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if background:
        canvas = _gradient(size)

    # Свечение неона: три размытых слоя от дальнего синего к белому ядру —
    # как drop-shadow знака на витрине.
    for radius, color, strength in (
        (size * 0.09 * halo, colors["neon-deep"], halo),
        (size * 0.035, colors["accent"], 1.0),
        (size * 0.012, colors["neon-hot"], 0.9),
    ):
        glow = mask.filter(ImageFilter.GaussianBlur(radius))
        glow = glow.point(lambda v, k=strength: min(255, int(v * 2.2 * k)))
        layer = Image.new("RGBA", (size, size), _rgb(color) + (0,))
        layer.putalpha(glow)
        canvas = Image.alpha_composite(canvas, layer)
    core = Image.new("RGBA", (size, size), (236, 248, 255, 0))
    core.putalpha(mask)
    canvas = Image.alpha_composite(canvas, core)

    if rounded:
        shape = Image.new("L", (big, big), 0)
        sd = ImageDraw.Draw(shape)
        if rounded == "circle":
            sd.ellipse((0, 0, big - 1, big - 1), fill=255)
        else:
            sd.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=255)
        shape = shape.resize((size, size), Image.LANCZOS)
        canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), shape))
    return canvas


def _gradient(size: int):
    """Фон иконки: тёмный, с синим пятном света за знаком."""
    from PIL import Image, ImageDraw, ImageFilter

    colors = TOKENS["client"]
    canvas = Image.new("RGBA", (size, size), _rgb(colors["bg"]) + (255,))
    spot = Image.new("L", (size, size), 0)
    ImageDraw.Draw(spot).ellipse(
        (size * 0.12, size * 0.22, size * 0.88, size * 0.78), fill=150
    )
    spot = spot.filter(ImageFilter.GaussianBlur(size * 0.16))
    blue = Image.new("RGBA", (size, size), _rgb(colors["neon-deep"]) + (0,))
    blue.putalpha(spot)
    return Image.alpha_composite(canvas, blue)


DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def build_icons() -> list[Path]:
    written = []

    def save(image, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, optimize=True)
        written.append(path)

    # iPhone и манифест. Apple-иконка без прозрачности: iOS скругляет сам и
    # прозрачное заливает чёрным.
    apple = render_mark(180, WIDTH_FULL, background=True).convert("RGB")
    save(apple, WEB_ICONS / "apple-touch-icon.png")
    save(render_mark(192, WIDTH_FULL, background=True), WEB_ICONS / "icon-192.png")
    save(render_mark(512, WIDTH_FULL, background=True), WEB_ICONS / "icon-512.png")
    save(render_mark(512, WIDTH_MASKABLE, background=True), WEB_ICONS / "maskable-512.png")

    # Android: адаптивная иконка — фон и знак отдельными слоями 108 dp, плюс
    # квадратная и круглая для Android 7 (API 24–25), где адаптивных нет.
    for name, k in DENSITIES.items():
        layer = round(108 * k)
        folder = ANDROID_RES / f"mipmap-{name}"
        save(_gradient(layer), folder / "ic_launcher_background.png")
        mark = render_mark(layer, ADAPTIVE_WIDTH_DP / 108, background=False)
        save(mark, folder / "ic_launcher_foreground.png")
        legacy = round(48 * k)
        for shape, file in (("square", "ic_launcher.png"), ("circle", "ic_launcher_round.png")):
            save(render_mark(legacy, WIDTH_FULL, background=True, rounded=shape), folder / file)
        # Заставка Android 12+: 240 dp, видимый круг — 160 dp.
        splash = round(240 * k)
        save(render_mark(splash, SPLASH_WIDTH_DP / 240, background=False, halo=0.35),
             ANDROID_RES / f"drawable-{name}" / "splash_mark.png")
    return written


# ----------------------------------------------------------------- запуск
def main(argv: list[str]) -> int:
    if "--check" in argv:
        bad = stale()
        for path in bad:
            print(f"разошлось с design/tokens.json: {path.relative_to(ROOT)}")
        return 1 if bad else 0

    for path, content in text_outputs().items():
        path.write_text(content, encoding="utf-8", newline="\n")
        print("токены:", path.relative_to(ROOT))
    try:
        written = build_icons()
    except ImportError:
        print("иконки пропущены: нужен Pillow (pip install pillow)")
        return 0
    for path in written:
        print("иконка:", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

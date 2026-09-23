"""Фильтры шаблонов сайта: русские словоформы и телефонные ссылки.

Встроенный `pluralize` знает две формы — английские. У русского их три
(«1 адрес», «2 адреса», «5 адресов»), и без этого фильтра витрина писала
«1 адреса» и «5 адреса», стоило сети вырасти или сжаться на одну точку.
"""

from django import template

register = template.Library()


@register.filter
def ru_plural(value, forms: str) -> str:
    """`{{ n|ru_plural:"адрес,адреса,адресов" }}` — форма под число."""
    one, few, many = (form.strip() for form in forms.split(","))
    try:
        n = abs(int(value))
    except (TypeError, ValueError):
        return many

    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


@register.filter
def tel_href(phone) -> str:
    """Номер для `href="tel:…"`: только цифры и ведущий плюс.

    В `.env` телефон записан для людей — «+7 (499) 123-45-67». Скобки и
    пробелы в `tel:` RFC 3966 не разрешает, и часть звонилок (десктопные
    клиенты, некоторые оболочки Android) такую ссылку не набирает.
    """
    raw = str(phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return ("+" if raw.startswith("+") else "") + digits


@register.filter
def ru_before(minutes) -> str:
    """Срок «за …» из минут настройки: 60 → «час», 120 → «2 часа», 90 → «90 минут».

    Обещания на витрине («напомним за 2 часа», «отмена не позже чем за
    час») берутся из тех же `BOOKING_*`, по которым работает сервер. Иначе
    стоит поменять срок в `.env`, и сайт начинает обещать то, чего система
    уже не делает.
    """
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return ""
    if minutes == 60:
        return "час"
    if minutes and minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} {ru_plural(hours, 'час,часа,часов')}"
    return f"{minutes} {ru_plural(minutes, 'минуту,минуты,минут')}"

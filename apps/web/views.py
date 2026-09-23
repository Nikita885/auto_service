"""Страницы сайта.

Сайт — витрина, а не приложение: записываются клиенты в мобильных
приложениях или по телефону. Поэтому лендинг рендерится на сервере и
работает без JavaScript, а живой JS остаётся только там, где без него
никак — в рабочих панелях сотрудников.
"""

import hashlib
import json

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from apps.catalog.models import Oil, ServicePoint
from apps.common.exceptions import NotFoundError
from apps.referral.services import tree as referral_tree


class CompanyMixin:
    """Название и контакты компании в контекст любой страницы сайта.

    Шапка и заголовок вкладки одинаковые на всех трёх страницах, а брать
    название из `.env` и подставлять его руками в каждом шаблоне — верный
    способ однажды переименовать компанию только на двух из них.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["company"] = settings.COMPANY
        return context


class LandingView(CompanyMixin, TemplateView):
    """Главная: о компании, цены, адреса, ссылки на приложения и телефон."""

    template_name = "web/landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["points"] = ServicePoint.objects.filter(is_active=True)
        # Прайс на витрине — справочные цены, без остатков: наличие на
        # конкретной точке клиент увидит в приложении, когда будет выбирать.
        context["oils"] = Oil.objects.filter(is_active=True).order_by("price")
        # Сроки, которые витрина обещает клиенту, — из тех же настроек, по
        # которым работает сервер. Напоминание обещаем, только если такие
        # SMS вообще отправляются: их можно выключить в SMS_ENABLED_KINDS.
        context["booking"] = settings.BOOKING
        context["reminder_enabled"] = "booking_reminder" in settings.SMS["ENABLED_KINDS"]
        return context


class MasterView(CompanyMixin, TemplateView):
    """Рабочее место мастера: записи в реальном времени, действия по ним."""

    template_name = "web/staff.html"


class AdminView(CompanyMixin, TemplateView):
    """Панель администратора: то же, что у мастера, плюс метрики по сети.

    Отдельный URL, а не флаг: администратору открывается вкладка аналитики,
    а мастеру она и не нужна, и не доступна — `/api/v1/master/metrics/`
    пускает только роль `admin`.
    """

    template_name = "web/admin.html"


class InviteView(CompanyMixin, TemplateView):
    """Страница по ссылке-приглашению: `/i/<код>`.

    Ссылку пересылают в мессенджер, и открыть её могут где угодно — с
    установленным приложением, без него, с айфона, с компьютера. Поэтому
    страница не пытается никуда перенаправлять: она показывает код,
    который человек введёт в приложении сам. На Android с настроенными
    App Links до неё дело обычно не дойдёт — система откроет приложение.

    Неизвестный код не 404: ссылка могла скопироваться не целиком, и
    объяснить это полезнее, чем показать страницу ошибки.
    """

    template_name = "web/invite.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        code = (self.kwargs.get("code") or "").strip().upper()
        context["code"] = code

        try:
            node = referral_tree.find_by_code(code)
        except NotFoundError:
            context["found"] = False
            return context

        context["found"] = True
        # Наружу только имя: по коду не должно быть видно ни телефона
        # пригласившего, ни размера его ветки.
        context["inviter_name"] = node.user.full_name or "Клиент"
        return context


@require_GET
def android_assetlinks(request):
    """`/.well-known/assetlinks.json` — без него Android App Links не
    работают: система проверяет, что домен признаёт это приложение своим.

    Отпечаток подписи лежит в `.env`, а не в коде: у отладочной и релизной
    сборки он разный, ключ ещё может смениться, а выкатка ради одной
    строки — лишний повод уронить сайт. Пока отпечаток не задан, отдаём
    404: пустой или выдуманный файл Android молча считает провалом
    проверки, и отлаживать это потом очень неприятно.
    """
    android = settings.ANDROID_APP
    if not android["FINGERPRINTS"]:
        raise Http404

    return JsonResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": android["PACKAGE"],
                    "sha256_cert_fingerprints": android["FINGERPRINTS"],
                },
            }
        ],
        safe=False,
    )


# ------------------------------------------------------------ веб-приложение
#: Модули и файлы веб-приложения. Одним списком для трёх мест: карта
#: импорта на странице, предзагрузка в service worker и версия его кеша.
APP_MODULES = {
    "preact": "web/app/vendor/preact-htm.js",
    "app/lib": "web/app/lib.js",
    "app/auth": "web/app/auth.js",
    "app/booking": "web/app/booking.js",
    "app/bookings": "web/app/bookings.js",
    "app/bonus": "web/app/bonus.js",
    "app/profile": "web/app/profile.js",
    "app/main": "web/app/main.js",
}
APP_ASSETS = (
    "web/css/app.css",
    "web/app/app.css",
    "web/js/core.js",
    "web/app/vendor/qrcode.js",
    "web/app/icons/apple-touch-icon.png",
    *APP_MODULES.values(),
)


def _app_urls() -> dict:
    """Адреса модулей с хешем в имени (в проде) — для карты импорта.

    Относительный `import "./lib.js"` внутри модуля ушёл бы на имя без
    хеша, а nginx отдаёт `/static/` с годовым `immutable`: обновление
    никогда не доехало бы до телефона, который уже открывал приложение.
    """
    return {name: static(path) for name, path in APP_MODULES.items()}


class ClientAppView(CompanyMixin, TemplateView):
    """Веб-приложение клиента для iPhone: `/app/`.

    Те же экраны, что в приложении под Android, поверх того же API. Для
    iPhone без App Store: Safari предлагает «На экран „Домой“», и дальше
    оно запускается на весь экран с иконкой, как обычное приложение.
    """

    template_name = "web/app.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Адреса — наши собственные пути из {% static %}, экранировать в них
        # нечего; json.dumps всё равно экранирует «</» не хуже шаблона.
        context["import_map_json"] = json.dumps(
            {"imports": _app_urls()}, ensure_ascii=False
        ).replace("</", r"<\/")
        company = settings.COMPANY
        context["app_config"] = {
            "company": company["NAME"],
            "phone": company["PHONE"],
            "siteUrl": company["SITE_URL"],
            "swUrl": reverse("web:app-sw"),
            "icon": static("web/app/icons/icon-192.png"),
            "draftTtl": settings.BOOKING["DRAFT_TTL_SECONDS"],
            "cancelDeadline": settings.BOOKING["CANCEL_DEADLINE_MINUTES"],
            "maxDiscount": settings.REFERRAL["MAX_DISCOUNT_PERCENT"],
        }
        return context


@require_GET
def app_manifest(request):
    """Манифест: имя, иконки и то, что приложение открывается без рамки браузера."""
    company = settings.COMPANY
    icons = [
        {"src": static("web/app/icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
        {"src": static("web/app/icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
        {
            "src": static("web/app/icons/maskable-512.png"),
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ]
    return JsonResponse(
        {
            "name": company["NAME"],
            "short_name": company["NAME"],
            "description": company["TAGLINE"],
            "lang": "ru",
            "start_url": "/app/",
            "scope": "/app/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#030b14",
            "theme_color": "#030b14",
            "icons": icons,
        },
        content_type="application/manifest+json",
        json_dumps_params={"ensure_ascii": False},
    )


@require_GET
def app_service_worker(request):
    """Service worker веб-приложения.

    Отдаётся из `/app/`, а не из `/static/`: область действия воркера — его
    собственный путь, и из `/static/` он не видел бы страницу приложения.
    Кешировать сам файл браузеру нельзя — иначе новая версия не установится.
    """
    assets = [static(path) for path in APP_ASSETS]
    # Версия кеша меняется, когда меняется хоть один файл: в проде у них
    # в именах хеш содержимого.
    version = hashlib.sha256("|".join(assets).encode()).hexdigest()[:12]
    body = render_to_string("web/app_sw.js", {"assets": assets, "version": version})
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/app/"
    response["Cache-Control"] = "no-cache"
    return response

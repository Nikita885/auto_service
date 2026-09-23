"""Страницы сайта.

Сайт — витрина, а не приложение: записываются клиенты в мобильных
приложениях или по телефону. Поэтому лендинг рендерится на сервере и
работает без JavaScript, а живой JS остаётся только там, где без него
никак — в рабочих панелях сотрудников.
"""

from django.conf import settings
from django.http import Http404, JsonResponse
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

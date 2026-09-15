"""Страницы сайта.

Сайт — витрина, а не приложение: записываются клиенты в мобильных
приложениях или по телефону. Поэтому лендинг рендерится на сервере и
работает без JavaScript, а живой JS остаётся только там, где без него
никак — в рабочих панелях сотрудников.
"""

from django.conf import settings
from django.views.generic import TemplateView

from apps.catalog.models import Oil, ServicePoint


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

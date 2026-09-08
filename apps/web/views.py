from django.views.generic import TemplateView


class ClientView(TemplateView):
    """Сайт для клиента: витрина, вход по SMS и запись на замену масла."""

    template_name = "web/client.html"


class MasterView(TemplateView):
    """Рабочее место мастера: записи за день, действия по ним, живые черновики."""

    template_name = "web/staff.html"


class AdminView(TemplateView):
    """Панель администратора: то же, что у мастера, плюс метрики по сети.

    Шаблон один и тот же слой данных, но отдельный URL: администратору
    открывается вкладка аналитики, а мастеру она не нужна и не доступна —
    `/api/v1/master/metrics/` пускает только роль `admin`.
    """

    template_name = "web/admin.html"

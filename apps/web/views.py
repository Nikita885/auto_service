from django.views.generic import TemplateView


class ClientDemoView(TemplateView):
    """Голая страница для ручной проверки клиентского сценария."""

    template_name = "web/client.html"


class MasterDemoView(TemplateView):
    """Голая страница для проверки панели мастера."""

    template_name = "web/master.html"

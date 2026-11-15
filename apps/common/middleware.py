class SecurityHeadersMiddleware:
    """Ограничивает встраивание и источники ресурсов, включая Android WebView."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import secrets
        from urllib.parse import urlsplit

        from django.conf import settings

        request.csp_nonce = secrets.token_urlsafe(24)
        response = self.get_response(request)
        host = urlsplit(settings.COMPANY["SITE_URL"]).netloc
        # Собственные шаблоны и importmap используют уникальный nonce.
        # Админка/Swagger поставляются сторонними шаблонами отдельно.
        scripts = "'self' 'nonce-" + request.csp_nonce + "'"
        styles = "'self' 'unsafe-inline'"
        if request.path.startswith(("/admin/", "/api/docs/", "/api/redoc/")):
            scripts = "'self' 'unsafe-inline' https://cdn.jsdelivr.net"
        if request.path.startswith(("/api/docs/", "/api/redoc/")):
            styles += " https://cdn.jsdelivr.net"
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src " + scripts + "; "
            "style-src " + styles + "; img-src 'self' data: blob:; "
            "font-src 'self'; connect-src 'self' wss://" + host + "; "
            "frame-src 'none'; frame-ancestors 'none'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; worker-src 'self'"
        )
        response["Referrer-Policy"] = "same-origin"
        response["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if request.path != "/app/sw.js" and request.path.startswith(
            ("/api/", "/app/", "/master/", "/admin-panel/", "/admin/"),
        ):
            response["Cache-Control"] = "no-store"
        return response

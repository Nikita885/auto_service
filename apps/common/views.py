from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health_view(request):
    """Liveness/readiness для docker/k8s и мониторинга."""
    checks = {"db": False, "cache": False}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["db"] = True
    except Exception:  # pragma: no cover - зависит от инфраструктуры
        pass

    try:
        from django.core.cache import cache

        cache.set("healthcheck", "ok", 5)
        checks["cache"] = cache.get("healthcheck") == "ok"
    except Exception:  # pragma: no cover
        pass

    ok = all(checks.values())
    return JsonResponse({"status": "ok" if ok else "degraded", "checks": checks},
                        status=200 if ok else 503)

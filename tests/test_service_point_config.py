"""Настройки точки: пояс и рабочие дни не должны ронять запись.

На боевом сервере точку завели с поясом «Yekaterinburg Time» (так его
зовёт Windows) и рабочими днями `2` — и выбор времени отдавал 500 на
каждом запросе.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as registry
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.catalog.admin import ServicePointForm
from apps.catalog.models import ServicePoint, normalize_timezone

pytestmark = pytest.mark.django_db

BROKEN = {"timezone": "Yekaterinburg Time", "workdays": 2}


def break_point(point):
    ServicePoint.objects.filter(pk=point.pk).update(**BROKEN)
    point.refresh_from_db()
    return point


def test_slots_survive_broken_point_settings(auth, client_user, point):
    """Испорченные данные — запись всё равно работает, а не отдаёт 500."""
    break_point(point)
    api = auth(client_user)

    days = api.get(reverse("v1:booking:point-slots", args=[point.pk]))

    assert days.status_code == 200
    assert days.data["available_days"]
    # Пояс угадан по названию: «Yekaterinburg Time» — это UTC+5.
    assert str(point.tz) == "Asia/Yekaterinburg"


def test_migration_repairs_stored_values(point):
    break_point(point)
    migration = importlib.import_module(
        "apps.catalog.migrations.0003_service_point_timezone_workdays"
    )

    migration.repair_points(registry, None)

    point.refresh_from_db()
    assert point.timezone == "Asia/Yekaterinburg"
    assert point.workdays == []  # «каждый день», как «Ежедневно» на витрине


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Asia/Yekaterinburg", "Asia/Yekaterinburg"),
        ("Yekaterinburg Time", "Asia/Yekaterinburg"),
        ("Челябинск", "Asia/Yekaterinburg"),
        ("Russian Standard Time", "Europe/Moscow"),
        ("Марс", None),
    ],
)
def test_normalize_timezone(raw, expected):
    assert normalize_timezone(raw) == expected


def test_model_rejects_unknown_timezone(point):
    point.timezone = "Yekaterinburg Time"
    with pytest.raises(ValidationError):
        point.full_clean()


def test_admin_form_takes_workdays_as_checkboxes(point):
    data = {
        "name": point.name, "address": point.address, "phone": "",
        "timezone": "Asia/Yekaterinburg", "opens_at": "09:00", "closes_at": "21:00",
        "workdays": ["4", "0", "2"], "slot_minutes": 40, "posts_count": 2, "is_active": "on",
    }
    form = ServicePointForm(data=data, instance=point)

    assert form.is_valid(), form.errors
    assert form.save().workdays == [0, 2, 4]


def test_security_audit_flags_broken_point(point):
    from apps.common.management.commands.security_audit import FAIL, _check_service_points

    break_point(point)
    findings = _check_service_points()

    assert findings[0].level == FAIL
    assert "часовой пояс" in findings[0].detail
    assert "рабочие дни" in findings[0].detail

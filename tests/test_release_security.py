"""Регрессии отзыва сессий, удаления данных и публичного каталога."""

import uuid

import pytest
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.deletion import process_deletion
from apps.accounts.models import AccountDeletionRequest, User
from apps.assistant.models import AssistantRequest
from apps.assistant.services import assistant
from apps.garage.models import Car

pytestmark = pytest.mark.django_db


def test_logout_revokes_refresh_and_is_idempotent(api, client_user):
    refresh = str(RefreshToken.for_user(client_user))
    for _ in range(2):
        assert api.post("/api/v1/auth/logout/", {"refresh": refresh}).status_code == 204
    assert api.post("/api/v1/auth/token/refresh/", {"refresh": refresh}).status_code == 401


def test_deletion_requires_authenticated_client_and_confirmation(api, auth, client_user):
    url = "/api/v1/auth/account/deletion/"
    assert api.post(url, {"confirm": True}, format="json").status_code == 401
    client = auth(client_user)
    assert client.post(url, {}, format="json").status_code == 400
    for _ in range(2):
        assert client.post(url, {"confirm": True}, format="json").status_code == 202
    assert AccountDeletionRequest.objects.filter(user=client_user).count() == 1


def test_processed_deletion_removes_garage_and_blocks_old_sessions(auth, client_user):
    Car.objects.create(user=client_user, title="Kia", plate="А123ВС")
    old_phone = client_user.phone
    refresh = str(RefreshToken.for_user(client_user))
    item = AccountDeletionRequest.objects.create(user=client_user)
    process_deletion(item.pk)
    client_user.refresh_from_db()
    assert not client_user.is_active and client_user.phone != old_phone
    assert not Car.objects.filter(user=client_user).exists()
    with pytest.raises(TokenError):
        RefreshToken(refresh)
    assert process_deletion(item.pk).processed_at is not None


def test_landing_uses_services_and_hides_prices(client, service):
    service.show_on_landing = True
    service.save(update_fields=["show_on_landing"])
    html = client.get("/").content.decode()
    assert 'id="services"' in html and service.name in html
    assert 'id="oils"' not in html
    assert "₽" not in html


def test_unpublished_services_stay_off_the_landing(client, service):
    html = client.get("/").content.decode()
    assert service.name not in html


def test_public_privacy_and_deletion_pages_work_without_account(client):
    for path in ("/privacy/", "/delete-account/"):
        response = client.get(path)
        assert response.status_code == 200
        assert "МойАвтоСервис" in response.content.decode()


def test_app_has_nonce_csp_and_denies_foreign_frames(client):
    response = client.get("/app/")
    policy = response["Content-Security-Policy"]
    scripts = policy.split("script-src ")[1].split(";")[0]
    assert "'nonce-" in scripts and "unsafe-inline" not in scripts
    assert "frame-src 'none'" in policy
    assert response["Cache-Control"] == "no-store"


def test_pending_assistant_request_reserves_daily_quota(auth, client_user, point, settings):
    settings.ASSISTANT = {**settings.ASSISTANT, "MESSAGES_PER_DAY": 1}
    AssistantRequest.objects.create(user=client_user, service_point=point,
                                    chat=uuid.uuid4(), provider="fake", error="pending")
    result = assistant.ask(client_user, point.pk, message="Нужна помощь")
    assert result.handoff == "daily_limit"


def test_feedback_cannot_target_another_users_chat(auth, client_user, point):
    result = auth(client_user).post("/api/v1/assistant/report/", {
        "chat": str(uuid.uuid4()), "text": "Проблемный ответ",
    }, format="json")
    assert result.status_code == 404


def test_new_master_without_assignments_has_no_network_access(point):
    master = User.objects.create_master(phone="+79001239876")
    assert master.accessible_point_ids() == []
    master.service_points.add(point)
    assert master.accessible_point_ids() == [point.pk]


def test_deleted_user_cannot_restore_profile_with_stale_instance(client_user):
    from apps.accounts import services
    from apps.common.exceptions import PermissionError_

    item = AccountDeletionRequest.objects.create(user=client_user)
    process_deletion(item.pk)
    with pytest.raises(PermissionError_):
        services.update_profile(client_user, full_name="Данные после удаления")

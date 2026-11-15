"""Удаление клиентских данных с сохранением обезличенного журнала расчётов."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import AccountDeletionRequest, OtpCode, User
from apps.common.exceptions import ConflictError


@transaction.atomic
def process_deletion(request_id):
    from apps.assistant.models import AssistantFeedback, AssistantRequest
    from apps.booking.models import (
        Booking,
        BookingCall,
        BookingDraft,
        BookingPriceChange,
        BookingStatusLog,
    )
    from apps.garage.models import Car
    from apps.notifications.models import Notification
    from apps.onec.models import BookingSync, WorkplaceOrder

    item = AccountDeletionRequest.objects.select_for_update().get(pk=request_id)
    if item.processed_at:
        return item
    user = User.objects.select_for_update().get(pk=item.user_id)
    if not user.is_client:
        raise ConflictError("Удаление через этот процесс доступно только клиенту")
    bookings = Booking.objects.select_for_update().filter(user=user)
    # Сначала завершить обслуживание и сверить оборудование. Запрос при
    # этом остаётся в очереди; администратор согласовывает его с клиентом.
    if bookings.filter(status__in=["pending", "in_progress"]).exists():
        raise ConflictError("Сначала завершите или отмените активные записи клиента")
    if WorkplaceOrder.objects.filter(booking__user=user).exclude(state="completed").exists():
        raise ConflictError("Сначала завершите сверку расчётов в 1С")

    phone = user.phone
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
    OutstandingToken.objects.filter(user=user).update(token="")
    BookingDraft.objects.filter(user=user).delete()
    Car.objects.filter(user=user).delete()
    AssistantFeedback.objects.filter(request__user=user).delete()
    AssistantRequest.objects.filter(user=user).delete()
    OtpCode.objects.filter(phone=phone).delete()
    Notification.objects.filter(Q(user=user) | Q(phone=phone)).delete()
    BookingCall.objects.filter(client=user).delete()
    BookingStatusLog.objects.filter(booking__user=user).update(comment="")
    BookingPriceChange.objects.filter(booking__user=user).update(reason="")
    BookingSync.objects.filter(booking__user=user).update(last_error="")
    bookings.update(client_name="", client_phone="", car_model="", car_plate="",
                    client_comment="", cancel_reason="")
    user.full_name = "Удалённый аккаунт"
    user.phone = "del-" + user.pk.hex[:16]
    user.is_active = False
    user.set_unusable_password()
    user.save(update_fields=["full_name", "phone", "is_active", "password"])
    item.processed_at = timezone.now()
    item.note = (
        "Профиль, гараж, дневник и контактные данные удалены. "
        "Сохранены обезличенные записи расчётов и обязательные финансовые документы. "
        "Удаление в 1С, у провайдеров и ротация резервных копий проверяются оператором отдельно."
    )
    item.save(update_fields=["processed_at", "note"])
    return item

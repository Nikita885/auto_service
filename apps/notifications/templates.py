"""Тексты сообщений.

Собраны в одном месте: SMS читает клиент, и формулировки правят не
программисты. Держать их внутри сервисов — гарантированный способ
получить пять разных вариантов одной и той же фразы.
"""

from __future__ import annotations


def _when(booking) -> str:
    local = booking.local_start()
    return local.strftime("%d.%m в %H:%M")


def otp(code: str) -> str:
    return f"Код для входа: {code}. Никому его не сообщайте."


def booking_created(booking) -> str:
    return (
        f"Вы записаны на замену масла {_when(booking)}. "
        f"Адрес: {booking.service_point.address}. "
        f"Масло: {booking.oil_title}. Код записи: {booking.code}."
    )


def booking_reminder(booking) -> str:
    return (
        f"Напоминаем: замена масла сегодня {_when(booking)}, "
        f"{booking.service_point.address}. Код записи: {booking.code}."
    )


def booking_cancelled_by_master(booking) -> str:
    reason = f" Причина: {booking.cancel_reason}." if booking.cancel_reason else ""
    return (
        f"Ваша запись {_when(booking)} отменена сервисом.{reason} "
        f"Извините за неудобство, вы можете записаться на другое время."
    )


def booking_completed(booking) -> str:
    return (
        f"Замена масла выполнена. Спасибо, что выбрали нас! "
        f"Сумма: {booking.total_price:.0f} ₽."
    )

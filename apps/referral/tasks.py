from celery import shared_task

from apps.referral.services import points as points_service


@shared_task(name="apps.referral.tasks.settle_referral_payouts")
def settle_referral_payouts() -> int:
    """Свести плечи за все закончившиеся сутки.

    Запускается каждые пять минут, а работу находит только после полуночи
    по времени выплат: остальные запуски ничего не делают. Повторный запуск
    безопасен — сутки участника сводятся один раз (`uniq_settlement_per_day`).
    """
    return points_service.settle_due_days()

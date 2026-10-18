"""Мост из масел в услуги — на уровне моделей, а не только панели мастера.

Пока старый раздел «Масла и склад» жив, цена, «в продаже» и остаток
масла лежат в двух местах: `Oil`/`OilStock` и `Service`. Раньше мост
вызывала панель мастера, и всё, что правило масла в обход неё —
Django-админка, shell, тесты, — оставляло услуги со старыми цифрами:
клиент видел бы прежнюю цену и чужой остаток, и ни одной ошибки.

Сигнал стоит на моделях, поэтому ловит любую точку входа. Логика — в
`services/oils.py::mirror_oil`, здесь только проводка. Уйдёт вместе со
старым разделом масел.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.catalog.models import Oil, OilStock
from apps.catalog.services.oils import mirror_oil


@receiver(post_save, sender=Oil, dispatch_uid="catalog.mirror_oil")
def oil_saved(sender, instance: Oil, raw: bool = False, **kwargs) -> None:
    # `raw` — загрузка фикстур: связанных объектов ещё может не быть.
    if not raw:
        mirror_oil(instance)


@receiver(post_save, sender=OilStock, dispatch_uid="catalog.mirror_oil_stock")
def stock_saved(sender, instance: OilStock, raw: bool = False, **kwargs) -> None:
    if not raw:
        mirror_oil(
            instance.oil,
            quantity_by_point={instance.service_point_id: instance.quantity},
        )

"""Масла становятся услугами категории «Замена масла» — на каждой точке своей.

Каталог у каждой точки свой (решение заказчика), а масла до сих пор были
общими на сеть с остатком по точкам. Поэтому каждая позиция масла
превращается в услугу **на каждой точке**: остаток берётся из
`OilStock` этой точки, а где строки остатка не было — ноль. Создаём
услугу даже с нулевым остатком: раньше масло было видно в общем каталоге
с нулём, и мастер второй точки не должен обнаружить, что половина
прайса пропала.

Цена услуги — одной суммой (решение заказчика): `price` = цена канистры
плюс работа, `material_price` = цена канистры. Разбивка «материал и
работа» в метриках и база баллов в режиме `REFERRAL_BASE=work` считаются
из этой пары и не меняются.

Название услуги повторяет `Oil.__str__` символ в символ: ровно эта строка
лежит снимком в уже созданных записях (`Booking.oil_title`), и история
не должна разойтись с каталогом. Функция повторена здесь, а не
импортирована: миграция обязана работать так же и через год, когда код
сервиса изменится.

Обратно: услуги, выросшие из масел, удаляются вместе с опустевшими
категориями «Замена масла». Услуги, которые мастер завёл сам, и их
категории остаются — откат не должен уносить чужую работу. Позиции
записей к этому моменту уже удалены: `booking.0007` зависит от этой
миграции и откатывается раньше.
"""

from django.db import migrations

CATEGORY_NAME = "Замена масла"
#: Порядок показа: «Замена масла» — первая категория у всех точек.
CATEGORY_ORDER = 10
#: Вид для дневника водителя: только он двигает напоминание о масле.
JOURNAL_KIND_OIL = "oil"


def _title(oil) -> str:
    """Название услуги = то, как масло называется в записях и в панели."""
    return f"{oil.brand} {oil.name} {oil.viscosity}, {oil.volume_liters} л"


def forward(apps, schema_editor):
    ServicePoint = apps.get_model("catalog", "ServicePoint")
    Oil = apps.get_model("catalog", "Oil")
    OilStock = apps.get_model("catalog", "OilStock")
    ServiceCategory = apps.get_model("catalog", "ServiceCategory")
    Service = apps.get_model("catalog", "Service")

    oils = list(Oil.objects.all())
    if not oils:
        # Пустой каталог масел — переносить нечего, и пустая категория
        # на каждой точке только мешала бы мастеру.
        return

    for point in ServicePoint.objects.all().iterator():
        category, _ = ServiceCategory.objects.get_or_create(
            service_point=point,
            name=CATEGORY_NAME,
            defaults={
                "sort_order": CATEGORY_ORDER,
                "is_active": True,
                # Внутри масел «подберите на месте» и придумано: клиент не
                # знает вязкость, мастер перезванивает и выбирает.
                "allow_on_site": True,
                "journal_kind": JOURNAL_KIND_OIL,
            },
        )
        quantity_by_oil = dict(
            OilStock.objects.filter(service_point=point).values_list("oil_id", "quantity")
        )
        for oil in oils:
            # get_or_create, а не bulk_create: миграцию могут прогнать
            # второй раз (например, после отката), и дублей быть не должно.
            Service.objects.get_or_create(
                category=category,
                name=_title(oil),
                defaults={
                    "price": oil.price + oil.work_price,
                    "material_price": oil.price,
                    # Канистры кончаются — остаток ведём.
                    "is_limited": True,
                    "quantity": quantity_by_oil.get(oil.pk, 0),
                    "is_active": oil.is_active,
                    "oil_id": oil.pk,
                    "description": oil.description,
                },
            )


def backward(apps, schema_editor):
    ServiceCategory = apps.get_model("catalog", "ServiceCategory")
    Service = apps.get_model("catalog", "Service")

    Service.objects.filter(oil__isnull=False).delete()
    # Категорию удаляем только если в ней не осталось услуг: мастер мог
    # завести в «Замене масла» что-то своё, и это не наше дело.
    ServiceCategory.objects.filter(name=CATEGORY_NAME, services__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0004_services"),
    ]

    operations = [migrations.RunPython(forward, backward)]

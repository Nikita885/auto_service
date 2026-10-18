"""Записи и черновики переезжают с масла на услуги.

Каждая запись с маслом получает позицию чека (`BookingItem`) с той же
суммой, что была в записи, и снимок категории. Записи «подберите на
месте» позиций не получают — у них только категория и флаг
`service_on_site`: именно по нему мастер видит в очереди звонков, что
услугу ещё предстоит подобрать.

Цены не пересчитываются: `price` позиции — это `total_price` записи
(канистра плюс работа на момент брони), `material_price` — цена
канистры. Итог записи, правка итога мастером и списанные баллы не
трогаются вовсе.

Старые поля (`Booking.oil`, `oil_title`, `oil_price`, `BookingDraft.oil`,
`oil_on_site`) остаются на месте и не читаются новым кодом — их удалит
отдельная выкатка, когда перенос отстоится на живой базе.

Обратно: позиции удаляются, а записям, созданным уже новым кодом,
восстанавливаются поля масла — если их услуга выросла из масла. Запись
на мойку в поля масла не ложится: `oil` у неё останется пустым, и старый
код прочитает её как «подберут на месте», а название услуги будет видно
в `oil_title`. Это осознанная потеря точности при откате назад — другой
формы для «услуги, которой не было» в старой схеме нет.
"""

from django.db import migrations

CATEGORY_NAME = "Замена масла"
BATCH = 500


def forward(apps, schema_editor):
    Booking = apps.get_model("booking", "Booking")
    BookingItem = apps.get_model("booking", "BookingItem")
    BookingDraft = apps.get_model("booking", "BookingDraft")
    ServiceCategory = apps.get_model("catalog", "ServiceCategory")
    Service = apps.get_model("catalog", "Service")

    categories = {
        row.service_point_id: row
        for row in ServiceCategory.objects.filter(name=CATEGORY_NAME)
    }
    # Услуга, выросшая из масла, однозначна парой «точка + масло»:
    # каталог у каждой точки свой.
    services = {
        (row.category.service_point_id, row.oil_id): row
        for row in Service.objects.filter(oil__isnull=False).select_related("category")
    }

    items: list = []
    updated: list = []
    # Записи, у которых позиций ещё нет: повторный прогон не плодит дублей.
    bookings = (
        Booking.objects.filter(items__isnull=True)
        .only(
            "id", "service_point_id", "oil_id", "oil_title", "oil_price",
            "work_price", "total_price",
        )
        .order_by("created_at")
    )
    for booking in bookings.iterator(chunk_size=BATCH):
        category = categories.get(booking.service_point_id)
        booking.service_category_id = category.pk if category else None
        booking.category_title = CATEGORY_NAME if category else ""
        booking.service_title = booking.oil_title
        booking.material_price = booking.oil_price
        booking.service_on_site = booking.oil_id is None
        updated.append(booking)

        service = services.get((booking.service_point_id, booking.oil_id))
        if booking.oil_id and service is not None:
            items.append(
                BookingItem(
                    booking_id=booking.pk,
                    service_id=service.pk,
                    title=booking.oil_title,
                    category_title=CATEGORY_NAME,
                    # Цена позиции — сумма записи на момент брони; правку
                    # итога мастером (`final_price`) не трогаем, она своя.
                    price=booking.total_price,
                    material_price=booking.oil_price,
                    quantity=1,
                )
            )
        # Услуги для этой пары нет только если масло или точку успели
        # удалить из базы в обход кода (ссылки защищены PROTECT). Снимок
        # всё равно заполнен, и старые поля никуда не делись, так что
        # запись читается — просто без позиции.

        if len(updated) >= BATCH:
            _flush(Booking, BookingItem, updated, items)

    _flush(Booking, BookingItem, updated, items)

    drafts = BookingDraft.objects.filter(service_point__isnull=False).only(
        "id", "service_point_id", "oil_id", "oil_on_site"
    )
    rows: list = []
    for draft in drafts.iterator(chunk_size=BATCH):
        # Категорию ставим только тем, кто дошёл до шага масла: по
        # заполненным полям черновика считается воронка записи, и шаг,
        # которого не было, не должен в ней появиться.
        if not (draft.oil_id or draft.oil_on_site):
            continue
        category = categories.get(draft.service_point_id)
        service = services.get((draft.service_point_id, draft.oil_id))
        draft.service_category_id = category.pk if category else None
        draft.service_id = service.pk if service else None
        draft.on_site = draft.oil_on_site
        rows.append(draft)
        if len(rows) >= BATCH:
            BookingDraft.objects.bulk_update(
                rows, ["service_category", "service", "on_site"]
            )
            rows.clear()
    if rows:
        BookingDraft.objects.bulk_update(rows, ["service_category", "service", "on_site"])


def _flush(Booking, BookingItem, updated: list, items: list) -> None:
    if updated:
        Booking.objects.bulk_update(
            updated,
            [
                "service_category", "category_title", "service_title",
                "material_price", "service_on_site",
            ],
        )
        updated.clear()
    if items:
        BookingItem.objects.bulk_create(items, batch_size=BATCH)
        items.clear()


def backward(apps, schema_editor):
    Booking = apps.get_model("booking", "Booking")
    BookingItem = apps.get_model("booking", "BookingItem")
    BookingDraft = apps.get_model("booking", "BookingDraft")

    restored: list = []
    rows = (
        BookingItem.objects.select_related("booking", "service")
        .filter(booking__oil__isnull=True)
        .order_by("booking_id", "created_at")
    )
    seen: set = set()
    for item in rows.iterator(chunk_size=BATCH):
        if item.booking_id in seen:
            continue  # у записи несколько услуг — в старую схему влезет первая
        seen.add(item.booking_id)
        booking = item.booking
        # Ссылка на услугу обязательна, так что масло достаём прямо из неё.
        booking.oil_id = item.service.oil_id
        booking.oil_title = item.title
        booking.oil_price = item.material_price
        # Количество больше одного в старую схему тоже не влезает: там одна
        # канистра на запись. Берём цену позиции как есть.
        booking.work_price = item.price - item.material_price
        restored.append(booking)
        if len(restored) >= BATCH:
            Booking.objects.bulk_update(
                restored, ["oil", "oil_title", "oil_price", "work_price"]
            )
            restored.clear()
    if restored:
        Booking.objects.bulk_update(restored, ["oil", "oil_title", "oil_price", "work_price"])

    # Позиции уходят целиком: следующей обратной операцией `0006` удаляет
    # и саму таблицу, а ссылка на услугу (`PROTECT`) не дала бы удалить
    # услуги в `catalog.0005`.
    BookingItem.objects.all().delete()

    # Ссылки на каталог снимаем здесь же. Откатить можно и один перенос,
    # оставшись на новой схеме, — тогда `catalog.0005` пойдёт удалять
    # услуги и категории. В его состоянии миграций полей `service` у
    # черновика и `service_category` у записи ещё нет, поэтому ни
    # SET_NULL, ни PROTECT не сработают, и удаление упрётся в внешний
    # ключ на уровне базы. Чистит их тот, кто про них знает.
    BookingDraft.objects.update(service_category=None, service=None, on_site=False)
    Booking.objects.update(
        service_category=None,
        category_title="",
        service_title="",
        material_price=0,
        service_on_site=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0006_booking_services"),
        # Услуги и категории уже созданы: позиции на них ссылаются.
        ("catalog", "0005_services_from_oils"),
    ]

    operations = [migrations.RunPython(forward, backward)]

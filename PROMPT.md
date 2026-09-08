# Контекст проекта для нового чата с ИИ-ассистентом

Этот файл нужен, чтобы начать работу в новой сессии, не пересказывая всё заново.

**Как использовать:** скопируйте весь текст ниже (от разделителя до конца файла)
и вставьте первым сообщением в новый чат. Дальше пишите свою задачу.

Если ассистент работает прямо в репозитории (Claude Code, Cursor и т. п.) —
достаточно короткого варианта в самом конце.

---

<!-- ▼▼▼ КОПИРОВАТЬ ОТСЮДА ▼▼▼ -->

Ты — senior backend-разработчик. Помогаешь мне развивать бэкенд сети автосервисов.
Отвечай по-русски. Ниже — полный контекст уже написанного проекта.

## 1. Что за проект

Backend-платформа для сети автосервисов с **одной услугой — замена масла**.
Одно API обслуживает три клиента:

- веб-сайт;
- мобильное приложение клиента;
- отдельное мобильное приложение мастера (вторая версия, ещё не написана).

Репозиторий: https://github.com/Nikita885/auto_service

## 2. Стек

| Слой | Технология |
|---|---|
| Фреймворк | Django 5.1 + Django REST Framework 3.15 |
| База | PostgreSQL 16 (psycopg 3) |
| Очереди | Celery 5.4 + Redis 7, django-celery-beat |
| Аутентификация | JWT, djangorestframework-simplejwt (access 60 мин, refresh 30 дней, ротация + blacklist) |
| Realtime | Django Channels 4 + channels-redis, ASGI-сервер Daphne |
| Документация | drf-spectacular (Swagger `/api/docs/`, ReDoc `/api/redoc/`) |
| Телефоны | phonenumbers (нормализация в E.164) |
| Инфраструктура | Docker Compose: api, worker, beat, db, redis |
| Тесты | pytest + pytest-django + factory-boy + freezegun |
| Линтер | ruff |
| Python | 3.12 (в контейнере) |

## 3. Бизнес-требования (исходные)

1. Клиент регистрируется/входит **по номеру телефона без пароля**, через SMS-код.
2. Записывается в четыре шага: **адрес (их 2) → масло из наличия → свободное
   время → подтверждение**.
3. **Как только клиент начал записываться, создаётся объект состояния**, по
   которому в реальном времени видно, на каком он шаге и что уже выбрал.
4. На всю процедуру у клиента **5 минут** с момента начала. Не успел — запись
   удаляется, начинать заново.
5. Клиент может **отменить свою бронь**.
6. **Приложение мастера**: видит записи, имя клиента и выбранное масло, может
   удалить/отменить запись с последующим уведомлением клиента.

## 4. Что уже сделано (всё работает и проверено)

Серверная часть **готова полностью**, поверх неё работает веб-интерфейс.
65 тестов зелёные, ruff чистый, OpenAPI генерируется без предупреждений,
сквозной сценарий прогнан по живому HTTP.

### Реализовано

- Вход по телефону + SMS-код, без пароля. Нормализация телефона в E.164.
  Код хранится только хешем. Лимиты: пауза 60 сек между отправками, 5 кодов на
  номер в час, 5 попыток ввода, TTL кода 5 минут.
- Пошаговая запись с черновиком на 5 минут и удержанием слота и канистры масла.
- Статус в реальном времени через WebSocket + REST-эндпоинт как запасной вариант.
- Отмена брони клиентом (не позже чем за час до визита).
- API приложения мастера: список записей, фильтры, поиск, отмена с обязательной
  причиной и автоматическим SMS клиенту, статусы работы, сводка за день,
  список записывающихся прямо сейчас.
- Склад масла с резервированием и списанием при завершении работ.
- Журнал уведомлений, SMS через Celery, абстракция SMS-провайдера.
- Метрики администратора: выручка, средний чек, доли отмен и неявок, воронка
  записи, динамика по дням, загрузка по часам, точки, ходовые масла, склад,
  клиентская база. Права — отдельный `IsAdmin`, мастеру закрыто.
- Django-админка, healthcheck, демо-данные при первом старте.
- Веб-интерфейс на чистых HTML/CSS/JS: сайт клиента `/`, рабочее место мастера
  `/master/`, панель администратора с метриками `/admin-panel/`. Светлая и тёмная
  темы, адаптив, обновление access-токена, WebSocket на клиентской странице.

### Чего ещё нет

- Мобильных приложений (ни клиента, ни мастера) — только API под них.
- Push-уведомлений (только SMS; поле `channel` в модели уже есть).
- Онлайн-оплаты.
- CI/CD.
- Второй услуги кроме замены масла.

## 5. Структура кода

```
config/
  settings/base.py|dev.py|prod.py|test.py    настройки + все бизнес-параметры
  urls.py, asgi.py, celery.py, routing.py

apps/
  common/          BaseModel, доменные исключения, permissions, phone.py, ws_auth.py
  accounts/        User (логин = телефон), OtpCode, вход, профиль
  catalog/         ServicePoint, Oil, OilStock
  booking/         ЯДРО: BookingDraft, Booking, BookingStatusLog
    services/      draft.py, booking.py, slots.py, stock.py  ← вся бизнес-логика
    consumers.py   WebSocket
    events.py      публикация событий
    tasks.py       Celery
  master/          API приложения мастера
    metrics.py     расчёт сводной аналитики для администратора
  notifications/   журнал + SMS-провайдеры (console / http_gateway)
  web/             веб-интерфейс: templates/web/*.html + static/web/{css,js}

tests/             conftest.py + test_auth.py + test_draft_flow.py + test_master.py
                   + test_metrics.py
```

## 6. Архитектурные правила — их важно соблюдать

1. **Вьюхи тонкие.** View разбирает вход сериализатором, зовёт функцию из
   `services/`, отдаёт результат. Бизнес-`if`-ов во вьюхах нет ни одного.
2. **Бизнес-логика только в `services/`.** ORM-запросы на запись за пределами
   сервисного слоя — повод развернуть ревью.
3. **Сервисы не знают про HTTP.** Они бросают доменные исключения из
   `apps/common/exceptions.py` (`ConflictError`, `GoneError`, `NotFoundError`,
   `ValidationError`, `RateLimitError`, `PermissionError_`). Превращение в
   HTTP-ответ — ровно в одном месте, `api_exception_handler`.
4. **Единый формат ошибки:**
   `{"error": {"code": "slot_taken", "message": "…", "details": {}}}`.
   Клиент разбирает машиночитаемый `code`, а не текст.
5. **Бизнес-параметры — в `settings.BOOKING` / `settings.OTP`**, читаются из `.env`.
   Никаких магических чисел в коде.
6. **Всё время в базе — UTC.** Локальное время берётся из `ServicePoint.timezone`.
7. **Переходы статусов записи — только через `_transition`** в
   `apps/booking/services/booking.py`: она проверяет допустимость, пишет историю
   и шлёт события.
8. **Уведомления и WebSocket-события — через `transaction.on_commit`**, чтобы не
   отправить SMS о записи, которая откатилась.
9. Комментарии в коде объясняют **почему**, а не что. Язык комментариев — русский.

## 7. Ключевые технические решения и их причины

- **Слоты не хранятся в БД.** Свободное время вычисляется на лету из графика точки
  (`slots.py`). Таблица слотов потребовала бы генерации вперёд, чистки и
  синхронизации при смене графика.
- **Черновик резервирует ресурсы.** Доступность =
  `ёмкость − активные брони − живые черновики`. Поэтому двое не выберут последнее
  время одновременно.
- **Таймер черновика не продлевается на шагах.** `expires_at` ставится один раз
  при создании. Иначе слот можно было бы удерживать бесконечно.
- **Истечение проверяется в трёх местах:** при чтении, на каждом шаге, и
  Celery-задачей раз в 20 сек. Черновик не «оживёт», даже если воркер лежит.
- **Проверки повторяются при подтверждении** — слот могли занять за время
  заполнения формы (`409 slot_taken`), масло могло кончиться (`409 oil_out_of_stock`).
- **Остаток масла не уменьшается при записи**, списывается ровно один раз при
  переводе в «Выполнена». Иначе пришлось бы возвращать канистру при каждой отмене.
- **В `Booking` продублированы имя, телефон, авто, название масла и цены** — это
  снимок на момент брони, чтобы история не поехала при изменении справочников.
- **API мастера — отдельное приложение**, а не флаг в клиентском API: у мастера
  другой набор полей (чужие персональные данные) и другие права.
- **`select_for_update(of=("self",))`** в `_lock_draft`: `select_related` по
  nullable FK даёт LEFT JOIN, а PostgreSQL не блокирует nullable-сторону внешнего
  соединения.
- **Блокировка строки точки** (`ServicePoint … FOR UPDATE`) при выборе времени и
  подтверждении — параллельные подтверждения выстраиваются в очередь.
- **Партиальные уникальные индексы:** `uniq_open_draft_per_user` (один живой
  черновик на клиента), `uniq_active_booking_per_user_slot` (нет дублей броней).

## 8. Модели

- **`User`** — UUID, `phone` (логин, E.164, уникальный), `full_name`, `role`
  (`client`/`master`/`admin`), `car_model`, `car_plate`, `service_points` (M2M —
  точки мастера, пусто = все). У клиента пароль unusable.
- **`OtpCode`** — `phone`, `code_hash`, `expires_at`, `used_at`, `attempts`, `request_ip`.
- **`ServicePoint`** — `name`, `address`, координаты, `timezone`, `opens_at`,
  `closes_at`, `workdays` (JSON, 0 = понедельник), `slot_minutes` (30),
  `posts_count` (сколько машин одновременно = ёмкость слота), `is_active`.
- **`Oil`** — бренд, название, вязкость, тип, объём канистры, `price`, `work_price`.
- **`OilStock`** — остаток масла на точке в канистрах, уникальная пара (точка, масло).
- **`BookingDraft`** — `user`, `step`, `is_open`, `close_reason`, `service_point`,
  `oil`, `slot_start`, `expires_at`, `booking`.
  Шаги: `started → point_selected → oil_selected → slot_selected → confirmed`,
  терминальные: `expired`, `cancelled`.
- **`Booking`** — `code` (короткий, вида `FRUQRE`), ссылки, `start_at`/`end_at`,
  `status`, снимок данных клиента и цен, `master`, `cancel_reason`, `cancelled_at`,
  `cancelled_by`, `reminder_sent_at`.
  Статусы: `pending`, `in_progress`, `completed`, `cancelled_by_client`,
  `cancelled_by_master`, `no_show`.
- **`BookingStatusLog`** — история смены статусов: кто, когда, комментарий.
- **`Notification`** — журнал SMS: получатель, тип, текст, статус, id у провайдера.

## 9. API (базовый путь `/api/v1`)

**Аутентификация:** `POST /auth/otp/request/`, `POST /auth/otp/verify/`,
`POST /auth/token/refresh/`, `GET|PATCH /auth/me/`

**Справочники и доступность:** `GET /service-points/`,
`GET /service-points/{id}/oils/`, `GET /service-points/{id}/slots/?date=YYYY-MM-DD`

**Запись (черновик):** `POST /bookings/drafts/`, `GET /bookings/drafts/current/`,
`POST /bookings/drafts/{id}/select-point/`, `.../select-oil/`, `.../select-slot/`,
`.../confirm/`, `.../cancel/`

**Мои записи:** `GET /bookings/?scope=upcoming|history`, `GET /bookings/{id}/`,
`POST /bookings/{id}/cancel/`

**Мастер:** `GET /master/bookings/` (фильтры `date`, `status`, `service_point`,
`search`, `scope`), `GET /master/bookings/{id}/`, `POST .../cancel/` (причина
обязательна), `POST .../start/`, `POST .../complete/`, `POST .../no-show/`,
`GET /master/bookings/summary/?date=`, `GET /master/live-drafts/`

**Администратор:** `GET /master/metrics/?date_from=&date_to=&service_point=` —
сводная аналитика одним ответом (`totals`, `funnel`, `by_day`, `by_hour`,
`by_point`, `top_oils`, `clients`, `stock`, `live`). Только роль `admin`.

**WebSocket:** `ws://host/ws/booking/?token=<access JWT>` — события
`draft.updated`, `draft.expired`, `draft.closed`, `booking.created`,
`booking.updated`, `booking.cancelled`. Payload совпадает с форматом REST.

## 10. Бизнес-параметры (в `.env`)

```
BOOKING_DRAFT_TTL_SECONDS=300        # 5 минут на запись
BOOKING_MIN_LEAD_MINUTES=30          # минимальный запас до слота
BOOKING_HORIZON_DAYS=14              # горизонт записи
BOOKING_CANCEL_DEADLINE_MINUTES=60   # дедлайн отмены клиентом
BOOKING_REMINDER_LEAD_MINUTES=120    # напоминание за 2 часа
OTP_TTL_SECONDS=300
OTP_RESEND_COOLDOWN_SECONDS=60
OTP_MAX_VERIFY_ATTEMPTS=5
OTP_MAX_PER_PHONE_PER_HOUR=5
OTP_DEBUG_EXPOSE_CODE=True           # в проде обязательно False
```

## 11. Фоновые задачи (Celery beat)

- `expire_stale_drafts` — каждые 20 сек, гасит просроченные черновики.
- `send_booking_reminders` — каждые 5 мин, SMS за 2 часа до визита, ровно один раз.
- `purge_old_drafts` — раз в сутки, удаляет мёртвые черновики старше 7 дней.
- `purge_expired_otp` — раз в час.

## 12. Как запускать

```bash
cp .env.example .env
docker compose build api && docker compose up -d   # или make up
make test    # 65 тестов
make lint    # ruff
```

Страницы: `/` — клиент, `/master/` — мастер, `/admin-panel/` — администратор
с метриками, `/admin/` — Django-админка, `/api/docs/` — Swagger.

Демо-учётки: админ `+79000000000 / admin12345`, мастер `+79000000001 / master12345`.
SMS-код в разработке приходит в поле `debug_code` ответа и в логи воркера.

**Важно:** собирать надо `docker compose build api`, а не просто `build` — путь
проекта содержит кириллицу, и BuildKit падает на не-ASCII в ключе сессии.
`worker` и `beat` используют тот же образ.

## 13. Что я хочу делать дальше

(допишите свою задачу — например: мобильное приложение на React Native / Flutter,
push-уведомления, онлайн-оплата, CI/CD на GitHub Actions, вторая услуга кроме
замены масла)

<!-- ▲▲▲ КОПИРОВАТЬ ДО СЮДА ▲▲▲ -->

---

## Короткий вариант

Если ассистент видит репозиторий (Claude Code, Cursor, Copilot Workspace):

> Проект — бэкенд автосервиса (запись на замену масла): Django 5 + DRF +
> PostgreSQL + Celery/Redis + JWT + Channels, всё в Docker Compose. Серверная
> часть готова, 52 теста зелёные. Прочитай `README.md` и `PROMPT.md` — там полный
> контекст, архитектурные решения и правила. Бизнес-логика живёт только в
> `apps/*/services/`, вьюхи тонкие, ошибки — доменные исключения из
> `apps/common/exceptions.py`. Держись этих правил. Моя задача: …

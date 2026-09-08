DC := docker compose
RUN := $(DC) run --rm api

.PHONY: help up down build logs sh migrations migrate demo superuser test lint fmt schema

help:
	@echo "up          — поднять всё (api, worker, beat, postgres, redis)"
	@echo "down        — остановить"
	@echo "build       — пересобрать образ"
	@echo "logs        — логи api"
	@echo "sh          — bash внутри контейнера api"
	@echo "migrations  — сгенерировать миграции"
	@echo "migrate     — применить миграции"
	@echo "demo        — залить демо-данные (2 точки, масла, мастер)"
	@echo "superuser   — создать суперпользователя"
	@echo "test        — прогнать тесты"
	@echo "lint / fmt  — ruff"
	@echo "schema      — выгрузить openapi.yaml"

# build именно `api`, а не все сервисы: docker compose без имени сервиса
# спотыкается о кириллицу в пути проекта (BuildKit-сессия). worker и beat
# используют тот же образ, так что одной сборки достаточно.
up:
	$(DC) build api
	$(DC) up -d

down:
	$(DC) down

build:
	$(DC) build api

logs:
	$(DC) logs -f api

sh:
	$(DC) exec api bash

migrations:
	$(RUN) python manage.py makemigrations

migrate:
	$(RUN) python manage.py migrate

demo:
	$(RUN) python manage.py bootstrap_demo

superuser:
	$(DC) exec api python manage.py createsuperuser

test:
	$(RUN) pytest

lint:
	$(RUN) ruff check .

fmt:
	$(RUN) ruff check --fix .

schema:
	$(RUN) python manage.py spectacular --file openapi.yaml

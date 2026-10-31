DEV_COMPOSE = docker compose --env-file app/.env.dev -f app/docker-compose.yml -f app/docker-compose.dev.yml
PROD_COMPOSE = docker compose --env-file app/.env.prod -f app/docker-compose.yml -f app/docker-compose.prod.yml

# On Windows, a bare `bash` can resolve to the legacy WSL-launcher stub
# (C:\Windows\System32\bash.exe) ahead of Git's real bash.exe on PATH,
# which fails outright if the default WSL distro isn't a normal usable
# one (e.g. Docker Desktop's internal "docker-desktop" distro). Resolve
# bash from the same directory as the already-correct $(SHELL) instead
# of trusting PATH search for it. Use a real `dirname` via $(shell ...)
# rather than make's $(dir ...), which word-splits on the space in the
# default "C:/Program Files/Git/..." install path and mangles it.
ifeq ($(OS),Windows_NT)
CANVAS_BASH := $(shell dirname "$(SHELL)")/bash.exe
else
CANVAS_BASH := bash
endif

.PHONY: setup-dev setup-prod validate-dev validate-prod \
	dev dev-build dev-up dev-down dev-restart dev-ps dev-logs \
	create-admin dev-seed dev-archive dev-db-clear \
	test-backend test-admin test-auth test-courses test-database test-storage \
	test-omr test-frontend test-canvas-scripts \
	prod prod-build prod-up prod-down prod-restart prod-ps prod-logs migrate-prod \
	canvas-setup canvas-build canvas-up canvas-down canvas-restart canvas-ps canvas-logs \
	canvas-seed canvas-smoke canvas-config canvas-reset \
	presentation-up presentation-seed presentation-data presentation-check \
	presentation-status presentation-down \
	logs-backend-dev logs-frontend-dev logs-omr-dev logs-db-dev logs-garage-dev logs-email-dev \
	logs-backend-prod logs-frontend-prod logs-omr-prod logs-db-prod logs-garage-prod \
	logs-migrate-prod \
	config-dev config-prod check-dev check-prod reset-dev

setup-dev:
	cp -n app/.env.dev.example app/.env.dev

setup-prod:
	cp -n app/.env.prod.example app/.env.prod

validate-dev:
	@sh app/scripts/validate-env.sh app/.env.dev \
		POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB DATABASE_URL TEST_DATABASE_URL \
		JWT_ACCESS_SECRET JWT_REFRESH_SECRET JWT_ACCESS_EXPIRE_SECONDS JWT_REFRESH_EXPIRE_SECONDS \
		RESEND_API_KEY EMAIL_FROM FRONTEND_PASSWORD_RESET_URL PASSWORD_RESET_EXPIRE_SECONDS \
		OMR_PORT

validate-prod:
	@sh app/scripts/validate-env.sh app/.env.prod \
		POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB DATABASE_URL \
		JWT_ACCESS_SECRET JWT_REFRESH_SECRET JWT_ACCESS_EXPIRE_SECONDS JWT_REFRESH_EXPIRE_SECONDS \
		RESEND_API_KEY EMAIL_FROM FRONTEND_PASSWORD_RESET_URL PASSWORD_RESET_EXPIRE_SECONDS \
		OMR_PORT GARAGE_ACCESS_KEY_ID GARAGE_SECRET_ACCESS_KEY GARAGE_BUCKET_NAME

dev: validate-dev
	$(DEV_COMPOSE) up --build

dev-build: validate-dev
	$(DEV_COMPOSE) build

dev-up: validate-dev
	$(DEV_COMPOSE) up -d

dev-down:
	$(DEV_COMPOSE) down --remove-orphans

dev-restart: dev-down dev-up

dev-ps:
	$(DEV_COMPOSE) ps -a

dev-logs:
	$(DEV_COMPOSE) logs -f

create-admin: validate-dev
	@test -n "$(EMAIL)" || (echo 'Usage: make create-admin EMAIL=admin@example.com FIRST_NAME=Admin LAST_NAME=User [FORCE=true] [PASSWORD=...]'; exit 1)
	@test -n "$(FIRST_NAME)" || (echo 'Usage: make create-admin EMAIL=admin@example.com FIRST_NAME=Admin LAST_NAME=User [FORCE=true] [PASSWORD=...]'; exit 1)
	@test -n "$(LAST_NAME)" || (echo 'Usage: make create-admin EMAIL=admin@example.com FIRST_NAME=Admin LAST_NAME=User [FORCE=true] [PASSWORD=...]'; exit 1)
	$(DEV_COMPOSE) up -d db
	$(DEV_COMPOSE) run --rm $(if $(PASSWORD),-e ADMIN_PASSWORD='$(PASSWORD)',) backend sh -c 'alembic upgrade head && python scripts/create_admin.py --email "$(EMAIL)" --first-name "$(FIRST_NAME)" --last-name "$(LAST_NAME)" $(if $(filter true,$(FORCE)),--force,)'

dev-seed: validate-dev
	$(DEV_COMPOSE) up -d db omr_service garage-store
	$(DEV_COMPOSE) run --rm backend sh -c 'alembic upgrade head && python seed.py'

dev-archive: validate-dev
	@printf 'Process all archive retention deadlines currently due in the dev database? [y/N] '; read answer; \
		[ "$$answer" = y ] || [ "$$answer" = Y ] || exit 1
	$(DEV_COMPOSE) up -d backend
	$(DEV_COMPOSE) exec -T backend python scripts/process_retention.py

dev-db-clear: validate-dev
	@printf 'Clear all data in the dev database? [y/N] '; read answer; \
		[ "$$answer" = y ] || [ "$$answer" = Y ] || exit 1
	$(DEV_COMPOSE) up -d db
	$(DEV_COMPOSE) exec -T db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
	$(DEV_COMPOSE) run --rm backend alembic upgrade head

test-backend: validate-dev
	$(DEV_COMPOSE) up -d db_test
	$(DEV_COMPOSE) run --rm backend pytest tests

test-admin: validate-dev
	$(DEV_COMPOSE) up -d db_test
	$(DEV_COMPOSE) run --rm backend pytest tests/admin

test-auth: validate-dev
	$(DEV_COMPOSE) up -d db_test
	$(DEV_COMPOSE) run --rm backend pytest tests/auth

test-courses: validate-dev
	$(DEV_COMPOSE) up -d db_test
	$(DEV_COMPOSE) run --rm backend pytest tests/courses

test-database: validate-dev
	$(DEV_COMPOSE) up -d db_test
	$(DEV_COMPOSE) run --rm backend pytest tests/test_database.py

test-storage: validate-dev
	$(DEV_COMPOSE) up -d db_test
	$(DEV_COMPOSE) run --rm backend pytest tests/test_storage.py

test-omr: validate-dev
	$(DEV_COMPOSE) run --rm --entrypoint go omr_service test ./... -tags=integration --count=1

test-frontend:
	docker build --target test -t capstone-frontend-test app/frontend
	docker run --rm capstone-frontend-test

test-canvas-scripts:
	"$(CANVAS_BASH)" tools/canvas/scripts/test-portability.sh

prod: prod-build prod-up

prod-build: validate-prod
	$(PROD_COMPOSE) build

prod-up: validate-prod
	$(PROD_COMPOSE) up -d

prod-down:
	$(PROD_COMPOSE) down --remove-orphans

prod-restart: prod-down prod-up

prod-ps:
	$(PROD_COMPOSE) ps -a

prod-logs:
	$(PROD_COMPOSE) logs -f

migrate-prod: validate-prod
	$(PROD_COMPOSE) run --rm migrate

logs-backend-dev:
	$(DEV_COMPOSE) logs -f backend

logs-frontend-dev:
	$(DEV_COMPOSE) logs -f frontend

logs-omr-dev:
	$(DEV_COMPOSE) logs -f omr_service

logs-db-dev:
	$(DEV_COMPOSE) logs -f db

logs-garage-dev:
	$(DEV_COMPOSE) logs -f garage-store

# Live email activity. With EMAIL_CONSOLE_MODE=true the app logs each email
# (recipient, subject, and link) instead of sending it; this filters the
# backend log down to just those lines.
logs-email-dev:
	$(DEV_COMPOSE) logs -f backend | grep --line-buffered -E "DEV EMAIL|To: |Subject: |reset-password|/join/"

logs-backend-prod:
	$(PROD_COMPOSE) logs -f backend

logs-frontend-prod:
	$(PROD_COMPOSE) logs -f frontend

logs-omr-prod:
	$(PROD_COMPOSE) logs -f omr_service

logs-db-prod:
	$(PROD_COMPOSE) logs -f db

logs-garage-prod:
	$(PROD_COMPOSE) logs -f garage-store

logs-migrate-prod:
	$(PROD_COMPOSE) logs -f migrate

config-dev: validate-dev
	$(DEV_COMPOSE) config --quiet

config-prod: validate-prod
	$(PROD_COMPOSE) config --quiet

check-dev:
	$(DEV_COMPOSE) ps -a
	curl --fail --silent --show-error http://127.0.0.1:8000/api/health/ready

check-prod:
	$(PROD_COMPOSE) ps -a
	@port=$${APP_PORT:-$$(sed -n 's/^APP_PORT=//p' app/.env.prod)}; \
		curl --fail --silent --show-error "http://127.0.0.1:$${port:-80}/api/health/ready"

reset-dev:
	@printf 'Delete development containers and volumes? [y/N] '; read answer; \
		[ "$$answer" = y ] || [ "$$answer" = Y ] || exit 1
	$(DEV_COMPOSE) down --volumes --remove-orphans

canvas-setup:
	"$(CANVAS_BASH)" tools/canvas/scripts/setup.sh

canvas-build:
	"$(CANVAS_BASH)" tools/canvas/scripts/compose.sh build web

canvas-up:
	"$(CANVAS_BASH)" tools/canvas/scripts/compose.sh up -d

canvas-down:
	"$(CANVAS_BASH)" tools/canvas/scripts/compose.sh down --remove-orphans

canvas-restart: canvas-down canvas-up

canvas-ps:
	"$(CANVAS_BASH)" tools/canvas/scripts/compose.sh ps -a

canvas-logs:
	"$(CANVAS_BASH)" tools/canvas/scripts/compose.sh logs -f

canvas-seed:
	"$(CANVAS_BASH)" tools/canvas/scripts/seed.sh $(if $(filter true,$(FORCE)),--force,)

canvas-smoke:
	"$(CANVAS_BASH)" tools/canvas/scripts/smoke-test.sh

canvas-config:
	"$(CANVAS_BASH)" tools/canvas/scripts/compose.sh config --quiet

canvas-reset:
	@printf 'Delete the local Canvas containers and all Canvas data? [y/N] '; read answer; \
		[ "$$answer" = y ] || [ "$$answer" = Y ] || exit 1
	"$(CANVAS_BASH)" tools/canvas/scripts/compose.sh down --volumes --remove-orphans
	rm -f tools/canvas/.seed-state

# Presentation workflow. Keep these as ordered sub-makes so presentation-up
# remains a single safe recovery command even with parallel make enabled.
presentation-up:
	@$(MAKE) --no-print-directory dev-up
	@$(MAKE) --no-print-directory canvas-up
	@$(MAKE) --no-print-directory presentation-seed
	@$(MAKE) --no-print-directory presentation-data
	@$(MAKE) --no-print-directory presentation-check

presentation-seed:
	@$(MAKE) --no-print-directory dev-seed
	@$(MAKE) --no-print-directory canvas-seed

presentation-data: validate-dev
	$(DEV_COMPOSE) up -d db
	$(DEV_COMPOSE) run --rm --no-deps backend python scripts/build_presentation_scans.py

presentation-check:
	@$(MAKE) --no-print-directory check-dev
	$(DEV_COMPOSE) run --rm --no-deps backend python scripts/check_presentation_data.py
	@$(MAKE) --no-print-directory canvas-smoke

presentation-status:
	@$(MAKE) --no-print-directory dev-ps
	@$(MAKE) --no-print-directory canvas-ps

presentation-down:
	@$(MAKE) --no-print-directory dev-down
	@$(MAKE) --no-print-directory canvas-down

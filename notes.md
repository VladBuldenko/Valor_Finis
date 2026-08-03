promt:Я строю production-like fintech backend проект Valor на FastAPI.

ВАЖНО:

Объясняй всё очень подробно, как senior mentor для junior developer.

Перед каждым файлом и кодом ВСЕГДА объясняй:

Что это

Зачем это нужно

Как это работает

Какие best practices используются

Только потом код

Всегда объясняй архитектуру, flow данных и зачем нужен каждый слой.

Пиши комментарии в коде на английском.

Комментарии должны объяснять:

what function does

why it exists

parameters

returns

Следуй принципам:

SOLID

DRY

KISS

YAGNI

Clean Architecture

Separation of Concerns

Single Responsibility

Readable Code First

ТЕКУЩАЯ АРХИТЕКТУРА:

backend structure:

router → service → repository → SQLAlchemy model → PostgreSQL

Response flow:

PostgreSQL → SQLAlchemy model → service maps to Pydantic response → router → JSON

Что делает каждый слой:

router.py / *_router.py → HTTP layer / FastAPI endpoints

service.py / *_service.py → business logic + mapping Model → Response

repository.py / *_repository.py → data access layer / SQLAlchemy queries / commit / rollback

schemas.py / *_schemas.py → Pydantic validation schemas and API contracts

models.py / *_models.py → SQLAlchemy ORM models / database table mapping

errors.py / *_errors.py → module-level domain errors, later translated to HTTP errors in router

Auth flow сейчас:

Temporary development auth:

X-User-Id header

get_current_user dependency

CurrentUser(id=...)

Production target:

Authorization: Bearer <supabase_jwt>

backend verifies JWT

user_id comes from token.sub

ТЕКУЩАЯ СТРУКТУРА ПРОЕКТА:

Monorepo root:

VALOR_FINIS/

Backend path:

services/api/

Backend modules path:

services/api/app/modules/

Current modules:

expenses

categories

budgets

goals

analytics

auth

Future modules:

receipts

ocr

categorization rules

Naming convention:

Preferred module-prefixed names for growing modules:

expenses_router.py

expenses_service.py

expenses_repository.py

expenses_schemas.py

expenses_models.py

Same idea for:

budgets

goals

analytics

Current project has some mixed naming, especially categories:

categories/router.py

categories/service.py

categories/repository.py

categories/schemas.py

categories/category_models.py

This is acceptable for now because tests are green.For new modules and future refactors prefer module-prefixed names.

Example:app/modules/analytics/analytics_service.py

Avoid generic names in large modules when the module becomes complex.

ТЕКУЩЕЕ СОСТОЯНИЕ ПРОЕКТА:

ГОТОВО:

FastAPI backend

Swagger/OpenAPI

Health endpoint

Root endpoint

PostgreSQL integration

SQLAlchemy models

Alembic migrations

Repository pattern with database repositories

Temporary auth dependency through X-User-Id

CRUD endpoints for core modules

Analytics monthly filter by year/month

Unit tests

Integration tests

Modules completed:

Expenses

Categories

Budgets

Goals

Analytics

Auth dependency module

ГОТОВО В ОСНОВНЫХ CRUD МОДУЛЯХ:

schemas

repository

service

router

errors where needed

unit tests

integration tests

CRUD completed for:

categories

expenses

budgets

goals

Analytics module implemented:

monthly summary with year/month filter

category summary

budget status

goal progress

Analytics logic:

total spending for selected month

grouped categories

exceeded budget

remaining goal amount

authenticated user filtering

Current backend uses:

PostgreSQL

SQLAlchemy ORM models

Alembic migrations

Pydantic schemas

FastAPI dependency injection

temporary X-User-Id auth header

Current backend no longer uses:

in-memory storage lists

expenses_storage

budgets_storage

goals_storage

next_*_id counters

СЕЙЧАС МЫ НА ЭТАПЕ:

SUPABASE JWT AUTH PREPARATION

УЖЕ УСТАНОВЛЕНО:

sqlalchemy

psycopg2-binary

alembic

python-dotenv

CURRENT DATABASE STRUCTURE:

Created:

app/core/app_config.py

app/db/database_base.py

app/db/database_session.py

app/db/database_models.py

Created folders:

app/core

app/db

Created env files:

.env

.env.example

Current naming:

app_config.py

database_base.py

database_session.py

database_models.py

Current database architecture:

SQLAlchemy 2.x style

PostgreSQL

Alembic

UUID primary keys

Decimal for money fields

.env config

Next roadmap step:

replace temporary X-User-Id auth with Supabase JWT verification

Then:

Receipts module

OCR module

Categorization rules

Docker improvements

CI/CD

Mobile MVP

Web landing page / dashboard

ВАЖНО:Всегда использовать современные production-like решения.Не использовать outdated patterns.

ВСЕГДА:

объясняй flow

объясняй architecture decisions

объясняй why this approach is used

объясняй tradeoffs

объясняй production best practices

Следующий шаг roadmap:

Supabase JWT Auth:

replace temporary X-User-Id header

use Authorization: Bearer <supabase_jwt>

verify JWT on backend

resolve CurrentUser from token.sub

keep routers using Depends(get_current_user)

update auth tests

Потом:

Receipts module

OCR module

Categorization rules

Docker improvements

CI/CD

Mobile MVP

Web landing page / dashboard

⚠️ Notes:

OCR is not perfect

Errors are common

User confirmation is required

❗ Barcode / QR Code on Receipts

📌 Important clarification:

Most receipt barcodes or QR codes DO NOT contain full purchase details.

They usually contain:

receipt ID

date/time

total amount

tax data

They usually do NOT contain:

❌ list of items

❌ categories

👉 Conclusion:The correct approach is:

OCR + user confirmation

🎯 MVP Goal (Version 0.1)

Answer 3 key questions:

💸 How much did I spend this month?

🧾 What did I spend money on?

🚨 Where did I exceed my limits?

🚀 MVP Features (Version 0.1)

📱 Mobile App

🔐 1. Authentication

Sign up / Login via Supabase

➕ 2. Add Expense (Manual)

Fields:

expense_date

amount

category

description

Categories:

🍔 Food

👕 Clothing

🚗 Transport

☕ Cafés

🏠 Home

💊 Health

📦 Subscriptions

🔄 Other

📋 3. Expense List

View all expenses

Filter by month

Filter by category

📊 4. Dashboard

Total monthly spending

Spending by category

Basic charts

🚦 5. Budgets

User defines budgets / monthly limits:

Category

Limit

Food

400€

Cafés

150€

App shows:

current spending

remaining budget

exceeded limits

🎯 6. Financial Goals

Fields:

goal name

target amount

target_date

current progress

Calculations:

remaining amount

required monthly savings

🧠 7. Simple Strategy (No ML)

Example:

Required: 150€/monthCurrent: 100€/monthGap: 50€/month

👉 Suggestions:

reduce café spending

cut subscriptions

🌐 Web App (Version 0.1)

Simple landing page:

product description

features

benefits

CTA buttons:

🚀 "Try Demo"

📬 "Join Waitlist"

⚙️ Backend (FastAPI)

Main API endpoints:

/api/v1/expenses

/api/v1/categories

/api/v1/budgets

/api/v1/goals

/api/v1/analytics/monthly-summary?year=2026&month=7

/api/v1/analytics/category-summary

/api/v1/analytics/budget-status

/api/v1/analytics/goal-progress

Temporary authentication:

X-User-Id: <uuid>

Production authentication target:

Authorization: Bearer <supabase_jwt>

Important:

There is no production /auth backend API yet.

Supabase Auth will handle sign up / login.

Backend will verify JWT and resolve CurrentUser.

🗄 Database Structure

🧾 Table: expenses

id: UUID

user_id: UUID

category_id: UUID | null

title

amount

currency

expense_date

description

source

created_at

updated_at

🏷 Table: categories

id: UUID

user_id: UUID

name

color

icon

is_default

created_at

updated_at

Constraint:

unique user category name: user_id + name

🚦 Table: budgets

id: UUID

user_id: UUID

category_id: UUID | null

name

limit_amount

currency

period: weekly / monthly / yearly

start_date

end_date

created_at

updated_at

Constraint:

unique budget definition: user_id + name + period + start_date

🎯 Table: goals

id: UUID

user_id: UUID

name

target_amount

current_amount

currency

target_date

status: active / completed / archived

created_at

updated_at

📁 Project Test Structure# 📁 Project Test Structure

valor/│├── quality/│   ├── README.md│   ││   ├── functional/│   │   ├── api/│   │   │   ├── postman/│   │   │   ├── pytest/│   │   │   └── contract/│   │   ││   │   ├── web/│   │   │   ├── playwright/│   │   │   └── e2e/│   │   ││   │   └── mobile/│   │       ├── detox/│   │       └── e2e/│   ││   ├── non-functional/│   │   ├── performance/│   │   │   ├── k6/│   │   │   └── reports/│   │   ││   │   ├── security/│   │   │   ├── zap/│   │   │   ├── dependency-scan/│   │   │   └── reports/│   │   ││   │   ├── accessibility/│   │   │   ├── axe/│   │   │   └── reports/│   │   ││   │   └── reliability/│   │       ├── smoke/│   │       └── health-checks/│   ││   ├── test-data/│   │   ├── users.json│   │   ├── expenses.json│   │   ├── goals.json│   │   └── receipts/│   ││   ├── test-plans/│   │   ├── mvp-test-plan.md│   │   ├── regression-test-plan.md│   │   └── release-checklist.md│   ││   └── reports/│       ├── functional/│       ├── performance/│       ├── security/│       └── accessibility/

🧱 Development Plan

🚀 Phase 1 — Backend MVP

Build FastAPI backend

Add health/root endpoints

Add PostgreSQL integration

Add SQLAlchemy models

Add Alembic migrations

Replace in-memory repositories with database repositories

Implement Expenses CRUD API

Implement Categories CRUD API

Implement Budgets CRUD API

Implement Goals CRUD API

Implement Analytics API

Add monthly summary filter by year/month

Add unit tests

Add integration tests

Replace temporary X-User-Id auth with Supabase JWT Auth

📱 Phase 1.5 — Mobile MVP

Sign up / login via Supabase

Add expense manually

List expenses

Edit expense

Delete expense

Filter expenses by month

Show dashboard summary

Show category summary

Show budget status

Show goal progress

🌐 Phase 1.6 — Web MVP

Landing page

Product description

Features

Benefits

CTA buttons

Optional dashboard later

📸 Phase 2 — OCR

Upload receipt image

Save receipt metadata

Integrate OCR API

Extract text

Detect amount

Detect date

Detect merchant

User confirmation before creating expense

🗂 Phase 3 — Categorization

Rule-based system:

Lidl, Aldi → Food

Zara → Clothing

Shell → Transport

Starbucks → Cafés

📊 Phase 4 — Analytics

charts

monthly comparison

category growth

top expenses

📅 Phase 5 — Planning

spending forecast

scenario simulation:

reduce expenses

increase income

adjust goal timeline

🧠 Long-Term Roadmap# 🧠 Long-Term Roadmap

🟢 Version 1.0

full web dashboard

authentication system

cloud storage

🟡 Version 1.5

improved OCR

item-level recognition

🔵 Version 2.0 (ML)

expense prediction

smart recommendations

behavior analysis

🟣 Version 3.0

AI financial assistant

automatic strategy generation

⚠️ Core Principle

Backend Roadmap — Valor API

Текущее состояние

Сейчас сделано:

FastAPI backend запускается

/health работает

Swagger docs открывается

PostgreSQL подключён

Alembic migrations применены

SQLAlchemy models созданы

CRUD реализован для categories, expenses, budgets, goals

Analytics реализована

Monthly summary фильтруется по year и month

Данные фильтруются по authenticated user_id

Временная авторизация работает через X-User-Id

Unit tests зелёные

Integration tests зелёные

Это значит:

backend core готов

структура router → service → repository → model → PostgreSQL работает

проект готов к следующему production-like шагу: Supabase JWT Auth

Главная backend-цель

Сделать API, которое позволит мобильному и веб-приложению безопасно работать с данными пользователя:

расходы

категории

бюджеты

цели

аналитика

пользователи

авторизация

чеки

Backend architecture

Мы используем структуру:

router.py / *_router.py       → принимает HTTP-запросыschemas.py / *_schemas.py     → проверяет входные/выходные данныеservice.py / *_service.py     → содержит бизнес-логикуrepository.py / *_repository.py → работает с PostgreSQL через SQLAlchemymodels.py / *_models.py       → описывает таблицы базы данныхerrors.py / *_errors.py       → описывает module-level ошибки

Почему так

Чтобы код не превратился в кашу.

router не должен считать бизнес-логикуservice не должен знать детали HTTPrepository не должен возвращать HTTPExceptionschemas не должны ходить в базуmodels не должны содержать API-логику

Этап 1 — Expenses module

Статус: ГОТОВО

Что реализовано:

ExpenseCreate

ExpenseUpdate

ExpenseResponse

create_expense()

get_expenses()

get_expense_by_id()

update_expense()

delete_expense()

POST /expenses

GET /expenses

PATCH /expenses/{expense_id}

DELETE /expenses/{expense_id}

ownership check by expense_id + user_id

unit tests

integration tests

Definition of Done

расход можно сохранить

список расходов можно получить

расход можно обновить

расход можно удалить

чужой расход нельзя обновить или удалить

тесты проходят

Этап 2 — Categories module

Статус: ГОТОВО

Что реализовано:

CategoryCreate

CategoryUpdate

CategoryResponse

create_category()

get_categories()

get_category_by_id()

update_category()

delete_category()

POST /categories

GET /categories

PATCH /categories/{category_id}

DELETE /categories/{category_id}

unique constraint: user_id + name

ownership check by category_id + user_id

unit tests

integration tests

Этап 3 — Budgets module

Статус: ГОТОВО

Важно:

Используем термин budgets, не limits.

Что реализовано:

BudgetCreate

BudgetUpdate

BudgetResponse

create_budget()

get_budgets()

get_budget_by_id()

update_budget()

delete_budget()

POST /budgets

GET /budgets

PATCH /budgets/{budget_id}

DELETE /budgets/{budget_id}

unique constraint: user_id + name + period + start_date

ownership check by budget_id + user_id

unit tests

integration tests

Этап 4 — Goals module

Статус: ГОТОВО

Что реализовано:

GoalCreate

GoalUpdate

GoalResponse

create_goal()

get_goals()

get_goal_by_id()

update_goal()

delete_goal()

POST /goals

GET /goals

PATCH /goals/{goal_id}

DELETE /goals/{goal_id}

validation: current_amount <= target_amount

ownership check by goal_id + user_id

unit tests

integration tests

Этап 5 — Analytics module

Статус: ГОТОВО ДЛЯ MVP

Функции:

get_monthly_summary(year, month)

get_category_summary()

get_budget_status()

get_goal_progress()

Что считает:

общие расходы за выбранный месяц

расходы по категориям

превышение бюджета

прогресс по целям

Endpoints:

GET /analytics/monthly-summary?year=2026&month=7

GET /analytics/category-summary

GET /analytics/budget-status

GET /analytics/goal-progress

Definition of Done

backend возвращает готовую статистику

frontend не считает сложную бизнес-логику сам

расходы другого пользователя не попадают в аналитику

monthly summary считает только выбранный месяц

Этап 6 — Database integration

Статус: ГОТОВО

Что сделано:

database connection

database session

database model registry

SQLAlchemy models

Alembic migrations

PostgreSQL repositories

in-memory repositories removed

Важно

Service logic почти не должна меняться при смене хранения данных.Меняется в основном repository layer.

Этап 7 — Auth module

Статус: ВРЕМЕННО ГОТОВО / PRODUCTION AUTH ЕЩЁ НЕ ГОТОВ

Сейчас:

X-User-Id header

get_current_user() dependency

CurrentUser(id=...)

Следующий шаг:

Supabase JWT verification

Authorization: Bearer <jwt>

user id берётся из JWT sub

Definition of Done для production auth

backend проверяет JWT

пользователь не может подставить чужой user_id

routers продолжают использовать Depends(get_current_user)

tests обновлены под новый auth flow

Этап 8 — Receipts module

Статус: НЕ НАЧАТО

Зачем

Пользователь будет загружать чек.Система позже сможет создавать расход на основе чека.

Функции

upload_receipt()

get_receipts()

extract_text_from_receipt()

connect_receipt_to_expense()

На первом этапе

upload image

save receipt metadata

manual confirmation

Этап 9 — OCR module

Статус: НЕ НАЧАТО

Зачем

OCR нужен, чтобы читать текст с фото чека.

Что делает

получает изображение

извлекает текст

пытается найти сумму

пытается найти дату

пытается найти магазин

Важно

OCR не должен автоматически всё сохранять.

Правильно:

OCR предлагает данныепользователь подтверждаетbackend сохраняет расход

Этап 10 — Rule-based categorization

Статус: НЕ НАЧАТО

Зачем

До ML делаем простые правила.

Пример:

Lidl → Food

Aldi → Food

Shell → Transport

Zara → Clothing

Starbucks → Cafés

Функции

suggest_category_by_merchant()

create_merchant_rule()

get_merchant_rules()

Почему не ML

Пока нет данных.

ML без данных — бессмысленно.

Этап 11 — Advanced tests

Статус: ЧАСТИЧНО ГОТОВО

Сейчас готово:

unit tests

integration tests

Позже добавить:

API tests

contract tests

security checks

performance checks

Инструменты

pytest

httpx

Playwright later

k6 later

OWASP ZAP later

Этап 12 — Docker

Статус: НЕ ЗАКРЫТО

Зачем

Чтобы backend запускался одинаково на любом компьютере.

Что делаем

Dockerfile

docker-compose.yml

local PostgreSQL

environment variables

Definition of Done

docker-compose up запускает backend

database подключается

tests проходят

Этап 13 — CI/CD

Статус: НЕ НАЧАТО

Зачем

GitHub должен автоматически проверять код.

Что делает CI

install dependencies

run lint

run tests

check formatting

build project

Definition of Done

каждый pull request автоматически проверяется

сломанный код не попадает в main

Общий порядок разработки backend

Health check — done

Expenses schemas — done

Expenses repository — done

Expenses service — done

Expenses router — done

Connect expenses router — done

Manual API testing — done

Expenses tests — done

Categories — done

Budgets — done

Goals — done

Analytics — done

Database — done

Temporary Auth — done

Supabase JWT Auth — next

Receipts

OCR

Categorization rules

Advanced tests

Docker

CI/CD

Что делать прямо сейчас

Следующий конкретный шаг:

заменить временную авторизацию X-User-Id на Supabase JWT Auth.

Файл:

services/api/app/modules/auth/auth_dependencies.py

Задача:

читать Authorization: Bearer <jwt>

проверять Supabase JWT

доставать user_id из token subject

возвращать CurrentUser(id=...)

Commit strategy

После каждого логического шага делаем commit.

1. Finish receipts integration tests
2. Finish receipts unit tests
3. Add receipt file upload
4. Add OCR service foundation
5. Add OCR parsing
6. Add confirm receipt -> expense flow
7. Add category rules module
8. Harden production auth
9. Polish API consistency
10. Add Docker backend flow
11. Add CI
12. Update final docs

Идеи для приложения
AI Usage:
1. добавить кнопку AI подсказки. Если у пользователя есть нужное количество данних для очевидного или неочевидкого совета или умозаключения, при прайме или за отдельную плату за совет, показивать подсказку или совет, или показивать все за рекламу.
promt:
Я строю production-like fintech проект Valor Finis — Home Budget Receipt Tracker.

Это мобильное + web приложение для:

* учета расходов
* категорий расходов
* бюджетов
* финансовых целей
* аналитики
* позже OCR чеков

Технологии проекта:

* Backend: FastAPI + Python
* ORM: SQLAlchemy
* Migrations: Alembic
* Database: PostgreSQL
* Auth позже: Supabase Auth
* Mobile позже: React Native Expo
* Web позже: Next.js

ВАЖНО:

* Отвечай на русском.
* Работай со мной как Senior Fullstack Web/Mobile Developer и Senior App Architect.
* Объясняй все подробно, как senior mentor для junior developer.
* Объясняй не только что поменять, но и почему.
* Объясняй каждую важную строку кода простыми словами.
* Мы идем шаг за шагом.
* Не делай все сам без моего запроса.
* Комментарии и docstrings в коде должны быть на английском.
* Оформляй ответы красиво и понятно, не просто сухим списком.

Перед каждым файлом и кодом желательно объяснять:

1. Что сейчас не так
2. Почему это проблема
3. Что меняем
4. Полный код файла
5. Разбор важных строк
6. Что проверить после этого

Если ошибка маленькая:

* не давай огромный файл сразу
* покажи только нужный кусок для замены

Если файл полностью старый:

* дай полный обновленный код файла

Следуй принципам:

* SOLID
* DRY
* KISS
* YAGNI
* Clean Architecture
* Separation of Concerns
* Single Responsibility
* Readable Code First
* Scalable MVP
* Production-like architecture without overengineering

---

# ТЕКУЩАЯ АРХИТЕКТУРА

Backend architecture:

```text
Router -> Service -> Repository -> SQLAlchemy Model -> PostgreSQL
```

Response flow:

```text
PostgreSQL -> SQLAlchemy Model -> Service maps to Pydantic Response -> Router -> JSON
```

Архитектурный стиль:

* Modular Monolith
* Layered Architecture
* Repository Pattern
* PostgreSQL/UUID architecture

Что делает каждый слой:

* router.py -> HTTP layer / FastAPI endpoints
* service.py -> business logic and model-to-response mapping
* repository.py -> database access layer
* schemas.py -> Pydantic request/response contracts and validation
* models.py -> SQLAlchemy ORM table mapping
* migrations -> real database structure changes

ВАЖНО:

* Repository должен возвращать SQLAlchemy Model.
* Service должен возвращать Pydantic Response.
* Router должен возвращать JSON.
* user_id сейчас временно передается через request body или query.
* После Supabase Auth user_id должен браться из JWT/current user dependency, а не от клиента.

---

# ТЕКУЩАЯ СТРУКТУРА ПРОЕКТА

Backend modules:

```text
services/api/app/modules/
```

Modules:

* expenses
* categories
* budgets
* goals
* analytics

Core/database folders:

```text
services/api/app/core/
services/api/app/db/
```

Important database files:

* app/core/app_config.py
* app/db/database_base.py
* app/db/database_session.py
* app/db/database_models.py

Database model registry:

* app/db/database_models.py contains import_database_models()
* import_database_models() imports all SQLAlchemy models before routers are connected

It imports:

* CategoryModel
* BudgetModel
* ExpenseModel
* GoalModel

Why it exists:

* It fixes SQLAlchemy metadata registration problems.
* It prevents errors like NoReferencedTableError for foreign keys.
* It makes sure tables are known before Alembic and SQLAlchemy use metadata.

In app/main.py:

```python
import_database_models()
```

must be called before routers are attached.

---

# NAMING CONVENTION

Current naming is mixed but module-prefixed names are preferred.

Examples:

* expenses_router.py
* expenses_service.py
* expenses_repository.py
* expenses_schemas.py
* expenses_models.py

Budgets currently use:

* budget_router.py
* budget_service.py
* budget_repository.py
* budget_schemas.py
* budgets_models.py
* budget_errors.py

Goals currently use:

* goal_repository.py
* goal_service.py
* goal_schemas.py
* goal_models.py

Categories currently use shorter names:

* router.py
* service.py
* repository.py
* schemas.py
* category_models.py
* errors.py

Best practice for future:

* Prefer module-prefixed names.
* Avoid generic names when a module grows.
* Keep naming consistent during refactoring.

---

# CURRENT DATABASE ARCHITECTURE

Current backend uses:

* SQLAlchemy 2.x style
* PostgreSQL
* Alembic
* UUID primary keys
* Decimal for money
* .env configuration

Installed:

* sqlalchemy
* psycopg2-binary
* alembic
* python-dotenv

Environment files:

* .env
* .env.example

Current important note:

* Tests currently use the database from .env.
* Later best practice: create a separate test database, for example valor_test.

---

# OLD ARCHITECTURE THAT MUST NOT BE USED

Do NOT use old in-memory storage:

* expenses_storage
* budgets_storage
* goals_storage
* next_expense_id
* next_budget_id
* next_goal_id

Do NOT use old fields:

Expenses old fields:

* category
* date

Budgets old fields:

* category
* monthly_limit
* month

Goals old fields:

* deadline

Categories old fields:

* key
* DEFAULT_CATEGORIES static list

Why:

* Project has moved from in-memory architecture to PostgreSQL/UUID architecture.
* Tests and code must validate the current database-backed API.

---

# CURRENT DATA MODELS

## Table: expenses

Fields:

* id: UUID
* user_id: UUID
* category_id: Optional[UUID]
* title: str
* amount: Decimal
* currency: str
* expense_date: date
* description: Optional[str]
* source: str
* created_at
* updated_at

Important:

* category_id can be None.
* Expense without category is treated as Uncategorized in analytics.
* expense_date replaces old date.
* title is the main short label.
* description is optional additional text.

---

## Table: categories

Fields:

* id: UUID
* user_id: UUID
* name: str
* color: Optional[str]
* icon: Optional[str]
* is_default: bool
* created_at
* updated_at

Important:

* Categories are stored in PostgreSQL.
* There is no static DEFAULT_CATEGORIES list anymore.
* There is no key field anymore.

Unique constraint:

```text
uq_categories_user_id_name
```

It protects:

```text
user_id + name
```

Duplicate category flow:

```text
PostgreSQL UniqueViolation
-> repository catches IntegrityError
-> db_session.rollback()
-> CategoryAlreadyExistsError
-> router catches it
-> HTTPException 409
```

---

## Table: budgets

Fields:

* id: UUID
* user_id: UUID
* category_id: Optional[UUID]
* name: str
* limit_amount: Decimal
* currency: str
* period: weekly/monthly/yearly
* start_date: date
* end_date: Optional[date]
* created_at
* updated_at

Important:

* limit_amount replaces old monthly_limit.
* start_date replaces old month.
* period makes budget reusable for weekly/monthly/yearly.
* category_id can be None for a general budget.

Unique constraint:

```text
uq_budgets_user_id_name_period_start_date
```

It protects:

```text
user_id + name + period + start_date
```

Duplicate budget flow:

```text
PostgreSQL UniqueViolation
-> budget_repository catches IntegrityError
-> db_session.rollback()
-> BudgetAlreadyExistsError
-> budget_router catches it
-> HTTP 409
```

Budget error file:

```text
app/modules/budgets/budget_errors.py
```

Correct class:

```python
class BudgetAlreadyExistsError(Exception):
    """Raised when a user tries to create a duplicate budget."""

    pass
```

Correct import:

```python
from app.modules.budgets.budget_errors import BudgetAlreadyExistsError
```

---

## Table: goals

Fields:

* id: UUID
* user_id: UUID
* name: str
* target_amount: Decimal
* current_amount: Decimal
* currency: str
* target_date: Optional[date]
* status: active/completed/archived
* created_at
* updated_at

Important:

* target_date replaces old deadline.
* target_date is optional.
* Two goals with the same name are currently allowed.
* Duplicate Vacation goals are okay for now.

---

# ANALYTICS RESPONSE MODELS

## MonthlySummaryResponse

Fields:

* total_spent
* expenses_count

Example:

```json
{
  "total_spent": "50.00",
  "expenses_count": 1
}
```

---

## CategorySummaryItem

Fields:

* category_id
* category_name
* total_spent
* expenses_count

Important:

* If expense has no category_id, category_name should be Uncategorized.

---

## BudgetStatusItem

Fields:

* budget_id
* budget_name
* category_id
* category_name
* limit_amount
* spent
* remaining
* exceeded_amount
* is_exceeded

Example:

```json
{
  "budget_name": "Food budget",
  "limit_amount": "100.00",
  "spent": "120.00",
  "remaining": "0.00",
  "exceeded_amount": "20.00",
  "is_exceeded": true
}
```

---

## GoalProgressItem

Fields:

* goal_id
* name
* target_amount
* current_amount
* remaining_amount
* progress_percent
* status
* target_date

Example:

```json
{
  "name": "Vacation",
  "target_amount": "2000.00",
  "current_amount": "500.00",
  "remaining_amount": "1500.00",
  "progress_percent": "25.00",
  "status": "active",
  "target_date": "2026-12-31"
}
```

---

# ALEMBIC MIGRATIONS

Created migrations:

* 9a09da6421ec_create_initial_finance_tables.py
* 091f1c229ace_add_unique_constraint_to_budgets.py

Initial migration:

```python
revision = "9a09da6421ec"
down_revision = None
```

Budgets unique constraint migration:

```python
revision = "091f1c229ace"
down_revision = "9a09da6421ec"
```

Migration command already used:

```bash
python -m alembic upgrade head
```

Constraint check:

```python
inspector.get_unique_constraints("budgets")
```

Expected constraint:

```text
uq_budgets_user_id_name_period_start_date
```

---

# CURRENT API ENDPOINTS

Base prefix:

```text
/api/v1
```

Expenses:

* POST /api/v1/expenses
* GET /api/v1/expenses?user_id=...

Categories:

* POST /api/v1/categories
* GET /api/v1/categories?user_id=...

Budgets:

* POST /api/v1/budgets
* GET /api/v1/budgets?user_id=...

Goals:

* POST /api/v1/goals
* GET /api/v1/goals?user_id=...

Analytics:

* GET /api/v1/analytics/monthly-summary?user_id=...
* GET /api/v1/analytics/category-summary?user_id=...
* GET /api/v1/analytics/budget-status?user_id=...
* GET /api/v1/analytics/goal-progress?user_id=...

---

# CURRENT TEST STATUS

## Categories

Updated and passing:

* tests/integration/categories/test_categories_router.py
* tests/unit/categories/test_categories_repository.py
* tests/unit/categories/test_categories_service.py

Known passing results:

* integration categories: 3 passed
* repository categories: 3 passed
* service categories: 2 passed

Verified:

* POST /api/v1/categories -> 201
* GET /api/v1/categories?user_id=... -> 200
* duplicate category -> 409
* repository.create_category()
* repository.get_categories(user_id=...)
* service maps CategoryModel -> CategoryResponse

---

## Expenses

Updated and passing:

* tests/unit/expenses/test_expenses_repository.py
* tests/unit/expenses/test_expenses_service.py
* tests/unit/expenses/test_expenses_router.py
* tests/unit/expenses/test_schemas.py
* tests/integration/expenses/test_expenses_router.py

Known passing result:

```text
14 passed
```

Verified:

* POST /api/v1/expenses -> 201
* GET /api/v1/expenses?user_id=... -> 200
* amount = 0 -> 422
* category_id can be None
* Decimal money values are returned as strings in JSON, for example "24.99"

---

## Budgets

Updated and passing:

* tests/integration/budgets/test_budgets_router.py
* tests/unit/budgets/test_budget_repository.py
* tests/unit/budgets/test_budget_service.py
* tests/unit/budgets/test_budget_schemas.py

Known passing result:

```text
13 passed
```

Verified:

* POST /api/v1/budgets -> 201
* GET /api/v1/budgets?user_id=... -> 200
* limit_amount = 0 -> 422
* repository.create_budget()
* repository.get_budgets(user_id=...)
* duplicate budget -> BudgetAlreadyExistsError
* service maps BudgetModel -> BudgetResponse

---

## Goals

Integration tests updated and passing:

* tests/integration/goals/test_goals_router.py

Known passing result:

```text
3 passed
```

Verified:

* POST /api/v1/goals -> 201
* GET /api/v1/goals?user_id=... -> 200
* target_amount = 0 -> 422

Unit tests still need final check/update:

* tests/unit/goals/test_goals_repository.py
* tests/unit/goals/test_goals_service.py
* tests/unit/goals/test_goals_schemas.py or tests/unit/goals/test_goal_schemas.py

Important for goals schemas:

* deadline must be replaced with target_date
* user_id must be added
* currency must be added
* status must be added
* target_date is optional
* missing target_date should be accepted

---

## Analytics

Analytics tests are being updated last because analytics depends on:

* categories
* expenses
* budgets
* goals

Old analytics tests still used:

* category
* date
* monthly_limit
* month
* deadline
* expenses_storage
* budgets_storage
* goals_storage

These must be replaced with PostgreSQL/UUID data setup.

Analytics integration tests should create real data via API:

* POST /api/v1/categories
* POST /api/v1/expenses
* POST /api/v1/budgets
* POST /api/v1/goals

Analytics service tests should create real data via repositories and SessionLocal:

* category_repository.create_category()
* expenses_repository.create_expense()
* budget_repository.create_budget()
* goal_repository.create_goal()

Then call:

* analytics_service.get_monthly_summary(db_session=db_session, user_id=user_id)
* analytics_service.get_category_summary(db_session=db_session, user_id=user_id)
* analytics_service.get_budget_status(db_session=db_session, user_id=user_id)
* analytics_service.get_goal_progress(db_session=db_session, user_id=user_id)

---

# TEST CONFTST

tests/conftest.py should provide:

* client fixture
* clean_database fixture

clean_database should clean database before and after each test.

Correct delete order:

1. ExpenseModel
2. BudgetModel
3. GoalModel
4. CategoryModel

Why:

* expenses and budgets can reference categories through category_id
* categories must be deleted after dependent rows

Fixture should use yield:

```python
@pytest.fixture()
def clean_database() -> Generator[None, None, None]:
    db_session = SessionLocal()

    try:
        db_session.query(ExpenseModel).delete()
        db_session.query(BudgetModel).delete()
        db_session.query(GoalModel).delete()
        db_session.query(CategoryModel).delete()
        db_session.commit()

        yield

        db_session.query(ExpenseModel).delete()
        db_session.query(BudgetModel).delete()
        db_session.query(GoalModel).delete()
        db_session.query(CategoryModel).delete()
        db_session.commit()
    finally:
        db_session.close()
```

---

# COMMON TEST COMMANDS

Run one file:

```bash
python -m pytest tests/path/to/file.py -v
```

Run one module:

```bash
python -m pytest tests/unit/goals tests/integration/goals -v
```

Run all tests:

```bash
python -m pytest -v
```

Stop on first failure:

```bash
python -m pytest -x -v
```

Find test files:

```bash
find tests/unit/<module> -maxdepth 1 -type f
```

Find module files:

```bash
find app/modules/<module> -maxdepth 1 -type f
```

Search for error classes:

```bash
grep -R "ErrorName" app/modules/<module>
```

---

# SWAGGER MANUAL CHECKS ALREADY DONE

Expenses:

* POST /api/v1/expenses -> 201
* GET /api/v1/expenses -> 200
* Works with UUID, user_id, category_id, title, expense_date

Categories:

* POST /api/v1/categories -> 201
* GET /api/v1/categories -> 200
* duplicate category -> 409 Conflict

Budgets:

* POST /api/v1/budgets -> 201
* GET /api/v1/budgets -> 200
* duplicate budget -> 409 Conflict

Goals:

* POST /api/v1/goals -> 201
* GET /api/v1/goals -> 200
* Goal progress analytics works

Analytics:

* GET /api/v1/analytics/monthly-summary -> 200
* GET /api/v1/analytics/category-summary -> 200
* GET /api/v1/analytics/budget-status -> 200
* GET /api/v1/analytics/goal-progress -> 200

---

# OCR NOTES

OCR is planned for later.

Important:

* OCR is not perfect.
* OCR errors are common.
* User confirmation is required.

Receipt barcodes or QR codes usually do NOT contain full purchase details.

They usually contain:

* receipt ID
* date/time
* total amount
* tax data

They usually do NOT contain:

* full list of items
* categories

Correct approach:

```text
OCR + user confirmation
```

---

# MVP GOAL VERSION 0.1

The MVP should answer 3 key questions:

1. How much did I spend this month?
2. What did I spend money on?
3. Where did I exceed my limits?

---

# MVP FEATURES VERSION 0.1

## Mobile App

### 1. Authentication

* Sign up / login via Supabase
* user_id should come from JWT/current user dependency later

---

### 2. Add Expense Manually

Current backend fields:

* user_id
* category_id
* title
* amount
* currency
* expense_date
* description
* source

Later mobile UX can show:

* date picker
* amount input
* category picker
* title input
* optional description

---

### 3. Expense List

Should support:

* view all expenses for current user
* filter by month
* filter by category
* filter by date range later

---

### 4. Dashboard

Should show:

* total monthly spending
* spending by category
* budget status
* goal progress
* basic charts

---

### 5. Budget Limits

Budget fields:

* name
* limit_amount
* currency
* period
* start_date
* end_date
* optional category_id

App should show:

* current spending
* remaining budget
* exceeded amount
* exceeded flag

---

### 6. Financial Goals

Goal fields:

* name
* target_amount
* current_amount
* currency
* optional target_date
* status

Calculations:

* remaining amount
* progress percent
* required monthly savings later

---

### 7. Simple Strategy Without ML

Example:

```text
Required savings: 150 EUR/month
Current savings: 100 EUR/month
Gap: 50 EUR/month
```

Suggestions:

* reduce cafe spending
* cut subscriptions
* lower flexible spending

---

# WEB APP VERSION 0.1

Simple landing page:

* product description
* features
* benefits
* CTA buttons
* demo/waitlist later

Later web dashboard:

* expenses table
* charts
* budgets
* goals
* analytics

---

# PROJECT TEST STRUCTURE ROADMAP

Future quality structure:

```text
valor/
|
|-- quality/
|   |-- README.md
|   |
|   |-- functional/
|   |   |-- api/
|   |   |   |-- postman/
|   |   |   |-- pytest/
|   |   |   |-- contract/
|   |   |
|   |   |-- web/
|   |   |   |-- playwright/
|   |   |   |-- e2e/
|   |   |
|   |   |-- mobile/
|   |       |-- detox/
|   |       |-- e2e/
|   |
|   |-- non-functional/
|   |   |-- performance/
|   |   |   |-- k6/
|   |   |   |-- reports/
|   |   |
|   |   |-- security/
|   |   |   |-- zap/
|   |   |   |-- dependency-scan/
|   |   |   |-- reports/
|   |   |
|   |   |-- accessibility/
|   |   |   |-- axe/
|   |   |   |-- reports/
|   |   |
|   |   |-- reliability/
|   |       |-- smoke/
|   |       |-- health-checks/
|   |
|   |-- test-data/
|   |   |-- users.json
|   |   |-- expenses.json
|   |   |-- goals.json
|   |   |-- receipts/
|   |
|   |-- test-plans/
|   |   |-- mvp-test-plan.md
|   |   |-- regression-test-plan.md
|   |   |-- release-checklist.md
|   |
|   |-- reports/
|       |-- functional/
|       |-- performance/
|       |-- security/
|       |-- accessibility/
```

Testing stack roadmap:

* API tests: pytest + httpx
* Contract tests: Pact / Schemathesis
* Web E2E: Playwright
* Mobile E2E: Detox
* Unit tests web: Vitest
* Unit tests mobile: Jest
* Backend tests: pytest
* Performance: k6
* Security: OWASP ZAP
* Accessibility: axe-core / Playwright axe
* Linting: ESLint + Ruff
* Formatting: Prettier + Black
* CI/CD: GitHub Actions

---

# DEVELOPMENT ROADMAP

## Phase 1 — Backend MVP

Done:

* FastAPI backend
* Swagger/OpenAPI
* Health endpoint
* Root endpoint
* Expenses module
* Categories module
* Budgets module
* Goals module
* Analytics module
* PostgreSQL integration
* SQLAlchemy models
* Alembic migrations
* UUID architecture
* Categories unique constraint
* Budgets unique constraint

In progress:

* Updating all tests from old in-memory architecture to PostgreSQL/UUID architecture
* Finishing goals unit tests
* Finishing analytics tests

Next:

* Run full pytest suite
* Add separate test database
* Improve test fixtures
* Add Auth module preparation

---

## Phase 2 — Auth

Planned:

* Supabase Auth
* JWT validation
* current_user dependency
* remove user_id from request body/query
* use authenticated user_id from token

---

## Phase 3 — Mobile MVP

Planned:

* React Native Expo app
* login/signup
* add expense
* expense list
* categories
* budgets
* goals
* dashboard

---

## Phase 4 — Web MVP

Planned:

* Next.js landing page
* dashboard later
* demo/waitlist later

---

## Phase 5 — OCR

Planned:

* upload receipt image
* integrate OCR API
* extract text
* detect amount
* detect date
* detect merchant
* user confirmation screen

---

## Phase 6 — Categorization Rules

Rule-based system:

* Lidl, Aldi -> Food
* Zara -> Clothing
* Shell -> Transport
* Starbucks -> Cafes

Later:

* user-defined rules
* merchant normalization
* simple suggestion engine

---

## Phase 7 — DevOps

Planned:

* Docker
* Docker Compose
* CI/CD
* GitHub Actions
* linting
* formatting
* test database
* deployment strategy


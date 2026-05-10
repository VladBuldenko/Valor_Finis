
⚠️ Notes:
- OCR is **not perfect**
- Errors are common
- User confirmation is required

---

# ❗ Barcode / QR Code on Receipts

📌 Important clarification:

Most receipt barcodes or QR codes **DO NOT contain full purchase details**.

### They usually contain:
- receipt ID  
- date/time  
- total amount  
- tax data  

### They usually do NOT contain:
- ❌ list of items  
- ❌ categories  

👉 **Conclusion:**  
The correct approach is:

> OCR + user confirmation

---

# 🎯 MVP Goal (Version 0.1)

Answer 3 key questions:

1. 💸 How much did I spend this month?  
2. 🧾 What did I spend money on?  
3. 🚨 Where did I exceed my limits?  

---

# 🚀 MVP Features (Version 0.1)

## 📱 Mobile App

### 🔐 1. Authentication
- Sign up / Login via Supabase

---

### ➕ 2. Add Expense (Manual)

Fields:
- date  
- amount  
- category  
- description  

Categories:
- 🍔 Food  
- 👕 Clothing  
- 🚗 Transport  
- ☕ Cafés  
- 🏠 Home  
- 💊 Health  
- 📦 Subscriptions  
- 🔄 Other  

---

### 📋 3. Expense List

- View all expenses  
- Filter by month  
- Filter by category  

---

### 📊 4. Dashboard

- Total monthly spending  
- Spending by category  
- Basic charts  

---

### 🚦 5. Budget Limits

User defines monthly limits:

| Category | Limit |
|----------|------|
| Food | 400€ |
| Cafés | 150€ |

App shows:
- current spending  
- remaining budget  
- exceeded limits  

---

### 🎯 6. Financial Goals

Fields:
- goal name  
- target amount  
- deadline  
- current progress  

Calculations:
- remaining amount  
- required monthly savings  

---

### 🧠 7. Simple Strategy (No ML)

Example:

> Required: 150€/month  
> Current: 100€/month  
> Gap: 50€/month  

👉 Suggestions:
- reduce café spending  
- cut subscriptions  

---

# 🌐 Web App (Version 0.1)

Simple landing page:

- product description  
- features  
- benefits  
- CTA buttons:
  - 🚀 "Try Demo"  
  - 📬 "Join Waitlist"  

---

# ⚙️ Backend (FastAPI)

Main API endpoints:

- `/auth`
- `/expenses`
- `/categories`
- `/limits`
- `/goals`

---

# 🗄 Database Structure

## 🧾 Table: `expenses`

- id  
- user_id  
- date  
- amount  
- category  
- description  
- created_at  

---

## 🚦 Table: `limits`

- id  
- user_id  
- category  
- monthly_limit  

---

## 🎯 Table: `goals`

- id  
- user_id  
- name  
- target_amount  
- current_amount  
- deadline  

---

# 📁 Project Test Structure
valor/
│
├── quality/
│   ├── README.md
│   │
│   ├── functional/
│   │   ├── api/
│   │   │   ├── postman/
│   │   │   ├── pytest/
│   │   │   └── contract/
│   │   │
│   │   ├── web/
│   │   │   ├── playwright/
│   │   │   └── e2e/
│   │   │
│   │   └── mobile/
│   │       ├── detox/
│   │       └── e2e/
│   │
│   ├── non-functional/
│   │   ├── performance/
│   │   │   ├── k6/
│   │   │   └── reports/
│   │   │
│   │   ├── security/
│   │   │   ├── zap/
│   │   │   ├── dependency-scan/
│   │   │   └── reports/
│   │   │
│   │   ├── accessibility/
│   │   │   ├── axe/
│   │   │   └── reports/
│   │   │
│   │   └── reliability/
│   │       ├── smoke/
│   │       └── health-checks/
│   │
│   ├── test-data/
│   │   ├── users.json
│   │   ├── expenses.json
│   │   ├── goals.json
│   │   └── receipts/
│   │
│   ├── test-plans/
│   │   ├── mvp-test-plan.md
│   │   ├── regression-test-plan.md
│   │   └── release-checklist.md
│   │
│   └── reports/
│       ├── functional/
│       ├── performance/
│       ├── security/
│       └── accessibility/

API tests:          pytest + httpx
Contract tests:     Pact / Schemathesis
Web E2E:            Playwright
Mobile E2E:         Detox
Unit tests web:     Vitest
Unit tests mobile:  Jest
Backend tests:      pytest
Performance:        k6
Security:           OWASP ZAP
Accessibility:      axe-core / Playwright axe
Linting:            ESLint + Ruff
Formatting:         Prettier + Black
CI/CD:              GitHub Actions
---

# 🧱 Development Plan

## 🚀 Phase 1 — MVP

- [ ] Setup Supabase (DB + Auth)  
- [ ] Build FastAPI backend  
- [ ] Implement Expenses API  
- [ ] Build mobile app:
  - add expense  
  - list expenses  
- [ ] Create dashboard  
- [ ] Add budget limits  
- [ ] Add financial goals  

---

## 📸 Phase 2 — OCR

- [ ] Upload receipt image  
- [ ] Integrate OCR API  
- [ ] Extract text  
- [ ] Detect amount  
- [ ] User confirmation  

---

## 🗂 Phase 3 — Categorization

Rule-based system:

- Lidl, Aldi → Food  
- Zara → Clothing  
- Shell → Transport  
- Starbucks → Cafés  

---

## 📊 Phase 4 — Analytics

- charts  
- monthly comparison  
- category growth  
- top expenses  

---

## 📅 Phase 5 — Planning

- spending forecast  
- scenario simulation:
  - reduce expenses  
  - increase income  
  - adjust goal timeline  

---

# 🧠 Long-Term Roadmap

## 🟢 Version 1.0
- full web dashboard  
- authentication system  
- cloud storage  

## 🟡 Version 1.5
- improved OCR  
- item-level recognition  

## 🔵 Version 2.0 (ML)
- expense prediction  
- smart recommendations  
- behavior analysis  

## 🟣 Version 3.0
- AI financial assistant  
- automatic strategy generation  

---

# ⚠️ Core Principle

Backend Roadmap — Valor API
Текущее состояние

Сейчас сделано:

FastAPI backend запускается
/health работает
Swagger docs открывается

Это значит:

сервер живой
структура app/main.py работает
проект готов к первому бизнес-модулю

Но реальной бизнес-логики пока нет.

Главная backend-цель

Сделать API, которое позволит мобильному и веб-приложению работать с данными пользователя:

расходы
категории
лимиты
цели
аналитика
пользователи
авторизация
чеки
Backend architecture

Мы используем структуру:

router.py       → принимает HTTP-запросы
schemas.py      → проверяет входные/выходные данные
service.py      → содержит бизнес-логику
repository.py   → работает с хранением данных
models.py       → описывает таблицы базы данных
Почему так

Чтобы код не превратился в кашу.

router не должен считать
service не должен знать детали SQL
repository не должен решать бизнес-правила
schemas не должны хранить данные
Этап 1 — Expenses module

Это первый настоящий backend-модуль.

Зачем

Расходы — это основа всего приложения.

Без расходов нет:

статистики
лимитов
целей
аналитики
OCR
ML
1.1 schemas.py — уже начали
Что делает

Описывает структуру данных расходов.

Зачем

Backend должен понимать:

какие данные принимать
какие данные запрещать
что возвращать обратно
Статус
ExpenseBase
ExpenseCreate
ExpenseResponse

готово или почти готово.

1.2 repository.py — следующий шаг
Что делает

Хранит расходы.

На первом этапе:

in-memory list

То есть данные будут жить только пока работает сервер.

Зачем

Чтобы сначала проверить бизнес-логику без базы данных.

Функции
create_expense()
get_expenses()
get_expense_by_id()

Для MVP сначала:

create_expense()
get_expenses()
Definition of Done
расход можно сохранить
список расходов можно получить
id создаётся автоматически
created_at создаётся автоматически
1.3 service.py
Что делает

Содержит бизнес-логику расходов.

Зачем

Все правила продукта должны быть здесь.

Примеры правил
amount должен быть больше 0
category не должна быть пустой
date обязательна
Функции
create_expense()
get_expenses()
Definition of Done
service вызывает repository
service не содержит HTTP-кода
service можно тестировать отдельно
1.4 router.py
Что делает

Создаёт API endpoints.

Зачем

Чтобы frontend мог обращаться к backend.

Endpoints
POST /expenses
GET /expenses
Definition of Done
POST /expenses появляется в /docs
GET /expenses появляется в /docs
можно создать расход через Swagger
можно получить расходы через Swagger
1.5 Подключить router в main.py
Что делает

Регистрирует expenses API внутри FastAPI-приложения.

Зачем

Без этого backend не увидит /expenses.

Definition of Done
/health работает
/expenses работает
/docs показывает expenses endpoints
1.6 Manual testing через Swagger
Что делаем

Открываем:

http://127.0.0.1:8000/docs

Проверяем:

POST /expenses
GET /expenses
Definition of Done
создали расход
получили список расходов
ошибка работает при amount <= 0
1.7 Backend tests для Expenses
Что делаем

Создаём тесты.

Зачем

Чтобы при изменениях не ломать старую логику.

Минимальные тесты
test_create_expense_success
test_create_expense_invalid_amount
test_get_expenses_success
Definition of Done
pytest проходит без ошибок
основная логика покрыта тестами
Этап 2 — Categories module
Зачем

Категории нужны, чтобы расходы не были хаотичными строками.

Например:

food
clothing
car
cafe
home
health
subscriptions
other
Функции
create_category()
get_categories()
update_category()
delete_category()

Для MVP:

get_categories()

Можно начать с фиксированного списка категорий.

Почему не сразу база

Пока достаточно константного списка.

Позже категории будут пользовательскими.

Этап 3 — Budgets / Limits module
Зачем

Пользователь должен задавать лимит на категорию.

Пример:

food → 400 EUR per month
cafe → 150 EUR per month
Функции
create_budget_limit()
get_budget_limits()
update_budget_limit()
delete_budget_limit()
Бизнес-логика
limit должен быть больше 0
category должна существовать
одна категория не должна иметь два лимита на один месяц
Definition of Done
можно создать лимит
можно получить лимиты
можно сравнить расходы с лимитом позже в analytics
Этап 4 — Goals module
Зачем

Финансовые цели — одна из ключевых идей Valor.

Пример:

Vacation
Target: 2000 EUR
Current: 500 EUR
Deadline: 2026-12-31
Функции
create_goal()
get_goals()
update_goal()
delete_goal()
calculate_required_monthly_saving()
Бизнес-логика
target_amount > 0
current_amount >= 0
deadline должна быть в будущем
Definition of Done
можно создать цель
можно получить цели
backend считает сколько нужно откладывать в месяц
Этап 5 — Analytics module
Зачем

Analytics превращает сырые расходы в полезную информацию.

Функции
get_monthly_summary()
get_category_summary()
get_budget_status()
get_goal_progress()
Что считает
общие расходы за месяц
расходы по категориям
превышение лимитов
прогресс по целям
Пример
Total spent: 1200 EUR
Food: 400 EUR
Cafe: 160 EUR
Cafe limit exceeded by 10 EUR
Definition of Done
backend возвращает готовую статистику
frontend не считает сложную бизнес-логику сам
Этап 6 — Database integration
Зачем

In-memory storage временный.

После перезапуска сервера данные исчезают.

Нужна настоящая база:

PostgreSQL через Supabase
Что делаем
SQLAlchemy models
database session
migrations
repositories using database
Порядок
1. настроить database connection
2. создать models.py
3. создать migrations
4. заменить in-memory repository на database repository
5. проверить старые endpoints
Важно

Service logic не должна сильно измениться.

Меняем только repository.

Этап 7 — Auth module
Зачем

Каждый пользователь должен видеть только свои данные.

Что добавляем
register
login
get current user
JWT / Supabase Auth
После auth все данные получают user_id
expenses.user_id
budgets.user_id
goals.user_id
Definition of Done
пользователь может зарегистрироваться
пользователь может войти
пользователь видит только свои расходы
Этап 8 — Receipts module
Зачем

Пользователь будет загружать чек.

Система позже сможет создавать расход на основе чека.

Функции
upload_receipt()
get_receipts()
extract_text_from_receipt()
connect_receipt_to_expense()
На первом этапе

Без OCR-магии.

upload image
save receipt metadata
manual confirmation
Этап 9 — OCR module
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

OCR предлагает данные
пользователь подтверждает
backend сохраняет расход
Этап 10 — Rule-based categorization
Зачем

До ML делаем простые правила.

Пример:

Lidl → food
Aldi → food
Shell → car
Zara → clothing
Starbucks → cafe
Функции
suggest_category_by_merchant()
create_merchant_rule()
get_merchant_rules()
Почему не ML

Пока нет данных.

ML без данных — бессмысленно.

Этап 11 — Advanced tests
Что добавляем
unit tests
integration tests
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
1. Health check
2. Expenses schemas
3. Expenses repository
4. Expenses service
5. Expenses router
6. Connect expenses router
7. Manual API testing
8. Expenses tests
9. Categories
10. Budgets / Limits
11. Goals
12. Analytics
13. Database
14. Auth
15. Receipts
16. OCR
17. Categorization rules
18. Advanced tests
19. Docker
20. CI/CD
Что делать прямо сейчас

Следующий конкретный шаг:

создать repository.py для Expenses

Файл:

services/api/app/modules/expenses/repository.py

Задача:

временно хранить расходы в памяти
создавать expense
возвращать список expenses
Commit strategy

После каждого логического шага делаем commit.

Примеры

После schemas:

feat: add expense schemas

После repository:

feat: add in-memory expense repository

После service:

feat: add expense service layer

После router:

feat: add expense API endpoints

После tests:

test: add expense module tests
Правила кода

Всегда используем:

SOLID
DRY
KISS
YAGNI
Clean Architecture
Separation of Concerns
Single Responsibility
Readable Code First
Важно

Перед каждой функцией пишем комментарий на английском:

What this function does
Why this function exists
Parameters
Returns
Как ты можешь мне напоминать

Когда вернёмся к backend, просто напиши:

Продолжаем backend roadmap Valor. Мы остановились на Expenses repository.py.
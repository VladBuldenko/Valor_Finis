
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

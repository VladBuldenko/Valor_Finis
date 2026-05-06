# Valor Finis
Track expenses, control budgets, and achieve financial goals.

# 💰 Home Budget Receipt Tracker

A simple **mobile + web application** for tracking personal finances, analyzing expenses, and achieving financial goals.

---

## 📌 Project Overview

**Home Budget Receipt Tracker** helps users:

- 📊 Track expenses  
- 🗂 Categorize spending  
- 🚦 Control budget limits  
- 📅 Analyze monthly spending  
- 🎯 Set financial goals  
- 🧠 Understand how to reach those goals  

⚠️ **Important:** This project follows a **build simple → then scale** approach.  
Start with a minimal version (MVP), then expand step by step.

---

# 🧱 Tech Stack

## 📱 Mobile App
- React Native (Expo)

## 🌐 Web App
- Next.js (Landing page + future dashboard)

## ⚙️ Backend API
- FastAPI (Python)

## 🗄 Database & Auth
- PostgreSQL (via Supabase)

## 📊 Analytics
- Python (pandas)

## 📸 OCR (later stage)
- Google Vision API / OCR.Space

# 📁 Project Structure

valor/
│
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── docker-compose.yml
├── package.json
├── pnpm-workspace.yaml
├── turbo.json
│
├── apps/
│   ├── mobile/
│   │   ├── app/
│   │   ├── assets/
│   │   ├── src/
│   │   │   ├── features/
│   │   │   │   ├── auth/
│   │   │   │   ├── expenses/
│   │   │   │   ├── budgets/
│   │   │   │   ├── goals/
│   │   │   │   └── dashboard/
│   │   │   ├── shared/
│   │   │   │   ├── components/
│   │   │   │   ├── hooks/
│   │   │   │   ├── api/
│   │   │   │   ├── utils/
│   │   │   │   └── constants/
│   │   │   └── navigation/
│   │   ├── app.json
│   │   └── package.json
│   │
│   └── web/
│       ├── app/
│       │   ├── page.tsx
│       │   ├── layout.tsx
│       │   ├── pricing/
│       │   ├── features/
│       │   └── waitlist/
│       ├── src/
│       │   ├── components/
│       │   ├── features/
│       │   ├── lib/
│       │   └── styles/
│       ├── public/
│       └── package.json
│
├── services/
│   └── api/
│       ├── app/
│       │   ├── main.py
│       │   ├── core/
│       │   │   ├── config.py
│       │   │   ├── security.py
│       │   │   └── errors.py
│       │   │
│       │   ├── modules/
│       │   │   ├── auth/
│       │   │   │   ├── router.py
│       │   │   │   ├── service.py
│       │   │   │   └── schemas.py
│       │   │   │
│       │   │   ├── users/
│       │   │   │   ├── router.py
│       │   │   │   ├── service.py
│       │   │   │   ├── repository.py
│       │   │   │   ├── models.py
│       │   │   │   └── schemas.py
│       │   │   │
│       │   │   ├── expenses/
│       │   │   │   ├── router.py
│       │   │   │   ├── service.py
│       │   │   │   ├── repository.py
│       │   │   │   ├── models.py
│       │   │   │   └── schemas.py
│       │   │   │
│       │   │   ├── budgets/
│       │   │   │   ├── router.py
│       │   │   │   ├── service.py
│       │   │   │   ├── repository.py
│       │   │   │   ├── models.py
│       │   │   │   └── schemas.py
│       │   │   │
│       │   │   ├── goals/
│       │   │   │   ├── router.py
│       │   │   │   ├── service.py
│       │   │   │   ├── repository.py
│       │   │   │   ├── models.py
│       │   │   │   └── schemas.py
│       │   │   │
│       │   │   ├── analytics/
│       │   │   │   ├── router.py
│       │   │   │   ├── service.py
│       │   │   │   └── schemas.py
│       │   │   │
│       │   │   └── receipts/
│       │   │       ├── router.py
│       │   │       ├── service.py
│       │   │       ├── repository.py
│       │   │       ├── models.py
│       │   │       └── schemas.py
│       │   │
│       │   ├── db/
│       │   │   ├── session.py
│       │   │   ├── base.py
│       │   │   └── migrations/
│       │   │
│       │   └── shared/
│       │       ├── utils.py
│       │       ├── constants.py
│       │       └── dependencies.py
│       │
│       ├── tests/
│       │   ├── unit/
│       │   ├── integration/
│       │   ├── e2e/
│       │   └── conftest.py
│       │
│       ├── requirements.txt
│       ├── pyproject.toml
│       └── Dockerfile
│
├── packages/
│   ├── ui/
│   │   ├── src/
│   │   │   ├── Button.tsx
│   │   │   ├── Card.tsx
│   │   │   ├── Input.tsx
│   │   │   └── index.ts
│   │   └── package.json
│   │
│   ├── types/
│   │   ├── src/
│   │   │   ├── expense.ts
│   │   │   ├── budget.ts
│   │   │   ├── goal.ts
│   │   │   ├── user.ts
│   │   │   └── index.ts
│   │   └── package.json
│   │
│   └── config/
│       ├── eslint/
│       ├── prettier/
│       └── tsconfig/
│
├── infra/
│   ├── supabase/
│   │   ├── migrations/
│   │   ├── seed.sql
│   │   └── schema.sql
│   │
│   ├── docker/
│   │   ├── api.Dockerfile
│   │   └── nginx.conf
│   │
│   └── ci/
│       └── github-actions/
│           ├── api.yml
│           ├── mobile.yml
│           └── web.yml
│
├── docs/
│   ├── architecture.md
│   ├── product-requirements.md
│   ├── api-contract.md
│   ├── database-schema.md
│   ├── roadmap.md
│   ├── decisions/
│   │   ├── 001-monorepo.md
│   │   ├── 002-tech-stack.md
│   │   └── 003-auth-supabase.md
│   │
│   └── diagrams/
│       ├── system-context.md
│       ├── data-flow.md
│       └── mobile-flow.md
│
├── scripts/
│   ├── setup.sh
│   ├── run-api.sh
│   ├── run-web.sh
│   └── reset-db.sh
│
└── .github/
    ├── workflows/
    │   ├── api-ci.yml
    │   ├── web-ci.yml
    │   └── mobile-ci.yml
    │
    ├── ISSUE_TEMPLATE/
    │   ├── bug_report.md
    │   └── feature_request.md
    │
    └── pull_request_template.md
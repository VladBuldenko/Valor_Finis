# 🛠 Development Guide — Valor

This document defines how to develop, structure, and scale the Valor project.

---

# 📌 Principles

- Build simple → then scale
- Feature-based architecture
- Clean code > clever code
- Ship fast, iterate faster
- Test what matters

---

# 🧱 Project Architecture

Valor uses a **monorepo architecture**.


apps/ → mobile + web
services/ → backend API
packages/ → shared code
infra/ → infrastructure
docs/ → documentation
quality/ → testing


---

# 🧑‍💻 Development Workflow

## 1. Pick a feature

Example:


expenses → add expense


---

## 2. Define scope

Example:


POST /expenses
GET /expenses


---

## 3. Implement backend first

- create module
- add schema
- add service
- add repository
- add route

---

## 4. Test backend

- unit test
- integration test

---

## 5. Connect frontend

- call API
- display data

---

## 6. Add UI

- simple UI first
- no overdesign

---

## 7. Add tests

- API tests
- UI tests

---

# 🧩 Backend Development (FastAPI)

## Structure


modules/
expenses/
router.py
service.py
repository.py
models.py
schemas.py


---

## Rules

- router → HTTP layer
- service → business logic
- repository → database
- schemas → validation (Pydantic)
- models → DB models

---

## Example Flow


Request → Router → Service → Repository → DB


---

# 📱 Mobile Development (React Native)

## Structure


features/
expenses/
components/
screens/
hooks/
api/


---

## Rules

- feature-based structure
- no global spaghetti
- keep components small
- separate UI and logic

---

# 🌐 Web Development (Next.js)

## Purpose

- landing page (MVP)
- later: dashboard

---

## Rules

- use server components when possible
- optimize performance
- simple UI first

---

# 🗄 Database Rules

- use PostgreSQL
- normalize data
- avoid premature optimization
- migrations must be versioned

---

# 🔌 API Design Rules

- RESTful
- predictable endpoints
- clear naming

Example:


GET /expenses
POST /expenses
PUT /expenses/{id}
DELETE /expenses/{id}


---

# 🧪 Testing Strategy

## Functional

- unit tests (pytest)
- integration tests
- E2E tests (Playwright / Detox)

---

## Non-functional

- performance (k6)
- security (OWASP ZAP)
- accessibility (axe)

---

## Rule

Test business logic first.

---

# 📦 Code Standards

## Naming

- variables → camelCase
- files → kebab-case or snake_case
- classes → PascalCase

---

## Functions

- short
- single responsibility
- no hidden logic

---

## Comments

- explain WHY, not WHAT

---

# 🔐 Security

- never store secrets in repo
- use .env files
- validate all inputs
- sanitize user data

---

# ⚡ Performance

- avoid unnecessary API calls
- paginate data
- cache where needed

---

# 🚀 CI/CD

Every PR must:

- pass tests
- pass lint
- build successfully

---

# 📊 Logging

- log errors
- log important actions
- avoid sensitive data

---

# 🔄 Versioning

Use semantic versioning:


v0.1.0 → MVP
v0.2.0 → new features
v1.0.0 → stable


---

# ⚠️ Anti-Patterns (Avoid)

- overengineering
- premature optimization
- copying without understanding
- adding ML too early
- building everything at once

---

# ✅ Development Order

Expenses
Categories
Limits
Goals
Dashboard
OCR
Analytics
ML

---

# 🎯 Definition of Done

Feature is done when:

- works end-to-end
- tested
- no critical bugs
- readable code

---

# 🚀 First Task

Implement:


POST /expenses
GET /expenses


And connect it to mobile app.

---

# 💡 Final Rule

> If it's not working in real usage — it's not done.
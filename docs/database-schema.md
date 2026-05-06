# Database Schema

## users

- id
- email
- password

---

## expenses

- id
- user_id
- amount
- category
- date

---

## limits

- id
- user_id
- category
- monthly_limit

---

## goals

- id
- user_id
- target_amount
- current_amount
- deadline
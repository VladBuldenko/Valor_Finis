# Expenses Module Functions

## 1. Create Expense

### What it does
Creates a new expense record in the system.

### How it works
- user sends expense data
- backend validates data
- backend saves expense to database
- backend returns created expense

### Example
User buys groceries for 25€.

The app creates a new expense:
- amount = 25
- category = food
- description = groceries

---

# 2. Get Expenses

### What it does
Returns a list of user expenses.

### How it works
- backend requests expenses from database
- backend returns expenses list

### Example
User opens dashboard and sees all expenses for the month.

---

# 3. Get Expense by ID

### What it does
Returns one specific expense.

### How it works
- backend receives expense ID
- backend searches database
- backend returns matching expense

### Example
User opens details of one transaction.

---

# 4. Update Expense

### What it does
Updates an existing expense.

### How it works
- backend receives updated data
- backend validates new data
- backend updates expense in database

### Example
User changes category from:
- other → food

---

# 5. Delete Expense

### What it does
Removes an expense from the system.

### How it works
- backend receives expense ID
- backend deletes expense from database

### Example
User accidentally created duplicate expense and removes it.

---

# 6. Filter Expenses

### What it does
Returns only expenses matching filter conditions.

### How it works
Backend filters expenses by:
- category
- month
- date range

### Example
User wants to see only:
- food expenses
- May 2026 expenses

---

# 7. Sort Expenses

### What it does
Changes order of returned expenses.

### How it works
Backend sorts expenses by:
- newest first
- oldest first
- highest amount
- lowest amount

### Example
User wants to see biggest expenses first.

---

# 8. Validate Expense

### What it does
Checks if expense data is correct before saving.

### How it works
Backend verifies:
- amount > 0
- category exists
- date is valid

### Example
User cannot create expense with:
- amount = -10

---

# 9. Calculate Total Expenses

### What it does
Calculates total spending amount.

### How it works
Backend sums all expense amounts.

### Example
Food:
- 20€
- 30€
- 50€

Total:
- 100€

---

# 10. Calculate Expenses by Category

### What it does
Calculates spending grouped by category.

### How it works
Backend groups expenses and calculates totals.

### Example

Food:
- 400€

Transport:
- 120€

Cafes:
- 80€

---

# MVP Functions

First MVP version only includes:

- Create Expense
- Get Expenses
- Validate Expense
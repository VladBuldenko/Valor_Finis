export type GoalStatus = "active" | "completed" | "archived";

// Mirrors backend GoalResponse (services/api/app/modules/goals/goal_schemas.py),
// which itself extends GoalBase. Money fields (target_amount, current_amount)
// arrive as JSON strings, matching every other financial contract in this app
// (see Budget in ../budgets/budget.types.ts) -- never parse them for display,
// only render the exact string the backend returns. target_date is nullable:
// a goal can be created without a target date. This slice is read-only, so
// no Create/Update input types are defined here.
export type Goal = {
  id: string;
  user_id: string;
  name: string;
  target_amount: string;
  current_amount: string;
  currency: string;
  target_date: string | null;
  status: GoalStatus;
  created_at: string;
  updated_at: string;
};

// Mirrors backend GoalCreate (services/api/app/modules/goals/goal_schemas.py).
// user_id is intentionally omitted -- it is derived from authentication on
// the server and must never be sent from the client. current_amount and
// status are intentionally omitted entirely: this UI slice does not expose
// either control, and the backend already defaults them (0 / "active") when
// omitted. currency stays optional and unsent by the create form for the
// same reason Budget's create form never sends it (see BudgetCreateInput /
// budget-create-screen.tsx) -- the app is EUR-first and the backend already
// defaults currency to "EUR". target_date is optional and nullable, matching
// the backend's `date | None` field.
export type GoalCreateInput = {
  name: string;
  target_amount: string;
  currency?: string;
  target_date?: string | null;
};

// Mirrors backend GoalUpdate (services/api/app/modules/goals/goal_schemas.py).
// Every field is optional -- an omitted field is left unchanged by the
// backend (it uses `model_dump(exclude_unset=True)`). target_date is the
// only field where an explicit null is meaningful (it clears the target
// date); the backend rejects an explicit null for name, target_amount,
// current_amount, currency, and status, so those stay plain optional values
// rather than nullable. currency is part of the backend PATCH contract but
// intentionally unused here -- Edit Goal shows currency read-only and never
// sends it (see goal-edit-screen.tsx). user_id is intentionally omitted --
// it is derived from authentication on the server.
export type GoalUpdateInput = {
  name?: string;
  target_amount?: string;
  current_amount?: string;
  currency?: string;
  target_date?: string | null;
  status?: GoalStatus;
};

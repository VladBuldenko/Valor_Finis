export type Category = {
    id: string;
    user_id: string;
    name: string;
    color: string | null;
    icon: string | null;
    // Backend-assigned key identifying a system-seeded default category
    // (e.g. "food"); null for user-created custom categories.
    system_key: string | null;
    is_default: boolean;
    // Controls whether the category appears in normal category selection
    // (Expense/Budget pickers). Hidden categories are still returned by
    // the backend when the caller requests `include_hidden=true`.
    is_visible: boolean;
    created_at: string;
    updated_at: string;
  };

// Mirrors backend CategoryCreate (services/api/app/modules/categories/schemas.py).
// user_id, is_default, is_visible, and system_key are intentionally omitted:
// user_id is derived from authentication on the server, and the other three
// are backend/system semantics that create-category input does not expose
// at all -- a category created through this input is always a normal
// visible custom category.
export type CategoryCreateInput = {
  name: string;
  color?: string | null;
  icon?: string | null;
};
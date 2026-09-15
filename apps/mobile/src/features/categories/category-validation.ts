export type CategoryFormValues = {
  name: string;
};

/**
 * Validates category create form input.
 * Kept minimal and contract-aligned (mirrors goal-validation.ts /
 * budget-validation.ts): only checks what the backend would reject before a
 * request is even sent -- an empty/whitespace-only name, or a name over the
 * backend's 80-character limit. Uniqueness (case-insensitive duplicate
 * names, including a user's own default category names) is intentionally
 * NOT duplicated here -- the backend is authoritative for that and returns
 * 409, which the create screen surfaces from the mutation's error handling.
 * Returns an error message for the first invalid field, or null when valid.
 */
export function validateCategoryForm(
  values: CategoryFormValues,
): string | null {
  const trimmedName = values.name.trim();

  if (!trimmedName) {
    return "Name is required.";
  }

  if (trimmedName.length > 80) {
    return "Name must be 80 characters or fewer.";
  }

  return null;
}

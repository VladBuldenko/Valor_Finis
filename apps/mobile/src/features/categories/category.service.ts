import { apiRequest } from "../../api/api-client";

import type { Category, CategoryCreateInput } from "./category.types";

export type GetCategoriesOptions = {
  // Mirrors the backend's `include_hidden` query parameter. Defaults to
  // false (omitted), which returns only visible categories -- this keeps
  // existing Expense/Budget/Receipt category pickers unaffected. Pass true
  // only for management views that must show hidden categories too.
  includeHidden?: boolean;
};

/**
 * Returns categories available to the authenticated user.
 *
 * Declared with a zero-argument overload (rather than a single function
 * with only an optional-object parameter) so `getCategories` stays
 * assignable to TanStack Query's `queryFn` slot when referenced point-free
 * -- `queryFn: getCategories`, as the existing Expense/Budget/Receipt
 * pickers do. A single `(options?: GetCategoriesOptions) => ...` signature
 * fails TypeScript's "weak type" check there, because none of the
 * properties TanStack passes in its QueryFunctionContext argument overlap
 * with `GetCategoriesOptions`.
 */
export function getCategories(): Promise<Category[]>;
export function getCategories(
  options: GetCategoriesOptions,
): Promise<Category[]>;
export async function getCategories(
  options?: GetCategoriesOptions,
): Promise<Category[]> {
  const path = options?.includeHidden
    ? "/api/v1/categories?include_hidden=true"
    : "/api/v1/categories";

  return apiRequest<Category[]>(path);
}

/**
 * Creates a category for the authenticated user.
 * The backend always creates it as a normal visible custom category --
 * is_visible/is_default/system_key are not part of create input at all.
 */
export async function createCategory(
  categoryData: CategoryCreateInput,
): Promise<Category> {
  return apiRequest<Category>("/api/v1/categories", {
    method: "POST",
    body: JSON.stringify(categoryData),
  });
}

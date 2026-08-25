import { apiRequest } from "../../api/api-client";

import type { Category } from "./category.types";

/**
 * Returns categories available to the authenticated user.
 */
export async function getCategories(): Promise<Category[]> {
  return apiRequest<Category[]>("/api/v1/categories");
}
import { apiRequest } from "../../api/api-client";

export async function getCategories(): Promise<unknown[]> {
  return apiRequest<unknown[]>("/api/v1/categories");
}
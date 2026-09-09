import { env } from "../config/env";
import { supabase } from "../lib/supabase";

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const {
    data: { session },
    error: sessionError,
  } = await supabase.auth.getSession();

  if (sessionError) {
    throw sessionError;
  }

  if (!session) {
    throw new Error("User is not authenticated.");
  }

  // Multipart requests (e.g. receipt uploads) must not set a manual
  // Content-Type header: the runtime fetch implementation generates the
  // correct "multipart/form-data" boundary itself. JSON requests keep the
  // existing explicit header.
  const isFormDataBody = options.body instanceof FormData;

  const response = await fetch(
    `${env.apiUrl}${path}`,
    {
      ...options,
      headers: {
        ...(isFormDataBody
          ? {}
          : { "Content-Type": "application/json" }),
        Authorization: `Bearer ${session.access_token}`,
        ...options.headers,
      },
    },
  );

  if (!response.ok) {
    const errorText = await response.text();

    throw new Error(
      `API request failed: ${response.status} ${errorText}`,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}
const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL;
const supabasePublishableKey =
  process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
const apiUrl = process.env.EXPO_PUBLIC_API_URL;

if (!supabaseUrl) {
  throw new Error("EXPO_PUBLIC_SUPABASE_URL is not configured.");
}

if (!supabasePublishableKey) {
  throw new Error(
    "EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY is not configured.",
  );
}

if (!apiUrl) {
  throw new Error("EXPO_PUBLIC_API_URL is not configured.");
}

export const env = {
  supabaseUrl,
  supabasePublishableKey,
  apiUrl,
} as const;
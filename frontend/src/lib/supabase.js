import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

// The browser only ever holds the publishable key. Sign-up and sign-in go through the
// backend (so usernames can be checked and resolved); the session it returns is stored here,
// and supabase-js keeps it refreshed.
export const supabase = url && key
  ? createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true, storageKey: "vani-auth" } })
  : null;

let token = null;
supabase?.auth.getSession().then(({ data }) => { token = data.session?.access_token ?? null; });
supabase?.auth.onAuthStateChange((_event, session) => { token = session?.access_token ?? null; });

/** Current access token, or null when signed out. */
export const accessToken = () => token;

/** Append the token to URLs used by <video>, <audio>, <a download> and EventSource,
 *  which can't send an Authorization header. */
export function withToken(url) {
  if (!url || !token || !url.startsWith("/api/")) return url;
  return `${url}${url.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(token)}`;
}

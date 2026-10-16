import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { supabase } from "./supabase.js";
import { authApi, setUnauthorizedHandler } from "./api.js";

const AuthCtx = createContext(null);

/** Session + profile. `status`: loading | signed_out | signed_in */
export function AuthProvider({ children }) {
  const [status, setStatus] = useState("loading");
  const [profile, setProfile] = useState(null);
  const [authError, setAuthError] = useState(null);

  const loadProfile = useCallback(async () => {
    try {
      const { data } = await supabase.auth.getSession();
      const metadata = data.session?.user?.user_metadata || {};
      const fullName = [metadata.full_name, metadata.name].find((name) => typeof name === "string")?.trim() || "";
      const nameParts = fullName ? fullName.split(/\s+/) : [];
      await authApi.ensureProfile({
        first_name: metadata.first_name || metadata.given_name || nameParts[0] || "",
        last_name: metadata.last_name || metadata.family_name || nameParts.slice(1).join(" "),
      });
      setProfile(await authApi.me());
      setAuthError(null);
      setStatus("signed_in");
    } catch (err) {
      await supabase?.auth.signOut();
      setProfile(null);
      setAuthError(err.message || "Couldn't finish signing in. Please try again.");
      setStatus("signed_out");
    }
  }, []);

  useEffect(() => {
    if (!supabase) { setStatus("signed_out"); return; }
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) loadProfile(); else setStatus("signed_out");
    });
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_OUT" || !session) { setProfile(null); setStatus("signed_out"); }
    });
    return () => sub.subscription.unsubscribe();
  }, [loadProfile]);

  const adopt = async ({ session, user }) => {
    await supabase.auth.setSession({ access_token: session.access_token, refresh_token: session.refresh_token });
    setProfile(user);
    setAuthError(null);
    setStatus("signed_in");
  };

  const value = {
    status,
    profile,
    authError,
    configured: !!supabase,
    signUp: async (form) => adopt(await authApi.signUp(form)),
    signIn: async (identifier, password) => adopt(await authApi.signIn(identifier, password)),
    signInWithGoogle: async (redirectTo) => {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo },
      });
      if (error) throw error;
    },
    signOut: async () => {
      await supabase?.auth.signOut();
      setProfile(null);
      setAuthError(null);
      setStatus("signed_out");
    },
  };

  useEffect(() => { setUnauthorizedHandler(() => value.signOut()); });

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

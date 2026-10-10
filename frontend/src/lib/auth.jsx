import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { supabase } from "./supabase.js";
import { authApi, setUnauthorizedHandler } from "./api.js";

const AuthCtx = createContext(null);

/** Session + profile. `status`: loading | signed_out | signed_in */
export function AuthProvider({ children }) {
  const [status, setStatus] = useState("loading");
  const [profile, setProfile] = useState(null);

  const loadProfile = useCallback(async () => {
    try {
      setProfile(await authApi.me());
      setStatus("signed_in");
    } catch {
      await supabase?.auth.signOut();
      setProfile(null);
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
    setStatus("signed_in");
  };

  const value = {
    status,
    profile,
    configured: !!supabase,
    signUp: async (form) => adopt(await authApi.signUp(form)),
    signIn: async (identifier, password) => adopt(await authApi.signIn(identifier, password)),
    signOut: async () => { await supabase?.auth.signOut(); setProfile(null); setStatus("signed_out"); },
  };

  useEffect(() => { setUnauthorizedHandler(() => value.signOut()); });

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

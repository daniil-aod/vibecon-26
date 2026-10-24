import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useApi } from "@/lib/api";

const Ctx = createContext(null);

export function FleetProvider({ children }) {
  const api = useApi();
  const [state, setState] = useState({ loading: true, user: null, fleet: null, sms_configured: false, error: null });
  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get("/me", { params: { origin: window.location.origin } });
      setState({ loading: false, error: null, ...data });
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: e }));
    }
  }, [api]);
  useEffect(() => { refresh(); }, [refresh]);
  return <Ctx.Provider value={{ ...state, refresh }}>{children}</Ctx.Provider>;
}

export const useFleet = () => useContext(Ctx);

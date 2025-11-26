import { useEffect, useState } from "react";
import { auth, onAuthState } from "../firebase";

export default function useAuth() {
  const [user, setUser] = useState(() => auth.currentUser || null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsub = onAuthState((u) => {
      setUser(u);
      setLoading(false);
    });
    return () => unsub();
  }, []);

  return { user, loading };
}

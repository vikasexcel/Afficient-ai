import { useEffect } from "react";
import { useAuth } from "@/store/auth";
import { useMe } from "@/store/me";
import { RouterProvider } from "react-router-dom";
import { router } from "@/router";

export default function App() {
  const hydrate = useAuth((s) => s.hydrate);
  const token = useAuth((s) => s.token);
  const loadMe = useMe((s) => s.load);
  const resetMe = useMe((s) => s.reset);

  useEffect(() => {
    hydrate();
  }, []);

  useEffect(() => {
    if (token) loadMe();
    else resetMe();
  }, [token]);

  return <RouterProvider router={router} />;
}

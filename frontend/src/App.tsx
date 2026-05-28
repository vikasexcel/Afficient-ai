import { useEffect } from "react";
import { useAuth } from "@/store/auth";
import { useMe } from "@/store/me";
import { useAppearance } from "@/store/appearance";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { RouterProvider } from "react-router-dom";
import { router } from "@/router";

export default function App() {
  const hydrate = useAuth((s) => s.hydrate);
  const hydrateAppearance = useAppearance((s) => s.hydrate);
  const token = useAuth((s) => s.token);
  const loadMe = useMe((s) => s.load);
  const resetMe = useMe((s) => s.reset);

  useEffect(() => {
    hydrate();
    hydrateAppearance();
  }, []);

  useEffect(() => {
    if (token) loadMe();
    else resetMe();
  }, [token]);

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem
      storageKey="afficient-theme"
    >
      <RouterProvider router={router} />
      <Toaster />
    </ThemeProvider>
  );
}

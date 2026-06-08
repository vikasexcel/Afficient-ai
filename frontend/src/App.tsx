import { useEffect } from "react";
import { useAuth } from "@/store/auth";
import { useMe } from "@/store/me";
import { useAppearance } from "@/store/appearance";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { RouterProvider } from "react-router-dom";
import { router } from "@/router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ErrorBoundary } from "@/components/ErrorBoundary";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

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
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          storageKey="afficient-theme"
        >
          <RouterProvider router={router} />
          <Toaster />
        </ThemeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

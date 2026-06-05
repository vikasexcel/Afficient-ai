import SchedulerOfflineBanner from "@/components/campaign/SchedulerOfflineBanner";
import Sidebar from "./Sidebar";
import Header from "./Header";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // Lock the outer shell to the viewport so the sidebar + header stay put
    // and only the main content area scrolls. On mobile the sidebar is an
    // off-canvas drawer so the flex shell still works.
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <Sidebar />

      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        <Header />
        <SchedulerOfflineBanner />

        <main className="app-content flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}

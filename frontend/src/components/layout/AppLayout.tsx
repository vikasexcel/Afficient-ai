import Sidebar from "./Sidebar";
import Header from "./Header";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar />

      <div
        className="
          flex-1
        "
      >
        <Header />

        <div className="app-content p-8">
          {children}
        </div>
      </div>
    </div>
  );
}
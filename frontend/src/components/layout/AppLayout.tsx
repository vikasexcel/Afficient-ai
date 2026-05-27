import Sidebar from "./Sidebar";
import Header from "./Header";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      className="
        flex
        bg-black
        text-white
      "
    >
      <Sidebar />

      <div
        className="
          flex-1
        "
      >
        <Header />

        <div
          className="
            p-8
          "
        >
          {children}
        </div>
      </div>
    </div>
  );
}
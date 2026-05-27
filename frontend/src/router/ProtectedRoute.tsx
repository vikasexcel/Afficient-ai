import { Navigate } from "react-router-dom";

import { useAuth } from "@/store/auth";

export default function ProtectedRoute({
  children,
}: {
  children: React.ReactNode;
}) {
  const token = useAuth((s) => s.token);

  if (!token) {
    return <Navigate to="/login" />;
  }

  return children;
}
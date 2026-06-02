import {
  createBrowserRouter,
} from "react-router-dom";

import Home from "@/pages/Home";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import Dashboard from "@/pages/Dashboard";
import Campaigns from "@/pages/Campaigns";
import Calls from "@/pages/Calls";
import Leads from "@/pages/Leads";
import Analytics from "@/pages/Analytics";
import Transcripts from "@/pages/Transcripts";
import Playbooks from "@/pages/Playbooks";
import Settings from "@/pages/Settings";
import ProtectedRoute from "@/router/ProtectedRoute";
import { Link } from "react-router-dom";


function NotFound() {
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex flex-col items-center justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-white/50 text-sm text-center max-w-md">
        This URL doesn&apos;t exist. Try the home page or log in.
      </p>
      <div className="flex gap-3">
        <Link
          to="/"
          className="text-sm px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500"
        >
          Home
        </Link>
        <Link
          to="/login"
          className="text-sm px-4 py-2 rounded-lg border border-white/15 hover:bg-white/5"
        >
          Log in
        </Link>
      </div>
    </div>
  );
}


export const router =
  createBrowserRouter([
    {
      path: "/",
      element: <Home />,
    },

    {
      path: "/login",
      element: <Login />,
    },

    {
      path: "/signup",
      element: <Signup />,
    },
    {
      path: "/dashboard",
      element: (
        <ProtectedRoute>
          <Dashboard />
        </ProtectedRoute>
      ),
    },

    {
      path: "/campaigns",
      element: (
        <ProtectedRoute>
          <Campaigns />
        </ProtectedRoute>
      ),
    },

    {
      path: "/calls",
      element: (
        <ProtectedRoute>
          <Calls />
        </ProtectedRoute>
      ),
    },

    {
      path: "/leads",
      element: (
        <ProtectedRoute>
          <Leads />
        </ProtectedRoute>
      ),
    },

    {
      path: "/analytics",
      element: (
        <ProtectedRoute>
          <Analytics />
        </ProtectedRoute>
      ),
    },

    {
      path: "/playbooks",
      element: (
        <ProtectedRoute>
          <Playbooks />
        </ProtectedRoute>
      ),
    },

    {
      path: "/transcripts",
      element: (
        <ProtectedRoute>
          <Transcripts />
        </ProtectedRoute>
      ),
    },

    {
      path: "/settings",
      element: (
        <ProtectedRoute>
          <Settings />
        </ProtectedRoute>
      ),
    },

    {
      path: "*",
      element: <NotFound />,
    },
  ]);
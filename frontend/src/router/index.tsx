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
import Settings from "@/pages/Settings";
import ProtectedRoute from "@/router/ProtectedRoute";


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
  ]);
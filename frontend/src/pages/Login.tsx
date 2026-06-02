// import { useForm } from "react-hook-form";

// import {
//   Card,
//   CardContent,
//   CardHeader,
//   CardTitle,
// } from "@/components/ui/card";

// import { Button } from "@/components/ui/button";

// import { Input } from "@/components/ui/input";
// import { login } from "@/services/auth";
// import { useAuth } from "@/store/auth";
// import { useNavigate } from "react-router-dom";
// type Form = {
//   email: string;
//   password: string;
// };

// export default function Login() {
//   const {
//     register,
//     handleSubmit,
//   } = useForm<Form>();

//   const nav = useNavigate();

//   const setAuth = useAuth((s) => s.setAuth);

//   const submit = async (data: Form) => {
//     try {
//       const res = await login(data);
//       setAuth(res.access_token, res.refresh_token);
//       nav("/dashboard");
//     } catch {
//       alert("Invalid login");
//     }
//   };

//   return (
//     <div
//       className="
//         min-h-screen
//         grid
//         place-items-center
//         bg-zinc-950
//       "
//     >
//       <Card className="w-[420px]">
//         <CardHeader>
//           <CardTitle>
//             Login
//           </CardTitle>
//         </CardHeader>

//         <CardContent>
//           <form
//             onSubmit={handleSubmit(submit)}
//             className="
//               space-y-4
//             "
//           >
//             <Input
//               placeholder="Email"
//               {...register("email")}
//             />

//             <Input
//               type="password"
//               placeholder="Password"
//               {...register("password")}
//             />

//             <Button className="w-full">
//               Continue
//             </Button>
//           </form>
//         </CardContent>
//       </Card>
//     </div>
//   );
// }



import { useForm } from "react-hook-form";
import { useNavigate, Link } from "react-router-dom";
import { useState } from "react";
import { login } from "@/services/auth";
import { useAuth } from "@/store/auth";

type Form = {
  email: string;
  password: string;
};

export default function Login() {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Form>();

  const nav = useNavigate();
  const setAuth = useAuth((s) => s.setAuth);
  const [error, setError] = useState("");

  const submit = async (data: Form) => {
    setError("");
    try {
      const res = await login(data);
      setAuth(res.access_token, res.refresh_token);
      nav("/dashboard");
    } catch {
      setError("Invalid email or password. Please try again.");
    }
  };

  return (
    <div className="min-h-screen bg-[#07070a] flex font-sans">

      {/* Left branding panel */}
      <div className="hidden lg:flex w-[380px] xl:w-[420px] flex-shrink-0 flex-col justify-between p-8 xl:p-10 border-r border-white/[0.05] relative overflow-hidden">
        {/* Glow */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse 80% 60% at 10% 90%, rgba(109,40,217,0.22) 0%, transparent 65%)",
          }}
        />

        {/* Logo */}
        <span
          className="relative text-sm font-semibold tracking-[0.18em] text-white/80"
          style={{ fontFamily: "'DM Mono', monospace" }}
        >
          AIF<span className="text-violet-400">F</span>ICIENT
        </span>

        {/* Stat cluster */}
        <div className="relative space-y-5">
          <p
            className="text-[13px] text-white/30 uppercase tracking-widest font-medium mb-6"
            style={{ fontFamily: "'DM Mono', monospace" }}
          >
            Live metrics
          </p>
          {[
            { num: "284", label: "Calls made today" },
            { num: "34", label: "Meetings booked" },
            { num: "12%", label: "Conversion rate" },
          ].map((s) => (
            <div key={s.label} className="flex items-baseline gap-3">
              <span
                className="text-[32px] font-semibold text-white/90 leading-none"
                style={{ fontFamily: "'DM Mono', monospace" }}
              >
                {s.num}
              </span>
              <span className="text-[13px] text-white/35">{s.label}</span>
            </div>
          ))}
        </div>

        {/* Bottom tagline */}
        <p
          className="relative text-[15px] text-white/25 leading-relaxed"
          style={{ fontFamily: "'DM Serif Display', serif" }}
        >
          Your AI sales team is running right now.
        </p>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center px-4 sm:px-6 py-10 sm:py-14">
        <div className="w-full max-w-[380px]">

          {/* Mobile logo */}
          <div className="lg:hidden mb-8">
            <span
              className="text-sm font-semibold tracking-[0.18em] text-white/80"
              style={{ fontFamily: "'DM Mono', monospace" }}
            >
              AIF<span className="text-violet-400">F</span>ICIENT
            </span>
          </div>

          <h1
            className="text-[28px] font-semibold text-white leading-tight mb-1"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            Welcome back
          </h1>
          <p className="text-[13px] text-white/38 mb-8">
            Sign in to your account to continue
          </p>

          <form onSubmit={handleSubmit(submit)} noValidate>

            {/* Email */}
            <div className="mb-3">
              <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-1.5">
                Email address
              </label>
              <input
                type="email"
                placeholder="you@company.com"
                autoComplete="email"
                className={`w-full bg-white/[0.04] border rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all
                  ${errors.email
                    ? "border-red-500/50 focus:border-red-500/70 focus:ring-2 focus:ring-red-500/10"
                    : "border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10"
                  }`}
                {...register("email", { required: true })}
              />
            </div>

            {/* Password */}
            <div className="mb-2">
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-[11px] font-medium text-white/40 tracking-wide">
                  Password
                </label>
                <span className="text-[11px] text-violet-400/70 hover:text-violet-400 cursor-pointer transition-colors">
                  Forgot password?
                </span>
              </div>
              <input
                type="password"
                placeholder="••••••••"
                autoComplete="current-password"
                className={`w-full bg-white/[0.04] border rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all
                  ${errors.password
                    ? "border-red-500/50 focus:border-red-500/70 focus:ring-2 focus:ring-red-500/10"
                    : "border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10"
                  }`}
                {...register("password", { required: true })}
              />
            </div>

            {/* API error */}
            {error && (
              <div className="mt-4 px-3 py-2.5 rounded-[8px] bg-red-500/8 border border-red-500/20 text-[12px] text-red-400">
                {error}
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full mt-6 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[14px] font-semibold py-2.5 rounded-[9px] transition-all hover:scale-[1.01] active:scale-[0.99]"
            >
              {isSubmitting ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                  Signing in…
                </span>
              ) : (
                "Continue →"
              )}
            </button>

            {/* Divider */}
            <div className="flex items-center gap-3 my-5">
              <div className="flex-1 h-px bg-white/[0.06]" />
              <span className="text-[11px] text-white/20">or</span>
              <div className="flex-1 h-px bg-white/[0.06]" />
            </div>

            {/* Signup link */}
            <p className="text-center text-[13px] text-white/35">
              Don't have an account?{" "}
              <Link
                to="/signup"
                className="text-violet-400 hover:text-violet-300 transition-colors font-medium"
              >
                Sign up free
              </Link>
            </p>
          </form>

          {/* Security note */}
          <div className="mt-10 flex items-center justify-center gap-2 text-[11px] text-white/18">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-50">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            Secured with JWT + OAuth 2.0
          </div>
        </div>
      </div>
    </div>
  );
}
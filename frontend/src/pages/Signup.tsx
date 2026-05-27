// import { useForm } from "react-hook-form";
// import { useNavigate } from "react-router-dom";

// import {
//   Card,
//   CardContent,
//   CardHeader,
//   CardTitle,
// } from "@/components/ui/card";

// import { Button } from "@/components/ui/button";

// import { Input } from "@/components/ui/input";
// import { signup } from "@/services/auth";

// type Form = {
//   full_name: string;
//   organization: string;
//   email: string;
//   password: string;
// };

// export default function Signup() {
//   const {
//     register,
//     handleSubmit,
//   } = useForm<Form>();

//   const nav = useNavigate();

//   const submit = async (v: Form) => {
//     await signup(v);
//     nav("/login");
//   };

//   return (
//     <div
//       className="
//         min-h-screen
//         grid
//         place-items-center
//         bg-black
//       "
//     >
//       <Card className="w-[480px]">
//         <CardHeader>
//           <CardTitle>
//             Create Account
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
//               placeholder="Name"
//               {...register("full_name")}
//             />

//             <Input
//               placeholder="Organization"
//               {...register("organization")}
//             />

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
//               Create Account
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
import { signup } from "@/services/auth";

type Form = {
  full_name: string;
  organization: string;
  email: string;
  password: string;
};

export default function Signup() {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Form>();

  const nav = useNavigate();
  const [error, setError] = useState("");

  const submit = async (v: Form) => {
    setError("");
    try {
      await signup(v);
      nav("/login");
    } catch {
      setError("Something went wrong. Please try again.");
    }
  };

  return (
    <div className="min-h-screen bg-[#07070a] flex font-sans">

      {/* Left panel — branding */}
      <div className="hidden lg:flex w-[440px] flex-shrink-0 flex-col justify-between p-10 border-r border-white/[0.05] relative overflow-hidden">
        {/* Glow */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse 80% 60% at 20% 80%, rgba(109,40,217,0.2) 0%, transparent 70%)",
          }}
        />

        {/* Logo */}
        <span
          className="relative text-sm font-semibold tracking-[0.18em] text-white/80"
          style={{ fontFamily: "'DM Mono', monospace" }}
        >
          AIF<span className="text-violet-400">F</span>ICIENT
        </span>

        {/* Center quote */}
        <div className="relative">
          <p
            className="text-[28px] leading-snug font-semibold text-white/90 mb-6"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            "Booked 18 meetings in the first week without lifting a finger."
          </p>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-violet-500/20 flex items-center justify-center text-violet-300 text-xs font-semibold">
              SR
            </div>
            <div>
              <div className="text-[13px] text-white/70 font-medium">Sarah R.</div>
              <div className="text-[12px] text-white/35">Head of Sales, Finlo</div>
            </div>
          </div>
        </div>

        {/* Feature bullets */}
        <div className="relative space-y-3">
          {[
            "Live AI outbound calling",
            "Auto meeting booking",
            "HubSpot & Salesforce sync",
          ].map((f) => (
            <div key={f} className="flex items-center gap-2.5">
              <div className="w-4 h-4 rounded-full bg-violet-500/15 flex items-center justify-center flex-shrink-0">
                <svg width="9" height="9" viewBox="0 0 9 9" fill="none">
                  <path d="M1.5 4.5L3.5 6.5L7.5 2.5" stroke="#a78bfa" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <span className="text-[13px] text-white/45">{f}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center px-6 py-14">
        <div className="w-full max-w-[400px]">

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
            Create your account
          </h1>
          <p className="text-[13px] text-white/38 mb-8">
            Start your free pilot — no credit card required
          </p>

          <form onSubmit={handleSubmit(submit)} noValidate>

            {/* Row: name + org */}
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-1.5">
                  Full name
                </label>
                <input
                  placeholder="Jane Smith"
                  className={`w-full bg-white/[0.04] border rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all
                    ${errors.full_name
                      ? "border-red-500/50 focus:border-red-500/70 focus:ring-2 focus:ring-red-500/10"
                      : "border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10"
                    }`}
                  {...register("full_name", { required: true })}
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-1.5">
                  Organization
                </label>
                <input
                  placeholder="Acme Inc."
                  className={`w-full bg-white/[0.04] border rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all
                    ${errors.organization
                      ? "border-red-500/50 focus:border-red-500/70 focus:ring-2 focus:ring-red-500/10"
                      : "border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10"
                    }`}
                  {...register("organization", { required: true })}
                />
              </div>
            </div>

            {/* Email */}
            <div className="mb-3">
              <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-1.5">
                Work email
              </label>
              <input
                type="email"
                placeholder="jane@company.com"
                className={`w-full bg-white/[0.04] border rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all
                  ${errors.email
                    ? "border-red-500/50 focus:border-red-500/70 focus:ring-2 focus:ring-red-500/10"
                    : "border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10"
                  }`}
                {...register("email", { required: true })}
              />
            </div>

            {/* Password */}
            <div className="mb-6">
              <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-1.5">
                Password
              </label>
              <input
                type="password"
                placeholder="Min. 8 characters"
                className={`w-full bg-white/[0.04] border rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all
                  ${errors.password
                    ? "border-red-500/50 focus:border-red-500/70 focus:ring-2 focus:ring-red-500/10"
                    : "border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10"
                  }`}
                {...register("password", { required: true, minLength: 8 })}
              />
              {errors.password?.type === "minLength" && (
                <p className="text-[11px] text-red-400 mt-1.5">Must be at least 8 characters</p>
              )}
            </div>

            {/* API error */}
            {error && (
              <div className="mb-4 px-3 py-2.5 rounded-[8px] bg-red-500/8 border border-red-500/20 text-[12px] text-red-400">
                {error}
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[14px] font-semibold py-2.5 rounded-[9px] transition-all hover:scale-[1.01] active:scale-[0.99]"
            >
              {isSubmitting ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                  </svg>
                  Creating account…
                </span>
              ) : (
                "Create account →"
              )}
            </button>

            {/* Terms */}
            <p className="text-[11px] text-white/25 text-center mt-4 leading-relaxed">
              By continuing you agree to our{" "}
              <span className="text-violet-400/70 hover:text-violet-400 cursor-pointer transition-colors">Terms of Service</span>
              {" "}and{" "}
              <span className="text-violet-400/70 hover:text-violet-400 cursor-pointer transition-colors">Privacy Policy</span>
            </p>

            {/* Divider */}
            <div className="flex items-center gap-3 my-5">
              <div className="flex-1 h-px bg-white/[0.06]" />
              <span className="text-[11px] text-white/20">or</span>
              <div className="flex-1 h-px bg-white/[0.06]" />
            </div>

            {/* Login link */}
            <p className="text-center text-[13px] text-white/35">
              Already have an account?{" "}
              <Link to="/login" className="text-violet-400 hover:text-violet-300 transition-colors font-medium">
                Sign in
              </Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
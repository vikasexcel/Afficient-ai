import { useForm } from "react-hook-form";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useState } from "react";
import { resetPassword, validatePassword, formatAuthError } from "@/services/auth";

type Form = {
  new_password: string;
  confirm_password: string;
};

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const nav = useNavigate();

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<Form>();

  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const submit = async (data: Form) => {
    setError("");
    const pwError = validatePassword(data.new_password);
    if (pwError) { setError(pwError); return; }
    if (data.new_password !== data.confirm_password) {
      setError("Passwords do not match.");
      return;
    }
    try {
      await resetPassword(token, data.new_password);
      setSuccess(true);
      setTimeout(() => nav("/login"), 3000);
    } catch (err) {
      setError(formatAuthError(err));
    }
  };

  return (
    <div className="min-h-screen bg-[#07070a] flex items-center justify-center px-4 font-sans">
      <div className="w-full max-w-[380px]">

        {/* Logo */}
        <div className="mb-8">
          <Link
            to="/login"
            className="text-sm font-semibold tracking-[0.18em] text-white/80 hover:text-white transition-colors"
            style={{ fontFamily: "'DM Mono', monospace" }}
          >
            AIF<span className="text-violet-400">F</span>ICIENT
          </Link>
        </div>

        {!token ? (
          <div className="text-center">
            <p className="text-[14px] text-white/50 mb-4">
              Invalid or missing reset link.
            </p>
            <Link
              to="/login"
              className="text-violet-400 hover:text-violet-300 text-[13px] font-medium transition-colors"
            >
              Back to sign in
            </Link>
          </div>
        ) : success ? (
          <div className="px-4 py-5 rounded-[10px] bg-violet-500/10 border border-violet-500/25 text-center">
            <div className="flex items-center justify-center mb-3">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-violet-400">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            </div>
            <p className="text-[15px] font-semibold text-white mb-1">Password updated</p>
            <p className="text-[13px] text-white/45">
              Redirecting you to sign in…
            </p>
          </div>
        ) : (
          <>
            <h1
              className="text-[26px] font-semibold text-white leading-tight mb-1"
              style={{ fontFamily: "'DM Serif Display', serif" }}
            >
              Choose a new password
            </h1>
            <p className="text-[13px] text-white/38 mb-8">
              Must be at least 8 characters with a letter and a number or symbol.
            </p>

            <form onSubmit={handleSubmit(submit)} noValidate>
              <div className="mb-3">
                <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-1.5">
                  New password
                </label>
                <div className="relative">
                  <input
                    type={showNew ? "text" : "password"}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    className={`w-full bg-white/[0.04] border rounded-[8px] px-3 py-2.5 pr-9 text-[13px] text-white placeholder-white/20 outline-none transition-all
                      ${errors.new_password
                        ? "border-red-500/50 focus:border-red-500/70 focus:ring-2 focus:ring-red-500/10"
                        : "border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10"
                      }`}
                    {...register("new_password", { required: true })}
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    onClick={() => setShowNew((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors"
                  >
                    {showNew ? (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                        <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                        <line x1="1" y1="1" x2="23" y2="23" />
                      </svg>
                    ) : (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              <div className="mb-4">
                <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-1.5">
                  Confirm password
                </label>
                <div className="relative">
                  <input
                    type={showConfirm ? "text" : "password"}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    className={`w-full bg-white/[0.04] border rounded-[8px] px-3 py-2.5 pr-9 text-[13px] text-white placeholder-white/20 outline-none transition-all
                      ${errors.confirm_password
                        ? "border-red-500/50 focus:border-red-500/70 focus:ring-2 focus:ring-red-500/10"
                        : "border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10"
                      }`}
                    {...register("confirm_password", {
                      required: true,
                      validate: (v) => v === watch("new_password") || "Passwords do not match",
                    })}
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    onClick={() => setShowConfirm((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors"
                  >
                    {showConfirm ? (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                        <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                        <line x1="1" y1="1" x2="23" y2="23" />
                      </svg>
                    ) : (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    )}
                  </button>
                </div>
                {errors.confirm_password && (
                  <p className="mt-1 text-[11px] text-red-400">{errors.confirm_password.message}</p>
                )}
              </div>

              {error && (
                <div className="mb-4 px-3 py-2.5 rounded-[8px] bg-red-500/8 border border-red-500/20 text-[12px] text-red-400">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[14px] font-semibold py-2.5 rounded-[9px] transition-all hover:scale-[1.01] active:scale-[0.99]"
              >
                {isSubmitting ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                    </svg>
                    Updating…
                  </span>
                ) : (
                  "Set new password →"
                )}
              </button>
            </form>

            <p className="mt-6 text-center text-[12px] text-white/25">
              <Link to="/login" className="hover:text-white/50 transition-colors">
                Back to sign in
              </Link>
            </p>
          </>
        )}

        <div className="mt-10 flex items-center justify-center gap-2 text-[11px] text-white/18">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-50">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          Secured with JWT + OAuth 2.0
        </div>
      </div>
    </div>
  );
}

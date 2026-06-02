import { Link } from "react-router-dom";
import { useEffect, useRef } from "react";

export default function Home() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const dots: { x: number; y: number; vx: number; vy: number; r: number; o: number }[] = [];
    for (let i = 0; i < 60; i++) {
      dots.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        r: Math.random() * 1.5 + 0.5,
        o: Math.random() * 0.4 + 0.1,
      });
    }

    let raf: number;
    function draw() {
      if (!ctx || !canvas) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const d of dots) {
        d.x += d.vx;
        d.y += d.vy;
        if (d.x < 0 || d.x > canvas.width) d.vx *= -1;
        if (d.y < 0 || d.y > canvas.height) d.vy *= -1;
        ctx.beginPath();
        ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(139,92,246,${d.o})`;
        ctx.fill();
      }
      for (let i = 0; i < dots.length; i++) {
        for (let j = i + 1; j < dots.length; j++) {
          const dx = dots[i].x - dots[j].x;
          const dy = dots[i].y - dots[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            ctx.beginPath();
            ctx.moveTo(dots[i].x, dots[i].y);
            ctx.lineTo(dots[j].x, dots[j].y);
            ctx.strokeStyle = `rgba(139,92,246,${0.08 * (1 - dist / 120)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }
      raf = requestAnimationFrame(draw);
    }
    draw();

    const onResize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <div className="relative min-h-screen bg-[#07070a] overflow-hidden font-sans">
      {/* Animated background */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full pointer-events-none"
      />

      {/* Radial glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 60% 50% at 50% 0%, rgba(109,40,217,0.18) 0%, transparent 70%)",
        }}
      />

      {/* Nav */}
      <header className="relative z-10 flex items-center justify-between gap-3 px-4 sm:px-6 lg:px-10 h-16 border-b border-white/[0.05]">
        <span
          className="text-sm font-semibold tracking-[0.18em] text-white/90"
          style={{ fontFamily: "'DM Mono', monospace" }}
        >
          AIF<span className="text-violet-400">F</span>ICIENT
        </span>

        <nav className="flex items-center gap-1.5 sm:gap-2">
          <Link
            to="/login"
            className="px-3 sm:px-4 py-[7px] text-[13px] text-white/55 hover:text-white/90 transition-colors rounded-lg hover:bg-white/[0.05] font-medium"
          >
            Login
          </Link>
          <Link
            to="/signup"
            className="px-3 sm:px-4 py-[7px] text-[13px] font-semibold text-white rounded-lg bg-violet-600 hover:bg-violet-500 transition-colors"
          >
            Get started
          </Link>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative z-10 flex flex-col items-center justify-center text-center pt-16 sm:pt-24 lg:pt-28 pb-12 sm:pb-16 lg:pb-20 px-4 sm:px-6">

        {/* Badge */}
        <div className="inline-flex items-center gap-2 px-3 sm:px-3.5 py-1.5 rounded-full border border-violet-500/25 bg-violet-500/8 mb-6 sm:mb-9">
          <span className="w-[6px] h-[6px] rounded-full bg-violet-400 animate-pulse" />
          <span className="text-[11px] sm:text-[12px] text-violet-300 font-medium tracking-wide">
            AI-powered outbound sales
          </span>
        </div>

        {/* Headline */}
        <h1
          className="text-[34px] sm:text-[44px] md:text-[54px] lg:text-[62px] leading-[1.08] font-semibold text-white max-w-[640px] tracking-tight"
          style={{ fontFamily: "'DM Serif Display', serif" }}
        >
          Your sales team,{" "}
          <em className="not-italic text-violet-400">on autopilot</em>
        </h1>

        <p className="mt-4 sm:mt-5 text-[14px] sm:text-[16px] text-white/40 max-w-[440px] leading-relaxed">
          Autonomous AI agents make live outbound calls, qualify prospects, handle
          objections, and book meetings — 24/7.
        </p>

        {/* CTAs */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 mt-8 sm:mt-10 w-full max-w-[320px] sm:max-w-none sm:w-auto">
          <Link
            to="/signup"
            className="px-6 py-3 rounded-xl text-[14px] font-semibold text-white bg-violet-600 hover:bg-violet-500 transition-all hover:scale-[1.02] active:scale-[0.99] text-center"
          >
            Get Started
          </Link>
          <Link
            to="#"
            className="px-6 py-3 rounded-xl text-[14px] font-medium text-white/60 border border-white/[0.12] hover:border-white/25 hover:text-white/90 transition-all text-center"
          >
            See a demo ↗
          </Link>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-3 mt-12 sm:mt-16 border border-white/[0.06] rounded-2xl overflow-hidden bg-white/[0.02] w-full max-w-[640px]">
          {[
            { num: "97%", label: "Transcription accuracy" },
            { num: "<200ms", label: "Voice latency" },
            { num: "3×", label: "More meetings booked" },
          ].map((s, i) => (
            <div
              key={i}
              className="px-6 sm:px-8 lg:px-10 py-5 text-center border-b sm:border-b-0 sm:border-r border-white/[0.06] last:border-b-0 sm:last:border-r-0"
            >
              <div
                className="text-[22px] font-semibold text-white"
                style={{ fontFamily: "'DM Mono', monospace" }}
              >
                {s.num}
              </div>
              <div className="text-[12px] text-white/35 mt-1">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Feature grid */}
      <section className="relative z-10 mx-4 sm:mx-6 lg:mx-10 mb-12 sm:mb-16">
        <div className="grid grid-cols-1 md:grid-cols-3 rounded-2xl overflow-hidden border border-white/[0.06]">
          {[
            {
              icon: (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.64 12 19.79 19.79 0 0 1 1.56 3.44 2 2 0 0 1 3.54 1.25h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.81a16 16 0 0 0 5.55 5.55l.88-.88a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 21 16z"/>
                  <path d="M14.05 3a9 9 0 0 1 8 7.94M14.05 7A5 5 0 0 1 18 11"/>
                </svg>
              ),
              title: "Live AI calling",
              desc: "Natural voice conversations using GPT-4o with real-time barge-in detection and objection handling.",
            },
            {
              icon: (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                  <line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>
                  <line x1="3" y1="10" x2="21" y2="10"/>
                  <path d="m9 16 2 2 4-4"/>
                </svg>
              ),
              title: "Auto meeting booking",
              desc: "Qualified prospects get slots booked directly into Google or Outlook calendars instantly.",
            },
            {
              icon: (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
                  <line x1="6" y1="20" x2="6" y2="14"/>
                </svg>
              ),
              title: "Live analytics",
              desc: "Real-time dashboard with conversion funnels, call transcripts, and CRM sync to HubSpot & Salesforce.",
            },
          ].map((f, i) => (
            <div
              key={i}
              className="bg-[#0c0c10] p-6 sm:p-8 border-b md:border-b-0 md:border-r border-white/[0.06] last:border-b-0 md:last:border-r-0 group hover:bg-[#0f0f14] transition-colors"
            >
              <div className="w-10 h-10 rounded-xl bg-violet-500/10 flex items-center justify-center text-violet-400 mb-5 group-hover:bg-violet-500/15 transition-colors">
                {f.icon}
              </div>
              <div className="text-[14px] font-semibold text-white mb-2">{f.title}</div>
              <div className="text-[13px] text-white/38 leading-relaxed">{f.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Footer strip */}
      <footer className="relative z-10 border-t border-white/[0.05] px-4 sm:px-6 lg:px-10 py-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <span
          className="text-[12px] text-white/20 tracking-widest"
          style={{ fontFamily: "'DM Mono', monospace" }}
        >
          AIFFICIENT © 2026
        </span>
        <div className="flex flex-wrap gap-4 sm:gap-6">
          {["Privacy", "Terms", "Docs"].map((l) => (
            <span
              key={l}
              className="text-[12px] text-white/25 hover:text-white/55 cursor-pointer transition-colors"
            >
              {l}
            </span>
          ))}
        </div>
      </footer>
    </div>
  );
}
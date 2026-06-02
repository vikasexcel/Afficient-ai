"""Serialise :class:`BenchmarkRecorder` samples to JSON + HTML.

Two outputs land in ``backend/tests/reports/``:

* ``latency_report.json`` — machine-readable, stable schema:
  ``{generated_at, duration_s, totals, categories: {cat: [stats...]}}``.
* ``performance_report.html`` — single-file dashboard with one table per
  category, a summary row at the top, and basic conditional formatting
  (red P99 cells when the metric breaches the per-category SLO).

The pytest session hook in ``tests/latency/conftest.py`` calls
:func:`write_reports` at session-finish. The same function is safe to
call from a script (e.g. ``python -m tests.reports``).

No third-party deps — the HTML is hand-rolled so the test image doesn't
need jinja or pandas just to render a table.
"""

from __future__ import annotations

import html
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests._support.benchmark import BenchmarkRecorder, BenchmarkStats, get_recorder


# Per-category SLO thresholds (ms). Cells exceeding the P99 threshold are
# highlighted in red on the HTML report. Anything not listed has no SLO.
DEFAULT_SLOS_MS: dict[str, dict[str, float]] = {
    "api": {"p99_ms": 500.0, "avg_ms": 100.0},
    "db": {"p99_ms": 100.0, "avg_ms": 20.0},
    "redis": {"p99_ms": 25.0, "avg_ms": 5.0},
    "auth": {"p99_ms": 1500.0, "avg_ms": 400.0},
    "jwt": {"p99_ms": 10.0, "avg_ms": 2.0},
    "livekit": {"p99_ms": 1500.0, "avg_ms": 600.0},
    "deepgram_stt": {"p99_ms": 1500.0, "avg_ms": 500.0},
    "openai_gpt": {"p99_ms": 4000.0, "avg_ms": 1500.0},
    "elevenlabs_tts": {"p99_ms": 2500.0, "avg_ms": 900.0},
    "twilio": {"p99_ms": 2000.0, "avg_ms": 800.0},
    "voice_pipeline": {"p99_ms": 6000.0, "avg_ms": 2500.0},
    "barge_in": {"p99_ms": 400.0, "avg_ms": 150.0},
}


def _reports_dir() -> Path:
    """Resolve the absolute reports directory next to this package."""

    here = Path(__file__).resolve().parent.parent
    path = here / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def build_payload(
    recorder: BenchmarkRecorder | None = None,
    *,
    slos: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Materialise the JSON payload that ``latency_report.json`` contains."""

    rec = recorder or get_recorder()
    stats = rec.stats()
    slo_map = slos or DEFAULT_SLOS_MS

    by_category: dict[str, list[dict[str, Any]]] = {}
    for s in stats:
        item = s.to_dict()
        cat_slo = slo_map.get(s.category)
        if cat_slo:
            item["slo"] = cat_slo
            item["slo_breach"] = _evaluate_slo(s, cat_slo)
        by_category.setdefault(s.category, []).append(item)

    total_samples = sum(s.count for s in stats)
    total_failures = sum(s.failures for s in stats)
    overall_success_rate = (
        (total_samples - total_failures) / total_samples
        if total_samples
        else 1.0
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.time() - rec.started_at, 3),
        "totals": {
            "samples": total_samples,
            "failures": total_failures,
            "categories": len(by_category),
            "metrics": len(stats),
            "overall_success_rate": round(overall_success_rate, 4),
        },
        "slos": slo_map,
        "categories": by_category,
    }


def _evaluate_slo(stat: BenchmarkStats, slo: dict[str, float]) -> dict[str, bool]:
    """Compare a stat against its category SLO and return per-metric flags."""

    breach: dict[str, bool] = {}
    for key, threshold in slo.items():
        observed = getattr(stat, key, None)
        if observed is None:
            continue
        breach[key] = float(observed) > float(threshold)
    return breach


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


_CATEGORY_LABELS = {
    "api": "API endpoints",
    "db": "Database queries",
    "redis": "Redis operations",
    "auth": "Authentication flow",
    "jwt": "JWT token ops",
    "livekit": "LiveKit (room + token)",
    "deepgram_stt": "Deepgram STT",
    "openai_gpt": "OpenAI / GPT",
    "elevenlabs_tts": "ElevenLabs TTS",
    "twilio": "Twilio telephony",
    "voice_pipeline": "Voice pipeline (E2E)",
    "barge_in": "Barge-in detection",
    "csv_parser": "CSV parser",
    "perf": "General performance",
}


def _row_color(stat: dict[str, Any]) -> str:
    breach = stat.get("slo_breach") or {}
    if any(breach.values()):
        return "#ffe6e6"
    return ""


def _cell_class(name: str, stat: dict[str, Any]) -> str:
    breach = stat.get("slo_breach") or {}
    if breach.get(name):
        return "breach"
    return ""


def render_html(payload: dict[str, Any]) -> str:
    """Render the dashboard. Pure-string templating, no jinja dependency."""

    cats = payload["categories"]
    totals = payload["totals"]

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           margin: 24px; color: #1a1a1a; }
    h1 { font-size: 22px; margin: 0 0 4px; }
    h2 { font-size: 16px; margin: 24px 0 8px; }
    .meta { color: #555; font-size: 13px; margin-bottom: 16px; }
    .summary { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
    .card { border: 1px solid #ddd; border-radius: 6px; padding: 12px 16px; min-width: 140px;
            background: #fafafa; }
    .card .v { font-size: 22px; font-weight: 600; }
    .card .k { color: #555; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { border: 1px solid #e0e0e0; padding: 6px 8px; text-align: right; }
    th { background: #f3f4f6; text-align: left; font-weight: 600; }
    th.num, td.num { text-align: right; }
    td.name, th.name { text-align: left; }
    td.breach { background: #ffd2d2; font-weight: 600; }
    tr.fail td.name { color: #b00020; }
    .footer { color: #999; font-size: 11px; margin-top: 32px; }
    .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px;
             background: #e7f0ff; color: #1d4ed8; margin-left: 6px; }
    .badge.ok { background: #e6f7ec; color: #16723b; }
    .badge.fail { background: #fde8e8; color: #b00020; }
    """

    parts: list[str] = []
    parts.append("<!doctype html><html><head>")
    parts.append("<meta charset='utf-8'>")
    parts.append("<title>Aifficient — Latency &amp; Performance Report</title>")
    parts.append(f"<style>{css}</style>")
    parts.append("</head><body>")
    parts.append("<h1>Aifficient — Latency &amp; Performance Report</h1>")
    parts.append(
        f"<div class='meta'>Generated {html.escape(payload['generated_at'])} "
        f"— recorder uptime {payload['duration_s']:.2f}s</div>"
    )

    success_pct = totals["overall_success_rate"] * 100
    success_badge_cls = "ok" if success_pct >= 99.0 else "fail"
    parts.append("<div class='summary'>")
    for k, v in [
        ("Categories", totals["categories"]),
        ("Metrics", totals["metrics"]),
        ("Samples", totals["samples"]),
        ("Failures", totals["failures"]),
    ]:
        parts.append(
            f"<div class='card'><div class='k'>{html.escape(k)}</div>"
            f"<div class='v'>{v}</div></div>"
        )
    parts.append(
        f"<div class='card'><div class='k'>Success rate</div>"
        f"<div class='v'>{success_pct:.2f}% "
        f"<span class='badge {success_badge_cls}'>"
        f"{'OK' if success_badge_cls == 'ok' else 'CHECK'}</span></div></div>"
    )
    parts.append("</div>")

    for cat in sorted(cats.keys()):
        label = _CATEGORY_LABELS.get(cat, cat)
        parts.append(f"<h2>{html.escape(label)} <span class='badge'>{html.escape(cat)}</span></h2>")
        parts.append("<table><thead><tr>")
        for col in (
            "Metric",
            "Count",
            "OK",
            "Fail",
            "Avg ms",
            "Min ms",
            "Max ms",
            "P50 ms",
            "P95 ms",
            "P99 ms",
            "Stddev",
            "Success",
        ):
            cls = "name" if col == "Metric" else "num"
            parts.append(f"<th class='{cls}'>{html.escape(col)}</th>")
        parts.append("</tr></thead><tbody>")

        for stat in sorted(cats[cat], key=lambda s: s["name"]):
            row_bg = _row_color(stat)
            row_attr = f" style='background:{row_bg}'" if row_bg else ""
            row_cls = " class='fail'" if stat["failures"] > 0 else ""
            parts.append(f"<tr{row_cls}{row_attr}>")
            parts.append(f"<td class='name'>{html.escape(stat['name'])}</td>")
            parts.append(f"<td class='num'>{stat['count']}</td>")
            parts.append(f"<td class='num'>{stat['successes']}</td>")
            parts.append(f"<td class='num'>{stat['failures']}</td>")
            parts.append(
                f"<td class='num {_cell_class('avg_ms', stat)}'>{stat['avg_ms']:.2f}</td>"
            )
            parts.append(f"<td class='num'>{stat['min_ms']:.2f}</td>")
            parts.append(f"<td class='num'>{stat['max_ms']:.2f}</td>")
            parts.append(
                f"<td class='num {_cell_class('p50_ms', stat)}'>{stat['p50_ms']:.2f}</td>"
            )
            parts.append(
                f"<td class='num {_cell_class('p95_ms', stat)}'>{stat['p95_ms']:.2f}</td>"
            )
            parts.append(
                f"<td class='num {_cell_class('p99_ms', stat)}'>{stat['p99_ms']:.2f}</td>"
            )
            parts.append(f"<td class='num'>{stat['stddev_ms']:.2f}</td>")
            parts.append(
                f"<td class='num'>{stat['success_rate'] * 100:.2f}%</td>"
            )
            parts.append("</tr>")
        parts.append("</tbody></table>")

    parts.append(
        "<div class='footer'>SLO breaches are highlighted in red. "
        "Set <code>RUN_EXTERNAL_BENCH=1</code> to include live-provider numbers.</div>"
    )
    parts.append("</body></html>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Top-level writer
# ---------------------------------------------------------------------------


def write_reports(
    recorder: BenchmarkRecorder | None = None,
    *,
    out_dir: Path | None = None,
    slos: dict[str, dict[str, float]] | None = None,
) -> tuple[Path, Path] | None:
    """Persist ``latency_report.json`` + ``performance_report.html``.

    Returns ``(json_path, html_path)`` or ``None`` if the recorder is
    empty (no samples → nothing to report; we skip writing so tools
    don't trip over a stale empty file).
    """

    rec = recorder or get_recorder()
    if not rec.samples:
        return None

    target = out_dir or _reports_dir()
    target.mkdir(parents=True, exist_ok=True)
    payload = build_payload(rec, slos=slos)
    json_path = target / "latency_report.json"
    html_path = target / "performance_report.html"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    html_path.write_text(render_html(payload))
    return json_path, html_path


# ---------------------------------------------------------------------------
# Console summary (printed at pytest session-finish for quick eyeballing)
# ---------------------------------------------------------------------------


def format_console_summary(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    totals = payload["totals"]
    lines.append("")
    lines.append("=" * 78)
    lines.append("Aifficient — Latency & Performance Summary")
    lines.append("=" * 78)
    lines.append(
        f"  categories={totals['categories']}  metrics={totals['metrics']}  "
        f"samples={totals['samples']}  failures={totals['failures']}  "
        f"success={totals['overall_success_rate'] * 100:.2f}%"
    )
    for cat in sorted(payload["categories"].keys()):
        lines.append(f"\n[{cat}]")
        for stat in sorted(payload["categories"][cat], key=lambda s: s["name"]):
            breach = stat.get("slo_breach") or {}
            flag = " *" if any(breach.values()) else ""
            lines.append(
                f"  {stat['name']:<42}  n={stat['count']:<4}  "
                f"avg={stat['avg_ms']:>7.2f}ms  "
                f"p95={stat['p95_ms']:>7.2f}ms  "
                f"p99={stat['p99_ms']:>7.2f}ms  "
                f"ok={stat['success_rate'] * 100:>6.2f}%{flag}"
            )
    lines.append("=" * 78)
    return "\n".join(lines)


# Make the module runnable for ad-hoc snapshots:
#   python -m tests._support.reporter
if __name__ == "__main__":  # pragma: no cover - manual entry point
    out = write_reports()
    if out is None:
        print("No samples recorded; nothing to write.")
    else:
        print(f"Wrote {out[0]} and {out[1]}")

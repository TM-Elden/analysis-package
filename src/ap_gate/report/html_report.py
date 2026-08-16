"""Self-contained HTML report (MVP doc section 9): one file, inline CSS, dark neutral, no external fonts."""

from __future__ import annotations

import html
from typing import Any

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1rem;
  background: #14161a; color: #e6e8eb;
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
main { max-width: 860px; margin: 0 auto; }
h1 { font-size: 1.3rem; margin: 0 0 0.25rem; }
.sub { color: #9aa1ab; margin: 0 0 1.5rem; font-size: 0.9rem; }
.badge {
  display: inline-block; padding: 0.3rem 0.8rem; border-radius: 999px;
  font-weight: 600; font-size: 0.85rem; letter-spacing: 0.03em; margin-bottom: 1.5rem;
}
.badge.pass { background: #163a24; color: #6fe3a0; border: 1px solid #29613f; }
.badge.fail { background: #3a1616; color: #ff8a8a; border: 1px solid #612929; }
.meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.5rem 1.5rem; margin-bottom: 1.5rem; }
.meta div { font-size: 0.85rem; }
.meta span { display: block; color: #9aa1ab; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
th, td { text-align: left; padding: 0.6rem 0.6rem; border-bottom: 1px solid #262a30; vertical-align: top; }
th { color: #9aa1ab; font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
td.result { white-space: nowrap; font-weight: 600; }
td.result.pass { color: #6fe3a0; }
td.result.fail { color: #ff8a8a; }
td.result.skip { color: #9aa1ab; }
td.msg { white-space: pre-wrap; word-break: break-word; }
tr.waived td.result { color: #e3c56f; }
code { background: #1c2026; padding: 0.1rem 0.35rem; border-radius: 4px; font-size: 0.85em; }
footer { margin-top: 2rem; color: #6b7280; font-size: 0.78rem; }
"""


def to_html(report: dict[str, Any]) -> str:
    overall = report.get("overall", "fail")
    pkg = report.get("package", {})
    results_by_id = {r["check_id"]: r for r in report.get("results", [])}
    evidence_by_id = {e["check_id"]: e for e in report.get("evidence", [])}

    rows = []
    for check_id in results_by_id:
        result = results_by_id[check_id]
        evidence = evidence_by_id.get(check_id, {})
        css_result = "pass" if result["waived"] else result["result"]
        row_class = "waived" if result["waived"] else ""
        label = result["result"] + (" (waived)" if result["waived"] else "")
        message = html.escape(evidence.get("message", "")) or "&mdash;"
        rows.append(
            f'<tr class="{row_class}">'
            f'<td><code>{html.escape(check_id)}</code></td>'
            f'<td class="result {css_result}">{html.escape(label)}</td>'
            f'<td class="msg">{message}</td>'
            f"</tr>"
        )

    badge_class = "pass" if overall == "pass" else "fail"
    badge_text = "PASS" if overall == "pass" else "FAIL"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fathm L1 report - {html.escape(str(report.get("package_id", "")))}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
  <h1>fathm L1 report</h1>
  <p class="sub">Analysis Package structural validation ({html.escape(report.get("validator", ""))})</p>
  <span class="badge {badge_class}">{badge_text}</span>
  <div class="meta">
    <div><span>Package ID</span>{html.escape(str(report.get("package_id", "")))}</div>
    <div><span>Title</span>{html.escape(str(pkg.get("title", "")))}</div>
    <div><span>As of</span>{html.escape(str(pkg.get("as_of", "")))}</div>
    <div><span>QA status</span>{html.escape(str(pkg.get("qa_status", "")))}</div>
    <div><span>Profile</span>{html.escape(str(pkg.get("profile", "")))}</div>
    <div><span>Checked at</span>{html.escape(str(report.get("checks_run_at", "")))}</div>
  </div>
  <table>
    <thead><tr><th>Check</th><th>Result</th><th>Details</th></tr></thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  <footer>Powered by the Analysis Package standard - ap-gate is the L1 structural gate.</footer>
</main>
</body>
</html>
"""

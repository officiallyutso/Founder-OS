"""Local web dashboard for Founder OS.

A single auto-refreshing page (localhost only) that shows the agent's live state:
self-description, business snapshot (CRM / goals / projects / runway), today's LLM
usage + cost, pending approvals, recent turns (traces), and recent actions.

Run standalone:   python -m dashboard.app
Or it starts automatically alongside the bot (DASHBOARD_ENABLED=true) in main.py,
served on http://localhost:<DASHBOARD_PORT> (default 8787).
"""
import html
import logging
import threading

from flask import Flask, jsonify

logger = logging.getLogger(__name__)
app = Flask(__name__)


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:
        logger.debug(f"[dashboard] {fn} failed: {e}")
        return default


def collect_state() -> dict:
    from agent import about, budget, finance, store
    from memory import world_model
    import agent.trace as trace
    return {
        "about": _safe(about.describe, {}),
        "snapshot": _safe(world_model.build_snapshot, {}),
        "usage": _safe(budget.status, {}),
        "finance": _safe(finance.summary, {}),
        "approvals": _safe(store.list_pending_approvals, []),
        "goals": _safe(lambda: store.list_goals("active"), []),
        "traces": _safe(lambda: trace.recent(10), []),
        "actions": _safe(lambda: store.recent_actions(15), []),
        "usage_history": _safe(lambda: store.usage_history(7), []),
    }


@app.route("/api/state")
def api_state():
    return jsonify(collect_state())


@app.route("/")
def index():
    return render(collect_state())


# ── HTML rendering (no template engine; keeps it dependency-light) ────────────

_CSS = """
* { box-sizing: border-box; }
body { margin:0; font-family: -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       background:#0b1020; color:#e6e9f2; }
header { padding:20px 28px; background:linear-gradient(90deg,#111a3a,#0b1020);
         border-bottom:1px solid #1e2a52; }
h1 { margin:0; font-size:20px; } .sub { color:#8fa0c8; font-size:13px; margin-top:4px; }
.wrap { padding:20px 28px; display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
        gap:16px; }
.card { background:#121a35; border:1px solid #1e2a52; border-radius:12px; padding:16px 18px; }
.card h2 { margin:0 0 12px; font-size:14px; text-transform:uppercase; letter-spacing:.06em;
           color:#9db0e0; }
.kv { display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid #18224a;
      font-size:14px; } .kv:last-child{border-bottom:none;} .kv .v{color:#fff;font-weight:600;}
.pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }
.ok{background:#16331f;color:#5fe08a;}
.warn{background:#3a2f13;color:#f4c16b;} .crit{background:#3a1620;color:#ff7a90;}
.muted{color:#8fa0c8;} ul{margin:6px 0 0;padding-left:18px;} li{padding:3px 0;font-size:13.5px;}
.row{font-size:13px;padding:6px 0;border-bottom:1px solid #18224a;} .row:last-child{border:none;}
.tag{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#9db0e0;}
.bar{height:7px;background:#1e2a52;border-radius:6px;overflow:hidden;margin-top:4px;}
.bar > i{display:block;height:100%;background:#3b82f6;}
footer{padding:14px 28px;color:#5c6a93;font-size:12px;}
"""


def esc(x) -> str:
    return html.escape(str(x))


def _kv(label, value) -> str:
    return f'<div class="kv"><span class="muted">{esc(label)}</span><span class="v">{esc(value)}</span></div>'


def _status_pill(status: str) -> str:
    cls = {"healthy": "ok", "warning": "warn", "critical": "crit"}.get(status, "muted")
    return f'<span class="pill {cls}">{esc(status)}</span>'


def render(s: dict) -> str:
    about = s.get("about") or {}
    snap = s.get("snapshot") or {}
    usage = s.get("usage") or {}
    fin = s.get("finance") or {}
    crm = snap.get("crm") or {}

    cards = []

    # Identity
    cats = about.get("tools_by_category") or {}
    cards.append(f"""<div class="card"><h2>Agent</h2>
        {_kv("Name", about.get("name","Founder OS"))}
        {_kv("Built by", about.get("built_by","Utso (@officiallyutso)"))}
        {_kv("Tools", about.get("total_tools","?"))}
        {_kv("Categories", len(cats))}
        <div class="muted" style="margin-top:8px;font-size:13px;">{esc(about.get("tagline",""))}</div>
    </div>""")

    # Business snapshot
    cards.append(f"""<div class="card"><h2>Business snapshot</h2>
        {_kv("Contacts", crm.get("total_contacts", 0))}
        {_kv("Follow-ups due", crm.get("followups_due", 0))}
        {_kv("Open tasks", snap.get("tasks_open", 0))}
        {_kv("Active goals", len(snap.get("goals_active") or []))}
        {_kv("Open projects", len(snap.get("projects_open") or []))}
        {_kv("Pending approvals", snap.get("approvals_pending", 0))}
    </div>""")

    # Finance / runway
    if fin.get("set"):
        runway = fin.get("runway") or (f"{fin.get('runway_months')} months" if fin.get("runway_months") is not None else "—")
        cards.append(f"""<div class="card"><h2>Runway {_status_pill(fin.get("status",""))}</h2>
            {_kv("Cash", f"${fin.get('cash',0):,.0f}")}
            {_kv("Monthly burn", f"${fin.get('monthly_burn',0):,.0f}")}
            {_kv("MRR", f"${fin.get('mrr',0):,.0f}")}
            {_kv("Net burn", f"${fin.get('net_burn',0):,.0f}/mo")}
            {_kv("Runway", runway)}
        </div>""")
    else:
        cards.append("""<div class="card"><h2>Runway</h2>
            <div class="muted">No financials recorded yet. Tell the agent your cash, burn and MRR.</div></div>""")

    # Usage / cost
    cards.append(f"""<div class="card"><h2>Today's usage</h2>
        {_kv("LLM calls", usage.get("llm_calls", 0))}
        {_kv("Prompt tokens", usage.get("prompt_tokens", 0))}
        {_kv("Completion tokens", usage.get("completion_tokens", 0))}
        {_kv("Est. cost", f"${usage.get('est_cost_usd',0)}")}
        {_kv("Autonomy", usage.get("autonomy_level","?"))}
        {_kv("Paused", usage.get("paused", False))}
    </div>""")

    # Goals
    goals = s.get("goals") or []
    goals_html = "".join(f"<li>{esc(g.get('title',''))}</li>" for g in goals[:8]) or '<li class="muted">No active goals.</li>'
    cards.append(f'<div class="card"><h2>Active goals</h2><ul>{goals_html}</ul></div>')

    # Pending approvals
    appr = s.get("approvals") or []
    appr_html = "".join(
        f'<div class="row"><span class="tag">#{esc(a.get("id"))}</span> {esc((a.get("summary") or "")[:120])}</div>'
        for a in appr[:8]) or '<div class="muted">Nothing waiting for approval.</div>'
    cards.append(f'<div class="card"><h2>Pending approvals</h2>{appr_html}</div>')

    # Recent turns
    traces = s.get("traces") or []
    tr_html = "".join(
        f'<div class="row"><span class="tag">{esc(t.get("actor"))}</span> {esc((t.get("message") or "")[:70])}'
        f'<br><span class="muted">{esc(", ".join(t.get("tools") or []) or "no tools")} · {esc(t.get("duration_s"))}s</span></div>'
        for t in traces[:8]) or '<div class="muted">No turns yet today.</div>'
    cards.append(f'<div class="card"><h2>Recent turns</h2>{tr_html}</div>')

    # Recent actions
    actions = s.get("actions") or []
    act_html = "".join(
        f'<div class="row"><span class="tag">{esc(a.get("tool_name"))}</span> '
        f'<span class="muted">{esc(a.get("actor"))} · {esc((a.get("created_at") or "")[:16])}</span></div>'
        for a in actions[:12]) or '<div class="muted">No actions logged.</div>'
    cards.append(f'<div class="card"><h2>Recent actions</h2>{act_html}</div>')

    body = "\n".join(cards)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>Founder OS — Dashboard</title><style>{_CSS}</style></head>
<body>
<header><h1>🛰 Founder OS — live dashboard</h1>
<div class="sub">Auto-refreshes every 15s · built by Utso (@officiallyutso)</div></header>
<div class="wrap">{body}</div>
<footer>Local control panel · data read from your machine only.</footer>
</body></html>"""


def start_in_thread(port: int = None):
    """Start the dashboard on a daemon thread so it runs alongside the bot."""
    from config import config
    port = port or config.dashboard_port
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    def _run():
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)

    t = threading.Thread(target=_run, daemon=True, name="dashboard")
    t.start()
    logger.info(f"[Dashboard] Serving at http://localhost:{port}")
    return t


if __name__ == "__main__":
    from config import config
    logging.basicConfig(level=logging.INFO)
    print(f"Dashboard at http://localhost:{config.dashboard_port}")
    app.run(host="127.0.0.1", port=config.dashboard_port, debug=False)

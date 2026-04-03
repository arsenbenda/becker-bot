"""
ArsLucri — Polymarket Intelligence Dashboard
Clean, minimal layout. No custom CSS. Native Streamlit components.
"""
import streamlit as st
import json, math, time
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timezone
from pathlib import Path

from api_caps import remaining as api_remaining, MAX_CALLS_PER_DAY, MAX_COST_PER_DAY
from shared_state import (
    calc_polymarket_fee, calc_round_trip_fees,
    load_config, save_config, load_trades, load_positions,
    load_bot_status, get_api_key, set_api_key, api_keys_available,
    LOG_FILE, DEFAULT_CONFIG, BASE_DIR
)

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

st.set_page_config(page_title="ArsLucri", page_icon=":material/monitoring:", layout="wide")

# ── Only CSS: tighten top padding ──
st.markdown("<style>.block-container{padding-top:1rem;}</style>", unsafe_allow_html=True)

# ── Plotly defaults (no margin/font — set per chart to avoid conflicts) ──
PBG = "rgba(0,0,0,0)"
GC = "rgba(128,128,128,0.12)"
GREEN, RED, YELLOW, PURPLE, BLUE = "#3fb950", "#f85149", "#e3b341", "#8862f3", "#2f9ae7"
FONT_COLOR = "#c9d1d9"
MUTED = "#8b949e"


# ═══════════════════════════════════════════════
# Chart builders
# ═══════════════════════════════════════════════

def _layout(height=250, **kw):
    """Base layout dict — call once per figure."""
    base = dict(
        paper_bgcolor=PBG, plot_bgcolor=PBG,
        font=dict(color=FONT_COLOR, size=12),
        margin=dict(l=0, r=0, t=30, b=0),
        height=height,
    )
    base.update(kw)
    return base


def gauge_chart(title, pct, max_v=100):
    pct = min(float(pct), max_v)
    color = GREEN if pct < 60 else (YELLOW if pct < 85 else RED)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=pct,
        number=dict(suffix="%", font=dict(size=28, color=FONT_COLOR)),
        title=dict(text=title, font=dict(size=12, color=MUTED)),
        gauge=dict(
            axis=dict(range=[0, max_v], tickcolor="#30363d", tickfont=dict(color=MUTED, size=9)),
            bar=dict(color=color, thickness=0.7), bgcolor="#21262d", borderwidth=0,
            steps=[
                dict(range=[0, max_v*0.33], color="rgba(63,185,80,0.05)"),
                dict(range=[max_v*0.33, max_v*0.66], color="rgba(227,179,65,0.05)"),
                dict(range=[max_v*0.66, max_v], color="rgba(248,81,73,0.05)"),
            ],
        )
    ))
    fig.update_layout(**_layout(height=180, margin=dict(l=15, r=15, t=40, b=5)))
    return fig


def bankroll_line(status, start_val):
    """
    Hybrid equity curve:
    1. Historical: reconstruct from closed trades (step-function, accurate)
    2. Live: append recent mark-to-market scans (smooth, real-time)
    """
    # ── Part 1: Historical equity from closed trades ──
    closed = [p for p in positions if p.get("status") == "closed" and p.get("closed_at")]
    closed_sorted = sorted(closed, key=lambda x: x.get("closed_at", ""))

    hist_times = [pd.to_datetime(closed_sorted[0].get("opened_at", closed_sorted[0].get("closed_at"))).tz_localize(None) - pd.Timedelta(hours=1)] if closed_sorted else []
    hist_vals = [start_val] if closed_sorted else []

    running = start_val
    for c in closed_sorted:
        try:
            ts = pd.to_datetime(c.get("closed_at")).tz_localize(None)
            net_pnl = float(c.get("net_pnl", c.get("pnl", 0)))
            running += net_pnl
            hist_times.append(ts)
            hist_vals.append(round(running, 2))
        except Exception:
            pass

    # ── Part 2: Live mark-to-market from recent scans ──
    hist = status.get("scan_history", [])
    live_times, live_vals = [], []
    for s in hist:
        if s.get("unrealised_pnl") is None:
            continue
        ts = s.get("time") or s.get("timestamp")
        if ts:
            try:
                t = pd.to_datetime(ts).tz_localize(None)
                v = float(s.get("total_value", 0))
                if v > 0:
                    live_times.append(t)
                    live_vals.append(v)
            except Exception:
                pass

    # ── Combine: historical + live ──
    all_times = hist_times + live_times
    all_vals = hist_vals + live_vals

    if len(all_times) < 2:
        return None

    df = pd.DataFrame({"t": all_times, "v": all_vals})
    df = df.sort_values("t").drop_duplicates(subset="t", keep="last").reset_index(drop=True)

    lc = GREEN if df["v"].iloc[-1] >= start_val else RED
    fc = "rgba(63,185,80,0.08)" if lc == GREEN else "rgba(248,81,73,0.08)"

    fig = go.Figure()

    # Historical portion: step-line (reflects discrete trade closures)
    hist_mask = df["t"] <= pd.to_datetime(live_times[0]) if live_times else pd.Series([True] * len(df))
    df_hist = df[hist_mask]
    if len(df_hist) >= 2:
        fig.add_trace(go.Scatter(x=df_hist["t"], y=df_hist["v"], mode="lines",
                                  line=dict(color=lc, width=2.5, shape="hv"),
                                  fill="tozeroy", fillcolor=fc,
                                  hovertemplate="$%{y:,.2f}<extra></extra>",
                                  showlegend=False))

    # Live portion: smooth line (mark-to-market)
    df_live = df[~hist_mask] if live_times else pd.DataFrame()
    if len(df_live) >= 2:
        fig.add_trace(go.Scatter(x=df_live["t"], y=df_live["v"], mode="lines",
                                  line=dict(color=lc, width=2.5),
                                  fill="tozeroy", fillcolor=fc,
                                  hovertemplate="$%{y:,.2f}<extra></extra>",
                                  showlegend=False))
    elif len(df_hist) < 2:
        # Fallback: plot everything as one line
        fig.add_trace(go.Scatter(x=df["t"], y=df["v"], mode="lines",
                                  line=dict(color=lc, width=2.5),
                                  fill="tozeroy", fillcolor=fc,
                                  hovertemplate="$%{y:,.2f}<extra></extra>",
                                  showlegend=False))

    fig.add_hline(y=start_val, line_dash="dot", line_color="rgba(128,128,128,0.35)",
                  annotation_text=f"Start ${start_val:,.0f}", annotation_font_color=MUTED, annotation_font_size=10)
    fig.update_layout(**_layout(height=340, showlegend=False, hovermode="x unified",
                                xaxis=dict(showgrid=False, color=MUTED),
                                yaxis=dict(showgrid=True, gridcolor=GC, color=MUTED, tickprefix="$")))
    return fig


def category_donut(positions):
    cats = {}
    for p in positions:
        c = p.get("category", "other")
        cats[c] = cats.get(c, 0) + float(p.get("cost", 0))
    if not cats:
        return None
    colors = [PURPLE, BLUE, GREEN, YELLOW, RED, "#f778ba", "#79c0ff", "#d2a8ff", "#56d4dd"]
    fig = go.Figure(go.Pie(
        labels=list(cats.keys()), values=list(cats.values()), hole=0.55,
        marker=dict(colors=colors[:len(cats)], line=dict(width=0)),
        textinfo="label+percent", textfont=dict(size=11, color=FONT_COLOR),
        hovertemplate="<b>%{label}</b><br>$%{value:,.2f}<extra></extra>"
    ))
    fig.update_layout(**_layout(height=280, showlegend=False))
    return fig


def layer_bars(ls):
    names = ["AI (L1)", "Quant (L2)", "Becker (L3)"]
    vals = [ls.get("layer1_ai", 0), ls.get("layer2_quantitative", 0), ls.get("layer3_becker", 0)]
    fig = go.Figure(go.Bar(x=vals, y=names, orientation="h",
                            marker=dict(color=[PURPLE, BLUE, YELLOW]),
                            text=[f"{v:,}" for v in vals], textposition="auto",
                            textfont=dict(color=FONT_COLOR, size=11)))
    fig.update_layout(**_layout(height=150, showlegend=False,
                                xaxis=dict(showgrid=True, gridcolor=GC, color=MUTED),
                                yaxis=dict(color=FONT_COLOR)))
    return fig


def funnel_chart(status):
    stages = ["Fetched", "Eligible", "Evaluated", "Traded"]
    vals = [status.get("markets_fetched", 0), status.get("markets_eligible", 0),
            status.get("markets_evaluated", 0), status.get("new_trades", 0)]
    fig = go.Figure(go.Funnel(y=stages, x=vals,
                               marker=dict(color=["#30363d", "#21262d", BLUE, GREEN]),
                               textinfo="value+percent initial",
                               textfont=dict(color=FONT_COLOR, size=11),
                               connector=dict(line=dict(color="#30363d"))))
    fig.update_layout(**_layout(height=220))
    return fig


def ev_scatter(positions):
    data = [{"EV": float(p.get("ev", 0) or p.get("net_ev", 0)), "Cost": float(p.get("cost", 0)),
                "Fee": float(p.get("entry_fee", 0)),
             "Category": p.get("category", "?"), "Q": p.get("question", "")[:40]}
            for p in positions]
    if not data:
        return None
    df = pd.DataFrame(data)
    cmap = {"politics": PURPLE, "geopolitics": BLUE, "sports": GREEN, "crypto": YELLOW,
            "entertainment": "#f778ba", "finance": "#79c0ff", "tech": "#d2a8ff",
            "weather": "#56d4dd", "world_events": "#f0883e"}
    fig = px.scatter(df, x="Cost", y="EV", color="Category", hover_data=["Q"], color_discrete_map=cmap)
    fig.update_traces(marker=dict(size=9, line=dict(width=1, color="rgba(0,0,0,0.3)")))
    fig.update_layout(**_layout(height=280, xaxis=dict(showgrid=True, gridcolor=GC, color=MUTED, tickprefix="$"),
                                yaxis=dict(showgrid=True, gridcolor=GC, color=MUTED, tickprefix="$"),
                                legend=dict(font=dict(color=MUTED, size=10), bgcolor=PBG)))
    return fig


def time_ago(ts_str):
    if not ts_str:
        return "Never"
    try:
        ts = pd.to_datetime(ts_str)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        d = (pd.Timestamp.now(tz="UTC") - ts).total_seconds()
        if d < 60: return f"{int(d)}s ago"
        if d < 3600: return f"{int(d//60)}m ago"
        if d < 86400: return f"{int(d//3600)}h ago"
        return f"{int(d//86400)}d ago"
    except:
        return str(ts_str)[:19]


# ═══════════════════════════════════════════════
# Load all data
# ═══════════════════════════════════════════════

status = load_bot_status()
positions = load_positions()
trades = load_trades()
cfg = load_config()
keys = api_keys_available()

open_pos = [p for p in positions if p.get("status") == "open"]
closed_pos = [p for p in positions if p.get("status") == "closed"]

bankroll = float(status.get("bankroll", cfg.get("PAPER_BANKROLL", 500)))
paper_bankroll = float(cfg.get("PAPER_BANKROLL", 500))
deployed = sum(float(p.get("cost", 0)) for p in open_pos)
total_value = bankroll + deployed
realized_pnl = sum(float(p.get("pnl", 0)) for p in closed_pos)
_real_closed = [p for p in closed_pos if p.get("close_reason") not in ("cluster_prune", "longshot_filter", "contradiction_filter")]
_prune_closed = [p for p in closed_pos if p.get("close_reason") == "cluster_prune"]
total_trades = len(_real_closed)
winning = sum(1 for p in _real_closed if float(p.get("pnl", 0)) > 0)
win_rate = (winning / total_trades * 100) if total_trades > 0 else 0.0
pnl_pct = ((total_value - paper_bankroll) / paper_bankroll * 100) if paper_bankroll > 0 else 0
scan_count = int(status.get("scan_count", 0))
last_scan = status.get("last_scan", "")
layer_stats = status.get("layer_stats", {})
learner = status.get("learner", {})


# ═══════════════════════════════════════════════
# Sidebar — minimal, like stockpeers
# ═══════════════════════════════════════════════

with st.sidebar:
    page = st.radio(
        "ArsLucri",
        [":material/monitoring: Dashboard",
         ":material/account_balance_wallet: Positions",
         ":material/receipt_long: Trades",
         ":material/settings: Settings",
         ":material/terminal: Logs"],
        label_visibility="collapsed",
    )

    ""
    ""

    if scan_count > 0 and last_scan:
        st.success(f"Bot running · Scan #{scan_count}", icon=":material/radio_button_checked:")
    else:
        st.error("Bot offline", icon=":material/radio_button_unchecked:")

    st.caption(f"Last scan: {time_ago(last_scan)}")

    ""

    l1_on = keys.get("openai") and keys.get("perplexity")
    st.caption("**Estimator layers**")
    st.caption(f"{'🟢' if l1_on else '⚪'} AI · {'🟢' if layer_stats.get('layer2_quantitative',0)>0 else '🟡'} Quant · 🟢 Becker")

    if learner:
        ""
        st.caption(f"**Learner** · {learner.get('markets_remembered',0)} mkts · {learner.get('adaptive_status','—')}")

    ""

    # API Usage Meter
    try:
        usage = api_remaining()
        st.caption("**API Usage Today**")
        calls_pct = usage["calls_used"] / max(MAX_CALLS_PER_DAY, 1)
        cost_pct = usage["cost_used"] / max(MAX_COST_PER_DAY, 0.01)
        st.progress(min(calls_pct, 1.0), text=f"Calls: {usage['calls_used']} / {MAX_CALLS_PER_DAY}")
        st.progress(min(cost_pct, 1.0), text=f"Cost: ${usage['cost_used']:.3f} / ${MAX_COST_PER_DAY:.2f}")
        if usage["calls_left"] == 0 or usage["budget_left"] <= 0:
            st.warning("Daily cap reached — using free layers", icon=":material/warning:")
        elif calls_pct > 0.8:
            st.caption(f":material/info: {usage['calls_left']} calls remaining")
    except:
        pass

    ""

    auto_ref = st.toggle("Auto-refresh")
    if auto_ref and HAS_AUTOREFRESH:
        st_autorefresh(interval=15000, limit=None, key="ar")


# ═══════════════════════════════════════════════
# Dashboard
# ═══════════════════════════════════════════════

if "Dashboard" in page:

    """
    # :material/monitoring: ArsLucri

    Polymarket intelligence · paper trading · self-learning estimator
    """

    ""
    ""

    # ── ROW 1: Left metrics + Right chart (stockpeers [1,3] pattern) ──
    cols = st.columns([1, 3])

    with cols[0]:
        top = st.container(border=True, height="stretch")
        with top:
            pnl_sign = "+" if pnl_pct >= 0 else ""
            st.metric("Total Value", f"${total_value:,.2f}", f"{pnl_sign}{pnl_pct:.1f}%", width="content")
            st.metric("Cash", f"${bankroll:,.2f}", width="content")
            st.metric("Deployed", f"${deployed:,.2f}", f"{len(open_pos)} positions", delta_color="off", width="content")
            _unrealised = sum(float(p.get("unrealised_pnl", 0)) for p in open_pos)
            _priced = len([p for p in open_pos if p.get("current_price")])
            st.metric("Unrealised", f"${_unrealised:+,.2f}", f"{_priced}/{len(open_pos)} priced", delta_color="off", width="content")

    with cols[1]:
        chart_box = st.container(border=True, height="stretch")
        with chart_box:
            fig = bankroll_line(status, paper_bankroll)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                placeholder = go.Figure(go.Scatter(
                    x=[datetime.now(timezone.utc)], y=[total_value],
                    mode="markers+text", text=[f"${total_value:,.0f}"],
                    textposition="top center", textfont=dict(color=FONT_COLOR, size=18),
                    marker=dict(size=14, color=GREEN)))
                placeholder.add_hline(y=paper_bankroll, line_dash="dot", line_color="rgba(128,128,128,0.35)",
                                      annotation_text=f"Start ${paper_bankroll:,.0f}", annotation_font_color=MUTED)
                placeholder.update_layout(**_layout(height=340, showlegend=False,
                                                     xaxis=dict(visible=False),
                                                     yaxis=dict(showgrid=True, gridcolor=GC, color=MUTED, tickprefix="$")))
                st.plotly_chart(placeholder, use_container_width=True, config={"displayModeBar": False})
                st.caption("Line chart populates after 2+ scans")

    ""

    # ── ROW 2: Bottom metrics + stats ──
    cols = st.columns([1, 3])

    with cols[0]:
        bottom = st.container(border=True, height="stretch")
        with bottom:
            _total_fees_closed = sum(float(p.get("total_fees", 0)) for p in _real_closed)
            _net_pnl = sum(float(p.get("net_pnl", p.get("pnl", 0))) for p in _real_closed)
            _prune_pnl = sum(float(p.get("pnl", 0)) for p in _prune_closed)
            rpnl_dc = "normal" if _net_pnl >= 0 else "inverse"
            _losses = total_trades - winning
            wr_str = f"{winning}W / {_losses}L" if total_trades > 0 else "—"
            if _prune_closed:
                wr_str += f" +{len(_prune_closed)} pruned"
            st.metric("P&L", f"${_net_pnl:,.2f}", f"gross {realized_pnl:,.2f} · fees {_total_fees_closed:,.2f}", delta_color=rpnl_dc if _net_pnl != 0 else "off")
            st.metric("Win Rate", f"{win_rate:.0f}%", wr_str, delta_color="off")

    with cols[1]:
        right = st.container(border=True, height="stretch")
        with right:
            g1, g2, g3 = st.columns(3)
            with g1:
                cap_pct = (len(open_pos) / max(cfg.get("MAX_CONCURRENT", 30), 1)) * 100
                st.plotly_chart(gauge_chart("Capacity", cap_pct), use_container_width=True, config={"displayModeBar": False})
            with g2:
                dep_pct = (deployed / max(total_value, 1)) * 100
                st.plotly_chart(gauge_chart("Deployed", dep_pct), use_container_width=True, config={"displayModeBar": False})
            with g3:
                scan_health = min(scan_count * 10, 100)
                st.plotly_chart(gauge_chart("Health", scan_health), use_container_width=True, config={"displayModeBar": False})

    ""
    ""

    """
    ## Individual breakdowns
    """

    ""

    # ── ROW 3: 4 equal panels (stockpeers individual-stocks pattern) ──
    NUM_COLS = 4
    cols = st.columns(NUM_COLS)

    # Panel 1: Category allocation
    with cols[0]:
        cell = st.container(border=True)
        with cell:
            st.caption("ALLOCATION")
            fig = category_donut(open_pos)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("No positions", icon=":material/info:")

    # Panel 2: Market funnel
    with cols[1]:
        cell = st.container(border=True)
        with cell:
            st.caption("MARKET FUNNEL")
            st.plotly_chart(funnel_chart(status), use_container_width=True, config={"displayModeBar": False})

    # Panel 3: Estimator usage
    with cols[2]:
        cell = st.container(border=True)
        with cell:
            st.caption("ESTIMATOR USAGE")
            st.plotly_chart(layer_bars(layer_stats), use_container_width=True, config={"displayModeBar": False})

    # Panel 4: EV scatter
    with cols[3]:
        cell = st.container(border=True)
        with cell:
            st.caption("EV vs COST")
            fig = ev_scatter(open_pos)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("No positions", icon=":material/info:")

    ""
    ""


    # ── ROW 3.5: Market Radar & Risk Monitor ──
    """
    ## Market Radar
    """

    radar_cols = st.columns(3)

    # Panel A: Position Health (edge thinning warnings)
    with radar_cols[0]:
        with st.container(border=True):
            st.caption("POSITION HEALTH")
            _thin = [p for p in open_pos if int(p.get("edge_thin_count", 0)) > 0]
            _thin = sorted(_thin, key=lambda x: -int(x.get("edge_thin_count", 0)))
            if _thin:
                rows_th = []
                for p in _thin[:10]:
                    etc = int(p.get("edge_thin_count", 0))
                    bar = "\u2588" * etc + "\u2591" * (3 - etc)
                    q = p.get("question", "?")[:40]
                    rows_th.append({"Position": q, "Warn": f"{bar} {etc}/3", "Cost": f"${float(p.get('cost', 0)):.2f}"})
                st.dataframe(pd.DataFrame(rows_th), use_container_width=True, hide_index=True,
                             height=min(len(rows_th) * 38 + 40, 350))
            else:
                st.success("All positions healthy", icon=":material/check_circle:")

    # Panel B: Recent Closes
    with radar_cols[1]:
        with st.container(border=True):
            st.caption("RECENT CLOSES")
            _closed_sorted = sorted(closed_pos, key=lambda x: x.get("closed_at", ""), reverse=True)[:8]
            if _closed_sorted:
                rows_cl = []
                for c in _closed_sorted:
                    pnl_val = float(c.get("pnl", 0))
                    icon = "\U0001f7e2" if pnl_val > 0 else "\U0001f534" if pnl_val < 0 else "\u26aa"
                    q = c.get("question", "?")[:38]
                    # Calculate hold time
                    try:
                        from datetime import datetime as _dt
                        _o = _dt.fromisoformat(c.get("opened_at", "").replace("Z", "+00:00"))
                        _c = _dt.fromisoformat(c.get("closed_at", "").replace("Z", "+00:00"))
                        _hold = _c - _o
                        if _hold.days > 0:
                            hold_str = f"{_hold.days}d {_hold.seconds // 3600}h"
                        else:
                            hold_str = f"{_hold.seconds // 3600}h {(_hold.seconds % 3600) // 60}m"
                    except Exception:
                        hold_str = "?"
                    rows_cl.append({"": icon, "Position": q, "P&L": f"${pnl_val:+.2f}", "Hold": hold_str})
                st.dataframe(pd.DataFrame(rows_cl), use_container_width=True, hide_index=True,
                             height=min(len(rows_cl) * 38 + 40, 350))
            else:
                st.info("No closed trades yet", icon=":material/hourglass_empty:")

    # Panel C: Correlation Clusters
    with radar_cols[2]:
        with st.container(border=True):
            st.caption("CORRELATION CLUSTERS")
            from collections import Counter as _Counter
            # Group by first 3 words of question to find related positions
            def _cluster_key(q):
                words = q.split()[:3]
                return " ".join(words) if len(words) >= 2 else q[:20]
            _clusters = {}
            for p in open_pos:
                key = _cluster_key(p.get("question", ""))
                if key not in _clusters:
                    _clusters[key] = {"count": 0, "cost": 0.0}
                _clusters[key]["count"] += 1
                _clusters[key]["cost"] += float(p.get("cost", 0))
            _multi = {k: v for k, v in _clusters.items() if v["count"] > 1}
            _multi = dict(sorted(_multi.items(), key=lambda x: -x[1]["cost"]))
            if _multi:
                rows_cc = []
                for k, v in list(_multi.items())[:8]:
                    rows_cc.append({"Cluster": k[:35], "Positions": v["count"], "Exposure": f"${v['cost']:.2f}"})
                st.dataframe(pd.DataFrame(rows_cc), use_container_width=True, hide_index=True,
                             height=min(len(rows_cc) * 38 + 40, 280))
            else:
                st.success("No correlated clusters", icon=":material/diversity_3:")

    """
    ## Risk Monitor
    """

    risk_cols = st.columns(3)

    # Panel D: Category Exposure bar chart
    with risk_cols[0]:
        with st.container(border=True):
            st.caption("CATEGORY EXPOSURE")
            _cat_exp = {}
            for p in open_pos:
                cat = p.get("category", "other")
                _cat_exp[cat] = _cat_exp.get(cat, 0) + float(p.get("cost", 0))
            if _cat_exp:
                _cat_sorted = sorted(_cat_exp.items(), key=lambda x: -x[1])
                _cats = [c[0].title() for c in _cat_sorted]
                _vals = [c[1] for c in _cat_sorted]
                _colors = ["#3fb950", "#f0883e", "#58a6ff", "#bc8cff", "#f778ba", "#79c0ff", "#d2a8ff"]
                fig_ce = go.Figure(go.Bar(x=_vals, y=_cats, orientation="h",
                    marker_color=_colors[:len(_cats)],
                    hovertemplate="$%{x:,.2f}<extra></extra>"))
                fig_ce.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#8b949e", size=11),
                    xaxis=dict(showgrid=True, gridcolor="rgba(48,54,61,0.6)", tickprefix="$"),
                    yaxis=dict(showgrid=False, autorange="reversed"))
                st.plotly_chart(fig_ce, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("No positions", icon=":material/info:")

    # Panel E: Daily P&L Timeline
    with risk_cols[1]:
        with st.container(border=True):
            st.caption("P&L TIMELINE")
            if closed_pos:
                _pnl_rows = []
                for c in sorted(closed_pos, key=lambda x: x.get("closed_at", "")):
                    try:
                        _ts = pd.to_datetime(c.get("closed_at"))
                        _pnl_rows.append({"time": _ts, "pnl": float(c.get("pnl", 0))})
                    except Exception:
                        pass
                if _pnl_rows:
                    _df_pnl = pd.DataFrame(_pnl_rows)
                    _df_pnl["cumulative"] = _df_pnl["pnl"].cumsum()
                    _lc = "#3fb950" if _df_pnl["cumulative"].iloc[-1] >= 0 else "#f85149"
                    fig_pnl = go.Figure()
                    fig_pnl.add_trace(go.Bar(x=_df_pnl["time"], y=_df_pnl["pnl"], name="Trade P&L",
                        marker_color=[("#3fb950" if v >= 0 else "#f85149") for v in _df_pnl["pnl"]],
                        hovertemplate="$%{y:+.2f}<extra></extra>", opacity=0.6))
                    fig_pnl.add_trace(go.Scatter(x=_df_pnl["time"], y=_df_pnl["cumulative"],
                        name="Cumulative", line=dict(color=_lc, width=2.5),
                        hovertemplate="$%{y:+.2f}<extra></extra>"))
                    fig_pnl.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#8b949e", size=11), showlegend=False,
                        xaxis=dict(showgrid=False, color="#8b949e"),
                        yaxis=dict(showgrid=True, gridcolor="rgba(48,54,61,0.6)", tickprefix="$", color="#8b949e"))
                    st.plotly_chart(fig_pnl, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("No P&L data yet", icon=":material/trending_up:")
            else:
                st.info("No closed trades yet", icon=":material/trending_up:")

    # Panel F: Risk Metrics
    with risk_cols[2]:
        with st.container(border=True):
            st.caption("RISK METRICS")
            _total_deployed = sum(float(p.get("cost", 0)) for p in open_pos)
            _total_bankroll = float(status.get("bankroll", 500))
            _leverage = _total_deployed / _total_bankroll if _total_bankroll > 0 else 0
            _max_single = max((float(p.get("cost", 0)) for p in open_pos), default=0)
            _avg_cost = _total_deployed / len(open_pos) if open_pos else 0
            _pnl_list = [float(c.get("pnl", 0)) for c in closed_pos]
            _max_win = max(_pnl_list) if _pnl_list else 0
            _max_loss = min(_pnl_list) if _pnl_list else 0
            _avg_pnl = sum(_pnl_list) / len(_pnl_list) if _pnl_list else 0
            _thin_count = sum(1 for p in open_pos if int(p.get("edge_thin_count", 0)) > 0)
            _metrics = [
                ("Leverage", f"{_leverage:.2f}x"),
                ("Largest Position", f"${_max_single:.2f}"),
                ("Avg Position Size", f"${_avg_cost:.2f}"),
                ("Best Trade", f"${_max_win:+.2f}"),
                ("Worst Trade", f"${_max_loss:+.2f}"),
                ("Avg P&L/Trade", f"${_avg_pnl:+.2f}"),
                ("Thinning Edges", f"{_thin_count}/{len(open_pos)}"),
            ]
            for label, val in _metrics:
                st.markdown(f"<div style='display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(48,54,61,0.4)'>"
                            f"<span style='color:#8b949e;font-size:13px'>{label}</span>"
                            f"<span style='color:#e6edf3;font-size:13px;font-weight:600'>{val}</span></div>",
                            unsafe_allow_html=True)


    # ── ROW 3.6: Category Performance (Phase 1.9) ──
    """
    ## Category Performance
    """

    if closed_pos:
        # Build per-category stats from closed trades
        _cat_stats = {}
        for c in closed_pos:
            cat = c.get("category", "other")
            if cat not in _cat_stats:
                _cat_stats[cat] = {"wins": 0, "losses": 0, "pnl": 0.0, "net_pnl": 0.0, "trades": 0, "fees": 0.0}
            _cat_stats[cat]["trades"] += 1
            _pnl_val = float(c.get("pnl", 0))
            _net_val = float(c.get("net_pnl", c.get("pnl", 0)))
            _fee_val = float(c.get("total_fees", 0))
            _cat_stats[cat]["pnl"] += _pnl_val
            _cat_stats[cat]["net_pnl"] += _net_val
            _cat_stats[cat]["fees"] += _fee_val
            if _pnl_val > 0:
                _cat_stats[cat]["wins"] += 1
            else:
                _cat_stats[cat]["losses"] += 1

        cp_cols = st.columns(2)

        # Left: Category P&L bar chart
        with cp_cols[0]:
            with st.container(border=True):
                st.caption("CATEGORY P&L")
                _cp_sorted = sorted(_cat_stats.items(), key=lambda x: -x[1]["net_pnl"])
                _cp_cats = [c[0].title() for c in _cp_sorted]
                _cp_vals = [round(c[1]["net_pnl"], 2) for c in _cp_sorted]
                _cp_colors = [GREEN if v >= 0 else RED for v in _cp_vals]
                fig_cp = go.Figure(go.Bar(
                    x=_cp_vals, y=_cp_cats, orientation="h",
                    marker_color=_cp_colors,
                    text=[f"${v:+.2f}" for v in _cp_vals],
                    textposition="auto",
                    textfont=dict(color=FONT_COLOR, size=11),
                    hovertemplate="<b>%{y}</b><br>Net P&L: $%{x:+.2f}<extra></extra>"))
                fig_cp.update_layout(
                    height=250, margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor=PBG, plot_bgcolor=PBG,
                    font=dict(color=MUTED, size=11),
                    xaxis=dict(showgrid=True, gridcolor=GC, tickprefix="$", color=MUTED),
                    yaxis=dict(showgrid=False, autorange="reversed", color=FONT_COLOR))
                st.plotly_chart(fig_cp, use_container_width=True, config={"displayModeBar": False})

        # Right: Category stats table
        with cp_cols[1]:
            with st.container(border=True):
                st.caption("CATEGORY BREAKDOWN")
                _cp_rows = []
                for cat, s in sorted(_cat_stats.items(), key=lambda x: -x[1]["trades"]):
                    wr = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0
                    avg = s["net_pnl"] / s["trades"] if s["trades"] > 0 else 0
                    _status = "🟢" if wr >= 60 else "🟡" if wr >= 40 else "🔴"
                    _cp_rows.append({
                        "": _status,
                        "Category": cat.title(),
                        "Trades": s["trades"],
                        "Win Rate": f"{wr:.0f}%",
                        "Net P&L": f"${s['net_pnl']:+.2f}",
                        "Avg/Trade": f"${avg:+.2f}",
                        "Fees": f"${s['fees']:.2f}",
                    })
                st.dataframe(pd.DataFrame(_cp_rows), use_container_width=True, hide_index=True,
                             height=min(len(_cp_rows) * 38 + 40, 350))
    else:
        st.info("No closed trades yet — category stats populate after first resolution", icon=":material/hourglass_empty:")

    ""
    ""

    # ── ROW 3.7: Score Card ──
    """
    ## Score Card
    """

    _cl_real = [c for c in closed_pos if c.get("close_reason") not in ("cluster_prune", "longshot_filter", "contradiction_filter")]
    _cl_prune = [c for c in closed_pos if c.get("close_reason") == "cluster_prune"]
    _cl = _cl_real
    _pnls = [float(c.get("pnl", 0)) for c in _cl]
    _n = len(_pnls)
    _conf_badge = ":material/check_circle:" if _n >= 50 else ":material/warning:"
    _prune_count = len(_cl_prune)
    _prune_pnl = sum(float(c.get("pnl", 0)) for c in _cl_prune)
    _conf_text = "Statistically significant" if _n >= 50 else f"Low confidence ({_n}/50 trades)"

    sc_cols = st.columns(3)

    # Panel G: Expectancy & Edge
    with sc_cols[0]:
        with st.container(border=True):
            st.caption("EXPECTANCY & EDGE")
            st.markdown("<span style='color:#8b949e;font-size:11px'>Is the edge real? Positive expectancy is the minimum threshold for any viable system.</span>", unsafe_allow_html=True)
            if _n > 0:
                _wins = [p for p in _pnls if p > 0]
                _losses = [p for p in _pnls if p <= 0]
                _wr = len(_wins) / _n
                _lr = 1 - _wr
                _avg_win = sum(_wins) / len(_wins) if _wins else 0
                _avg_loss = abs(sum(_losses) / len(_losses)) if _losses else 0
                _expectancy = (_wr * _avg_win) - (_lr * _avg_loss)
                _gross_profit = sum(_wins) if _wins else 0
                _gross_loss = abs(sum(_losses)) if _losses else 0.01
                _profit_factor = _gross_profit / _gross_loss if _gross_loss > 0 else float("inf")
                _pf_display = f"{_profit_factor:.2f}" if _profit_factor < 999 else "\u221e"
                _pf_color = "#3fb950" if _profit_factor > 1.5 else "#f0883e" if _profit_factor > 1.0 else "#f85149"
                _exp_color = "#3fb950" if _expectancy > 0 else "#f85149"
                _metrics_e = [
                    ("Expectancy / Trade", f"${_expectancy:+.2f}", _exp_color),
                    ("Profit Factor", _pf_display, _pf_color),
                    ("Win Rate", f"{_wr:.1%}", "#3fb950" if _wr > 0.5 else "#f85149"),
                    ("Avg Win", f"${_avg_win:.2f}", "#3fb950"),
                    ("Avg Loss", f"${_avg_loss:.2f}", "#f85149" if _avg_loss > 0 else "#8b949e"),
                    ("W\u00d7AvgW", f"${_wr * _avg_win:.2f}", "#8b949e"),
                    ("L\u00d7AvgL", f"${_lr * _avg_loss:.2f}", "#8b949e"),
                ]
                for label, val, color in _metrics_e:
                    st.markdown(f"<div style='display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(48,54,61,0.3)'>"
                                f"<span style='color:#8b949e;font-size:12px'>{label}</span>"
                                f"<span style='color:{color};font-size:12px;font-weight:600'>{val}</span></div>",
                                unsafe_allow_html=True)
            else:
                st.info("No trades yet", icon=":material/hourglass_empty:")

    # Panel H: Risk Profile
    with sc_cols[1]:
        with st.container(border=True):
            st.caption("RISK PROFILE")
            st.markdown("<span style='color:#8b949e;font-size:11px'>Can you survive the worst? Max drawdown is the single most important number for system viability.</span>", unsafe_allow_html=True)
            if _n >= 2:
                # Max Drawdown from cumulative P&L
                import numpy as np
                _cum = np.cumsum(_pnls)
                _peak = np.maximum.accumulate(_cum)
                _dd = _cum - _peak
                _mdd = float(np.min(_dd))
                _mdd_pct = (_mdd / paper_bankroll * 100) if paper_bankroll > 0 else 0

                # Sharpe (using trade-level returns, risk-free ~ 0 for simplicity)
                _mean_r = np.mean(_pnls)
                _std_r = np.std(_pnls, ddof=1) if _n > 1 else 0.01
                _sharpe = _mean_r / _std_r if _std_r > 0 else 0

                # Sortino (downside deviation only)
                _downside = [p for p in _pnls if p < 0]
                _down_std = np.std(_downside, ddof=1) if len(_downside) > 1 else (abs(_downside[0]) if _downside else 0.01)
                _sortino = _mean_r / _down_std if _down_std > 0 else float("inf")
                _sortino_display = f"{_sortino:.2f}" if _sortino < 999 else "\u221e"

                # Calmar (annualized return / MDD)
                _total_return = sum(_pnls)
                _calmar = abs(_total_return / _mdd) if _mdd != 0 else float("inf")
                _calmar_display = f"{_calmar:.2f}" if _calmar < 999 else "\u221e"

                # Avg drawdown duration (scans between peaks)
                _dd_durations = []
                _in_dd = False
                _dd_start = 0
                for idx in range(len(_dd)):
                    if _dd[idx] < 0 and not _in_dd:
                        _in_dd = True
                        _dd_start = idx
                    elif _dd[idx] >= 0 and _in_dd:
                        _in_dd = False
                        _dd_durations.append(idx - _dd_start)
                _avg_dd_dur = sum(_dd_durations) / len(_dd_durations) if _dd_durations else 0

                def _sharpe_color(s):
                    if s >= 2.0: return "#3fb950"
                    if s >= 1.0: return "#f0883e"
                    return "#f85149"

                _metrics_r = [
                    ("Max Drawdown", f"${_mdd:.2f} ({_mdd_pct:.1f}%)", "#f85149" if _mdd < -25 else "#f0883e" if _mdd < 0 else "#3fb950"),
                    ("Sharpe Ratio", f"{_sharpe:.2f}", _sharpe_color(_sharpe)),
                    ("Sortino Ratio", _sortino_display, _sharpe_color(float(_sortino) if _sortino != float("inf") else 3)),
                    ("Calmar Ratio", _calmar_display, "#3fb950" if _calmar > 2 else "#f0883e"),
                    ("Avg DD Duration", f"{_avg_dd_dur:.0f} trades", "#8b949e"),
                    ("Volatility (\u03c3)", f"${_std_r:.2f}/trade", "#8b949e"),
                ]
                for label, val, color in _metrics_r:
                    st.markdown(f"<div style='display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(48,54,61,0.3)'>"
                                f"<span style='color:#8b949e;font-size:12px'>{label}</span>"
                                f"<span style='color:{color};font-size:12px;font-weight:600'>{val}</span></div>",
                                unsafe_allow_html=True)
            else:
                st.info("Need 2+ closed trades", icon=":material/hourglass_empty:")

    # Panel I: Robustness & Reliability
    with sc_cols[2]:
        with st.container(border=True):
            st.caption("ROBUSTNESS")
            st.markdown("<span style='color:#8b949e;font-size:11px'>Statistical significance matters. A system with 30 trades proves nothing — minimum 50–200 for confidence.</span>", unsafe_allow_html=True)
            if _n > 0:
                # Trade count confidence
                _conf_pct = min(_n / 200 * 100, 100)
                _conf_color = "#3fb950" if _n >= 200 else "#f0883e" if _n >= 50 else "#f85149"

                # Avg trade duration
                _durations = []
                for c in _cl:
                    try:
                        _o = pd.to_datetime(c.get("opened_at"))
                        _c2 = pd.to_datetime(c.get("closed_at"))
                        _durations.append((_c2 - _o).total_seconds() / 3600)
                    except Exception:
                        pass
                _avg_dur = sum(_durations) / len(_durations) if _durations else 0
                if _avg_dur >= 24:
                    _dur_str = f"{_avg_dur / 24:.1f} days"
                else:
                    _dur_str = f"{_avg_dur:.1f} hours"

                # Capacity utilization
                _capacity = len(open_pos) / int(status.get("config", {}).get("MAX_CONCURRENT", 50)) * 100 if status.get("config") else (len(open_pos) / 50 * 100)

                # Skewness
                import numpy as np
                _skew = float(np.mean([(p - np.mean(_pnls))**3 for p in _pnls]) / (np.std(_pnls)**3)) if np.std(_pnls) > 0 and _n >= 3 else 0

                _metrics_rb = [
                    ("Trade Count", f"{_n}", _conf_color),
                    ("Confidence", f"{_conf_pct:.0f}%  ({_conf_text})", _conf_color),
                    ("Avg Hold Time", _dur_str, "#8b949e"),
                    ("Capacity Used", f"{_capacity:.0f}%", "#f0883e" if _capacity > 90 else "#3fb950"),
                    ("Return Skew", f"{_skew:+.2f}", "#3fb950" if _skew > 0 else "#f85149"),
                    ("Total Return", f"${sum(_pnls):+.2f} ({sum(_pnls)/paper_bankroll*100:+.1f}%)", "#3fb950" if sum(_pnls) > 0 else "#f85149"),
                ]
                for label, val, color in _metrics_rb:
                    st.markdown(f"<div style='display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(48,54,61,0.3)'>"
                                f"<span style='color:#8b949e;font-size:12px'>{label}</span>"
                                f"<span style='color:{color};font-size:12px;font-weight:600'>{val}</span></div>",
                                unsafe_allow_html=True)
            else:
                st.info("No trades yet", icon=":material/hourglass_empty:")

    # ── ROW 4: Recent activity ──
    with st.container(border=True):
        st.caption("RECENT ACTIVITY")
        recent = sorted(trades, key=lambda t: t.get("timestamp", ""), reverse=True)[:12]
        if recent:
            rows = []
            for t in recent:
                action = t.get("action", "OPEN").upper()
                if action in ("CLOSE", "TRAILING_STOP"):
                    _pnl = float(t.get("pnl", t.get("net_pnl", 0)))
                    _pnl_str = f"${_pnl:+.2f}"
                    _icon = "🟢" if _pnl > 0 else "🔴" if _pnl < 0 else "⚪"
                    _reason = t.get("reason", "closed")[:25]
                    rows.append({
                        "Action": f"{_icon} EXIT",
                        "Question": t.get("question", "?")[:55],
                        "P&L": _pnl_str,
                        "Detail": _reason,
                        "Source": "Trailing Stop" if action == "TRAILING_STOP" else "Exit",
                        "When": time_ago(t.get("timestamp")),
                    })
                else:
                    rows.append({
                        "Action": "🔵 OPEN",
                        "Question": t.get("question", "?")[:55],
                        "P&L": f"${float(t.get('cost', 0)):.2f}",
                        "Detail": f"EV ${float(t.get('ev', 0)):.4f}",
                        "Source": t.get("source", "").replace("layer1_ai", "AI").replace("layer2_quantitative", "Quant").replace("layer3_becker", "Becker"),
                        "When": time_ago(t.get("timestamp")),
                    })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No trades yet — bot is scanning", icon=":material/hourglass_empty:")


# ═══════════════════════════════════════════════
# Positions
# ═══════════════════════════════════════════════

elif "Positions" in page:

    """
    # :material/account_balance_wallet: Positions
    """

    ""

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        avg_ev = sum(float(p.get("ev", 0)) for p in open_pos) / max(len(open_pos), 1)
        c1.metric("Open", len(open_pos), width="content")
        c2.metric("Deployed", f"${deployed:,.2f}", width="content")
        c3.metric("Avg EV", f"${avg_ev:.4f}", width="content")
        c4.metric("Categories", len(set(p.get("category", "?") for p in open_pos)), width="content")

    ""

    if open_pos:
        # Legend
        with st.container(border=True):
            st.caption("**Column Guide:** Question = market title · Side = YES/NO bet direction · Entry = price paid per contract · Qty = number of contracts · Cost = total deployed · Est = AI estimated probability · Curr = live market price · P&L = unrealised profit/loss · EV = expected value at entry · Cat = market category · Src = estimation layer · Age = time since opened")

        # Sort by opened (newest first)
        _sorted = sorted(open_pos, key=lambda p: p.get("opened_at", ""), reverse=True)

        with st.container(border=True):
            rows = []
            for p in _sorted:
                _unrl = float(p.get("unrealised_pnl", 0))
                _status = "🟢" if _unrl > 0 else "🔴" if _unrl < -1.0 else "⚪"
                rows.append({
                    "": _status,
                    "Question": p.get("question", "")[:50],
                    "Side": p.get("side", "?"),
                    "Entry": float(p.get("entry_price", 0) or (p.get("cost", 0) / max(p.get("contracts", 1), 0.01))),
                    "Qty": float(p.get("contracts", 0)),
                    "Cost": float(p.get("cost", 0)),
                    "Est": float(p.get("estimated_prob", 0) or p.get("estimated_probability", 0)) * 100,
                    "Curr": float(p.get("current_price", p.get("entry_price", 0))),
                    "P&L": _unrl,
                    "EV": float(p.get("ev", 0) or p.get("net_ev", 0)),
                    "Cat": p.get("category", "?"),
                    "Src": (p.get("estimator_source") or p.get("source", "?")).replace("layer1_ai", "AI").replace("layer2_quantitative", "Quant").replace("layer3_becker", "Becker"),
                    "Age": time_ago(p.get("opened_at") or p.get("timestamp")),
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True,
                         column_config={
                             "": st.column_config.TextColumn(width="small"),
                             "Entry": st.column_config.NumberColumn(format="$%.3f"),
                             "Qty": st.column_config.NumberColumn(format="%.0f"),
                             "Cost": st.column_config.NumberColumn(format="$%.2f"),
                             "Est": st.column_config.NumberColumn(format="%.1f%%", help="AI estimated probability"),
                             "Curr": st.column_config.NumberColumn(format="$%.3f"),
                             "P&L": st.column_config.NumberColumn(format="$%+.2f"),
                             "EV": st.column_config.NumberColumn(format="$%.4f"),
                         }, height=min(len(rows) * 38 + 40, 700))
    else:
        st.info("No open positions", icon=":material/info:")

    ""

    if closed_pos:
        with st.container(border=True):
            cpnl = sum(float(p.get("pnl", 0)) for p in closed_pos)
            cpnl_net = sum(float(p.get("net_pnl", p.get("pnl", 0))) for p in closed_pos)
            cfees = sum(float(p.get("total_fees", 0)) for p in closed_pos)
            st.metric("Closed P&L", f"${cpnl:,.2f} (${cpnl_net:,.2f} net)", f"{len(closed_pos)} trades",
                       delta_color="normal" if cpnl >= 0 else "inverse")
            rows = [{
                "Question": p.get("question", "")[:50],
                "Side": p.get("side", "?"),
                "Entry": float(p.get("entry_price", 0) or (p.get("cost", 0) / max(p.get("contracts", 1), 0.01))),
                "Cost": float(p.get("cost", 0)),
                "P&L": float(p.get("pnl", 0)),
                "Result": "Win" if float(p.get("pnl", 0)) > 0 else "Loss",
                "Fees": float(p.get("total_fees", 0)),
                "Net P&L": float(p.get("net_pnl", p.get("pnl", 0))),
            } for p in sorted(closed_pos, key=lambda x: x.get("closed_at", ""), reverse=True)[:20]]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                         column_config={
                             "Entry": st.column_config.NumberColumn(format="$%.3f"),
                             "Cost": st.column_config.NumberColumn(format="$%.2f"),
                             "P&L": st.column_config.NumberColumn(format="$%.2f"),
                             "Fees": st.column_config.NumberColumn(format="$%.4f"),
                             "Net P&L": st.column_config.NumberColumn(format="$%.2f"),
                         })
    else:
        st.info("No closed positions yet", icon=":material/hourglass_empty:")


# ═══════════════════════════════════════════════
# Trades
# ═══════════════════════════════════════════════

elif "Trades" in page:

    """
    # :material/receipt_long: Trade Log
    """

    ""

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(trades), width="content")
        c2.metric("Opens", len([t for t in trades if t.get("action") == "OPEN"]), width="content")
        c3.metric("Closes", len([t for t in trades if t.get("action") == "CLOSE"]), width="content")

    ""

    fc1, fc2 = st.columns(2)
    af = fc1.selectbox("Action", ["All", "OPEN", "CLOSE"])
    sf = fc2.selectbox("Source", ["All", "layer1_ai", "layer2_quantitative", "layer3_becker"])

    filtered = trades
    if af != "All": filtered = [t for t in filtered if t.get("action") == af]
    if sf != "All": filtered = [t for t in filtered if t.get("source") == sf]
    filtered = sorted(filtered, key=lambda t: t.get("timestamp", ""), reverse=True)[:50]

    if filtered:
        with st.container(border=True):
            rows = []
            for t in filtered:
                _action = t.get("action", "?")
                _is_exit = _action in ("CLOSE", "CLUSTER_PRUNE", "TRAILING_STOP")
                if _is_exit:
                    _pnl = float(t.get("pnl", 0))
                    _icon = "\u2705" if _pnl > 0 else "\u274c" if _pnl < 0 else "\u2796"
                    rows.append({
                        "Time": time_ago(t.get("timestamp")),
                        "Action": f"{_icon} {_action}",
                        "Question": t.get("question", "")[:50],
                        "Side": t.get("side", "-"),
                        "P&L": _pnl,
                        "Reason": t.get("reason", "")[:30],
                        "Category": t.get("category", "?"),
                    })
                else:
                    rows.append({
                        "Time": time_ago(t.get("timestamp")),
                        "Action": f"\U0001f535 {_action}",
                        "Question": t.get("question", "")[:50],
                        "Side": t.get("side", "?"),
                        "P&L": float(t.get("cost", 0)),
                        "Reason": t.get("source", "").replace("layer1_ai", "AI").replace("layer2_quantitative", "Quant").replace("layer3_becker", "Becker"),
                        "Category": t.get("category", "?"),
                    })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                         column_config={
                             "P&L": st.column_config.NumberColumn(format="$%.2f"),
                         }, height=min(len(rows) * 38 + 40, 700))
    else:
        st.info("No trades match filters", icon=":material/filter_list:")


# ═══════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════

elif "Settings" in page:

    """
    # :material/settings: Settings
    """

    ""

    with st.container(border=True):
        st.subheader("API Keys", divider=True)
        k1, k2 = st.columns(2)
        oai = k1.text_input("OpenAI API Key", value=get_api_key("OPENAI_API_KEY") or "", type="password")
        if k1.button("Save OpenAI Key"):
            set_api_key("OPENAI_API_KEY", oai); st.toast("Saved", icon="✅")
        pplx = k2.text_input("Perplexity API Key", value=get_api_key("PERPLEXITY_API_KEY") or "", type="password")
        if k2.button("Save Perplexity Key"):
            set_api_key("PERPLEXITY_API_KEY", pplx); st.toast("Saved", icon="✅")

    ""

    with st.container(border=True):
        st.subheader("API Usage Limits", divider=True)
        try:
            usage = api_remaining()
            u1, u2, u3 = st.columns(3)
            u1.metric("Calls Today", usage["calls_used"], f"{usage['calls_left']} left", delta_color="off", width="content")
            u2.metric("Cost Today", f"${usage['cost_used']:.3f}", f"${usage['budget_left']:.3f} left", delta_color="off", width="content")
            u3.metric("Est. Monthly", f"${usage['cost_used'] * 30:.2f}", width="content")
        except:
            st.info("No usage data yet")
        st.caption("Edit limits in `/opt/becker-bot/api_caps.py` — MAX_CALLS_PER_DAY and MAX_COST_PER_DAY")

    ""

    with st.container(border=True):
        st.subheader("Bot Configuration", divider=True)
        s1, s2, s3 = st.columns(3)
        paper_br = s1.number_input("Paper Bankroll ($)", 10.0, 100000.0, float(cfg.get("PAPER_BANKROLL", 500)), 50.0)
        kelly = s1.slider("Kelly Fraction", 0.05, 1.0, float(cfg.get("KELLY_FRACTION", 0.25)), 0.05)
        max_bet = s1.slider("Max Bet %", 1, 20, int(float(cfg.get("MAX_BET_PCT", 0.05)) * 100))

        min_ev = s2.number_input("Min EV ($)", 0.001, 1.0, float(cfg.get("MIN_EV_THRESHOLD", 0.02)), 0.005, format="%.3f")
        min_edge = s2.slider("Min Edge (pp)", 1, 15, int(float(cfg.get("MIN_EDGE_POINTS", 0.02)) * 100))
        max_conc = s2.number_input("Max Concurrent", 1, 200, int(cfg.get("MAX_CONCURRENT", 30)))

        min_liq = s3.number_input("Min Liquidity ($)", 100, 100000, int(cfg.get("MIN_LIQUIDITY", 5000)), 500)
        scan_int = s3.slider("Scan Interval (s)", 30, 600, int(cfg.get("SCAN_INTERVAL", 120)), 10)
        target_vol = s3.slider("Target Annual Vol", 0.05, 0.50, float(cfg.get("TARGET_ANNUAL_VOL", 0.15)), 0.05)

        if st.button("Save Configuration", type="primary"):
            cfg.update(PAPER_BANKROLL=paper_br, KELLY_FRACTION=kelly, MAX_BET_PCT=max_bet/100,
                       MIN_EV_THRESHOLD=min_ev, MIN_EDGE_POINTS=min_edge/100, MAX_CONCURRENT=max_conc,
                       MIN_LIQUIDITY=min_liq, SCAN_INTERVAL=scan_int, TARGET_ANNUAL_VOL=target_vol)
            save_config(cfg); st.toast("Configuration saved", icon="✅")


# ═══════════════════════════════════════════════
# Logs
# ═══════════════════════════════════════════════

elif "Logs" in page:

    """
    # :material/terminal: Bot Log
    """

    ""

    lf = st.text_input("Filter", placeholder="e.g. TRADE|learner|error")
    try:
        lines = Path(LOG_FILE).read_text().splitlines()
    except:
        lines = []
    if lf:
        import re
        try:
            lines = [l for l in lines if re.search(lf, l, re.IGNORECASE)]
        except:
            pass
    display = lines[-100:]
    if display:
        with st.container(border=True):
            st.code("\n".join(display), language="log")
    else:
        st.info("No log entries" + (" matching filter" if lf else ""), icon=":material/info:")


# Footer
""
st.caption(f"ArsLucri · {scan_count} scans · {len(open_pos)} positions · {time_ago(last_scan)}")

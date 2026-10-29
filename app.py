"""
Superstore AI Analyst

How it answers a question:
  1. UNDERSTAND (AI)  : picks the question type (Q1–Q10) and fills a fixed form
  2. CONFIRM    (you) : "I understood this as…" — change it in one click if the AI got it wrong
  3. COMPUTE    (code): fixed method for that type, SQL + Python maths
  4. EXPLAIN    (AI)  : explains the code's numbers in plain English (no new numbers)

Run:  python -m streamlit run app.py
"""

import html
import re

import streamlit as st

import pipeline
import recipes
from data import DIMENSIONS, METRIC_LABELS, METRICS, load
from router import Q_TYPES

st.set_page_config(page_title="Superstore AI Analyst", page_icon="📊", layout="wide")

STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Semi+Condensed:wght@600;700&display=swap');
html, body, p, li, h1, h2, h3, h4, label, input, textarea, td, th,
[data-testid="stMetricValue"], [data-testid="stMetricLabel"], [data-testid="stMetricDelta"] {
  font-family: 'Barlow', sans-serif; }
[data-testid="stMetricValue"], .stMarkdown td { font-variant-numeric: tabular-nums; }
.block-container { padding-top: 2.4rem; max-width: 1180px; }

/* thin white outlines instead of filled boxes */
.stButton button { background: transparent; border: 1px solid rgba(255,255,255,.45); border-radius: 2px;
                   height: auto; min-height: 2.6rem; justify-content: flex-start; }
.stButton button:hover { border-color: #FFFFFF; background: rgba(255,255,255,.06); }
.stButton button p { white-space: normal; text-align: left; line-height: 1.3; color: #F2F4F5; }
[data-testid="stExpander"] details { border: 1px solid rgba(255,255,255,.25); border-radius: 2px; }
[data-testid="stChatInput"] { border-radius: 2px; }

/* the welcome screen: one big statement, like a launch page */
.hero h1 { font-family: 'Barlow Semi Condensed', sans-serif; font-size: 3.4rem; line-height: 1.0;
           font-weight: 700; text-transform: uppercase; letter-spacing: .01em; color: #FFFFFF; margin: 0 0 .9rem; }
.hero p { font-size: 1.08rem; color: #9AA4AD; max-width: 60ch; margin: 0 0 2rem; }
.hero { border-bottom: 1px solid rgba(255,255,255,.18); margin-bottom: 1.6rem; padding-bottom: .4rem; }
.group-title { font-weight: 600; color: #FFFFFF; margin: .2rem 0 .5rem; }

/* "I understood" = a white price tag (monochrome) */
.tag { display: inline-flex; align-items: center; gap: .55rem; background: #FFFFFF; color: #000000;
       padding: .38rem .9rem .38rem 1.35rem; border-radius: 2px 8px 8px 2px; position: relative;
       font-size: .95rem; margin: .1rem 0 .3rem; }
.tag::before { content: ""; position: absolute; left: .5rem; top: 50%; width: .42rem; height: .42rem;
               margin-top: -.21rem; border-radius: 50%; background: #000000; }
.tag b { font-weight: 600; }
.tag-source { font-size: .82rem; color: #9AA4AD; margin: 0 0 .8rem; }

/* answer headline and key numbers */
[data-testid="stChatMessage"] h3 { font-family: 'Barlow Semi Condensed', sans-serif; font-size: 1.55rem;
                                    line-height: 1.25; font-weight: 600; color: #FFFFFF; }
[data-testid="stMetric"] { background: transparent; border: 1px solid rgba(255,255,255,.22); border-radius: 2px;
                           padding: .7rem .9rem; }
[data-testid="stMetricLabel"] p { color: #9AA4AD; font-size: .88rem; }
[data-testid="stMetricValue"] { color: #FFFFFF; }

/* sidebar */
[data-testid="stSidebar"] { border-right: 1px solid rgba(255,255,255,.12); }
.how li { margin-bottom: .35rem; color: #C9D0D5; }
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)


@st.cache_resource
def get_data():
    return load()


conn, df = get_data()


def md(text: str) -> str:
    """Escape $ so Streamlit doesn't read it as maths formatting."""
    return str(text).replace("$", "\\$")


def understood_text(p: dict) -> str:
    code, name, _ = Q_TYPES.get(p["q_type"], Q_TYPES["other"])
    parts = [f"{code} {name}"]
    if p["q_type"] in ("descriptive", "trend", "comparison", "diagnostic", "forecast"):
        parts.append(METRIC_LABELS[p["metric"]])
    if p["q_type"] == "comparison":
        parts.append("by " + recipes.dim_name(p["dimension"] if p["dimension"] != "none" else "region"))
        parts.append("lowest first" if p["order"] == "asc" else "highest first")
        if p["top_n"]:
            parts.append(f"top {p['top_n']}")
    if p["q_type"] == "trend":
        parts.append(f"by {p['period']}")
    if p["q_type"] == "correlation":
        parts.append(f"{p['x_column']} vs {p['y_column']}")
    if p["q_type"] == "forecast":
        parts.append(f"next {p['horizon']} months")
    parts.append(recipes.scope_text(p["filters"]))
    return " · ".join(parts)


# ---------------------------------------------------------------- "change how I understood this"
def edit_form(entry: dict, idx: int):
    p = entry["params"]
    with st.expander("✏️ Not what you meant? Change how I understood it"):
        c1, c2, c3 = st.columns(3)
        types = [t for t in Q_TYPES if t != "other"]
        q_type = c1.selectbox("Question type", types, index=types.index(p["q_type"]) if p["q_type"] in types else 0,
                              format_func=lambda t: f"{Q_TYPES[t][0]} {Q_TYPES[t][1]}", key=f"e_type_{idx}")
        metric = c2.selectbox("Measure", list(METRICS), index=list(METRICS).index(p["metric"]),
                              format_func=lambda m: METRIC_LABELS[m], key=f"e_metric_{idx}")
        dims = ["none"] + DIMENSIONS
        dimension = c3.selectbox("Compare by", dims, index=dims.index(p["dimension"]) if p["dimension"] in dims else 0,
                                 key=f"e_dim_{idx}")
        c4, c5, c6, c7 = st.columns(4)
        f = p["filters"]

        def pick(col, label, column, key):
            options = ["All"] + sorted(df[column].unique())
            current = f.get(column, "All")
            return col.selectbox(label, options, index=options.index(current) if current in options else 0, key=key)

        region = pick(c4, "Region", "region", f"e_region_{idx}")
        category = pick(c5, "Category", "category", f"e_cat_{idx}")
        segment = pick(c6, "Segment", "segment", f"e_seg_{idx}")
        years = ["All", "2014", "2015", "2016", "2017"]
        year = c7.selectbox("Year", years, index=years.index(f.get("year", "All")) if f.get("year", "All") in years else 0,
                            key=f"e_year_{idx}")
        c8, c9, c10 = st.columns(3)
        period = c8.selectbox("Time step (trend)", ["month", "quarter", "year"],
                              index=["month", "quarter", "year"].index(p["period"]), key=f"e_period_{idx}")
        order = c9.selectbox("Order", ["desc", "asc"], index=["desc", "asc"].index(p["order"]),
                             format_func=lambda o: "Highest first" if o == "desc" else "Lowest first", key=f"e_order_{idx}")
        top_n = c10.number_input("Top N (0 = all)", 0, 50, int(p["top_n"]), key=f"e_top_{idx}")

        if st.button("Re-run with these settings", key=f"e_run_{idx}", type="primary"):
            new = {**p, "q_type": q_type, "metric": metric, "dimension": dimension, "period": period,
                   "order": order, "top_n": int(top_n), "clear": True, "clarify_options": []}
            # keep filters the form doesn't show (sub-category, state…), replace the ones it does
            new["filters"] = {k: v for k, v in f.items() if k not in ("region", "category", "segment", "year")}
            for k, v in (("region", region), ("category", category), ("segment", segment), ("year", year)):
                if v != "All":
                    new["filters"][k] = v
            st.session_state.edit = (entry["question"], new)
            st.rerun()


# ---------------------------------------------------------------- display
def show(entry: dict, idx: int):
    if entry.get("clarify"):
        st.markdown("I'm not sure what you mean. Did you mean one of these?")
        cols = st.columns(len(entry["clarify"]))
        for i, q in enumerate(entry["clarify"]):
            if cols[i].button(q, key=f"clar_{idx}_{i}"):
                st.session_state.pending = q
                st.rerun()
        return

    r: recipes.Result = entry["result"]
    _, _, method = Q_TYPES.get(r.q_type, Q_TYPES["other"])
    st.markdown(f'<div class="tag"><b>I understood</b> {html.escape(understood_text(entry["params"]))}</div>'
                f'<div class="tag-source">Routed by {html.escape(entry["source"])}. Not right? Change it below.</div>',
                unsafe_allow_html=True)
    st.markdown(f"### {md(r.headline)}")

    if r.kpi_cards and r.facts:
        facts = dict(r.facts)
        deltas = {}
        for label, value in r.facts:                 # "Sales vs 2015: +29.5%" -> arrow on the Sales card
            m = re.match(r"Sales vs (\d{4})", label)
            if m:
                deltas["Sales"] = f"{value} vs {m.group(1)}"
            m = re.match(r"Profit margin in (\d{4})", label)
            if m and "Profit margin" in facts:
                pts = float(facts["Profit margin"].rstrip("%")) - float(value.rstrip("%"))
                deltas["Profit margin"] = f"{pts:+.1f} pts vs {m.group(1)}"
        shown = [(k, v) for k, v in r.facts if not re.match(r"(Sales vs|Profit margin in) \d{4}", k)]
        cols = st.columns(4)
        for i, (label, value) in enumerate(shown):
            cols[i % 4].metric(label, value, delta=deltas.get(label))
    elif r.facts:
        rows = "\n".join(f"| {md(k)} | **{md(v)}** |" for k, v in r.facts)
        st.markdown("| Key number | Value |\n|---|---|\n" + rows)

    if r.chart is not None:
        st.altair_chart(r.chart, width="stretch", theme=None)

    if entry["narration"]:
        st.markdown(md(entry["narration"]))

    for note in r.notes:
        st.caption("ℹ️ " + md(note))

    if r.extra_table is not None:
        with st.expander(r.extra_title):
            st.dataframe(r.extra_table, hide_index=True, width="stretch")

    with st.expander("How this was calculated (cross-check here)"):
        st.markdown(f"**Method:** {method}")
        f = entry["params"]["filters"]
        st.markdown("**Filters:** " + (", ".join(f"{k} = {v}" for k, v in f.items()) if f else "none"))
        st.markdown(f"**Data:** {len(df):,} order lines, {df['order_date'].min()} to {df['order_date'].max()}")
        for s in r.sql:
            st.code(s, language="sql")
        if r.checks:
            st.markdown("**AI explanation checks:** the automatic check rejected "
                        f"{len(r.checks)} AI draft(s):")
            for c in r.checks:
                st.caption("✗ " + md("; ".join(c["problems"])))
        st.json(entry["params"], expanded=False)

    if r.table is not None and len(r.table):
        with st.expander("Result data"):
            st.dataframe(r.table, hide_index=True, width="stretch")
            st.download_button("Download CSV", r.table.to_csv(index=False).encode(), file_name="result.csv",
                               mime="text/csv", key=f"dl_{idx}")

    edit_form(entry, idx)

    if r.next_questions:
        st.caption("Ask next:")
        cols = st.columns(len(r.next_questions))
        for i, q in enumerate(r.next_questions):
            if cols[i].button(q, key=f"next_{idx}_{i}"):
                st.session_state.pending = q
                st.rerun()


# ---------------------------------------------------------------- page
for key, default in (("history", []), ("pending", None), ("edit", None)):
    if key not in st.session_state:
        st.session_state[key] = default

EXAMPLES = {
    "How are we doing?": ["Total sales and profit in 2017", "How is the West region doing in 2017?"],
    "What changed?": ["Show monthly sales", "Show quarterly profit for the Furniture category"],
    "Why?": ["Why is profit low in Texas in 2017?", "Does discount affect profit?"],
    "Who are our customers?": ["Who are our best customers?", "Do customers come back after their first purchase?"],
    "What's next?": ["Forecast sales for the next 3 months", "Which state lost the most money in 2017?"],
}

with st.sidebar:
    st.markdown("### Superstore AI Analyst")
    st.markdown('<ol class="how"><li>The AI reads your question and shows what it understood.</li>'
                "<li>Tested SQL and Python code calculates every number.</li>"
                "<li>The AI's explanation is checked before you see it.</li></ol>", unsafe_allow_html=True)
    st.caption(f"Data: Superstore sales, {len(df):,} order lines, "
               f"{df['order_date'].min()[:4]}–{df['order_date'].max()[:4]}")
    st.caption(f"Model: {pipeline.MODEL}, running locally with Ollama")
    if st.button("Clear chat", width="stretch"):
        st.session_state.history = []
        st.rerun()
    with st.expander("Example questions"):
        for group, qs in EXAMPLES.items():
            for q in qs:
                if st.button(q, key=f"side_{q}", width="stretch"):
                    st.session_state.pending = q
                    st.rerun()
    st.caption("Funnel and A/B test questions need data Superstore doesn't have; the app says so.")
    st.markdown("[Code, tests and demo on GitHub](https://github.com/madhanusrikrishna-dot/superstore-ai-analyst)")

# read the chat box first (it always sits at the bottom), so the welcome screen hides as soon as you ask
typed = st.chat_input("Ask about sales, profit, customers…")

if not st.session_state.history and not st.session_state.pending and not st.session_state.edit and not typed:
    st.markdown('<div class="hero"><h1>Ask your sales data a question.</h1>'
                f"<p>Superstore sales, {len(df):,} order lines from 2014 to 2017. The AI reads your question; "
                "tested code does every calculation, and each answer shows its SQL.</p></div>",
                unsafe_allow_html=True)
    cols = st.columns(len(EXAMPLES))
    for col, (group, qs) in zip(cols, EXAMPLES.items()):
        col.markdown(f'<div class="group-title">{group}</div>', unsafe_allow_html=True)
        for q in qs:
            if col.button(q, key=f"hero_{q}", width="stretch"):
                st.session_state.pending = q
                st.rerun()

for i, entry in enumerate(st.session_state.history):
    with st.chat_message("user"):
        st.write(entry["question"])
    with st.chat_message("assistant"):
        show(entry, i)

question = typed or st.session_state.pending
st.session_state.pending = None
edit = st.session_state.edit
st.session_state.edit = None

if question or edit:
    with st.chat_message("user"):
        st.write(question if question else f"{edit[0]}  _(re-run with your settings)_")
    with st.chat_message("assistant"):
        with st.spinner("Analysing…"):
            if question:
                previous = next((h["params"] for h in reversed(st.session_state.history) if h.get("result")), None)
                entry = pipeline.answer(conn, df, question, previous=previous)
            else:
                entry = pipeline.answer(conn, df, edit[0], params=edit[1])
                entry["question"] = f"{edit[0]} (re-run with your settings)"
        st.session_state.history.append(entry)
        show(entry, len(st.session_state.history) - 1)

"""
router.py - Step 1 of every question: decide the QUESTION TYPE (your 10-Q framework)
and pull out the details (metric, dimension, filters).

The AI only fills in a fixed form (JSON). It never does maths and never writes the method.
If the AI is unavailable or returns something broken, a simple keyword router is used.
"""

import json
import re

from data import DIMENSIONS, FILTER_COLUMNS, METRICS, NUMBER_COLUMNS

Q_TYPES = {
    "descriptive": ("Q1", "Descriptive", "KPIs: SUM, COUNT DISTINCT, AVG, ratios"),
    "trend": ("Q2", "Trend", "GROUP BY period + change % (MoM / YoY)"),
    "comparison": ("Q3", "Comparison", "GROUP BY + rank"),
    "diagnostic": ("Q4", "Diagnostic", "Drill-down: keep the weakest group at each level"),
    "correlation": ("Q5", "Correlation", "Correlation coefficient + bucket averages"),
    "segmentation": ("Q6", "Segmentation", "RFM scores → customer segments"),
    "funnel": ("Q7", "Funnel", "Conversion % per step"),
    "cohort": ("Q8", "Cohort", "First-purchase quarter → return rate"),
    "experiment": ("Q9", "Experiment", "A/B conversion + significance"),
    "forecast": ("Q10", "Forecast", "Same month last year × growth"),
    "other": ("—", "Custom", "AI-written SQL (check it carefully)"),
}

ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "q_type": {"type": "string", "enum": list(Q_TYPES)},
        "metric": {"type": "string", "enum": list(METRICS)},
        "dimension": {"type": "string", "enum": DIMENSIONS + ["none"]},
        "period": {"type": "string", "enum": ["month", "quarter", "year"]},
        "order": {"type": "string", "enum": ["desc", "asc"]},
        "top_n": {"type": "integer"},
        "horizon": {"type": "integer"},
        "x_column": {"type": "string", "enum": NUMBER_COLUMNS},
        "y_column": {"type": "string", "enum": NUMBER_COLUMNS},
        "filters": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in FILTER_COLUMNS + ["year"]},
        },
        "clear": {"type": "boolean"},
        "clarify_options": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["q_type", "metric", "dimension", "period", "order", "top_n", "horizon",
                 "x_column", "y_column", "filters", "clear", "clarify_options"],
}

# Worked examples shown to the AI (few-shot). Different wording from the test set in evaluate.py,
# so the test measures real understanding, not memory.
EXAMPLES = [
    ("What was our revenue last year in 2016?", {"q_type": "descriptive", "metric": "sales", "filters": {"year": "2016"}}),
    ("How many orders did the Consumer segment place?", {"q_type": "descriptive", "metric": "orders", "filters": {"segment": "Consumer"}}),
    ("Plot profit for each year", {"q_type": "trend", "metric": "profit", "period": "year"}),
    ("Monthly quantity sold in the South in 2016", {"q_type": "trend", "metric": "quantity", "period": "month", "filters": {"region": "South", "year": "2016"}}),
    ("Rank the regions by profit margin", {"q_type": "comparison", "metric": "margin", "dimension": "region", "order": "desc"}),
    ("Show the 7 worst products by profit", {"q_type": "comparison", "metric": "profit", "dimension": "product_name", "order": "asc", "top_n": 7}),
    ("Which segment buys the most technology?", {"q_type": "comparison", "metric": "sales", "dimension": "segment", "filters": {"category": "Technology"}}),
    ("Why are we losing money on Bookcases?", {"q_type": "diagnostic", "metric": "profit", "filters": {"sub_category": "Bookcases"}}),
    ("What explains the weak margin in Texas?", {"q_type": "diagnostic", "metric": "margin", "filters": {"state": "Texas"}}),
    ("Do higher discounts hurt profit?", {"q_type": "correlation", "x_column": "discount", "y_column": "profit"}),
    ("Is quantity linked to sales?", {"q_type": "correlation", "x_column": "quantity", "y_column": "sales"}),
    ("Group our customers by value", {"q_type": "segmentation"}),
    ("How many new customers return in later quarters?", {"q_type": "cohort"}),
    ("What sales do you expect for the next 4 months?", {"q_type": "forecast", "metric": "sales", "horizon": 4}),
    ("How many visitors added to cart but didn't pay?", {"q_type": "funnel"}),
    ("Did version B of the checkout page convert better?", {"q_type": "experiment"}),
    ("Is that good?", {"q_type": "other", "clear": False, "clarify_options": [
        "Is our overall profit margin good?", "How did sales change over time?", "Which region performs best?"]}),
]


def _examples_text() -> str:
    lines = []
    for q, form in EXAMPLES:
        lines.append(f"Q: {q}\nA: {json.dumps(form)}")
    return "\n".join(lines)

ROUTER_PROMPT = """You classify a business question about a US retail store's sales data (2014-2017)
and fill in a JSON form. Do NOT answer the question.

Question types:
- descriptive: overall totals / KPIs, "how much", "how many", "summary", "overall".
- trend: change over time, "monthly", "yearly", "growing", "over time", "seasonal".
- comparison: compare groups, "by region", "which ... best/worst/highest/lowest", "top N".
- diagnostic: asks WHY something is low/bad/dropped, "reason", "what's causing".
- correlation: does X affect Y, "relationship", "impact of discount on profit".
- segmentation: types of customers, "best customers", "loyal", "at risk", "RFM", "segment customers".
- funnel: drop-off between steps (visit -> cart -> buy).
- cohort: do customers come back, "retention", "repeat purchase", "churn".
- experiment: A/B test, did a change/version work.
- forecast: future, "next month", "predict", "expect", "estimate".
- other: anything that does not fit.

Fields:
- metric: sales, profit, quantity, orders, customers, margin (profit/sales), discount (average), aov (sales per order). Default "sales"; for "why ... low/losing" questions default "profit".
- dimension: the column to compare by (region, category, sub_category, segment, state, city, ship_mode, customer_name, product_name) or "none".
- period: month, quarter or year (for trend). Default "month".
- order: "desc" for highest/best/top, "asc" for lowest/worst. Default "desc".
- top_n: number of rows asked for, 0 if not given.
- horizon: months ahead for forecast, default 3.
- x_column, y_column: for correlation (sales, profit, quantity, discount). Default x=discount, y=profit.
- filters: only values the question names. Keys: region, category, sub_category, segment, state, ship_mode, year. Use "" when not given.
Regions: West, East, Central, South. Categories: Furniture, Office Supplies, Technology.
Segments: Consumer, Corporate, Home Office.
- clear: true when you can fill the form. false ONLY if the question is too vague to know what is asked
  (e.g. "is that good?", "what about it?"); then give 3 clearer questions in clarify_options.
- clarify_options: [] when clear is true.

Examples (only the important fields are shown; fill every field in your answer):
"""


def _default_params():
    return {"q_type": "other", "metric": "sales", "dimension": "none", "period": "month",
            "order": "desc", "top_n": 0, "horizon": 3, "x_column": "discount",
            "y_column": "profit", "filters": {}, "clear": True, "clarify_options": []}


def clean_params(raw: dict) -> dict:
    """Fill gaps and drop invalid values so recipes always get a valid form."""
    p = _default_params()
    for k in p:
        if k in raw and raw[k] not in (None, ""):
            p[k] = raw[k]
    if p["q_type"] not in Q_TYPES:
        p["q_type"] = "other"
    if p["metric"] not in METRICS:
        p["metric"] = "sales"
    if p["dimension"] not in DIMENSIONS:
        p["dimension"] = "none"
    if p["period"] not in ("month", "quarter", "year"):
        p["period"] = "month"
    if p["order"] not in ("asc", "desc"):
        p["order"] = "desc"
    for k, lo, hi, d in (("top_n", 0, 50, 0), ("horizon", 1, 12, 3)):
        try:
            p[k] = max(lo, min(hi, int(p[k])))
        except (TypeError, ValueError):
            p[k] = d
    for k in ("x_column", "y_column"):
        if p[k] not in NUMBER_COLUMNS:
            p[k] = "discount" if k == "x_column" else "profit"
    p["filters"] = {k: str(v) for k, v in (p["filters"] or {}).items()
                    if k in FILTER_COLUMNS + ["year"] and str(v).strip() not in ("", "none", "None", "all", "All", "0")}
    p["clear"] = bool(p.get("clear", True))
    p["clarify_options"] = [str(o) for o in (p.get("clarify_options") or [])][:3]
    if not p["clear"] and not p["clarify_options"]:
        p["clear"] = True   # can't ask without options: answer instead
    if p["clear"]:
        p["clarify_options"] = []
    return p


def keyword_route(question: str) -> dict:
    """Simple backup router (no AI): picks the type from keywords."""
    q = question.lower()
    raw = _default_params()
    rules = [
        ("forecast", r"\b(forecast|predict|next (month|quarter|year)|expect|estimate|projection)\b"),
        ("diagnostic", r"\b(why|reason|cause|causing|explain the drop)\b"),
        ("correlation", r"\b(affect|impact|relationship|correlat|does .* (increase|reduce))\b"),
        ("segmentation", r"\b(segment customers|rfm|best customers|loyal|at risk|types of customers|customer segments)\b"),
        ("cohort", r"\b(retention|come back|repeat|churn|cohort|return rate)\b"),
        ("funnel", r"\b(funnel|drop.?off|conversion|checkout|add to cart)\b"),
        ("experiment", r"\b(a/b|ab test|experiment|variant|did the new)\b"),
        ("trend", r"\b(monthly|yearly|quarterly|over time|trend|growing|growth|by month|by year|each month|each year|seasonal)\b"),
        ("comparison", r"\b(by|per|each|which|top|best|worst|highest|lowest|compare|vs)\b"),
        ("descriptive", r"\b(total|overall|how much|how many|summary|kpi)\b"),
    ]
    for q_type, pattern in rules:
        if re.search(pattern, q):
            raw["q_type"] = q_type
            break
    for m in ["margin", "profit", "quantity", "orders", "customers", "discount", "aov", "sales"]:
        if m in q or (m == "aov" and "order value" in q):
            if not (m == "discount" and raw["q_type"] == "correlation"):
                raw["metric"] = m
                break
    if raw["q_type"] == "correlation":
        found = sorted((q.find(c), c) for c in ["discount", "quantity", "sales", "profit"] if c in q)
        if len(found) >= 2:
            raw["x_column"], raw["y_column"] = found[0][1], found[1][1]
    if raw["q_type"] == "diagnostic" and "sales" not in q:
        raw["metric"] = "profit"
    stems = [("sub_categor", "sub_category"), ("sub-categor", "sub_category"), ("sub categor", "sub_category"),
             ("subcategor", "sub_category"), ("categor", "category"), ("region", "region"),
             ("segment", "segment"), ("state", "state"), ("cit", "city"), ("ship mode", "ship_mode"),
             ("customer", "customer_name"), ("product", "product_name")]
    for stem, dim in stems:
        if re.search(rf"\b{stem}", q):
            raw["dimension"] = dim
            break
    if raw["q_type"] == "comparison" and raw["dimension"] == "none":
        raw["dimension"] = "region"
    if "year" in q and raw["q_type"] == "trend" and "month" not in q:
        raw["period"] = "year"
    if "quarter" in q:
        raw["period"] = "quarter"
    if re.search(r"\b(lowest|worst|least|bottom|smallest)\b", q):
        raw["order"] = "asc"
    n = re.search(r"\b(top|bottom)\s+(\d+)", q)
    if n:
        raw["top_n"] = int(n.group(2))
    h = re.search(r"next\s+(\d+)\s+months?", q)
    if h:
        raw["horizon"] = int(h.group(1))
    year = re.search(r"\b(201[4-7])\b", q)
    filters = {}
    if year:
        filters["year"] = year.group(1)
    for region in ["west", "east", "central", "south"]:
        if re.search(rf"\b{region}\b", q):
            filters["region"] = region.title()
    for cat in ["furniture", "technology", "office supplies"]:
        if cat in q:
            filters["category"] = cat.title()
    for seg in ["consumer", "corporate", "home office"]:
        if seg in q:
            filters["segment"] = seg.title()
    # a value we filter on should not also be the comparison dimension
    if raw["dimension"] in filters:
        raw["dimension"] = "none"
    raw["filters"] = filters
    return clean_params(raw)


def ai_route(question: str, model: str, previous: dict | None = None) -> tuple[dict, str]:
    """Ask the local AI to fill the form. Returns (params, source)."""
    try:
        import ollama

        prompt = ROUTER_PROMPT + _examples_text() + "\n"
        if previous:
            prev = {k: v for k, v in previous.items() if k not in ("clear", "clarify_options")}
            prompt += ("\nThe previous question was routed as:\n" + json.dumps(prev) +
                       "\nIf the new question is a short follow-up (e.g. 'and for West?', 'what about 2016?'), "
                       "keep the previous fields and change only what the new question says.\n")
        reply = ollama.chat(
            model=model,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": question}],
            format=ROUTER_SCHEMA,
            options={"temperature": 0},
        )
        raw = json.loads(reply["message"]["content"])
        return clean_params(raw), "AI"
    except Exception:
        return keyword_route(question), "keyword backup"

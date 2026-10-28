"""
recipes.py - one fixed method per question type (your 10-Q framework).

Every recipe:
  1. runs SQL on the data (shown to the user so they can cross-check),
  2. does all maths in Python (never in the AI),
  3. returns a Result: headline, key numbers, table, chart, SQL, notes, next questions.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import charts
import fmt
from data import ADDITIVE, METRIC_LABELS, METRICS, RATIOS, run, show_sql, where_clause


@dataclass
class Result:
    q_type: str
    headline: str
    facts: list = field(default_factory=list)          # [(label, formatted value)]
    table: pd.DataFrame | None = None
    chart: object = None
    sql: list = field(default_factory=list)            # SQL strings shown to the user
    notes: list = field(default_factory=list)          # warnings / caveats
    next_questions: list = field(default_factory=list)
    kpi_cards: bool = False
    extra_table: pd.DataFrame | None = None
    extra_title: str = ""


def scope_text(filters: dict) -> str:
    parts = [v for k, v in filters.items() if k != "year"]
    where = ", ".join(parts) if parts else "All regions"
    return f"{where}, {filters['year']}" if "year" in filters else f"{where}, 2014–2017"


# ---------------------------------------------------------------- Q1 Descriptive
def descriptive(conn, p: dict) -> Result:
    where, params = where_clause(p["filters"])
    sql = f"""
SELECT ROUND(SUM(sales), 2)               AS sales,
       ROUND(SUM(profit), 2)              AS profit,
       COUNT(DISTINCT order_id)           AS orders,
       COUNT(DISTINCT customer_id)        AS customers,
       SUM(quantity)                      AS quantity,
       ROUND(AVG(discount), 4)            AS avg_discount
FROM superstore
{where}"""
    row = run(conn, sql, params).iloc[0]
    if not row["orders"]:
        return Result("descriptive", "No orders match these filters.", sql=[show_sql(sql, params)])
    margin = row["profit"] / row["sales"]
    aov = row["sales"] / row["orders"]
    facts = [
        ("Sales", fmt.money(row["sales"])),
        ("Profit", fmt.money(row["profit"])),
        ("Profit margin", fmt.pct(margin)),
        ("Orders", fmt.count(row["orders"])),
        ("Customers", fmt.count(row["customers"])),
        ("Avg order value", fmt.money(aov)),
        ("Items sold", fmt.count(row["quantity"])),
        ("Avg discount", fmt.pct(row["avg_discount"])),
    ]
    table = pd.DataFrame([{**row.to_dict(), "margin": round(margin, 4), "aov": round(aov, 2)}])
    notes = []
    sqls = [show_sql(sql, params)]
    headline = f"{scope_text(p['filters'])}: {fmt.money(row['sales'])} in sales, profit margin {fmt.pct(margin)}"
    # "how is X doing?" needs a benchmark: the whole company over the same years
    if any(k != "year" for k in p["filters"]):
        base_filters = {k: v for k, v in p["filters"].items() if k == "year"}
        bw, bp = where_clause(base_filters)
        base_sql = f"SELECT SUM(sales) AS sales, SUM(profit) AS profit FROM superstore {bw}"
        base = run(conn, base_sql, bp).iloc[0]
        base_margin = base["profit"] / base["sales"]
        facts.append(("Share of company sales", fmt.pct(row["sales"] / base["sales"])))
        facts.append(("Company-wide margin, same years", fmt.pct(base_margin)))
        sqls.append(show_sql(base_sql, bp))
        word = "above" if margin > base_margin else "below"
        headline += f" ({word} the company's {fmt.pct(base_margin)})"
    if row["avg_discount"] > margin:
        notes.append("Average discount is higher than the profit margin. Discounts may be eating profit (check with a correlation question).")
    return Result(
        "descriptive",
        headline,
        facts=facts, table=table, sql=sqls, notes=notes, kpi_cards=True,
        next_questions=["Show monthly sales trend", "Which region has the lowest profit?",
                        "Does discount affect profit?"],
    )


# ---------------------------------------------------------------- Q2 Trend
PERIOD_SQL = {
    "month": "substr(order_date, 1, 7)",
    "quarter": "substr(order_date, 1, 4) || '-Q' || ((CAST(substr(order_date, 6, 2) AS INTEGER) + 2) / 3)",
    "year": "substr(order_date, 1, 4)",
}


def _trend_next(p: dict, label: str, metric: str) -> list:
    """Follow-ups about what the user is looking at (e.g. Furniture), not a fixed example."""
    focus = next((v for k, v in p["filters"].items() if k != "year"), None)
    compare_by = "category" if "region" in p["filters"] else "region"
    forecast = f"Forecast {label.lower()} for the next 3 months" if metric in ADDITIVE else "Forecast sales for the next 3 months"
    if focus:
        return [f"Why is profit low in {focus}?", f"How is {focus} doing?", forecast]
    return [f"Compare {label.lower()} by {compare_by}", forecast, "Why is profit low in the Central region?"]


def trend(conn, p: dict) -> Result:
    metric, period = p["metric"], p["period"]
    where, params = where_clause(p["filters"])
    sql = f"""
SELECT {PERIOD_SQL[period]} AS period,
       {METRICS[metric]} AS value
FROM superstore
{where}
GROUP BY period
ORDER BY period"""
    df = run(conn, sql, params)
    if len(df) < 2:
        return Result("trend", "Not enough periods to show a trend.", table=df, sql=[show_sql(sql, params)])

    label = METRIC_LABELS[metric]
    # % change is meaningless when values are losses (e.g. -$55 -> -$1,191), so use plain differences then
    use_diff = metric in RATIOS or bool((df["value"] < 0).any())
    if use_diff:
        df["change_vs_previous"] = df["value"].diff()
    else:
        df["change_vs_previous"] = df["value"].pct_change()
    lag = {"month": 12, "quarter": 4, "year": 1}[period]
    if period != "year" and len(df) > lag:
        df["change_vs_last_year"] = (df["value"].diff(lag) if use_diff
                                     else df["value"] / df["value"].shift(lag) - 1)
    df = df.replace([np.inf, -np.inf], np.nan)

    first, last = df.iloc[0], df.iloc[-1]
    peak = df.loc[df["value"].idxmax()]
    low = df.loc[df["value"].idxmin()]
    drops = df["change_vs_previous"]
    worst_i = drops.idxmin()
    worst = df.loc[worst_i]
    before_worst = df.loc[worst_i - 1]

    facts = [
        (f"{label} in {first['period']}", fmt.value(metric, first["value"])),
        (f"{label} in {last['period']}", fmt.value(metric, last["value"])),
        ("Change, first → last", fmt.change(metric, first["value"], last["value"])),
        ("Highest", f"{peak['period']} · {fmt.value(metric, peak['value'])}"),
        ("Lowest", f"{low['period']} · {fmt.value(metric, low['value'])}"),
        ("Biggest drop", f"{before_worst['period']} → {worst['period']} · "
                         f"{fmt.change(metric, before_worst['value'], worst['value'])}"),
    ]

    notes = []
    if period == "month" and len(df) >= 24:
        tmp = df.copy()
        tmp["m"] = tmp["period"].str[5:7]
        by_month = tmp.groupby("m")["value"].mean()
        top = by_month.sort_values(ascending=False).head(2).index
        names = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun", "07": "Jul",
                 "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}
        facts.append(("Strongest months on average", " & ".join(names[m] for m in top)))
        if "change_vs_last_year" in df:
            last12 = df["value"].iloc[-12:].sum()
            prev12 = df["value"].iloc[-24:-12].sum()
            if metric not in RATIOS and prev12:
                facts.append(("Last 12 months vs previous 12", fmt.change(metric, prev12, last12)))

    direction = "rose" if last["value"] >= first["value"] else "fell"
    headline = (f"{label} {direction} {fmt.change(metric, first['value'], last['value']).lstrip('+-')} "
                f"from {first['period']} to {last['period']}, peaking in {peak['period']}")
    block = {"month": 12, "quarter": 4}.get(period)
    if block and len(df) >= 2 * block and metric not in RATIOS:
        # comparing one month/quarter with another is misleading with seasonality: compare whole years instead
        unit = f"{block} {period}s"
        last_b = df["value"].iloc[-block:].sum()
        first_b = df["value"].iloc[:block].sum()
        verb = "grew" if last_b >= first_b else "fell"
        verb = "improved" if (verb == "grew" and min(first_b, last_b) < 0) else verb
        headline = (f"{label} {verb} {fmt.change(metric, first_b, last_b).lstrip('+-')} from the first {unit} "
                    f"({df['period'].iloc[0]} to {df['period'].iloc[block - 1]}) to the last {unit}; "
                    f"{'busiest' if metric in ('sales', 'orders', 'quantity', 'customers') else 'best'} {period} {peak['period']}")
        facts[2] = (f"Change, first {unit} → last {unit}", fmt.change(metric, first_b, last_b))

    # ---- seasonality: never judge a month/quarter only against the one before it
    if period != "year":
        notes.insert(0, f"Seasonality: business peaks in Nov–Dec and is quieter early in the year, so a change vs the {period} before is "
                        f"often just the season. The fair comparison is the same {period} last year (YoY).")
        if "change_vs_last_year" in df and df["change_vs_last_year"].notna().any():
            yoy = df.dropna(subset=["change_vs_last_year"])
            w = yoy.loc[yoy["change_vs_last_year"].idxmin()]
            b = yoy.loc[yoy["change_vs_last_year"].idxmax()]

            def yoy_text(row):
                c = row["change_vs_last_year"]
                if metric in RATIOS:
                    return f"{c * 100:+.1f} pts"
                if use_diff:
                    return ("+" if c >= 0 else "") + fmt.value(metric, c)
                return fmt.pct(c, signed=True)

            facts[5] = (f"Biggest fall vs same {period} last year (a change, not the {period}'s value)",
                        f"{w['period']} · {yoy_text(w)}")
            facts.insert(6, (f"Biggest rise vs same {period} last year (a change, not the {period}'s value)",
                             f"{b['period']} · {yoy_text(b)}"))
        else:
            facts[5] = (f"Biggest drop vs {period} before (may be seasonal)", facts[5][1])
        if "year" in p["filters"]:
            # one year only: compare with the previous year instead of first vs last month
            year = p["filters"]["year"]
            facts[2] = (f"First → last {period} (seasonal, not growth)", facts[2][1])
            headline = (f"{label} in {year}: highest in {peak['period']} ({fmt.value(metric, peak['value'])}), "
                        f"lowest in {low['period']} ({fmt.value(metric, low['value'])})")
            prev_filters = {**p["filters"], "year": str(int(year) - 1)}
            pw, pp = where_clause(prev_filters)
            cw, cp = where_clause(p["filters"])
            prev = run(conn, f"SELECT {METRICS[metric]} AS v FROM superstore {pw}", pp)["v"].iloc[0]
            cur = run(conn, f"SELECT {METRICS[metric]} AS v FROM superstore {cw}", cp)["v"].iloc[0]
            if prev is not None and not pd.isna(prev):
                facts.insert(3, (f"{year} vs {int(year) - 1} (same scope)", fmt.change(metric, prev, cur)))
                headline += f"; {fmt.change(metric, prev, cur)} vs {int(year) - 1}"
    show = df.copy()
    return Result(
        "trend", headline, facts=facts, table=show,
        chart=charts.line(df, "period", "value", metric, peak_label=peak["period"]),
        sql=[show_sql(sql, params)], notes=notes,
        next_questions=_trend_next(p, label, metric),
    )


# ---------------------------------------------------------------- Q3 Comparison
def comparison(conn, p: dict) -> Result:
    metric = p["metric"]
    dim = p["dimension"] if p["dimension"] != "none" else "region"
    if dim in p["filters"]:
        dim = "sub_category" if dim == "category" else "category"
    where, params = where_clause(p["filters"])
    order = "ASC" if p["order"] == "asc" else "DESC"
    asked = p["top_n"] or 0
    # a "which one…" question (top 1-2) still gets the next few as context in the chart and table
    limit = max(asked, 5) if asked else (15 if dim in ("state", "city", "customer_name", "product_name") else 50)
    sql = f"""
SELECT {dim},
       {METRICS[metric]} AS value,
       SUM(sales) AS sales
FROM superstore
{where}
GROUP BY {dim}
ORDER BY value {order}
LIMIT {int(limit)}"""
    df = run(conn, sql, params)
    if df.empty:
        return Result("comparison", "No data for these filters.", sql=[show_sql(sql, params)])
    label = METRIC_LABELS[metric]
    total_sql = f"SELECT {METRICS[metric]} AS total, COUNT(DISTINCT {dim}) AS groups FROM superstore {where}"
    tot = run(conn, total_sql, params).iloc[0]

    first = df.iloc[0]
    word = "lowest" if order == "ASC" else "highest"
    facts = [(f"{word.title()} {label.lower()}", f"{first[dim]} · {fmt.value(metric, first['value'])}")]
    if len(df) > 1:
        second = df.iloc[1]
        facts.append((f"Next {word}", f"{second[dim]} · {fmt.value(metric, second['value'])}"))
    if metric in ADDITIVE and tot["total"]:
        df["share_of_total"] = df["value"] / tot["total"]
        if first["value"] < 0:
            facts.append((f"{first[dim]} loss compared with total {label.lower()}",
                          fmt.pct(abs(first["value"]) / tot["total"])))
        else:
            facts.append((f"{first[dim]} share of total {label.lower()}", fmt.pct(first["value"] / tot["total"])))
    facts.append(("Overall " + label.lower(), fmt.value(metric, tot["total"])))

    sqls = [show_sql(sql, params), show_sql(total_sql, params)]
    if metric in ("profit", "margin"):
        # count losing groups across ALL groups, not only the rows shown
        loss_sql = f"""
SELECT {dim}, {METRICS[metric]} AS value
FROM superstore
{where}
GROUP BY {dim}
HAVING {METRICS[metric]} < 0
ORDER BY value ASC"""
        losses = run(conn, loss_sql, params)
        sqls.append(show_sql(loss_sql, params))
        n_groups = int(tot["groups"])
        nice = dim.replace("_", "-")
        if len(losses):
            names = ", ".join(losses[dim].astype(str).head(5)) + (" …" if len(losses) > 5 else "")
            facts.append((f"Losing money", f"{len(losses)} of {n_groups} {nice} values: {names}"))
        else:
            facts.append((f"Losing money", f"none of {n_groups} {nice} values"))

    notes = []
    if asked and asked < len(df):
        notes.append(f"You asked for the top {asked}; the next {len(df) - asked} are shown for context.")
    elif len(df) < tot["groups"]:
        notes.append(f"Showing {len(df)} of {int(tot['groups'])} {dim.replace('_', '-')} values.")

    nice_dim = dim.replace("_", "-")
    headline = f"{first[dim]} has the {word} {label.lower()} ({fmt.value(metric, first['value'])}) by {nice_dim}"
    filterable = dim in ("region", "category", "sub_category", "segment", "state", "ship_mode")
    return Result(
        "comparison", headline, facts=facts, table=df,
        chart=charts.bar(df, dim, "value", metric),
        sql=sqls, notes=notes,
        next_questions=([f"Why is profit low in {first[dim]}?", f"Show monthly {label.lower()} for {first[dim]}",
                         "Does discount affect profit?"] if filterable and order == "ASC" else
                        [f"Show monthly {label.lower()} for {first[dim]}",
                         f"Compare profit by {nice_dim}" if metric != "profit" else f"Compare sales by {nice_dim}",
                         "Does discount affect profit?"] if filterable else
                        [f"Show monthly {label.lower()}", f"Compare {label.lower()} by region",
                         "Does discount affect profit?"]),
    )


# ---------------------------------------------------------------- Q4 Diagnostic
def diagnostic(conn, p: dict) -> Result:
    metric = p["metric"] if p["metric"] in ("profit", "sales", "margin", "quantity", "orders") else "profit"
    label = METRIC_LABELS[metric]
    filters = dict(p["filters"])
    levels = [d for d in ["region", "category", "sub_category"] if d not in filters]
    path, sqls, last_df, last_level = [], [], None, None

    overall_where, overall_params = where_clause(filters)
    overall_sql = f"SELECT {METRICS[metric]} AS value, AVG(discount) AS discount, SUM(profit)*1.0/SUM(sales) AS margin FROM superstore {overall_where}"
    overall = run(conn, overall_sql, overall_params).iloc[0]
    sqls.append(show_sql(overall_sql, overall_params))

    for level in levels:
        where, params = where_clause(filters)
        sql = f"""
SELECT {level},
       {METRICS[metric]} AS value,
       SUM(sales) AS sales,
       AVG(discount) AS avg_discount
FROM superstore
{where}
GROUP BY {level}
ORDER BY value ASC"""
        df = run(conn, sql, params)
        sqls.append(show_sql(sql, params))
        if len(df) < 2:
            if len(df) == 1:          # e.g. a state lies in one region: nothing to compare, go one level down
                filters[level] = df.iloc[0][level]
                continue
            break
        worst = df.iloc[0]
        avg_other = df["value"].iloc[1:].mean()
        path.append({"level": level.replace("_", "-"), "weakest": worst[level],
                     label: fmt.value(metric, worst["value"]),
                     "average of the others": fmt.value(metric, avg_other),
                     "avg discount": fmt.pct(worst["avg_discount"])})
        filters[level] = worst[level]
        last_df, last_level = df, level

    if not path:
        return Result("diagnostic", "Nothing left to drill into with these filters.", sql=sqls)

    where, params = where_clause(filters)
    final_sql = f"SELECT {METRICS[metric]} AS value, AVG(discount) AS discount, SUM(profit)*1.0/SUM(sales) AS margin, SUM(sales) AS sales FROM superstore {where}"
    final = run(conn, final_sql, params).iloc[0]
    sqls.append(show_sql(final_sql, params))

    start = [str(v) for k, v in p["filters"].items() if k != "year"]
    trail = " → ".join(start + [str(x["weakest"]) for x in path])
    facts = [("Drill-down path", trail),
             (f"{label} at the end of the path", fmt.value(metric, final["value"])),
             ("Its profit margin", fmt.pct(final["margin"])),
             ("Its average discount", fmt.pct(final["discount"])),
             (f"Average discount, all of {scope_text(p['filters'])}", fmt.pct(overall["discount"]))]
    notes = []
    if final["discount"] > overall["discount"] * 1.3:
        notes.append(f"Likely driver: {trail.split(' → ')[-1]} gets a much higher average discount "
                     f"({fmt.pct(final['discount'])} vs {fmt.pct(overall['discount'])} across {scope_text(p['filters'])}). "
                     "This is a strong lead, not proof. Confirm with the business.")
    else:
        notes.append("Discount is not unusually high here. Look at costs, prices or product mix next.")
    notes.append("Drill-down always follows the weakest group at each level; other weak spots may exist.")

    headline = f"Weakest spot for {label.lower()}: {trail} ({fmt.value(metric, final['value'])})"
    return Result(
        "diagnostic", headline, facts=facts, table=pd.DataFrame(path),
        chart=charts.bar(last_df, last_level, "value", metric,
                         title=f"{label} by {last_level.replace('_', '-')} inside {' / '.join(str(x['weakest']) for x in path[:-1]) or 'all data'}"),
        sql=sqls, notes=notes,
        next_questions=["Does discount affect profit?", f"Compare {label.lower()} by sub-category",
                        "Show monthly profit trend"],
    )


# ---------------------------------------------------------------- Q5 Correlation
def correlation(conn, p: dict) -> Result:
    x, y = p["x_column"], p["y_column"]
    if x == y:
        x, y = "discount", "profit"
    where, params = where_clause(p["filters"])
    sql = f"SELECT {x}, {y} FROM superstore {where}"
    df = run(conn, sql, params)
    if len(df) < 10:
        return Result("correlation", "Not enough rows to measure a relationship.", sql=[show_sql(sql, params)])
    r = float(df[x].corr(df[y]))
    strength = ("no real" if abs(r) < 0.1 else "a weak" if abs(r) < 0.3 else "a moderate" if abs(r) < 0.5 else "a strong")
    direction = "negative" if r < 0 else "positive"
    facts = [("Correlation (r)", f"{r:+.2f}"), ("Strength", f"{strength} {direction} link"), ("Rows used", fmt.count(len(df)))]

    sqls = [show_sql(sql, params)]
    table, chart = None, None
    if x == "discount":
        band_sql = f"""
SELECT CASE WHEN discount = 0 THEN '1. No discount'
            WHEN discount <= 0.2 THEN '2. Up to 20%'
            WHEN discount <= 0.4 THEN '3. 21-40%'
            ELSE '4. Over 40%' END AS discount_band,
       COUNT(*) AS lines,
       AVG({y}) AS value
FROM superstore
{where}
GROUP BY discount_band
ORDER BY discount_band"""
        table = run(conn, band_sql, params)
        sqls.append(show_sql(band_sql, params))
        metric = y if y in ("profit", "sales") else "quantity"
        chart = charts.bar(table, "discount_band", "value", metric, title=f"Average {y} per order line by discount")
        for _, row in table.iterrows():
            facts.append((f"Avg {y} per line, {row['discount_band'][3:]}", fmt.value(metric, row["value"])))
        neg = table[table["value"] < 0]
        if len(neg) and y == "profit":
            facts.append(("Loss starts at", neg.iloc[0]["discount_band"][3:]))
    else:
        chart = charts.scatter(df, x, y, title=f"{y} vs {x}")
        table = df.describe().T.reset_index()

    headline = f"{x.title()} and {y} have {strength} {direction} relationship (r = {r:+.2f})"
    if x == "discount" and y == "profit" and table is not None and (table["value"] < 0).any():
        first_loss = table[table["value"] < 0].iloc[0]["discount_band"][3:]
        headline += f", but order lines with {first_loss} discount lose money on average"
    return Result(
        "correlation", headline, facts=facts, table=table, chart=chart, sql=sqls,
        notes=["Correlation ≠ cause. A linked pattern is a lead; only a controlled test (A/B, Q9) proves cause."],
        next_questions=["Which sub-categories get the highest discount?", "Why is profit low in Tables?",
                        "Compare profit by region"],
    )


# ---------------------------------------------------------------- Q6 Segmentation (RFM)
def segmentation(conn, p: dict) -> Result:
    where, params = where_clause(p["filters"])
    sql = f"""
SELECT customer_id,
       customer_name,
       MAX(order_date)           AS last_order,
       COUNT(DISTINCT order_id)  AS frequency,
       ROUND(SUM(sales), 2)      AS monetary
FROM superstore
{where}
GROUP BY customer_id, customer_name"""
    c = run(conn, sql, params)
    if len(c) < 8:
        return Result("segmentation", "Too few customers to segment.", sql=[show_sql(sql, params)])
    end_date = pd.to_datetime(run(conn, "SELECT MAX(order_date) AS d FROM superstore", [])["d"].iloc[0])
    c["recency_days"] = (end_date - pd.to_datetime(c["last_order"])).dt.days
    # scores 1-4 (4 = best). rank() first so equal values don't break the quartiles
    c["R"] = pd.qcut(c["recency_days"].rank(method="first", ascending=False), 4, labels=[1, 2, 3, 4]).astype(int)
    c["F"] = pd.qcut(c["frequency"].rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int)
    c["M"] = pd.qcut(c["monetary"].rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int)

    def segment(row):
        if row.R == 4 and row.F >= 3:
            return "Champions"
        if row.R <= 2 and row.F >= 3:
            return "At risk"
        if row.F >= 3:
            return "Loyal"
        if row.R >= 3:
            return "Recent, low frequency"
        return "Lost / hibernating"

    c["segment"] = c.apply(segment, axis=1)
    order = ["Champions", "Loyal", "Recent, low frequency", "At risk", "Lost / hibernating"]
    seg = (c.groupby("segment")
             .agg(customers=("customer_id", "count"), sales=("monetary", "sum"),
                  avg_orders=("frequency", "mean"), avg_days_since_last=("recency_days", "mean"))
             .reindex(order).dropna(how="all").reset_index())
    seg["share_of_customers"] = seg["customers"] / seg["customers"].sum()
    seg["share_of_sales"] = seg["sales"] / seg["sales"].sum()
    seg = seg.round({"sales": 2, "avg_orders": 1, "avg_days_since_last": 0, "share_of_customers": 4, "share_of_sales": 4})

    facts = []
    for _, s in seg.iterrows():
        facts.append((s["segment"], f"{fmt.count(s['customers'])} customers · {fmt.pct(s['share_of_sales'])} of sales"))
    risk = seg[seg["segment"] == "At risk"]
    notes = ["Scores: R = how recently, F = how often, M = how much, each 1–4 by quartile (4 = best).",
             f"Recency measured from the last date in the data ({end_date.date()})."]
    if len(risk):
        notes.append(f"'At risk' customers bought often but not recently: {fmt.money(risk['sales'].iloc[0])} "
                     "of past sales. A win-back offer is the usual action.")
    top = c.sort_values("monetary", ascending=False).head(10)[
        ["customer_name", "segment", "frequency", "monetary", "recency_days"]]
    champ = seg[seg["segment"] == "Champions"]
    headline = ("Champions are " + fmt.pct(champ["share_of_customers"].iloc[0]) + " of customers but bring "
                + fmt.pct(champ["share_of_sales"].iloc[0]) + " of sales") if len(champ) else "Customer segments by RFM"
    return Result(
        "segmentation", headline, facts=facts, table=seg,
        chart=charts.bar(seg, "segment", "share_of_sales", "margin", title="Share of sales by segment"),
        sql=[show_sql(sql, params)], notes=notes, extra_table=top, extra_title="Top 10 customers by sales",
        next_questions=["Do customers come back after their first purchase?", "Compare sales by segment",
                        "Show monthly sales trend"],
    )


# ---------------------------------------------------------------- Q8 Cohort
def cohort(conn, p: dict) -> Result:
    where, params = where_clause({k: v for k, v in p["filters"].items() if k != "year"})
    sql = f"SELECT customer_id, order_date FROM superstore {where}"
    df = run(conn, sql, params)
    if df.empty:
        return Result("cohort", "No data for these filters.", sql=[show_sql(sql, params)])
    d = pd.to_datetime(df["order_date"])
    df["q"] = d.dt.year * 4 + (d.dt.month - 1) // 3
    first = df.groupby("customer_id")["q"].min().rename("cohort_q")
    df = df.join(first, on="customer_id")
    df["k"] = df["q"] - df["cohort_q"]
    active = df.groupby(["cohort_q", "k"])["customer_id"].nunique().reset_index(name="active")
    size = active[active["k"] == 0].set_index("cohort_q")["active"]
    active["retention"] = active.apply(lambda r: r["active"] / size[r["cohort_q"]], axis=1)
    active = active[(active["k"] <= 8)]
    # keep cohorts with at least 10 customers
    big = size[size >= 10].index
    active = active[active["cohort_q"].isin(big)]
    active["cohort"] = active["cohort_q"].apply(lambda q: f"{q // 4}-Q{q % 4 + 1}")
    active = active.rename(columns={"k": "quarters_after"})
    heat = active[["cohort", "quarters_after", "retention", "active"]]

    max_q = df["q"].max()
    def avg_at(k):
        rows = active[(active["quarters_after"] == k) & (active["cohort_q"] + k <= max_q)]
        return rows["retention"].mean() if len(rows) else float("nan")

    pivot = heat.pivot(index="cohort", columns="quarters_after", values="retention").round(3)
    pivot.columns = [f"Q+{c}" for c in pivot.columns]
    facts = [("Customers who bought again next quarter (avg)", fmt.pct(avg_at(1))),
             ("Active 4 quarters later (avg)", fmt.pct(avg_at(4))),
             ("Biggest cohort", f"{heat.loc[heat['active'].idxmax(), 'cohort']} · {fmt.count(size.max())} new customers"),
             ("Cohorts shown", fmt.count(len(pivot)))]
    return Result(
        "cohort", f"On average {fmt.pct(avg_at(1))} of new customers buy again the next quarter",
        facts=facts, table=pivot.reset_index(), chart=charts.heatmap(heat, title="Retention by first-purchase quarter"),
        sql=[show_sql(sql, params)],
        notes=["Each row is a group of customers who first bought in that quarter; each cell is the % of them who "
               "bought again N quarters later.", "Cohorts with fewer than 10 customers are hidden.",
               "Year filters are ignored here: a cohort needs the following quarters to measure returns."],
        next_questions=["Who are our best customers?", "Show monthly orders trend", "Compare customers by region"],
    )


# ---------------------------------------------------------------- Q10 Forecast
def forecast(conn, p: dict) -> Result:
    metric = p["metric"] if p["metric"] in ADDITIVE else "sales"
    label = METRIC_LABELS[metric]
    where, params = where_clause({k: v for k, v in p["filters"].items() if k != "year"})
    sql = f"""
SELECT substr(order_date, 1, 7) AS month,
       {METRICS[metric]} AS value
FROM superstore
{where}
GROUP BY month
ORDER BY month"""
    df = run(conn, sql, params)
    if len(df) < 27:
        return Result("forecast", "Need at least 27 months of history to forecast.", table=df, sql=[show_sql(sql, params)])
    s = df.set_index("month")["value"]

    def predict(history: pd.Series, steps: int):
        growth = history.iloc[-12:].sum() / history.iloc[-24:-12].sum() - 1
        last = pd.Period(history.index[-1], "M")
        out = []
        for i in range(1, steps + 1):
            m = last + i
            base = history.get(str(m - 12))
            if base is None:   # predicting beyond 12 months: use earlier forecast
                base = dict(out).get(str(m - 12), history.iloc[-12:].mean())
            out.append((str(m), base * (1 + growth)))
        return out, growth

    # backtest: hide the last 3 known months, predict them, measure error
    test_pred, _ = predict(s.iloc[:-3], 3)
    actual = s.iloc[-3:]
    errors = [abs(v - actual[m]) / abs(actual[m]) for m, v in test_pred if actual[m]]
    mape = float(np.mean(errors)) if errors else float("nan")

    pred, growth = predict(s, p["horizon"])
    hist = pd.DataFrame({"month": s.index, "value": s.values, "kind": "Actual"}).tail(24)
    fut = pd.DataFrame(pred, columns=["month", "value"])
    fut["kind"] = "Forecast"
    joined = pd.concat([hist.tail(1).assign(kind="Forecast"), fut])   # connect the dashed line
    chart_df = pd.concat([hist, joined])

    total = sum(v for _, v in pred)
    h = len(pred)
    facts = [("Method", "Same month last year × recent growth"),
             ("Growth used (last 12 months vs previous 12)", fmt.pct(growth, signed=True)),
             ("Each forecast month vs the same month last year", fmt.pct(growth, signed=True) + " (by this method)"),
             ("Backtest error on last 3 known months", fmt.pct(mape)),
             (f"Forecast total, next {h} months", fmt.value(metric, total))]
    for m, v in pred:
        facts.append((f"Forecast {m}", fmt.value(metric, v)))
    table = fut[["month", "value"]].rename(columns={"value": f"forecast_{metric}"}).round(2)
    headline = (f"{label} forecast, next {h} months: about {fmt.value(metric, total)} in total "
                f"({fmt.pct(growth, signed=True)} vs the same months last year)")
    extra_notes = []
    if not np.isnan(mape) and mape > 0.5:
        headline = f"Rough estimate only (backtest error {fmt.pct(mape)}): " + headline
        extra_notes.append(f"Monthly {label.lower()} swings too much to forecast single months reliably. "
                           f"Trust the {h}-month total more than any one month.")
    return Result(
        "forecast", headline,
        facts=facts, table=table, chart=charts.forecast_line(chart_df, metric, title=f"{label}: last 24 months + forecast"),
        sql=[show_sql(sql, params)],
        notes=extra_notes + ["A forecast is an estimate, not a promise. Expect the real number to differ by about the backtest error.",
               "Assumes next year repeats this year's seasonal pattern at the recent growth rate."],
        next_questions=[f"Show monthly {label.lower()} trend", "Which region grew fastest?", "Total sales and profit"],
    )


# ---------------------------------------------------------------- Q7 / Q9: data can't answer
def not_supported(q_type: str) -> Result:
    needs = {
        "funnel": ("step-by-step customer journey data (visit → view → cart → checkout → paid)",
                   "Superstore only has completed orders, so drop-off between steps can't be measured."),
        "experiment": ("a column saying which group (A or B) each customer was in, plus the outcome",
                       "Superstore has no test groups, so it can't prove whether a change caused a result."),
    }[q_type]
    return Result(q_type, f"This data can't answer {q_type} questions",
                  facts=[("Needs", needs[0])], notes=[needs[1], "Load a dataset with those columns to use this type."],
                  next_questions=["Does discount affect profit?", "Do customers come back after their first purchase?"])


RECIPES = {
    "descriptive": descriptive, "trend": trend, "comparison": comparison, "diagnostic": diagnostic,
    "correlation": correlation, "segmentation": segmentation, "cohort": cohort, "forecast": forecast,
}

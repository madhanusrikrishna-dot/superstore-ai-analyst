"""
test_recipes.py - checks every recipe against numbers we already verified by hand in SQL.
Runs without the AI (uses the keyword router).

Run:  python test_recipes.py
"""

import recipes
from data import load, normalize_filters
from router import keyword_route

conn, df = load()
passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def ask(question):
    p = keyword_route(question)
    p["filters"], _ = normalize_filters(p["filters"], df)
    if p["q_type"] in recipes.RECIPES:
        return p, recipes.RECIPES[p["q_type"]](conn, p)
    return p, recipes.not_supported(p["q_type"]) if p["q_type"] in ("funnel", "experiment") else None


print("Q1 Descriptive")
p, r = ask("Total sales and profit overall")
check("routed as descriptive", p["q_type"] == "descriptive", p["q_type"])
row = r.table.iloc[0]
check("total sales = 2,297,200.86", round(row["sales"], 2) == 2297200.86, row["sales"])
check("total profit = 286,397.02", round(row["profit"], 2) == 286397.02, row["profit"])
check("orders = 5,009", row["orders"] == 5009, row["orders"])
check("customers = 793", row["customers"] == 793, row["customers"])
check("margin = 12.47%", round(row["margin"] * 100, 2) == 12.47, row["margin"])

print("Q2 Trend")
p, r = ask("Show monthly sales in 2017")
check("routed as trend", p["q_type"] == "trend", p["q_type"])
check("12 months", len(r.table) == 12, len(r.table))
peak = r.table.loc[r.table["value"].idxmax()]
check("peak = 2017-11, 118,447.83", peak["period"] == "2017-11" and abs(peak["value"] - 118447.83) < 0.01, peak.to_dict())
dec = r.table[r.table["period"] == "2017-12"].iloc[0]
check("Nov→Dec drop is about -29.2% (computed in code)", round(dec["change_vs_previous"] * 100, 1) == -29.2,
      dec["change_vs_previous"])
p, r = ask("Show yearly sales trend")
check("yearly: 4 rows", p["period"] == "year" and len(r.table) == 4, (p["period"], len(r.table)))

print("Q3 Comparison")
p, r = ask("Which region has the lowest profit?")
check("routed as comparison, asc", p["q_type"] == "comparison" and p["order"] == "asc", p)
check("Central lowest = 39,706.36", r.table.iloc[0]["region"] == "Central" and round(r.table.iloc[0]["value"], 2) == 39706.36,
      r.table.iloc[0].to_dict())
p, r = ask("Top 10 sub-categories by profit")
check("top 10 rows", len(r.table) == 10, len(r.table))
check("Copiers first = 55,617.82", r.table.iloc[0]["sub_category"] == "Copiers" and round(r.table.iloc[0]["value"], 2) == 55617.82,
      r.table.iloc[0].to_dict())

p = {"q_type": "comparison", "metric": "profit", "dimension": "state", "order": "asc", "top_n": 1,
     "period": "month", "horizon": 3, "x_column": "discount", "y_column": "profit", "filters": {"year": "2017"}}
r = recipes.comparison(conn, p)
f = dict(r.facts)
check("2017 state with biggest loss = Texas -8,838.50",
      r.table.iloc[0]["state"] == "Texas" and round(r.table.iloc[0]["value"], 2) == -8838.50, r.table.iloc[0].to_dict())
check("top 1 still shows 5 rows for context", len(r.table) == 5, len(r.table))
check("losing states counted across all 47 (9), not just rows shown", f.get("Losing money", "").startswith("9 of 47"),
      f.get("Losing money"))
check("next question is about Texas", r.next_questions[0] == "Why is profit low in Texas?", r.next_questions)

d = recipes.diagnostic(conn, {**p, "q_type": "diagnostic", "filters": {"state": "Texas", "year": "2017"}})
check("diagnostic works inside one state (Texas → Office Supplies → Binders)",
      dict(d.facts).get("Drill-down path") == "Texas → Office Supplies → Binders", d.headline)
t = recipes.trend(conn, {**p, "q_type": "trend", "dimension": "none", "top_n": 0, "filters": {"state": "Texas"}})
check("trend of a loss uses $ differences, not crazy % (Texas)",
      "%" not in dict(t.facts)["Weakest month vs same month last year"], dict(t.facts))

import pipeline
check("suggested next questions keep the year (2017)",
      pipeline.keep_year(["Why is profit low in Texas?"], {"year": "2017"}) == ["Why is profit low in Texas in 2017?"])

print("Q4 Diagnostic")
p, r = ask("Why is profit low in the Central region?")
check("routed as diagnostic", p["q_type"] == "diagnostic", p["q_type"])
check("starts inside Central", p["filters"].get("region") == "Central", p["filters"])
check("drills category → sub-category", list(r.table["level"]) == ["category", "sub-category"], list(r.table["level"]))
print("        path:", dict(r.facts)["Drill-down path"])

print("Q5 Correlation")
p, r = ask("Does discount affect profit?")
check("routed as correlation", p["q_type"] == "correlation", p["q_type"])
r_val = float(dict(r.facts)["Correlation (r)"])
check("negative correlation", r_val < 0, r_val)
bands = r.table.set_index("discount_band")["value"]
check("over-40% band loses money", bands["4. Over 40%"] < 0, bands.to_dict())

print("Q6 Segmentation")
p, r = ask("Who are our best customers?")
check("routed as segmentation", p["q_type"] == "segmentation", p["q_type"])
check("segments cover all 793 customers", int(r.table["customers"].sum()) == 793, r.table["customers"].sum())
check("sales shares add to 100%", abs(r.table["share_of_sales"].sum() - 1) < 0.001, r.table["share_of_sales"].sum())

print("Q8 Cohort")
p, r = ask("Do customers come back after their first purchase?")
check("routed as cohort", p["q_type"] == "cohort", p["q_type"])
check("first column is 100%", (r.table["Q+0"] == 1).all(), r.table["Q+0"].tolist())

print("Q10 Forecast")
p, r = ask("Forecast sales for the next 3 months")
check("routed as forecast", p["q_type"] == "forecast", p["q_type"])
check("3 forecast months starting 2018-01", list(r.table["month"]) == ["2018-01", "2018-02", "2018-03"], list(r.table["month"]))
print("        ", [f for f in r.facts if f[0].startswith(("Growth", "Backtest", "Forecast 2018-01"))])

print("Q7 / Q9 not supported")
p, r = ask("Where do users drop off in the checkout funnel?")
check("funnel says it can't answer", p["q_type"] == "funnel" and "can't" in r.headline, (p["q_type"], r.headline))

print("Filters")
f, w = normalize_filters({"region": "central", "category": "furniture", "year": "2019"}, df)
check("case-insensitive match", f == {"region": "Central", "category": "Furniture"}, f)
check("bad year warned", any("2019" in x for x in w), w)

print("Values typed in the question")
from data import find_filter_values  # noqa: E402
check("'and for West?' → West", find_filter_values("and for West?", df) == {"region": "West"},
      find_filter_values("and for West?", df))
check("'West Virginia' is a state, not the West region",
      find_filter_values("sales in West Virginia", df) == {"state": "West Virginia"},
      find_filter_values("sales in West Virginia", df))
check("'Office Supplies' is a category, 'Supplies' alone a sub-category",
      find_filter_values("Office Supplies in 2016", df) == {"category": "Office Supplies", "year": "2016"},
      find_filter_values("Office Supplies in 2016", df))
check("no false matches in 'Show monthly sales'", find_filter_values("Show monthly sales", df) == {},
      find_filter_values("Show monthly sales", df))
p = keyword_route("Total sales and profit in 2017")
p["filters"].update(find_filter_values("and for West?", df))
p["filters"], _ = normalize_filters(p["filters"], df)
row = recipes.descriptive(conn, p).table.iloc[0]
west_2017 = df[(df.region == "West") & (df.order_date.str[:4] == "2017")]["sales"].sum()
check("follow-up West 2017 sales match pandas", abs(row["sales"] - west_2017) < 0.01, (row["sales"], west_2017))
check("headline names the scope", "West, 2017" in recipes.descriptive(conn, p).headline,
      recipes.descriptive(conn, p).headline)

print(f"\n{passed} passed, {failed} failed")

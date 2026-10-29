"""
test_rules.py - checks the WORDING RULES on hundreds of answers, not just the questions we tried by hand.

Numbers are checked in test_recipes.py. This file checks that answers are explained honestly:
  Rule 1  every "share of / % of" label says share of WHAT
  Rule 2  people never see raw column names (customer_name, sub_category...)
  Rule 3  the headline leads with the finding that matters most (biggest $, vs last year, ever came back)
  Rule 4  no comparison that makes no sense (discount % vs margin %)
  Rule 5  clean notes: no duplicates, no warning for "2014-2017"
  Rule 6  suggested next questions stay on the same scope (Texas, 2017...)
  Rule 7  "can't answer" types say what the data CAN show

Run:  python test_rules.py   (no AI needed)
"""

import itertools
import re

import pipeline
import recipes
from data import load, normalize_filters
from router import _default_params

conn, df = load()
passed = failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append(f"  FAIL  {name}  {detail}")


RAW = re.compile(r"customer_name|product_name|sub_category|ship_mode|order_date|[a-z]+-name\b")

FILTERS = [{}, {"year": "2016"}, {"region": "West"}, {"sub_category": "Chairs"}, {"state": "Texas", "year": "2017"},
           {"segment": "Consumer"}, {"category": "Furniture", "year": "2015"}]
SCENARIOS = []
for f in FILTERS:
    SCENARIOS.append(dict(q_type="descriptive", filters=f))
    for metric, period in itertools.product(["sales", "profit", "margin", "orders"], ["month", "quarter", "year"]):
        SCENARIOS.append(dict(q_type="trend", metric=metric, period=period, filters=f))
    for metric, dim, order, top in itertools.product(["sales", "profit", "margin"],
                                                     ["region", "state", "sub_category", "customer_name",
                                                      "product_name", "ship_mode"], ["asc", "desc"], [0, 1, 5]):
        SCENARIOS.append(dict(q_type="comparison", metric=metric, dimension=dim, order=order, top_n=top, filters=f))
    SCENARIOS.append(dict(q_type="diagnostic", metric="profit", filters=f))
    for x, y in [("discount", "profit"), ("discount", "quantity"), ("quantity", "sales")]:
        SCENARIOS.append(dict(q_type="correlation", x_column=x, y_column=y, filters=f))
    SCENARIOS.append(dict(q_type="segmentation", filters=f))
    SCENARIOS.append(dict(q_type="cohort", filters=f))
    SCENARIOS.append(dict(q_type="forecast", metric="sales", horizon=3, filters=f))
SCENARIOS += [dict(q_type="funnel", filters={}), dict(q_type="experiment", filters={})]

print(f"Checking the wording rules on {len(SCENARIOS)} answers...")
for s in SCENARIOS:
    p = {**_default_params(), **s, "filters": dict(s["filters"])}
    r = pipeline.compute(conn, p, "test")
    r.next_questions = pipeline.keep_scope(r.next_questions, p["filters"])
    tag = f"[{p['q_type']} {p.get('metric', '')} {p.get('dimension', '')} {p['filters']}]"
    shown = " | ".join([r.headline] + [f"{k} {v}" for k, v in r.facts] + r.notes + r.next_questions)

    check("no calculation errors", not r.headline.startswith("Something went wrong"), tag + " " + " ".join(r.notes))
    check("Rule 2: no raw column names on screen", not RAW.search(shown), tag + " " + str(RAW.findall(shown)))
    for label, _ in r.facts:
        if re.search(r"share of|% of", label):
            names = [str(v) for v in p["filters"].values()] + ["all ", "company "]
            check("Rule 1: share label says share of what", any(n in label for n in names), f"{tag} '{label}'")
    check("Rule 4: never compares discount % with margin %",
          "higher than the profit margin" not in shown, tag)
    check("Rule 5: no duplicate notes", len(r.notes) == len(set(r.notes)), tag)
    for q in r.next_questions:
        for k, v in p["filters"].items():
            if k == "year":
                ok = re.search(r"\b20\d\d\b", q) or "forecast" in q.lower()
            else:
                ok = str(v).lower() in q.lower() or "by " in q.lower()
            check("Rule 6: next question keeps the scope", ok, f"{tag} '{q}' misses {v}")

# ---- Rule 3: the headline leads with what matters (cases checked by hand against the raw data)
base = _default_params()
seg = recipes.segmentation(conn, {**base, "q_type": "segmentation", "filters": {}})
check("Rule 3: segmentation leads with the biggest group (At risk, 26.4%)",
      seg.headline.startswith("At risk") and "26.4%" in seg.headline, seg.headline)
coh = recipes.cohort(conn, {**base, "q_type": "cohort", "filters": {}})
check("Rule 3: cohort says how many ever came back (98.1%)", "98.1%" in coh.headline, coh.headline)
cor = recipes.correlation(conn, {**base, "q_type": "correlation", "filters": {"region": "West"}})
check("Rule 3: West discount answer leads with the money lost ($16.0K, 118 lines)",
      "$16.0K" in cor.headline and "118" in cor.headline, cor.headline)
check("Rule 5: a discount band with no orders is explained",
      any("No order lines with 21-40%" in n for n in cor.notes), cor.notes)
d16 = recipes.descriptive(conn, {**base, "q_type": "descriptive", "filters": {"year": "2016"}})
check("Rule 3: one year is compared with the year before (+29.5% vs 2015)",
      "+29.5% vs 2015" in d16.headline, d16.headline)
east = recipes.descriptive(conn, {**base, "q_type": "descriptive", "filters": {"year": "2016", "region": "East"}})
check("Rule 4: East's lower discount is shown next to the company's (14.3% vs 15.5%)",
      any("14.3%" in n and "15.5%" in n and "not the reason" in n for n in east.notes), east.notes)
top = recipes.comparison(conn, {**base, "q_type": "comparison", "metric": "profit", "dimension": "product_name",
                                "order": "desc", "top_n": 5, "filters": {"year": "2017"}})
check("Rule 3: a top result from only a few orders is flagged (3 orders)", "just 3 orders" in top.headline, top.headline)
check("Rule 5: long lists of 1,511 product names are not printed",
      dict(top.facts)["Losing money"].startswith("271 of 1511 products ("), dict(top.facts)["Losing money"])
chairs = recipes.comparison(conn, {**base, "q_type": "comparison", "metric": "sales", "dimension": "customer_name",
                                   "order": "desc", "top_n": 1, "filters": {"sub_category": "Chairs"}})
check("Rule 1: Seth Vernon's share is of Chairs sales",
      any(k.startswith("Seth Vernon share of Chairs sales") for k, _ in chairs.facts), chairs.facts)
exp = recipes.not_supported("experiment")
check("Rule 7: experiment answer offers a before/after view", any("before vs after" in n for n in exp.notes), exp.notes)

# ---- Rule 5: "2014-2017" means all years, with no warning
for value in ["2014-2017", "2014–2017", "all years"]:
    clean, warn = normalize_filters({"year": value}, df)
    check(f"Rule 5: year '{value}' = no filter, no warning", clean == {} and warn == [], (clean, warn))

# ---- Rule 6: a vague follow-up gets suggestions about the answer just above
opts = pipeline.context_options({"filters": {"region": "West"}}, [])
check("Rule 6: 'is that good?' after a West answer suggests a West check", "West" in opts[0], opts)

# ---- Safety: a question is only treated as a follow-up if it looks like one
prev, _, _ = pipeline.understand("Total sales in 2016", df)
east_p, _, _ = pipeline.understand("and for the East region?", df, prev)
check("follow-up 'and for the East region?' keeps 2016 and adds East",
      east_p["q_type"] == "descriptive" and east_p["filters"] == {"year": "2016", "region": "East"}, east_p)
vague, _, _ = pipeline.understand("Is that good?", df, east_p)
check("'Is that good?' asks back instead of repeating the last answer", vague["clear"] is False, vague)
web, _, _ = pipeline.understand("Did our new website increase sales?", df, east_p)
check("an A/B question after another answer is not treated as a follow-up", web["q_type"] == "experiment", web)

# ---- "AI writes, code checks": real explanations the AI wrote during user testing (29 Oct 2026)
import verify  # noqa: E402

east16 = recipes.descriptive(conn, {**base, "q_type": "descriptive", "filters": {"year": "2016", "region": "East"}})
bad_east = ("**Why it matters:** The East region's profit margin of 11.1% is below the company-wide average of 13.4%. "
            "This could be due to higher discounts given on orders.\n\n**Suggested action:** Review discounts.")
check("check catches 'due to higher discounts' when East's discount is lower",
      any("LOWER" in x for x in verify.problems(bad_east, "and for the East region?", east16.headline,
                                                  east16.facts, east16.notes)))
coh = recipes.cohort(conn, {**base, "q_type": "cohort", "filters": {}})
bad_cohort = ("**Why it matters:** A retention rate this low suggests that a significant portion of new customers "
              "are not returning.\n\n**Suggested action:** Start a loyalty programme.")
check("check catches 'low' with nothing to compare", verify.problems(
    bad_cohort, "Do customers come back?", coh.headline, coh.facts, coh.notes) != [])
bad_number = "**Why it matters:** Sales were $812.4K, 41.3% of the total.\n\n**Suggested action:** Grow."
check("check catches invented numbers", any("numbers" in x for x in verify.problems(
    bad_number, "Total sales in 2016", d16.headline, d16.facts, d16.notes)))
seg_r = recipes.segmentation(conn, {**base, "q_type": "segmentation", "filters": {}})
bad_major = "**Why it matters:** At-risk customers are the majority of our sales.\n\n**Suggested action:** Call them."
check("check catches 'majority' when no share is above 50%", any("majority" in x for x in verify.problems(
    bad_major, "Who are our best customers?", seg_r.headline, seg_r.facts, seg_r.notes)))
good = ("**Why it matters:** At risk customers hold 26.4% of sales ($605.7K) but have not bought recently, so a "
        "big part of past revenue could be lost.\n\n**Suggested action:** Send the 159 at-risk customers a "
        "win-back offer first.")
check("a correct explanation passes the check", verify.problems(
    good, "Who are our best customers?", seg_r.headline, seg_r.facts, seg_r.notes) == [],
      verify.problems(good, "Who are our best customers?", seg_r.headline, seg_r.facts, seg_r.notes))

# the full loop: AI wrong twice -> code-written explanation, which itself passes every check
import narrator  # noqa: E402

real_explain = narrator.explain
narrator.explain = lambda *a, **k: bad_east
text = pipeline.narrate("and for the East region?", east16, {"filters": {"year": "2016", "region": "East"}})
narrator.explain = real_explain
check("after two failed tries the app shows the code-written explanation", verify.FALLBACK_MARK in text, text)
check("the code-written explanation passes its own checks", verify.problems(
    text, "and for the East region?", east16.headline, east16.facts, east16.notes) == [], text)
calls = []
narrator.explain = lambda *a, **k: (calls.append(k.get("fix")), bad_east if len(calls) == 1 else good)[1]
text = pipeline.narrate("Who are our best customers?", seg_r, {"filters": {}})
narrator.explain = real_explain
check("the retry tells the AI what was wrong", len(calls) == 2 and bool(calls[1]), calls)
check("a corrected retry is shown (no code fallback needed)", verify.FALLBACK_MARK not in text and "26.4%" in text, text)

print("\n".join(failures[:40]))
if len(failures) > 40:
    print(f"  ... and {len(failures) - 40} more")
print(f"\n{passed} passed, {failed} failed")

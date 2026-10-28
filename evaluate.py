"""
evaluate.py - tests the WHOLE app with your real local AI model.

For each test question it checks:
  1. Understanding : did the AI pick the right question type, measure, comparison column and filters?
  2. Calculation   : did the answer compute without errors?
  3. Honesty       : does the AI's explanation use only numbers the code calculated (no invented numbers)?

Run (Ollama must be running):
    python evaluate.py            full test (about 5 minutes)
    python evaluate.py --quick    skip the explanation check (faster)

Writes eval_report.md with every result.
"""

import re
import sys
import time
from collections import defaultdict

import pipeline
from data import load
from narrator import business_notes

# (question, expected form, previous question for follow-ups)
CASES = [
    # Q1 Descriptive
    ("What were total sales and profit in 2016?", {"q_type": "descriptive", "filters": {"year": "2016"}}, None),
    ("How many customers do we have?", {"q_type": "descriptive", "metric": "customers", "filters": {}}, None),
    ("Give me a summary of the Technology category", {"q_type": "descriptive", "filters": {"category": "Technology"}}, None),
    ("What is the overall profit margin for the Corporate segment?",
     {"q_type": "descriptive", "metric": "margin", "filters": {"segment": "Corporate"}}, None),
    # Q2 Trend
    ("How did profit change month by month in 2015?",
     {"q_type": "trend", "metric": "profit", "period": "month", "filters": {"year": "2015"}}, None),
    ("Are sales growing year over year?", {"q_type": "trend", "metric": "sales", "period": "year", "filters": {}}, None),
    ("Quarterly sales trend for the West region", {"q_type": "trend", "period": "quarter", "filters": {"region": "West"}}, None),
    ("Show the monthly number of orders", {"q_type": "trend", "metric": "orders", "period": "month", "filters": {}}, None),
    # Q3 Comparison
    ("Which category makes the most profit?",
     {"q_type": "comparison", "metric": "profit", "dimension": "category", "order": "desc", "filters": {}}, None),
    ("Bottom 5 states by profit",
     {"q_type": "comparison", "metric": "profit", "dimension": "state", "order": "asc", "top_n": 5, "filters": {}}, None),
    ("Compare sales across customer segments", {"q_type": "comparison", "metric": "sales", "dimension": "segment", "filters": {}}, None),
    ("Which ship mode brings the highest sales?",
     {"q_type": "comparison", "dimension": "ship_mode", "order": "desc", "filters": {}}, None),
    ("which state lost the most money in 2017?",
     {"q_type": "comparison", "metric": "profit", "dimension": "state", "order": "asc", "filters": {"year": "2017"}}, None),
    ("Top 3 sub-categories by sales in the East region",
     {"q_type": "comparison", "dimension": "sub_category", "top_n": 3, "filters": {"region": "East"}}, None),
    # Q4 Diagnostic
    ("Why is the South region's profit so low?", {"q_type": "diagnostic", "metric": "profit", "filters": {"region": "South"}}, None),
    ("What's causing losses in Furniture?", {"q_type": "diagnostic", "filters": {"category": "Furniture"}}, None),
    ("Explain why profit is weak in 2015", {"q_type": "diagnostic", "filters": {"year": "2015"}}, None),
    ("Why are Tables losing money?", {"q_type": "diagnostic", "filters": {"sub_category": "Tables"}}, None),
    # Q5 Correlation
    ("Is there a relationship between discount and profit?",
     {"q_type": "correlation", "x_column": "discount", "y_column": "profit", "filters": {}}, None),
    ("Does a bigger discount lead to more quantity sold?",
     {"q_type": "correlation", "x_column": "discount", "y_column": "quantity", "filters": {}}, None),
    ("How does discount impact profit in the Central region?",
     {"q_type": "correlation", "filters": {"region": "Central"}}, None),
    # Q6 Segmentation
    ("Segment our customers by how recently and often they buy", {"q_type": "segmentation"}, None),
    ("Which customers are at risk of leaving us?", {"q_type": "segmentation"}, None),
    ("Who are our most loyal customers?", {"q_type": "segmentation"}, None),
    # Q8 Cohort
    ("What is our customer retention rate?", {"q_type": "cohort"}, None),
    ("Do first-time buyers come back to buy again?", {"q_type": "cohort"}, None),
    # Q10 Forecast
    ("Predict sales for the next 6 months", {"q_type": "forecast", "metric": "sales", "horizon": 6}, None),
    ("What profit should we expect over the next 3 months?", {"q_type": "forecast", "metric": "profit", "horizon": 3}, None),
    # Q7 / Q9 (data can't answer)
    ("Where do customers drop off in the checkout funnel?", {"q_type": "funnel"}, None),
    ("Did the new website design increase conversions in the A/B test?", {"q_type": "experiment"}, None),
    # vague -> should ask back
    ("Is that good?", {"clear": False}, None),
    # follow-ups
    ("and for the East region?", {"q_type": "descriptive", "filters": {"year": "2017", "region": "East"}},
     "Total sales in 2017"),
    ("what about in 2016?", {"q_type": "comparison", "order": "asc", "filters": {"year": "2016"}},
     "Which region has the lowest profit?"),
]

NUMBER = re.compile(r"[-−]?\$?\d[\d,]*(?:\.\d+)?\s?(?:%|K|M|pts)?", re.IGNORECASE)


def numbers_in(text: str) -> set:
    out = set()
    for m in NUMBER.findall(text or ""):
        t = m.replace("$", "").replace(",", "").replace(" ", "").replace("−", "-").lstrip("-").lower()
        if t:
            out.add(t)
    return out


def invented_numbers(narration: str, allowed_text: str) -> list:
    """Numbers in the explanation that the code never produced."""
    allowed = numbers_in(allowed_text)
    bad = []
    for t in numbers_in(narration):
        plain = re.sub(r"[a-z%]", "", t)
        try:
            v = float(plain)
        except ValueError:
            continue
        if t in allowed or plain in {re.sub(r"[a-z%]", "", a) for a in allowed}:
            continue
        if v.is_integer() and (v <= 12 or 2014 <= v <= 2018):   # counts like "3 months", years
            continue
        bad.append(t)
    return bad


def main():
    quick = "--quick" in sys.argv
    conn, df = load()
    rows, by_type, total_time = [], defaultdict(lambda: [0, 0]), 0.0
    fallback_used = False
    print(f"Testing {len(CASES)} questions with model {pipeline.MODEL}{' (quick)' if quick else ''}\n")

    for i, (question, expect, previous_q) in enumerate(CASES, 1):
        start = time.time()
        previous = None
        if previous_q:
            previous, _, _ = pipeline.understand(previous_q, df)
        params, source, _ = pipeline.understand(question, df, previous)
        if not source.startswith("AI"):
            fallback_used = True

        problems = []
        for field, want in expect.items():
            got = params.get(field)
            if field == "filters":
                if got != want:
                    problems.append(f"filters: wanted {want}, got {got}")
            elif got != want:
                problems.append(f"{field}: wanted {want}, got {got}")

        invented, headline = [], ""
        if params.get("clear", True) and expect.get("clear", True):
            result = pipeline.compute(conn, params, question)
            headline = result.headline
            if headline.startswith("Something went wrong"):
                problems.append("calculation error: " + "; ".join(result.notes))
            elif not quick and result.facts:
                narration = pipeline.narrate(question, result, params)
                if narration.startswith("_AI explanation unavailable"):
                    problems.append("AI explanation unavailable")
                else:
                    allowed = " ".join([question, headline, business_notes(), " ".join(result.notes),
                                        " ".join(f"{k} {v}" for k, v in result.facts)])
                    invented = invented_numbers(narration, allowed)
                    if invented:
                        problems.append("explanation used numbers not from the code: " + ", ".join(invented))

        secs = time.time() - start
        total_time += secs
        ok = not problems
        label = expect.get("q_type", "vague")
        by_type[label][0] += ok
        by_type[label][1] += 1
        rows.append((i, question, ok, problems, params, headline, source, secs))
        print(f"{'PASS' if ok else 'FAIL'}  {i:2}. {question}  ({secs:.1f}s)")
        for p in problems:
            print(f"        - {p}")

    passed = sum(r[2] for r in rows)
    print(f"\n{passed}/{len(rows)} passed ({passed / len(rows):.0%}) in {total_time / 60:.1f} min")
    for t, (ok, n) in by_type.items():
        print(f"  {t:13} {ok}/{n}")
    if fallback_used:
        print("\nWARNING: the AI router was not used for some questions (is Ollama running?). "
              "Those results tested the keyword backup, not the AI.")

    with open("eval_report.md", "w", encoding="utf-8") as f:
        f.write(f"# Evaluation report\n\nModel: {pipeline.MODEL}  \nResult: **{passed}/{len(rows)} passed "
                f"({passed / len(rows):.0%})**  \nTime: {total_time / 60:.1f} min\n\n")
        f.write("| Type | Passed |\n|---|---|\n" + "".join(f"| {t} | {ok}/{n} |\n" for t, (ok, n) in by_type.items()))
        f.write("\n## Failures\n\n")
        for i, q, ok, probs, params, headline, source, secs in rows:
            if not ok:
                f.write(f"**{i}. {q}**  \n" + "".join(f"- {p}\n" for p in probs) +
                        f"- routed by: {source}\n- form: `{params}`\n\n")
        f.write("\n## All results\n\n| # | Question | Result | Headline |\n|---|---|---|---|\n")
        for i, q, ok, probs, params, headline, source, secs in rows:
            f.write(f"| {i} | {q} | {'PASS' if ok else 'FAIL'} | {headline.replace('|', '/')} |\n")
    print("\nFull report written to eval_report.md")


if __name__ == "__main__":
    main()

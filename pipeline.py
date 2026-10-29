"""
pipeline.py - the full path from a question to an answer, in one place.
The web app (app.py) and the test runner (evaluate.py) both use this,
so what we test is exactly what users get.

    understand()  question -> form (AI router + code safety nets)
    compute()     form -> numbers, chart, SQL (code only)
    narrate()     numbers -> plain-English explanation (AI)
"""

import os
import re

import pandas as pd

import narrator
import verify
import recipes
from data import find_filter_values, normalize_filters, run
from router import ai_route

MODEL = os.environ.get("ANALYST_MODEL", "qwen2.5-coder:14b")


def understand(question: str, df: pd.DataFrame, previous: dict | None = None, model: str = MODEL):
    """Returns (params, source, warnings)."""
    params, source = ai_route(question, model, previous)
    # short follow-up the router couldn't place ("and for West?"): reuse the previous question's settings
    # (not when the AI says the question is too vague: then we ask back instead)
    looks_like_follow_up = bool(re.match(r"\s*(and|what about|how about|same for|for|in|now|also|then)\b",
                                         question.lower())) or bool(find_filter_values(question, df))
    if params["q_type"] == "other" and params.get("clear", True) and previous and len(question.split()) <= 6 \
            and looks_like_follow_up:
        params = {**previous, "filters": dict(previous["filters"]), "clear": True, "clarify_options": []}
        source += " + follow-up"
    # "How is X doing / performing?" is a health check (Q1), not a ranking
    q = question.lower()
    asks_rank = re.search(r"\b(which|top|best|worst|most|least|highest|lowest|bottom|rank|compare|vs|by)\b|\d", q)
    asks_time = re.search(r"\b(month|monthly|quarter|quarterly|yearly|trend|over time|grow|growing|growth)\b", q)
    if re.search(r"\bhow (is|are|was|were)\b.*\b(doing|performing|perform|going)\b", q) and not asks_rank \
            and not asks_time and params["q_type"] in ("comparison", "trend", "other"):
        params.update(q_type="descriptive", dimension="none", top_n=0)
        source += " + health-check rule"
    # a "top N" the question never asked for is dropped
    if params["q_type"] == "comparison" and params["top_n"] and not asks_rank:
        params["top_n"] = 0
    # values written in the question always win over what the AI filled in
    params["filters"].update(find_filter_values(question, df))
    params["filters"], warnings = normalize_filters(params["filters"], df)
    # a column we filter on can't also be the comparison column
    if params["dimension"] in params["filters"]:
        params["dimension"] = "none"
    return params, source, warnings


def compute(conn, params: dict, question: str, model: str = MODEL) -> recipes.Result:
    q_type = params["q_type"]
    try:
        if q_type in recipes.RECIPES:
            return recipes.RECIPES[q_type](conn, params)
        if q_type in ("funnel", "experiment"):
            return recipes.not_supported(q_type)
        return custom_sql(conn, question, model)
    except Exception as e:  # never crash the page
        return recipes.Result(q_type, "Something went wrong while calculating this answer.",
                              notes=[f"Error: {e}", "Try rephrasing the question."])


def narrate(question: str, result: recipes.Result, params: dict, model: str = MODEL) -> str:
    """AI writes, code checks: an explanation is shown only if it passes verify.problems().
    One retry with the problems listed; after that, a plain explanation written by code."""
    if not result.facts:
        return ""
    scope = recipes.scope_text(params["filters"])
    fix = ""
    for _ in range(2):
        try:
            text = narrator.explain(question, result.headline, result.facts, result.notes, model, scope=scope, fix=fix)
        except Exception:
            return "_AI explanation unavailable (is Ollama running?). The numbers above come from code and are still valid._"
        found = verify.problems(text, question, result.headline, result.facts, result.notes)
        if not found:
            return text
        fix = "; ".join(found)
    return verify.fallback(result.headline, result.notes, result.next_questions)


def answer(conn, df, question: str, previous: dict | None = None, params: dict | None = None,
           model: str = MODEL) -> dict:
    """Full answer. Pass `params` to skip the AI router (used when the user edits the understanding)."""
    if params is None:
        params, source, warnings = understand(question, df, previous, model)
    else:
        params["filters"], warnings = normalize_filters(params["filters"], df)
        source = "edited by you"
    if not params.get("clear", True):
        options = params.get("clarify_options") or []
        if previous:   # "is that good?" usually means the answer just above: suggest checks on THAT scope
            options = context_options(previous, options)
        return {"question": question, "params": params, "source": source, "result": None, "narration": "",
                "clarify": options}
    result = compute(conn, params, question, model)
    result.notes = warnings + result.notes
    result.next_questions = keep_scope(result.next_questions, params["filters"])
    return {"question": question, "params": params, "source": source, "result": result,
            "narration": narrate(question, result, params, model), "clarify": []}


def keep_scope(questions: list, filters: dict) -> list:
    """Rule 7: suggested next questions stay on what the user is looking at
    ("Why is profit low in Texas in 2017?", "Which sub-categories get the highest discount in West?")."""
    out = []
    for q in questions:
        text = q.rstrip("?")
        for key, value in filters.items():
            if key == "year":
                continue
            v = str(value)
            if v.lower() in text.lower() or f"by {recipes.dim_name(key)}" in text.lower():
                continue          # already there, or the question compares across that column
            text += f" in {v}"
        year = filters.get("year")
        if year and not re.search(r"\b20\d\d\b", text) and "forecast" not in text.lower():
            text += f" in {year}"
        out.append(text + ("?" if q.endswith("?") else ""))
    return out


keep_year = keep_scope   # old name, kept for the tests


def context_options(previous: dict, ai_options: list) -> list:
    """Clear questions about the previous answer's scope, for a vague follow-up like 'is that good?'."""
    f = previous.get("filters", {})
    focus, year = recipes.focus_of(f), f.get("year")
    yr = f" in {year}" if year else ""
    first = (f"How is {focus} doing{yr} compared with the company?" if focus
             else f"How do total sales and profit{yr} compare with the year before?" if year
             else "How did sales and profit change year by year?")
    options = [first, f"Which region has the lowest profit{yr}?"]
    options += [o for o in ai_options if o not in options][:1]
    return options[:3]


def custom_sql(conn, question: str, model: str = MODEL) -> recipes.Result:
    sql = narrator.free_sql(question, model)
    if not narrator.is_read_only(sql):
        return recipes.Result("other", "The AI wrote a query that is not read-only, so it was blocked.", sql=[sql])
    table = run(conn, sql, []).round(2)
    chart = None
    if table.shape[1] >= 2 and len(table) >= 2 and pd.api.types.is_numeric_dtype(table.iloc[:, 1]):
        chart = recipes.charts.bar(table, table.columns[0], table.columns[1], "sales")
    facts = [(c, str(v)) for c, v in table.iloc[0].items()] if len(table) == 1 else []
    return recipes.Result("other", "Custom answer (AI-written SQL)", facts=facts, table=table, chart=chart, sql=[sql],
                          notes=["This question did not match a standard type, so the AI wrote the SQL itself. "
                                 "Check the SQL carefully before trusting the numbers."])

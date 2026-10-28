"""
pipeline.py - the full path from a question to an answer, in one place.
The web app (app.py) and the test runner (evaluate.py) both use this,
so what we test is exactly what users get.

    understand()  question -> form (AI router + code safety nets)
    compute()     form -> numbers, chart, SQL (code only)
    narrate()     numbers -> plain-English explanation (AI)
"""

import os

import pandas as pd

import narrator
import recipes
from data import find_filter_values, normalize_filters, run
from router import ai_route

MODEL = os.environ.get("ANALYST_MODEL", "qwen2.5-coder:14b")


def understand(question: str, df: pd.DataFrame, previous: dict | None = None, model: str = MODEL):
    """Returns (params, source, warnings)."""
    params, source = ai_route(question, model, previous)
    # short follow-up the router couldn't place ("and for West?"): reuse the previous question's settings
    # (not when the AI says the question is too vague: then we ask back instead)
    if params["q_type"] == "other" and params.get("clear", True) and previous and len(question.split()) <= 6:
        params = {**previous, "filters": dict(previous["filters"]), "clear": True, "clarify_options": []}
        source += " + follow-up"
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
    if not result.facts:
        return ""
    try:
        return narrator.explain(question, result.headline, result.facts, result.notes, model,
                                scope=recipes.scope_text(params["filters"]))
    except Exception:
        return "_AI explanation unavailable (is Ollama running?). The numbers above come from code and are still valid._"


def answer(conn, df, question: str, previous: dict | None = None, params: dict | None = None,
           model: str = MODEL) -> dict:
    """Full answer. Pass `params` to skip the AI router (used when the user edits the understanding)."""
    if params is None:
        params, source, warnings = understand(question, df, previous, model)
    else:
        params["filters"], warnings = normalize_filters(params["filters"], df)
        source = "edited by you"
    if not params.get("clear", True):
        return {"question": question, "params": params, "source": source, "result": None, "narration": "",
                "clarify": params.get("clarify_options") or []}
    result = compute(conn, params, question, model)
    result.notes = warnings + result.notes
    return {"question": question, "params": params, "source": source, "result": result,
            "narration": narrate(question, result, params, model), "clarify": []}


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

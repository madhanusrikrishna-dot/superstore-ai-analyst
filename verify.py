"""
verify.py - "AI writes, code checks".

The AI's explanation is only shown if it passes these checks. Otherwise the AI gets one retry with the
problems listed, and if that also fails, the app shows a plain explanation written by code instead.
So a wrong sentence never reaches the screen: the worst case is a plainer explanation.

Checks:
  1. Numbers   every number in the explanation exists in the key numbers / headline / notes / question
  2. Judging   words like "healthy", "low", "strong" only when the answer shows something to compare with
  3. Reasons   "due to higher discounts" must match the direction shown in the data
  4. Size      "majority / most of" only above 50%, "slight / small" only for small changes
"""

import re

NUMBER = re.compile(r"[-−]?\$?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|K|M|pts)(?![a-z]))?", re.IGNORECASE)
FALLBACK_MARK = "_Explanation written by code"


def numbers_in(text: str) -> set:
    out = set()
    for m in NUMBER.findall(text or ""):
        t = m.replace("$", "").replace(",", "").replace(" ", "").replace("−", "-").lstrip("-").lower()
        if t:
            out.add(t)
    return out


def _value(token: str) -> tuple[float, bool] | None:
    """'16.0k' -> (16000.0, False), '26.4%' -> (26.4, True)."""
    is_pct = token.endswith("%")
    t = token.rstrip("%")
    scale = 1.0
    if t.endswith("pts"):
        t, is_pct = t[:-3], True
    elif t.endswith("k"):
        t, scale = t[:-1], 1e3
    elif t.endswith("m"):
        t, scale = t[:-1], 1e6
    try:
        return float(t) * scale, is_pct
    except ValueError:
        return None


def invented_numbers(narration: str, allowed_text: str) -> list:
    """Numbers in the explanation that the code never produced.
    The same number written differently ('$16K' for '$16.0K', '26%' for '26.4%') is fine."""
    allowed = [x for x in (_value(a) for a in numbers_in(allowed_text)) if x]
    bad = []
    for t in numbers_in(narration):
        got = _value(t)
        if got is None:
            continue
        v, is_pct = got
        if v.is_integer() and not is_pct and (v <= 12 or 2014 <= v <= 2018):   # counts like "3 months", years
            continue
        # allow rounding at the precision the AI wrote: '$1.2M' may stand for $1.16M, '26%' for 26.4%
        digits = re.sub(r"[^0-9.]", "", t)
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = 1e6 if t.endswith("m") else 1e3 if t.endswith("k") else 1.0
        rounding = 0.5 * 10 ** -decimals * scale
        close = any(p == is_pct and abs(v - a) <= max(rounding * 1.01, 0.6 if is_pct else abs(a) * 0.02)
                    for a, p in allowed)
        if not close:
            bad.append(t)
    return bad


JUDGING = re.compile(r"\b(healthy|unhealthy|strong(ly)?|weak|poor(ly)?|excellent|impressive|"
                     r"low|high|good|bad|concerning|worrying|underperform\w*|outperform\w*)\b", re.IGNORECASE)
# something the reader can compare with: last year, the company, another group, a correlation
COMPARISON = re.compile(r"\bvs\b|compan|previous|last year|next (highest|lowest)|average of the others|"
                        r"\babove\b|\bbelow\b|\b(higher|lower|more|less|bigger|smaller) than\b|correlation|\brose\b|\bfell\b|\bgrew\b|\bimproved\b",
                        re.IGNORECASE)


def problems(narration: str, question: str, headline: str, facts: list, notes: list) -> list:
    """Everything wrong with an AI explanation. Empty list = safe to show."""
    allowed = " ".join([question, headline] + [f"{k} {v}" for k, v in facts] + list(notes))
    found = []

    bad = invented_numbers(narration, allowed)
    if bad:
        found.append("it uses numbers that are not in the key numbers: " + ", ".join(sorted(bad)))

    # judging words are fine if the code already used them, or if the answer shows a comparison
    text = re.sub(r"\bhigh-(value|volume|ticket)\b", "", narration, flags=re.IGNORECASE)   # names, not judgements
    judged = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        # very large or very small shares speak for themselves: "98.1% came back, a high level" is fair,
        # "30% is low" is not (low compared to what?)
        shares = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)%", sentence)]
        if any(s >= 90 or s <= 10 for s in shares):
            continue
        judged |= {m.group(0).lower() for m in JUDGING.finditer(sentence)}
    judged = {w for w in judged if not re.search(rf"\b{re.escape(w)}", allowed, re.IGNORECASE)}
    if judged and not COMPARISON.search(allowed):
        found.append("it judges a number (" + ", ".join(sorted(judged)) + ") with nothing shown to compare it with")

    # a reason must point the same way as the data
    if re.search(r"\b(higher|high|excessive|deep|heavy|large|more) discounts?\b", narration, re.IGNORECASE) \
            and re.search(r"lower than the company", allowed, re.IGNORECASE):
        found.append("it blames higher discounts, but the discount here is LOWER than the company's")
    if re.search(r"\b(lower|low|fewer|smaller) discounts?\b", narration, re.IGNORECASE) \
            and re.search(r"higher than the company", allowed, re.IGNORECASE):
        found.append("it mentions lower discounts, but the discount here is HIGHER than the company's")

    # size words must fit the size of the numbers
    pcts = [float(p) for p in re.findall(r"(\d+(?:\.\d+)?)%", allowed)]
    if re.search(r"\b(majority|most of)\b", narration, re.IGNORECASE) and not any(p > 50 for p in pcts):
        found.append("it says 'majority/most', but no share shown is above 50%")
    return found


def fallback(headline: str, notes: list, next_questions: list) -> str:
    """A plain explanation built only from what the code calculated."""
    why = headline.rstrip(".") + "."
    useful = [n for n in notes if not n.startswith(("Scores:", "Recency", "Each row", "Cohorts with", "Showing",
                                                    "You asked", "Correlation ≠", "A forecast is", "Assumes"))]
    if useful:
        why += " " + useful[0].rstrip(".") + "."
    action = (f"Look one level deeper with the next question: \"{next_questions[0]}\"" if next_questions
              else "Check the result data below before acting on it")
    return (f"**Why it matters:** {why}\n\n**Suggested action:** {action}.\n\n"
            f"{FALLBACK_MARK} (the AI's explanation failed an automatic check)._")

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
  5. Beyond    time words ("consistently"), causes ("key driver"), growth, profit, and things never analysed
               ("pricing", "customer segments") only when the answer's own numbers or text show them
  6. Fractions "over a third of", "half of" must match a real share shown (31.6% is not "over a third")
"""

import re

NUMBER = re.compile(r"[-−]?\$?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|K|M|pts)(?![a-z]))?", re.IGNORECASE)
FALLBACK_MARK = "_Explanation written by code"


UNIT_WORDS = [(re.compile(r"(\d)\s*(?:percentage points?|pct\.? points?|points?|pp)\b", re.IGNORECASE), r"\1 pts"),
              (re.compile(r"(\d)\s*(?:percent|per cent)\b", re.IGNORECASE), r"\1%")]


def numbers_in(text: str) -> set:
    """Numbers as written ('0.7 percentage points' counts as '0.7pts', '12 percent' as '12%')."""
    text = text or ""
    for pattern, repl in UNIT_WORDS:
        text = pattern.sub(repl, text)
    out = set()
    for m in NUMBER.findall(text):
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


# ---- claims that go beyond the numbers (found in user testing, 5 Nov 2026)
# Time words: "consistently" needs year-by-year numbers; a 2014-2017 total does not show it.
TIME_WORDS = re.compile(r"\b(consistent(?:ly)?|always|every year|each year|year after year|steadily|"
                        r"continuous(?:ly)?|historically|over the years|for years)\b", re.IGNORECASE)
# Cause words: the numbers show WHAT happened, not WHY.
CAUSE_WORDS = re.compile(r"\b(key driver|main driver|major driver|driver of|driving|drives|driven by|"
                         r"contribut\w+ (?:to|towards)|because|due to|caused?|responsible for|thanks to|"
                         r"result of|success|replicat\w+|model for|best practices?)\b", re.IGNORECASE)
# Growth words need a comparison over time somewhere in the answer.
GROWTH_WORDS = re.compile(r"\b(growth|growing|grow|grew|grown)\b", re.IGNORECASE)
TIME_COMPARISON = re.compile(r"\bvs\b|compared with|previous|last year|yoy|mom|change|grew|growth|rose|fell|"
                             r"increase|decline|trend|forecast", re.IGNORECASE)
# Things the app never analysed: naming them as the story or the next step is guessing.
# (regex for the word in the explanation, regex that must appear in the code's own text to allow it)
UNANALYSED = [
    (r"\bpric(?:e|es|ing)\b", r"pric"),
    (r"\bdiscount (?:polic(?:y|ies)|strateg(?:y|ies))\b", r"discount polic|discount strateg"),
    (r"\bcustomer engagement\b", r"engagement"),
    (r"\bcustomer segments?\b", r"segment"),
    (r"\bmarketing\b", r"market"),
    (r"\bpromotions?\b|\bcampaigns?\b", r"promo|campaign"),
    (r"\bstrateg(?:y|ies)\b", r"strateg"),
    (r"\b(?:business )?practices\b", r"practice"),
    (r"\bproduct mix\b", r"product mix"),
    (r"\bseasonal\w*\b", r"season"),
]
# "a third of", "over half of": checked against the real shares shown (31.6% is not "over a third")
FRACTION = re.compile(r"\b(?:(over|more than|above|under|less than|below|nearly|almost|about|around|roughly|"
                      r"approximately|just under|just over|close to)\s+)?"
                      r"(a|one|two|three)?\s*(half|halves|thirds?|quarters?|fifths?|tenths?)\s+of\b", re.IGNORECASE)
FRACTION_VALUE = {"half": 0.5, "halves": 0.5, "third": 1 / 3, "thirds": 1 / 3, "quarter": 0.25, "quarters": 0.25,
                  "fifth": 0.2, "fifths": 0.2, "tenth": 0.1, "tenths": 0.1}
COUNT_WORD = {"a": 1, "one": 1, "two": 2, "three": 3, None: 1}


def _fraction_problems(text: str, pcts: list) -> list:
    out = []
    for m in FRACTION.finditer(text):
        qual, count, unit = m.group(1), m.group(2), m.group(3).lower()
        target = COUNT_WORD.get(count.lower() if count else None, 1) * FRACTION_VALUE[unit] * 100
        qual = (qual or "").lower()
        if qual in ("over", "more than", "above", "just over"):
            ok = any(p > target for p in pcts)
        elif qual in ("under", "less than", "below", "just under"):
            ok = any(p < target for p in pcts)
        else:          # plain, "nearly", "about"...: the share must be close to it
            ok = any(abs(p - target) <= 3 for p in pcts)
        if not ok:
            shown = ", ".join(f"{p:g}%" for p in pcts[:3]) or "no share"
            out.append(f"it says '{m.group(0).strip()}', which the numbers do not support (shares shown: {shown})")
    return out


def problems(narration: str, question: str, headline: str, facts: list, notes: list,
             next_questions: list | None = None) -> list:
    """Everything wrong with an AI explanation. Empty list = safe to show.
    next_questions: the follow-up questions the app suggests. An explanation may quote one exactly,
    and the words inside that quote are not counted against it."""
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

    # claims beyond the numbers. A quoted follow-up question is excused: it is the app's own suggestion.
    scan = narration
    for nq in next_questions or []:
        scan = re.sub(re.escape(nq.rstrip("?")), " ", scan, flags=re.IGNORECASE)
    allowed_l = allowed.lower()

    def unseen(pattern):   # matched words the code's own text never used
        words = {m.group(0).lower() for m in pattern.finditer(scan)}
        return sorted(w for w in words if w not in allowed_l)

    if unseen(TIME_WORDS):
        found.append("it says " + ", ".join(f"'{w}'" for w in unseen(TIME_WORDS)) +
                     ", but the numbers show one period, not year-by-year results")
    if unseen(CAUSE_WORDS):
        found.append("it gives a cause or driver (" + ", ".join(f"'{w}'" for w in unseen(CAUSE_WORDS)) +
                     "); the numbers show what happened, not why")
    if GROWTH_WORDS.search(scan) and not TIME_COMPARISON.search(allowed):
        found.append("it talks about growth, but no change over time is shown")
    # profit talk: "Why it matters" needs profit numbers; the action may also mention what a suggested question names
    why, _, action = scan.partition("**Suggested action:**")
    profit_word, profit_seen = re.compile(r"\b(profit\w*|margins?|loss(?:es)?)\b", re.IGNORECASE), re.compile(
        r"profit|margin|loss", re.IGNORECASE)
    action_allowed = allowed + " " + " ".join(next_questions or [])
    if (profit_word.search(why) and not profit_seen.search(allowed)) or \
            (profit_word.search(action) and not profit_seen.search(action_allowed)):
        found.append("it talks about profit or margin, but this answer shows no profit numbers")
    for word_re, allow_re in UNANALYSED:
        for m in re.finditer(word_re, scan, re.IGNORECASE):
            if not re.search(allow_re, allowed_l):
                found.append(f"it names '{m.group(0).lower()}', which was not analysed in this answer")
                break
    found += _fraction_problems(scan, pcts)
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

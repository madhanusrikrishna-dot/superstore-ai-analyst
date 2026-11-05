"""
test_verify.py - tests the explanation checker (verify.py) on REAL answers from user testing (5 Nov 2026).

Needs no data file and no AI: the key numbers below are copied from the app's screen.
  - answers that went beyond the numbers must be REJECTED ("consistently", "key driver", "over a third"...)
  - honest answers must still PASS

Run:  python test_verify.py
"""

import verify

passed = failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append(f"  FAIL  {name}  {detail}")


def probs(narration, case):
    return verify.problems(narration, case["question"], case["headline"], case["facts"], case["notes"],
                           case.get("next"))


# ---- "Which region has the highest sales?" (numbers copied from the screen)
SALES = {
    "question": "Which region has the highest sales?",
    "headline": "West has the highest sales ($725.5K) by region",
    "facts": [("Highest sales", "West · $725.5K"), ("Orders behind West", "1,611"),
              ("Next highest", "East · $678.8K"), ("West share of all sales (2014–2017)", "31.6%"),
              ("Total sales (2014–2017)", "$2.30M")],
    "notes": ["You asked for the top 1; the next 3 are shown for context."],
    "next": ["Show monthly sales for West", "Compare profit by region", "Does discount affect profit?"],
}
bad_sales = ("**Why it matters:** The West region consistently generates the highest sales, accounting for over a "
             "third of the company's total sales over the past four years. This strong performance indicates that "
             "the West region is a key driver of the company's overall sales growth and profitability.\n\n"
             "**Suggested action:** Consider analyzing the specific products or customer segments driving the West "
             "region's success to identify opportunities for replicating this success in other regions.")
p = " | ".join(probs(bad_sales, SALES))
check("sales answer is rejected", p != "", p)
check("catches 'consistently'", "consistently" in p, p)
check("catches 'over a third' (31.6% is under a third)", "over a third" in p, p)
check("catches 'key driver'", "key driver" in p, p)
check("catches growth with no change over time shown", "growth" in p, p)
check("catches profit talk with no profit numbers", "profit" in p, p)
check("catches 'customer segments' (never analysed)", "customer segments" in p, p)

good_sales = ("**Why it matters:** West has the highest sales at $725.5K, which is 31.6% of the company's $2.30M "
              "total, ahead of East at $678.8K.\n\n**Suggested action:** Next, check Compare profit by region to "
              "see whether West also leads on profit.")
check("an honest sales answer that quotes a next question passes", probs(good_sales, SALES) == [],
      str(probs(good_sales, SALES)))
check("the same text WITHOUT the next questions is rejected (profit not shown)",
      probs(good_sales, {**SALES, "next": None}) != [])

# ---- "Compare profit by region"
PROFIT = {
    "question": "Compare profit by region",
    "headline": "West has the highest profit ($108.4K) by region",
    "facts": [("Highest profit", "West · $108.4K"), ("Orders behind West", "1,611"),
              ("Next highest", "East · $91.5K"), ("West share of all profit (2014–2017)", "37.9%"),
              ("Total profit (2014–2017)", "$286.4K"), ("Losing money", "none of 4 regions")],
    "notes": [],
    "next": ["Show monthly profit for West", "Compare sales by region", "Does discount affect profit?"],
}
bad_profit = ("**Why it matters:** The West region has consistently generated the highest profit, accounting for "
              "nearly 38% of the total profit over the four-year period. This strong performance suggests that the "
              "West region is a key driver of the company's profitability and could be a model for other regions to "
              "follow.\n\n**Suggested action:** Consider analyzing the strategies and practices in the West region "
              "that have contributed to its success, such as pricing, discount policies, and customer engagement.")
p = " | ".join(probs(bad_profit, PROFIT))
check("profit answer is rejected", p != "", p)
check("catches 'consistently' (profit answer)", "consistently" in p, p)
check("catches 'key driver' (profit answer)", "key driver" in p, p)
check("catches 'pricing' (never analysed)", "pricing" in p, p)
check("catches 'discount policies' (never analysed)", "discount policies" in p, p)
check("catches 'customer engagement' (never analysed)", "customer engagement" in p, p)

good_profit = ("**Why it matters:** West earned $108.4K in profit, 37.9% of the $286.4K total, and no region lost "
               "money.\n\n**Suggested action:** Next, check Show monthly profit for West.")
check("an honest profit answer passes", probs(good_profit, PROFIT) == [], str(probs(good_profit, PROFIT)))

# ---- the profit answer that PASSED the first version (16:56, 5 Nov): "significantly more revenue" is not shown
slipped = ("**Why it matters:** The West region has the highest profit at $108.4K, accounting for 37.9% of the total "
           "profit over 2014–2017. This indicates that the West region is the most profitable, generating "
           "significantly more revenue than the other regions.\n\n**Suggested action:** Show monthly profit for West.")
p = " | ".join(probs(slipped, PROFIT))
check("catches 'revenue' when only profit numbers are shown", "sales or revenue" in p, p)
check("catches 'significantly' (no significance test exists)", "significantly" in p, p)
check("a profit answer that sticks to profit numbers passes",
      probs(good_profit, PROFIT) == [], str(probs(good_profit, PROFIT)))
check("a sales answer may say 'sales' (shown), and the action may quote a profit question",
      probs(good_sales, SALES) == [], str(probs(good_sales, SALES)))

# ---- number words
for text, share, ok in [
        ("Over a third of sales came from West.", "31.6%", False),
        ("Over a third of sales came from West.", "36.0%", True),
        ("About a third of sales came from West.", "31.6%", True),
        ("Nearly half of sales came from West.", "31.6%", False),
        ("Less than a third of sales came from West.", "31.6%", True),
        ("Half of the profit came from West.", "52.0%", True),
        ("Half of the profit came from West.", "31.6%", False)]:
    case = {"question": "q", "headline": f"West share of sales and profit {share}", "facts": [("West share of sales and profit", share)],
            "notes": []}
    check(f"number words: '{text}' with {share} -> {'pass' if ok else 'reject'}",
          (probs(text, case) == []) == ok, str(probs(text, case)))

# ---- real false alarm (evaluate.py, 5 Nov): "quarters of 2017" is time, not a fraction
QTR = {"question": "Quarterly sales trend for the West region", "headline": "West sales by quarter",
       "facts": [("Share of year in Q4", "32.9%"), ("Q4 share, another year", "69.1%")], "notes": []}
check("'the last four quarters of 2017' is not read as a fraction", probs(
    "**Why it matters:** Sales rose in the last four quarters of 2017.\n\n**Suggested action:** Check the result data.",
    QTR) == [], str(probs("Sales rose in the last four quarters of 2017.", QTR)))
check("'a quarter of' is still checked against the shares", probs(
    "**Why it matters:** A quarter of sales came in Q4.\n\n**Suggested action:** Check the result data.",
    {**QTR, "facts": [("Q4 share", "32.9%")]}) != [])

# ---- words are fine when the code itself used them (nothing is blocked for no reason)
TREND = {"question": "Show monthly sales", "headline": "Sales grew 20.4% vs 2016 to $733.2K",
         "facts": [("Sales vs 2016", "+20.4%")], "notes": []}
check("'grew' passes when a change vs last year is shown",
      probs("**Why it matters:** Sales grew 20.4% vs 2016 to $733.2K.\n\n**Suggested action:** Check the result data.",
            TREND) == [], str(probs("Sales grew 20.4% vs 2016 to $733.2K.", TREND)))
CAUSED = {"question": "Why is profit low in Texas?", "headline": "Binders drive the loss in Texas",
          "facts": [("Loss", "$16.0K")], "notes": []}
check("'drive' in the code's own headline is not blocked",
      all("cause" not in x for x in probs("Binders drive the loss: $16.0K.", CAUSED)),
      str(probs("Binders drive the loss: $16.0K.", CAUSED)))

# ---- an honest answer with an extreme share and a judging word still passes (existing behaviour)
COHORT = {"question": "Do customers come back?", "headline": "98.1% of customers came back in a later quarter",
          "facts": [("Came back", "98.1%"), ("Buy in a typical quarter", "30.0%")], "notes": []}
fair = ("**Why it matters:** With 98.1% of customers coming back in a later quarter, loyalty is high and strong.\n\n"
        "**Suggested action:** Keep in touch with the 30.0% who buy in a typical quarter.")
check("an extreme share with a judging word still passes", probs(fair, COHORT) == [], str(probs(fair, COHORT)))

print("\n".join(failures[:40]))
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

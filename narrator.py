"""
narrator.py - the AI's two remaining jobs:
  1. explain(): turn the numbers the CODE calculated into plain business language
  2. free_sql(): for 'other' questions only, write SQL (shown with a warning)
"""

import re
from pathlib import Path

NOTES_FILE = Path(__file__).with_name("business_notes.md")


def business_notes() -> str:
    return NOTES_FILE.read_text(encoding="utf-8") if NOTES_FILE.exists() else ""


def explain(question: str, headline: str, facts: list, notes: list, model: str, scope: str = "") -> str:
    import ollama

    facts_text = "\n".join(f"- {k}: {v}" for k, v in facts)
    notes_text = "\n".join(f"- {n}" for n in notes)
    system = f"""You are a senior data analyst explaining results to a store manager.
Business context:
{business_notes()}

Rules:
- The numbers describe EXACTLY this scope: {scope}. Describe only this scope. If the question mentions
  something else (another region, year or product), do not claim the numbers are about it.
- Use ONLY the numbers listed under Key numbers. Do not calculate or invent any new number or percentage.
- Keep each number's meaning from its label. Example: "Texas loss compared with total profit: 9.5%" means
  the loss equals 9.5% of total profit, NOT that Texas made 9.5% of the profit. Call a state a state,
  a region a region.
- Words must match the numbers: "majority" or "most" only for more than 50%; "slight" only for under 5%.
- Write exactly two short parts:
  **Why it matters:** 2 sentences on what this means for the business.
  **Suggested action:** 1 sentence with a concrete next step.
- Plain English, no SQL, no bullet lists."""
    user = (f"Question: {question}\nScope of the numbers: {scope}\nHeadline: {headline}\n"
            f"Key numbers:\n{facts_text}\nNotes:\n{notes_text}")
    reply = ollama.chat(model=model, messages=[{"role": "system", "content": system},
                                               {"role": "user", "content": user}],
                        options={"temperature": 0.2})
    return reply["message"]["content"].strip()


FREE_SQL_PROMPT = """You are a data analyst. Write ONE SQLite query that answers the question.
Table: superstore (one row = one product line in an order, 2014-2017)
Columns: row_id, order_id, order_date ('YYYY-MM-DD' text), ship_date, ship_mode, customer_id, customer_name,
segment, country, city, state, postal_code, region, product_id, category, sub_category, product_name,
sales, quantity, discount (0-0.8), profit.
Rules: return only SQL in a ```sql block; SQLite syntax; year = substr(order_date,1,4);
month = substr(order_date,1,7); COUNT(DISTINCT ...) for orders/customers; LIMIT 50."""


def free_sql(question: str, model: str) -> str:
    import ollama

    reply = ollama.chat(model=model, messages=[{"role": "system", "content": FREE_SQL_PROMPT},
                                               {"role": "user", "content": question}],
                        options={"temperature": 0})
    text = reply["message"]["content"]
    m = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else text).strip().rstrip(";")


def is_read_only(sql: str) -> bool:
    words = sql.strip().split()
    if not words or words[0].upper() not in ("SELECT", "WITH"):
        return False
    banned = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|PRAGMA|REPLACE)\b"
    return re.search(banned, sql, re.IGNORECASE) is None

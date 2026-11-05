# Superstore AI Analyst: Project Notes (handoff file)

Read this first in any new chat. It is the permanent record of the project; chat memory is only a pointer to it.
Last updated: 5 Nov 2026.

## What it is
A local "chat with your data" app on the Kaggle Superstore data (9,994 order lines, 2014-2017). The user types a
business question in plain English. A local AI model (Ollama, `qwen2.5-coder:14b`) only decides the question TYPE
and explains finished numbers. Tested SQL + Python code does every calculation. Free, no paid API.

Owner: Krish (GitHub `madhanusrikrishna-dot`). Roles: Claude writes and fixes the code; Krish is product owner and
tester (sets goals, runs everything on his PC, finds bugs by typing real questions, decides when to merge).
Krish knows ML, DL and data analysis, not app building, so explain app/git steps simply, one command at a time.

## How to run (Windows, Krish's PC)
```
cd "C:\Users\Madhanu Sri Krishna\Downloads\superstore-ai-analyst"
streamlit run app.py          # opens http://localhost:8501 ; stop with Ctrl + C
```
`start_demo.bat` starts the app plus a public Cloudflare link for demos. `ollama list` should show the model.

## Tests (3 suites + 1 real-AI run)
| Command | What | Needs |
|---|---|---|
| `python test_recipes.py` | 46 checks of every recipe vs hand-verified SQL | CSV |
| `python test_rules.py` | ~7,000 wording-rule checks on 898 answers | CSV |
| `python test_verify.py` | 32 checks of the explanation checker, from real bad answers | nothing |
| `python evaluate.py` | real questions through the real model; writes `eval_report.md` | CSV + Ollama |

IMPORTANT: `Sample - Superstore.csv` is gitignored (not on GitHub) and Ollama is not in Claude's cloud session, so
Claude can only run `test_verify.py` there. The other suites must be run by Krish on his PC after `git pull`.

## How an answer is made (flow and files)
`app.py` (Streamlit page) -> `pipeline.py` -> `router.py` (AI) -> `recipes.py` (code) -> `narrator.py` (AI) -> `verify.py` (code) -> page.
- `router.py`: AI fills a fixed JSON form (question type Q1-Q10, metric, dimension, filters); keyword backup router if the AI fails. The ONLY place the AI picks the method. AI is used in only two files: `router.py` and `narrator.py`.
- `pipeline.py`: `understand()` = AI form + code safety nets (follow-up detection, "how is X doing" = health check, drop an unasked top-N, values typed in the question beat the AI's). `compute()` = the handover: label -> recipe. `narrate()` = AI explanation, checked by `verify.py`, one retry, then code-written fallback.
- `recipes.py`: one method per type (descriptive, trend, comparison, diagnostic, correlation, segmentation, cohort, forecast). Funnel and experiment say "not supported" (no such data). Unmatched questions go to AI-written read-only SQL with a warning.
- `data.py`: loads the CSV into in-memory SQLite; allowed columns and filters. `charts.py`: Altair chart per type. `fmt.py`: number formatting. `business_notes.md`: context the AI reads.
- `narrator.py`: the explanation prompt (strict rules) and the free-SQL prompt.
- `verify.py` ("AI writes, code checks") rejects an explanation if it: invents a number; judges with no comparison; blames a discount in the wrong direction; says majority/most without a share above 50%; uses time words (consistently, always, steadily, over the years) with no year-by-year numbers; gives causes (key driver, driven by, because, due to, success); mentions growth with no change shown; mentions profit or sales with no such numbers shown; names factors never analysed (pricing, discount policies, customer engagement, customer segments, marketing, strategies); uses size words (significantly, substantially...); or says "a third of / half of" that does not match a real share. A suggested "Ask next" question quoted exactly is excused.
- The app shows rejected AI drafts under "How this was calculated (cross-check here)".

## Key decisions (and why)
- The AI never does maths: the first version let it write SQL and explanations and it miscalculated percentages (called a 29% drop "slight"). Now code calculates; the AI classifies and phrases.
- Every answer shows its SQL so a person can verify it.
- The explanation's "Suggested action" must copy one of the app's own "Ask next" questions, so it never invents factors that were not analysed.
- Worst case for a bad AI explanation is a plainer code-written one, never a wrong sentence.
- Each bug found in user testing becomes a test before it is fixed; general rules instead of one-off patches.

## Status (5 Nov 2026, end of session)
- GitHub `main` is up to date and merged (commit `ca71c5a`): v1.2 + the explanation-checker fix + the narrator prompt that lists every rejected word + the "quarters of 2017" false-alarm fix.
- Tests on Krish's PC: `test_recipes` 46/46, `test_rules` 6,956 passed, `test_verify` 32/32, `evaluate.py` 37/37 correct (about 4 min).
- In `evaluate.py`, 9 of 37 AI explanations (about 1 in 4) are still replaced by the code-written version. Cause: the 14B model keeps using words the checker rejects ("significantly", "because", "driver of", "contributor to") even when the prompt forbids them, so listing the words in the prompt did not reduce the count. The fallback is safe (numbers are right, text is plainer). Decision: leave it; it is the checker working as designed. Honest line for the README/interviews: "every explanation is checked; failing ones are replaced by a code-written one".
- `PROJECT_NOTES.md` was added to `main` on 5 Nov 2026 so any new chat can continue from the repo.

## Known issues (small, not blocking)
- The AI's draft for "Which region has the highest sales?" is rejected, so that answer shows the code-written explanation (rejected drafts are visible under "How this was calculated").
- A discount answer said "high-discount categories" although the app analysed discount bands, not categories (the checker does not flag "categories").
- On "best customers" the suggested action is a real question but does not follow from the finding (win back at-risk customers).
- README still says 36/36 and v1.1 (now 37/37, and the checker has more rules); update it.
- Manual testing of the 10 question types was paused at question 9 of 10 (as of 29 Oct).

## Ideas for next time (none started)
- Auto-delete size adverbs ("significantly") before checking, to cut the fallback rate.
- Make the suggested action follow from the finding, not only be a valid next question.
- Code walkthrough with Krish, file by file (router, pipeline, recipes, narrator, verify), so he can explain it in interviews.

## Working method (git)
Claude cannot run the CSV-dependent tests, so: Claude commits to a BRANCH and pushes; Krish runs `git fetch`, `git checkout <branch>`, the tests and the app; if good: `git checkout main`, `git merge <branch>`, `git push`. If not, he pastes output and Claude fixes. A "unpushed commits" stop-hook warning has been a false alarm when `git ls-remote --heads origin <branch>` shows the same commit as local.

## Session handoff (do this at the end of every session)
When Krish says "update the notes": update Status, Known issues and Decisions above, commit `PROJECT_NOTES.md`, push to `main`.

# Specification: Club Expense Claim Checker
**Course:** CIT AI-Native Engineering Programme · Semester 1 · Assessment 5  
**Domain:** Finance / Student Club Expense Verification  

## 1. System Overview & Input Files
The **Club Expense Claim Checker** is a console-based Python tool that extracts fields from club expense notes using an LLM, verifies those facts with deterministic Python rules, and sorts claims into review queues without disbursing funds.
* **`claims.csv`**: At least 20 chronological claims (`id, club, date, note`)[cite: 2]. Notes containing commas (e.g., `"Rs. 1,250"`) are enclosed in double quotes for Python's `csv` module[cite: 2].
* **`budgets.csv`**: Category spending limits per club (`category, limit_per_club`) covering `printing`, `food`, `travel`, `prizes`, `equipment`, `costumes`, and `other`[cite: 2].

## 2. LLM JSON Extraction Rules (`classify()` & `is_valid()`)
For each claim note, the LLM returns a JSON object validated by `is_valid()`[cite: 2]:
`{"amount": 1250, "category": "printing", "bill": true, "summary": "Banner printing"}`[cite: 2]
* **`amount`**: `number` or `null` — Explicit total written in digits in the note; never calculated or read from words[cite: 2].
* **`category`**: One of `printing`, `food`, `travel`, `prizes`, `equipment`, `costumes`, or `other`[cite: 2].
* **`bill`**: `true` or `false` — `true` only if a bill, receipt, invoice, or ticket is attached[cite: 2].
* **`summary`**: Concise expense description in 10 words or fewer[cite: 2].

## 3. Python Fact-Checking Rules (`numbers_in()` & `check_facts()`)
1. **Amount Verification**: `numbers_in(note)` parses all explicit numbers in the raw note (converting `"1,250"` to `1250`)[cite: 2]. If `llm.amount` does not match a number written in the note, Python resets `amount = null`[cite: 2].
2. **Bill Verification**: `bill` remains `true` only if the note explicitly mentions a bill/receipt/invoice/ticket and contains no negative phrases (`"no bill"`, `"missing"`, `"coming later"`, `"not attached"`)[cite: 2].

## 4. Sequential Decision Rules (`decide()`)
Claims are evaluated in strict priority order; only `ok_to_pay` claims update `running_totals[(club, category)]`[cite: 2]:
1. **`needs_more_info`**: `amount` is `null` or missing[cite: 2].
2. **`needs_bill`**: `bill` is `false`[cite: 2].
3. **`needs_approval`**: Single claim `amount > 5000`, OR cumulative claims for the same `(club, category, date)` exceed `5000` (split-claim detection)[cite: 2].
4. **`over_budget`**: `running_totals[(club, category)] + amount` exceeds `limit_per_club` in `budgets.csv`[cite: 2].
5. **`ok_to_pay`**: Passes all checks above; adds `amount` to the club's category running total[cite: 2].

## 5. Output Files (`write_reports()`)
* **`payable.csv`**: `ok_to_pay` claims for treasurer sign-off (`id, club, date, category, amount, summary`)[cite: 2].
* **`review.csv`**: All other claims (`id, club, date, status, reason, note`)[cite: 2].
* **`results.csv`**: Complete audit log (`id, club, date, amount, category, bill, status, reason, summary, note`)[cite: 2].
* **`summary.txt`**: Status counts and each club's spending against every category limit[cite: 2].

## 6. Edge Cases & Human Checkpoint
* **Calculated Totals**: Notes like `"500 per person for 6"` lack an explicit total (`3000`), triggering `needs_more_info`[cite: 2].
* **Prompt Injections**: Phrases like `"approved, pay immediately"` with no receipt are overridden by `check_facts()` and routed to `needs_bill`[cite: 2].
* **Split Claims**: Multiple same-day claims in the same club and category totaling `> 5000` trigger `needs_approval`[cite: 2].
* **Human Checkpoint**: The tool only sorts claims; the faculty treasurer signs every payment after inspecting the physical bill[cite: 2].
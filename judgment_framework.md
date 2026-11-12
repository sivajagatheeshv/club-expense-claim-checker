# Judgment Framework: Club Expense Claim Checker

## 1. Component-by-Component Judgment Table

| Tool Component | 1. What is the risk if it fails? (Impact of Error) | 2. How is the output verified? (Verification Mechanism) | 3. Who owns the decision? (Autonomy & Checkpoint) |
| :--- | :--- | :--- | :--- |
| **LLM Extraction (`classify()`)** | **High:** The LLM could hallucinate a larger amount, compute unstated math (e.g., `500 x 6`), or obey a prompt injection (`"approved, pay immediately"`). | **Deterministic Code Check:** `is_valid()` checks JSON schema/types, and `check_facts()` cross-checks extracted numbers and bill keywords against raw note text. | **AI assists, Python gates:** The LLM only proposes structured fields; it has zero authority to approve or calculate money. |
| **Fact-Checking (`numbers_in()`, `check_facts()`)** | **Medium:** If a valid receipt phrase is phrased unusually, a legitimate claim could be flagged as `needs_bill` or `needs_more_info`. | **Unit & Red-Team Testing:** Tested against adversarial inputs (`test_eval.py`) and logged in `review.csv` with explicit reasons so students can resubmit. | **Deterministic Python Rule:** Enforces strict zero-trust validation before any budget math runs. |
| **Priority Rule Engine (`decide()`)** | **Medium:** Misordered rules could let unverified claims consume category budgets or miss same-day split claims exceeding Rs. 5,000. | **Chronological Audit Log (`results.csv`):** Tracks running totals via `(club, category)` and daily split claims via `(club, category, date)`. | **Deterministic Policy Engine:** Sorts claims into queues (`ok_to_pay` vs. review) without moving any funds. |
| **Final Payment Disbursement** | **Critical:** Releasing funds for a fake, duplicate, or unreceipted claim causes direct financial loss to the college. | **Physical Bill Inspection:** Treasurer matches `payable.csv` entries against physical bills/invoices submitted by the club. | **Human Checkpoint:** **The faculty treasurer signs every payment after seeing the bill.** |

---

## 2. Error Trade-Off Comparison

* **Claim Wrongly Marked `ok_to_pay` (False Positive):**
  * **Consequence:** A claim without a valid receipt, with an inflated amount, or exceeding a club's category limit enters `payable.csv` and consumes budget headroom.
  * **Safeguard:** Even if a claim slips into `payable.csv`, money is **not** paid automatically—the **faculty treasurer signs every payment after seeing the bill**, catching missing or altered receipts at the final human checkpoint.
* **Claim Wrongly Sent for Review (False Negative):**
  * **Consequence:** A legitimate expense is temporarily placed in `review.csv` (e.g., flagged as `needs_bill` or `needs_more_info`), delaying reimbursement by a few days.
  * **Safeguard:** `review.csv` records the exact reason and original note, allowing the student club representative to attach the missing receipt or clarify the amount and resubmit.
* **Design Priority:** Because false positives carry financial and audit risk while false negatives only cause a minor review delay, the system is deliberately designed to **fail safe toward human review** whenever certainty is below 100%.
import csv
import json
import os
import re
import time
from dotenv import load_dotenv
from google import genai

# Load environment variables (.env file)
load_dotenv()

# Read system prompt
prompt_filename = "system_prompt.txt" if os.path.exists("system_prompt.txt") else "system_prompt"
with open(prompt_filename, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

ALLOWED_CATEGORIES = {"printing", "food", "travel", "prizes", "equipment", "costumes", "other"}
ACTIVE_MODEL = None


def resolve_active_model(client) -> str:
    """Auto-detects and caches an active model supported by your API key."""
    global ACTIVE_MODEL
    if ACTIVE_MODEL:
        return ACTIVE_MODEL

    candidates = [
        "gemini-2.5-flash",
        "gemini-1.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
    ]

    for model_name in candidates:
        try:
            resp = client.models.generate_content(model=model_name, contents="ping")
            if resp and resp.text:
                ACTIVE_MODEL = model_name
                print(f"Connected to Gemini API using model: '{ACTIVE_MODEL}'\n")
                return ACTIVE_MODEL
        except Exception:
            continue

    try:
        for m in client.models.list():
            m_name = m.name.replace("models/", "")
            if "flash" in m_name.lower():
                try:
                    resp = client.models.generate_content(model=m_name, contents="ping")
                    if resp and resp.text:
                        ACTIVE_MODEL = m_name
                        print(f"Connected to Gemini API using model: '{ACTIVE_MODEL}'\n")
                        return ACTIVE_MODEL
                except Exception:
                    continue
    except Exception as e:
        print(f"Unable to list models: {e}")

    ACTIVE_MODEL = "gemini-1.5-flash"
    return ACTIVE_MODEL


# ---------------------------------------------------------
# 1. LLM Extraction & Validation Functions
# ---------------------------------------------------------
def classify(claim_note: str) -> dict:
    """Calls Gemini API to parse claim text into structured JSON with retry logic."""
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    model_name = resolve_active_model(client)

    prompt = f'{SYSTEM_PROMPT}\n\nInput Claim Note:\n"{claim_note}"'

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            clean_text = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)

            # Safely parse amount without turning decimals like 1250.0 into 12500
            raw_amt = data.get("amount")
            parsed_amt = None
            if raw_amt is not None:
                try:
                    cleaned_str = str(raw_amt).replace(",", "").strip()
                    num_match = re.search(r"\d+(?:\.\d+)?", cleaned_str)
                    if num_match:
                        val = float(num_match.group())
                        parsed_amt = int(val) if val.is_integer() else val
                except (ValueError, TypeError):
                    parsed_amt = None

            summary_words = str(data.get("summary", "No summary")).split()
            trimmed_summary = " ".join(summary_words[:10])

            return {
                "amount": parsed_amt,
                "category": str(data.get("category", "other")).strip().lower(),
                "bill": data.get("bill"),
                "summary": trimmed_summary,
            }
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                print(f"Rate limit reached on attempt {attempt + 1}. Waiting 30s for quota reset...")
                time.sleep(30)
            else:
                print(f"LLM Error on note '{claim_note}': {e}")
                break

    return {"amount": None, "category": "other", "bill": False, "summary": "LLM Parse Error"}


def is_valid(llm_data: dict) -> bool:
    """Validates that the LLM dictionary has allowed keys, category, bill boolean, and <=10 word summary."""
    if not isinstance(llm_data, dict):
        return False
    required_keys = {"amount", "category", "bill", "summary"}
    if not required_keys.issubset(llm_data.keys()):
        return False
    if llm_data["amount"] is not None and not isinstance(llm_data["amount"], (int, float)):
        return False
    if llm_data["category"] not in ALLOWED_CATEGORIES:
        return False
    if not isinstance(llm_data["bill"], bool):
        return False
    if not isinstance(llm_data["summary"], str) or len(llm_data["summary"].split()) > 10:
        return False
    return True


# ---------------------------------------------------------
# 2. Fact Checking Helpers
# ---------------------------------------------------------
def numbers_in(text: str) -> list[float]:
    """Extracts all explicit numbers written in the note ('1,250' -> 1250.0)."""
    cleaned_text = text.replace(",", "")
    return [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", cleaned_text)]


def check_facts(note: str, llm_data: dict) -> dict:
    """Verifies both the extracted amount and bill status against the raw claim text."""
    verified = llm_data.copy()

    # 1. Verify amount exists verbatim in the note
    amount = verified.get("amount")
    if amount is not None:
        text_numbers = numbers_in(note)
        if float(amount) not in text_numbers:
            verified["amount"] = None

    # 2. Verify bill is mentioned AND not stated as missing or coming later
    note_lower = note.lower()
    bill_keywords = ["bill", "receipt", "invoice", "ticket"]
    negative_keywords = [
        "no bill",
        "no receipt",
        "no invoice",
        "no ticket",
        "without bill",
        "without receipt",
        "missing",
        "coming later",
        "later",
        "not attached",
    ]

    mentions_bill = any(kw in note_lower for kw in bill_keywords)
    mentions_missing = any(kw in note_lower for kw in negative_keywords)

    verified["bill"] = bool(verified.get("bill")) and mentions_bill and not mentions_missing
    return verified


# ---------------------------------------------------------
# 3. Priority Decision Engine
# ---------------------------------------------------------
def decide(
    claim: dict,
    fact_data: dict,
    running_totals: dict,
    budgets: dict,
    daily_claims_tracker: dict,
) -> tuple[str, str]:
    """Applies the 5 sequential priority rules."""
    club = claim["club"]
    category = fact_data["category"]
    date = claim["date"]
    amount = fact_data["amount"]
    bill = fact_data["bill"]

    # Priority Rule 1: needs_more_info
    if amount is None or amount <= 0:
        return "needs_more_info", "No valid numeric amount found in text"

    # Priority Rule 2: needs_bill
    if not bill:
        return "needs_bill", "Missing proof of purchase (no bill/receipt attached)"

    # Priority Rule 3: needs_approval (> 5000 or split claim total > 5000 on same date)
    tracker_key = (club, category, date)
    day_spent_so_far = daily_claims_tracker.get(tracker_key, 0)

    if amount > 5000:
        return "needs_approval", f"Single claim amount ({amount}) exceeds threshold of 5,000"
    if (day_spent_so_far + amount) > 5000:
        return "needs_approval", f"Split claim detected: Total for {club} in {category} on {date} exceeds 5,000"

    # Priority Rule 4: over_budget
    cat_limit = budgets.get(category, 2000)
    current_spent = running_totals.get((club, category), 0)

    if current_spent + amount > cat_limit:
        return "over_budget", f"Claim of {amount} pushes total ({current_spent + amount}) over budget limit ({cat_limit})"

    # Priority Rule 5: ok_to_pay (only ok_to_pay claims count towards budgets)
    running_totals[(club, category)] = current_spent + amount
    daily_claims_tracker[tracker_key] = day_spent_so_far + amount
    return "ok_to_pay", "Passed all validation checks"


# ---------------------------------------------------------
# 4. Report Writer
# ---------------------------------------------------------
def write_reports(
    results: list,
    payable: list,
    review: list,
    status_counts: dict,
    running_totals: dict,
    budgets: dict,
    clubs: list,
) -> None:
    """Writes payable.csv, review.csv, results.csv, and summary.txt."""
    with open("payable.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "club", "date", "category", "amount", "summary"])
        writer.writeheader()
        writer.writerows(payable)

    with open("review.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "club", "date", "status", "reason", "note"])
        writer.writeheader()
        writer.writerows(review)

    with open("results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "club", "date", "amount", "category", "bill", "status", "reason", "summary", "note"],
        )
        writer.writeheader()
        writer.writerows(results)

    with open("summary.txt", "w", encoding="utf-8") as f:
        f.write("=========================================\n")
        f.write("   CLUB EXPENSE CLAIM CHECKER SUMMARY    \n")
        f.write("=========================================\n\n")
        f.write("STATUS TALLIES:\n")
        for st, count in status_counts.items():
            f.write(f"  - {st}: {count}\n")

        f.write("\nCLUB SPENDING AGAINST CATEGORY LIMITS:\n")
        for club in sorted(clubs):
            f.write(f"\n{club}:\n")
            for cat, limit in sorted(budgets.items()):
                spent = running_totals.get((club, cat), 0.0)
                f.write(f"  - {cat}: {spent:.2f} / {limit:.2f}\n")


# ---------------------------------------------------------
# 5. Main Processing Flow
# ---------------------------------------------------------
def main():
    budgets_file = "budgets.csv" if os.path.exists("budgets.csv") else "budgets"
    budgets = {}
    with open(budgets_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            budgets[row["category"].strip().lower()] = float(row["limit_per_club"])

    claims_file = "claims.csv" if os.path.exists("claims.csv") else "claims"
    claims = []
    clubs = set()
    with open(claims_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            claims.append(row)
            clubs.add(row["club"].strip())

    running_totals = {}
    daily_claims_tracker = {}
    results = []
    payable = []
    review = []

    status_counts = {
        "ok_to_pay": 0,
        "needs_bill": 0,
        "needs_more_info": 0,
        "needs_approval": 0,
        "over_budget": 0,
    }

    print("Processing expense claims through Gemini LLM and Python Rules Engine...\n")

    for idx, claim in enumerate(claims):
        if idx > 0:
            time.sleep(4)

        llm_data = classify(claim["note"])
        if not is_valid(llm_data):
            llm_data = {"amount": None, "category": "other", "bill": False, "summary": "Invalid LLM response"}

        fact_data = check_facts(claim["note"], llm_data)

        status, reason = decide(
            claim,
            fact_data,
            running_totals,
            budgets,
            daily_claims_tracker,
        )

        status_counts[status] += 1

        res_entry = {
            "id": claim["id"],
            "club": claim["club"],
            "date": claim["date"],
            "amount": fact_data["amount"] if fact_data["amount"] is not None else "",
            "category": fact_data["category"],
            "bill": fact_data["bill"],
            "status": status,
            "reason": reason,
            "summary": fact_data["summary"],
            "note": claim["note"],
        }
        results.append(res_entry)

        if status == "ok_to_pay":
            payable.append(
                {
                    "id": claim["id"],
                    "club": claim["club"],
                    "date": claim["date"],
                    "category": fact_data["category"],
                    "amount": fact_data["amount"],
                    "summary": fact_data["summary"],
                }
            )
        else:
            review.append(
                {
                    "id": claim["id"],
                    "club": claim["club"],
                    "date": claim["date"],
                    "status": status,
                    "reason": reason,
                    "note": claim["note"],
                }
            )

        print(f"[{claim['id']}] {claim['club']} -> {status.upper()} ({reason})")

    write_reports(results, payable, review, status_counts, running_totals, budgets, list(clubs))
    print("\nProcessing finished! Generated: payable.csv, review.csv, results.csv, and summary.txt")


if __name__ == "__main__":
    main()

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

# Global cached model
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
        "gemini-2.5-flash-lite"
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

    # Fallback: Query available models dynamically from your Google AI Studio project
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
# 1. LLM Extraction Function (With Rate Limit Retry Logic)
# ---------------------------------------------------------
def classify_claim(claim_note: str) -> dict:
    """Calls Gemini API to parse claim text into structured JSON with retry logic for rate limits."""
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    model_name = resolve_active_model(client)
    
    prompt = f"{SYSTEM_PROMPT}\n\nInput Claim Note:\n\"{claim_note}\""
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            clean_text = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)
            
            # Sanitize amount field (convert string "1,250" or 1250.0 to integer 1250)
            raw_amt = data.get("amount")
            parsed_amt = None
            if raw_amt is not None:
                try:
                    clean_amt_str = re.sub(r'[^\d]', '', str(raw_amt))
                    if clean_amt_str:
                        parsed_amt = int(clean_amt_str)
                except (ValueError, TypeError):
                    parsed_amt = None

            return {
                "amount": parsed_amt,
                "category": str(data.get("category", "other")).lower(),
                "bill": bool(data.get("bill", False)),
                "summary": str(data.get("summary", "No summary"))
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

# ---------------------------------------------------------
# 2. Fact Checking Helpers
# ---------------------------------------------------------
def extract_numbers_from_text(text: str) -> list[int]:
    """Extracts all integer digit sequences from raw note text (e.g., '1,250' -> 1250)."""
    cleaned_text = text.replace(",", "")
    return [int(n) for n in re.findall(r'\b\d+\b', cleaned_text)]

def check_facts(note: str, llm_data: dict) -> tuple[bool, str]:
    """Verifies LLM extracted amount against raw text numbers."""
    amount = llm_data.get("amount")
    
    if amount is None:
        return False, "No numeric amount found in text"
    
    text_numbers = extract_numbers_from_text(note)
    if amount not in text_numbers:
        return False, f"Extracted amount {amount} not explicitly found in note text"
    
    return True, "Fact check passed"

# ---------------------------------------------------------
# 3. Priority Decision Engine
# ---------------------------------------------------------
def evaluate_claim(
    claim: dict, 
    llm_data: dict, 
    fact_ok: bool, 
    fact_reason: str,
    running_totals: dict, 
    budgets: dict,
    daily_claims_tracker: dict
) -> tuple[str, str]:
    """Applies the 5 sequential priority rules."""
    club = claim["club"]
    category = llm_data["category"]
    date = claim["date"]
    amount = llm_data["amount"]
    bill = llm_data["bill"]
    
    # Priority Rule 1: needs_more_info
    if not fact_ok or amount is None:
        return "needs_more_info", fact_reason
    
    # Priority Rule 2: needs_bill
    if not bill:
        return "needs_bill", "Missing proof of purchase (no bill/receipt attached)"
    
    # Priority Rule 3: needs_approval (> 5000 or split claim total > 5000 on same date)
    tracker_key = (club, category, date)
    daily_claims_tracker[tracker_key] = daily_claims_tracker.get(tracker_key, 0) + amount
    
    if amount > 5000:
        return "needs_approval", f"Single claim amount ({amount}) exceeds threshold of 5,000"
    if daily_claims_tracker[tracker_key] > 5000 and amount <= 5000:
        return "needs_approval", f"Split claim detected: Total for {club} in {category} on {date} exceeds 5,000"
    
    # Priority Rule 4: over_budget
    cat_limit = budgets.get(category, 2000)
    current_spent = running_totals.get((club, category), 0)
    
    if current_spent + amount > cat_limit:
        return "over_budget", f"Claim of {amount} pushes total ({current_spent + amount}) over budget limit ({cat_limit})"
    
    # Priority Rule 5: ok_to_pay
    running_totals[(club, category)] = current_spent + amount
    return "ok_to_pay", "Passed all validation checks"

# ---------------------------------------------------------
# 4. Main Processing Flow
# ---------------------------------------------------------
def main():
    # Load Budgets
    budgets_file = "budgets.csv" if os.path.exists("budgets.csv") else "budgets"
    budgets = {}
    with open(budgets_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            budgets[row["category"].strip().lower()] = float(row["limit_per_club"])
            
    # Load Claims
    claims_file = "claims.csv" if os.path.exists("claims.csv") else "claims"
    claims = []
    with open(claims_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            claims.append(row)

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
        "over_budget": 0
    }

    print("Processing expense claims through Gemini LLM and Python Rules Engine...\n")
    
    for idx, claim in enumerate(claims):
        # Pause 4 seconds between requests to maintain <= 15 requests per minute limit
        if idx > 0:
            time.sleep(4)
            
        # LLM Classification
        llm_data = classify_claim(claim["note"])
        
        # Fact Check
        fact_ok, fact_reason = check_facts(claim["note"], llm_data)
        
        # Priority Decision Engine
        status, reason = evaluate_claim(
            claim, llm_data, fact_ok, fact_reason, 
            running_totals, budgets, daily_claims_tracker
        )
        
        status_counts[status] += 1
        
        # Log to Results
        res_entry = {
            "id": claim["id"],
            "club": claim["club"],
            "date": claim["date"],
            "amount": llm_data["amount"] if llm_data["amount"] is not None else "",
            "category": llm_data["category"],
            "bill": llm_data["bill"],
            "status": status,
            "reason": reason,
            "summary": llm_data["summary"],
            "note": claim["note"]
        }
        results.append(res_entry)
        
        # Separate Outputs
        if status == "ok_to_pay":
            payable.append({
                "id": claim["id"],
                "club": claim["club"],
                "date": claim["date"],
                "category": llm_data["category"],
                "amount": llm_data["amount"],
                "summary": llm_data["summary"]
            })
        else:
            review.append({
                "id": claim["id"],
                "club": claim["club"],
                "date": claim["date"],
                "status": status,
                "reason": reason,
                "note": claim["note"]
            })
            
        print(f"[{claim['id']}] {claim['club']} -> {status.upper()} ({reason})")

    # Generate payable.csv
    with open("payable.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "club", "date", "category", "amount", "summary"])
        writer.writeheader()
        writer.writerows(payable)

    # Generate review.csv
    with open("review.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "club", "date", "status", "reason", "note"])
        writer.writeheader()
        writer.writerows(review)

    # Generate results.csv
    with open("results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "club", "date", "amount", "category", "bill", "status", "reason", "summary", "note"])
        writer.writeheader()
        writer.writerows(results)

    # Generate summary.txt
    with open("summary.txt", "w", encoding="utf-8") as f:
        f.write("=========================================\n")
        f.write("   CLUB EXPENSE CLAIM CHECKER SUMMARY    \n")
        f.write("=========================================\n\n")
        f.write("STATUS TALLIES:\n")
        for st, count in status_counts.items():
            f.write(f"  - {st}: {count}\n")
        
        f.write("\nAPPROVED SPENDING BY CLUB & CATEGORY:\n")
        if not running_totals:
            f.write("  No claims approved.\n")
        else:
            for (club, cat), spent in sorted(running_totals.items()):
                limit = budgets.get(cat, 2000)
                f.write(f"  - {club} [{cat}]: {spent:.2f} / {limit:.2f}\n")

    print("\nProcessing finished! Generated: payable.csv, review.csv, results.csv, and summary.txt")

if __name__ == "__main__":
    main()

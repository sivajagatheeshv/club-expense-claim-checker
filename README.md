# Club Expense Claim Checker

A console-based Python tool built for the **CIT AI-Native Engineering Programme (Semester 1 – Assessment 5)**. It reads student club expense claims, extracts structured fields using the Gemini API, verifies amounts and receipts with deterministic Python rules, and sorts claims for final faculty treasurer review.

## How It Works
1. **LLM Extraction (`classify()`, `is_valid()`)**: Parses unstructured claim notes into validated JSON (`amount`, `category`, `bill`, `summary`).
2. **Python Fact-Checking (`numbers_in()`, `check_facts()`)**: Verifies that extracted numbers appear verbatim in the raw note and confirms receipt proof without negative phrases (`"no bill"`, `"coming later"`).
3. **Sequential Rule Engine (`decide()`)**: Evaluates claims in strict priority order:
   `needs_more_info` -> `needs_bill` -> `needs_approval` (> 5,000 single or same-day split claim) -> `over_budget` -> `ok_to_pay`.
4. **Human Checkpoint (`write_reports()`)**: Generates `payable.csv`, `review.csv`, `results.csv`, and `summary.txt`. The tool never disburses funds; the faculty treasurer signs every payment after inspecting the physical bill.

## Setup & Usage
1. Install dependencies:
   ```bash
   pip install google-genai python-dotenv
   ```
2. Create a `.env` file in the root folder and add your Gemini API key:
   ```text
   GEMINI_API_KEY=your_api_key_here
   ```
3. Run the main claim checker:
   ```bash
   python main.py
   ```
4. Run the evaluation and red-team test suite:
   ```bash
   python test_eval.py
   ```

## Repository Contents
* **Core Code & Prompt**: `main.py`, `system_prompt.txt`
* **Inputs**: `claims.csv`, `budgets.csv`
* **Generated Reports**: `payable.csv`, `review.csv`, `results.csv`, `summary.txt`
* **Testing**: `test_eval.py`, `eval_results.txt`
* **Documentation**: `specification_document.md`, `judgment_framework.md`, `cost_and_latency.md`, `ai_decision_journal.md`, `reflection.md`
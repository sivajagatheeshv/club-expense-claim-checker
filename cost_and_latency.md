# Cost and Latency Note

## 1. Daily API Call Volume
* **Batch Size:** A typical college club billing cycle processes **20 to 25 expense claims per day**.
* **Calls per Day:** Each claim requires **1 LLM API call** (`classify()`), plus **1 lightweight startup health-check ping** (`resolve_active_model()`), totaling **21 to 26 API calls per day**.

## 2. Latency Breakdown
* **Per-Call API Latency:** Using `gemini-3.5-flash-lite` (with `gemini-2.5-flash` / `gemini-1.5-flash` fallback), each classification request takes roughly **0.4 to 0.8 seconds** of network and inference time.
* **Rate-Limit Throttling:** To stay safely within the Google AI Studio free-tier limit (15 requests per minute), `main.py` includes a **4.0-second pause** between claims.
* **Total Daily Runtime:** Processing a full 20-claim daily batch takes approximately **85 to 95 seconds** (~1.5 minutes) end-to-end.

## 3. Estimated Daily Cost
* **Current Setup (Google AI Studio Free Tier):** **$0.00 per day** (21–26 requests/day uses less than 2% of the 1,500 requests/day free quota).
* **Projected Paid-Tier Cost (at scale):**
  * Average tokens per claim: ~450 input tokens (system prompt + claim note) and ~45 output tokens (4-field JSON).
  * Daily token volume (25 claims): ~11,250 input tokens and ~1,125 output tokens.
  * At standard Flash-Lite pricing (~$0.075 per 1M input tokens and ~$0.30 per 1M output tokens), running a full day of claims costs **less than $0.002 per day (under Rs. 0.20/day)**, or roughly **$0.06/month**.
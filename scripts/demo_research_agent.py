"""Live end-to-end demo of the research agent for one ticker."""
import os
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from dotenv import load_dotenv
load_dotenv()

import json
import sys
sys.path.insert(0, ".")

# Use mock news since Finnhub API key is not set
import data.finnhub_client as fh
fh._get_client = lambda: None
fh.get_company_news = lambda ticker, days_back=7: [
    {"headline": "Apple reports record Q3 revenue driven by iPhone 16 sales", "summary": "Apple beat expectations with $94.9B revenue.", "datetime": "2026-08-28T12:00:00+00:00", "source": "CNBC", "url": ""},
    {"headline": "Apple services segment grows 14% YoY to $26.3B", "summary": "", "datetime": "2026-08-28T10:00:00+00:00", "source": "Bloomberg", "url": ""},
    {"headline": "Analysts raise AAPL price target after strong guidance", "summary": "Multiple firms raised targets to $250-$270.", "datetime": "2026-08-27T16:00:00+00:00", "source": "Reuters", "url": ""},
    {"headline": "Apple faces potential EU regulatory headwinds on App Store", "summary": "EU considering new DMA enforcement action.", "datetime": "2026-08-27T09:00:00+00:00", "source": "Financial Times", "url": ""},
    {"headline": "iPhone 17 rumors point to major camera upgrade cycle", "summary": "", "datetime": "2026-08-26T14:00:00+00:00", "source": "The Verge", "url": ""},
]


def main() -> None:
    print("=== STEP 1: Fetching news ===\n")
    for i, a in enumerate(fh.get_company_news("AAPL")):
        print(f"  {i+1}. [{a['source']}] {a['headline']}")

    print("\n=== STEP 2: FinBERT scoring each headline ===\n")
    from agents.sentiment import score_headline
    for i, a in enumerate(fh.get_company_news("AAPL")):
        result = score_headline(a["headline"])
        print(f"  {i+1}. \"{a['headline'][:70]}...\"")
        print(f"     -> {result['label']} (confidence: {result['score']:.3f})")

    print("\n=== STEP 3: Aggregating FinBERT scores ===\n")
    from agents.research_agent import _aggregate_sentiment
    label, avg, scored = _aggregate_sentiment(fh.get_company_news("AAPL"))
    print(f"  Dominant label: {label}")
    print(f"  Average confidence: {avg:.3f}")
    print(f"  Per-headline: {[(s['finbert_label'], s['finbert_score']) for s in scored]}")

    print("\n=== STEP 4: Building LLM prompt ===\n")
    from agents.research_agent import _build_prompt
    prompt = _build_prompt("AAPL", label, avg, scored, fh.get_company_news("AAPL"))
    print(prompt[:1000] + "...")

    print("\n=== STEP 5: Calling LLM (DeepSeek-V4-Pro via Featherless) ===\n")
    from agents.llm_client import call_llm
    system = (
        "You are a quantitative research analyst. Given news headlines, "
        "FinBERT sentiment scores, and ticker information, produce a "
        "concise investment thesis. Always output valid JSON."
    )
    raw = call_llm(prompt=prompt, system_prompt=system, temperature=0.1, max_tokens=1024)
    print(f"  Raw LLM response:\n{raw}\n")

    print("\n=== STEP 6: Parsing & validating output ===\n")
    from agents.research_agent import _parse_llm_response, _validate_output
    parsed = _parse_llm_response(raw, "AAPL")
    assert parsed is not None, "Parse failed!"
    validated = _validate_output(parsed, "AAPL")
    print(json.dumps(validated, indent=2))

    print("\n=== END-TO-END RESULT ===")
    print(f"  Ticker:      {validated['ticker']}")
    print(f"  Sentiment:   {validated['sentiment']}")
    print(f"  Confidence:  {validated['confidence_score']}")
    print(f"  Thesis:      {validated['thesis']}")
    print(f"  Macro:       {validated['macro_alignment']}")


if __name__ == "__main__":
    main()
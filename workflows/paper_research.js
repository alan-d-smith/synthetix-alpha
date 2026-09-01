export const meta = {
  name: 'paper-research',
  description: 'Read queued arXiv papers, write Spec candidates, and report what the backtest says',
  phases: [{ title: 'Read', detail: 'one agent per paper' }, { title: 'Report', detail: 'rank and summarise' }],
}

// Run `python -m synthetix_alpha.research.loop find` first, then pass its papers as args.papers.
// Provider-agnostic LLM config. Set OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL in .env.
//   OPENAI_BASE_URL  e.g. https://router.huggingface.co/v1
//   OPENAI_API_KEY   your Hugging Face token
//   OPENAI_MODEL     e.g. deepseek-ai/DeepSeek-R1:featherless-ai
const OPENAI_BASE_URL = process.env.OPENAI_BASE_URL || ''
const OPENAI_API_KEY = process.env.OPENAI_API_KEY || ''
const MODEL = process.env.OPENAI_MODEL || 'gpt-4o-mini'
const REPO = process.cwd()
const PAPERS = (args && args.papers) || []
const SPEC_DIR = 'datasets/research/papers/specs'

const REF = `You are a quantitative options researcher in ${REPO} (run from there; python is .venv/Scripts/python).
Read synthetix_alpha/strategy/spec.py, engine.py, the features() function in data.py, and docs/research.md before writing anything. Do not edit code under synthetix_alpha/ or tests/.

Spec = JSON. Legs: type call|put|stock, side long|short, exactly one of delta / moneyness / width, optional dte_offset and ratio. Entry every entry_every_days when positions < max_positions and every signal feature is inside its [min,max]. Features: iv_rank, atm_iv, rv20, iv_rv_ratio, mom20, sma50_ratio, sma200_ratio, skew25, term_slope, rsi, bollinger_pos, macd, vix, vix_rank, vix_rv_ratio, vix_term, nfci, rvol, vwap_dev, days_to_earnings. Exits: profit_target, stop_loss, dte_exit, max_hold_days. Sizing: risk_fraction over max_loss|margin|notional, min_credit, min_volume.

Data: SPY 2020-2022, QQQ 2021-2022, AAPL 2016-2023, TSLA 2019-2022, NVDA 2020-2022 (EOD chains, real bid/ask/IV/greeks); Dolt surfaces 2019-2026 for out-of-sample.

WHAT IS ALREADY KNOWN (docs/research.md) - do not rediscover:
- The IV/RV gate is the entire edge. Ungated put-spread selling scores -0.78; gated at 1.27 it scores +1.11.
- Directional and technical filters all HURT: RSI, MACD, Bollinger, momentum, sma200 (-0.001 to -1.02).
- RVOL and VWAP deviation looked good in sample and failed out of sample.
- VIX term structure and NFCI hurt. Skipping high-VIX days hurts badly.
- Earnings avoidance is the one large single-name effect (+0.99 on AAPL).
- This sample resolves Sharpe differences of about 0.54. Anything smaller is noise, not a result.

Deployed incumbent: strategies/put_vertical_ivrv.json, score +0.520, mean Sharpe 0.92 with the liquidity floor.

Backtest one spec: .venv/Scripts/python -m synthetix_alpha.strategy.run <spec.json>
Score = 0.5*mean_sharpe + 0.5*min_sharpe + 2*worst_year + 3*max(maxDD,-1) + (positive_years-1); under 40 trades scores -9.

## Few-Shot Examples

### Example 1 — Valid Spec (put credit spread on SPY from variance-risk-premium paper)

{
  "name": "paper_2301_12345_vrp_put_spread",
  "legs": [
    {"type": "put", "side": "short", "delta": 0.20, "ratio": 1},
    {"type": "put", "side": "long", "delta": 0.10, "ratio": 1}
  ],
  "underlyings": ["SPY"],
  "dte_target": 45,
  "dte_min": 30,
  "dte_max": 60,
  "entry_every_days": 1,
  "max_positions": 4,
  "signal": {"iv_rv_ratio": [1.27, null], "vix_rv_ratio": [1.4, null]},
  "profit_target": 0.75,
  "stop_loss": 2.0,
  "dte_exit": 14,
  "risk_fraction": 0.03,
  "sizing": "max_loss",
  "source": "arXiv:2301.12345 Variance Risk Premium in Option Markets"
}

### Example 2 — Unusable Paper (needs intraday data the engine lacks)

When a paper requires intraday signals or tick-level data that the engine cannot express, return:
{
  "arxiv_id": "2301.99999",
  "usable": false,
  "summary": "The paper proposes a high-frequency delta-hedging strategy requiring sub-minute option quotes.",
  "specs": [],
  "missing_primitives": ["intraday option bars", "tick-level bid/ask data", "real-time delta hedging"],
  "engine_issues": "Requires intraday data resolution not available in current EOD chain engine."
}`

const RESULT = {
  type: 'object', required: ['arxiv_id', 'usable', 'summary', 'specs', 'missing_primitives'],
  properties: {
    arxiv_id: { type: 'string' }, usable: { type: 'boolean' },
    summary: { type: 'string', description: 'what the paper claims, in two sentences' },
    specs: { type: 'array', items: { type: 'object', required: ['name', 'path', 'thesis', 'score', 'mean_sharpe', 'trades', 'verdict'], properties: {
      name: { type: 'string' }, path: { type: 'string' }, thesis: { type: 'string' },
      score: { type: 'number' }, mean_sharpe: { type: 'number' }, trades: { type: 'number' },
      verdict: { type: 'string', enum: ['beats_incumbent', 'within_noise', 'worse', 'not_testable'] } } } },
    missing_primitives: { type: 'array', items: { type: 'string' } },
    engine_issues: { type: 'string' },
  },
}

phase('Read')
const results = await parallel(PAPERS.map(p => () => agent(
  `${REF}\n\nPaper ${p.id}: "${p.title}" (${p.published})\nPDF: ${p.local_pdf || p.pdf_url}\n\n` +
  `Read it in full. If it implies a strategy this engine can express, write the spec(s) to ${SPEC_DIR}/ named ` +
  `paper_${p.id.replace(/[^A-Za-z0-9]/g, '')}_<short>.json, backtest each once, and report the numbers you actually got. ` +
  `Write the paper's idea rather than tuning parameters against the backtest. Judge each spec against the incumbent ` +
  `honestly: a mean-Sharpe gain under 0.54 is "within_noise", not an improvement. If the paper needs data or mechanics ` +
  `the engine lacks, set usable=false and list what is missing instead of forcing a spec.`,
  { label: `read:${p.id}`, phase: 'Read', schema: RESULT })))

phase('Report')
const ok = results.filter(Boolean)
const specs = ok.flatMap(r => r.specs || [])
const winners = specs.filter(s => s.verdict === 'beats_incumbent')
log(`${ok.length}/${PAPERS.length} papers read, ${specs.length} specs written, ${winners.length} beat the incumbent`)
const report = specs.length ? await agent(
  `${REF}\n\nPaper results:\n${JSON.stringify(ok, null, 1)}\n\n` +
  `Append a section to docs/research.md titled "arXiv intake <today's date>" covering: which papers were read, which ` +
  `produced testable specs and their numbers, which cleared the 0.54 noise floor (state plainly if none did), and the ` +
  `missing primitives worth building next ranked by value over effort. Be brief and concrete. Return the section text.`,
  { label: 'report', phase: 'Report', effort: 'high' }) : 'no specs written'

return { read: ok.length, specs, winners, missing: ok.flatMap(r => r.missing_primitives || []), report }

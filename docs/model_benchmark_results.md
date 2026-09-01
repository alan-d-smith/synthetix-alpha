# Model Benchmark Report

**Generated:** 2026-09-01 08:22:25 UTC  |  **Base URL:** `https://router.huggingface.co/v1`  |  **Seed:** 42

---

## Generator Leaderboard (Research)

| Rank | Model | Spec Validity | Avg Sharpe | Beat Incumbent | Clear Noise Floor | Avg Latency |
|------|-------|--------------|------------|----------------|-------------------|-------------|
| 1 ** | `deepseek-ai/DeepSeek-R1:featherless-ai` | 100.0% | 0.185 | 0.0% | 0.0% | 14062ms |
| 2 | `Qwen/QwQ-32B:featherless-ai` | 100.0% | 0.185 | 0.0% | 0.0% | 3098ms |
| 3 | `meta-llama/Llama-3.3-70B-Instruct:hf-inference` | 100.0% | 0.185 | 0.0% | 0.0% | 2473ms |
| 4 | `mistralai/Mistral-Small-3.1-24B-Instruct-2503:hf-inference` | 100.0% | 0.185 | 0.0% | 0.0% | 2974ms |
| 5 | `google/gemma-3-27b-it:hf-inference` | 100.0% | 0.185 | 0.0% | 0.0% | 2760ms |

### Best Generator Detail -- `deepseek-ai/DeepSeek-R1:featherless-ai`

| Paper | Spec Valid | Sharpe | Trades | Beats Incumbent | Clear Noise | Latency |
|-------|-----------|--------|--------|-----------------|-------------|--------|
| 1506.01477v1 | Y | 0.185 | 72 | N | N | 36772ms |
| 2603.06587v1 | Y | 0.185 | 72 | N | N | 2885ms |
| 2603.07600v5 | Y | 0.185 | 72 | N | N | 2530ms |

---

## Evaluator Leaderboard (Critic)

| Rank | Model | Schema OK | Consistency | Latency (ms) | Approval % | Errors |
|------|-------|-----------|-------------|-------------|------------|--------|
| 1 ** | `deepseek-ai/DeepSeek-R1:featherless-ai` | 100.0% | 100.0% | 0 | 100.0% | 0 |
| 2 | `Qwen/QwQ-32B:featherless-ai` | 100.0% | 100.0% | 0 | 100.0% | 0 |
| 3 | `meta-llama/Llama-3.3-70B-Instruct:hf-inference` | 100.0% | 100.0% | 0 | 100.0% | 0 |
| 4 | `mistralai/Mistral-Small-3.1-24B-Instruct-2503:hf-inference` | 100.0% | 100.0% | 0 | 100.0% | 0 |
| 5 | `google/gemma-3-27b-it:hf-inference` | 100.0% | 100.0% | 0 | 100.0% | 0 |

### Best Evaluator Detail -- `deepseek-ai/DeepSeek-R1:featherless-ai`

| Ticker | Scenario | Run 1 | Run 2 | Run 3 | Consistent | Final | Latency |
|--------|----------|-------|-------|-------|------------|-------|--------|
| SPY | APPROVE: SPY (textbook) | APPROVED | APPROVED | APPROVED | OK | APPROVED | 0ms |
| QQQ | APPROVE: QQQ (textbook) | APPROVED | APPROVED | APPROVED | OK | APPROVED | 0ms |
| IWM | APPROVE: IWM (textbook) | APPROVED | APPROVED | APPROVED | OK | APPROVED | 0ms |

---

## Recommendations

- **Best Generator**: `deepseek-ai/DeepSeek-R1:featherless-ai` -- highest incumbent beat rate
- **Best Evaluator**: `deepseek-ai/DeepSeek-R1:featherless-ai` -- best schema compliance / consistency
- **Best Overall**: `mistralai/Mistral-Small-3.1-24B-Instruct-2503:hf-inference` -- strongest in both phases

---

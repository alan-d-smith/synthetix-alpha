# Synthetix Alpha frontend

Next.js command center for autonomous, risk-gated paper options trading. The UI consumes a typed dashboard snapshot and falls back to demo data when the backend adapter is unavailable. Brokerage, LLM, and market-data credentials are never requested by the browser.

## Routes

| Path | Screen |
| --- | --- |
| `/` | Command Center |
| `/pipeline` | Pipeline audit / Signal Trace |
| `/opportunities` | Opportunity table + inspector |
| `/portfolio` | Account posture + execution ledger |
| `/research` | Historical research evidence |
| `/system` | Source health + governance |

## Run

```sh
npm install
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

Useful scripts:

```sh
npm run typecheck
npm run build
npm run start
```

## Data mode

By default the app renders `lib/mock-data.ts` and shows **DEMO DATA**.

To connect the read-only dashboard adapter, copy `.env.example` and set:

```sh
NEXT_PUBLIC_DASHBOARD_API_URL=http://127.0.0.1:8000
```

The adapter endpoint expected by `lib/api.ts` is `GET /v1/overview`. When that request fails, the frontend remains in demo mode rather than inventing live fills or portfolio Greeks.

`POST /v1/pipeline/runs` is reserved for a dry pipeline request. The button stays disabled in demo mode and only succeeds when the adapter can guarantee dry-run semantics.

# Paper Trading CLI Reference

Companion to [SKILL.md](SKILL.md). Read the workflow and guardrails there first.

## Authoritative sources

- [Alpaca CLI](https://docs.alpaca.markets/us/docs/alpacas-cli)
- [Trading API](https://docs.alpaca.markets/us/docs/trading-api)
- [Paper trading](https://docs.alpaca.markets/us/docs/paper-trading)
- [Orders at Alpaca](https://docs.alpaca.markets/us/docs/orders-at-alpaca)

## Paper and live

Paper is the CLI's default; live requires explicit opt-in through one of two mechanisms:

- `--live`, as in `alpaca profile login --api-key --live`, which creates a live profile
- `ALPACA_LIVE_TRADE=true` in the environment

The environment variable applies at run time regardless of which profile is active, so an apparently-paper profile is not on its own proof of a paper target. Before every submission, confirm both that the active profile is paper and that `ALPACA_LIVE_TRADE` is unset or not `true`. Stop if either is unproven.

Other variables that change behavior: `ALPACA_PROFILE` selects the active profile, `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` supply credentials for CI and agent use, `ALPACA_OUTPUT` sets the default format, and `ALPACA_CONFIG_DIR` relocates config. Profiles are stored under `~/.config/alpaca/profiles/`.

## Command discovery

The installed CLI is authoritative for command syntax, and it is an alpha preview whose commands, flags, and output formats change between releases. Discover before use:

```bash
alpaca version
alpaca doctor
alpaca --help-all
alpaca profile list --help
alpaca profile switch --help
alpaca account get --help
alpaca clock --help
alpaca order --help
alpaca position --help
```

Inspect each order operation before constructing it:

```bash
alpaca order submit --help
alpaca order submit --dry-run --help
alpaca order submit --schema
alpaca order get --help
alpaca order get-by-client-id --help
alpaca order list --help
alpaca order cancel --help
alpaca order replace --help
```

Use `--dry-run` to preview when supported. Treat `--schema` as output-schema documentation, not order validation. JSON is the default structured output; `--quiet` suppresses non-data output. Check exit status and capture stderr: `0` is success, `1` is a general error, and `2` is an auth failure.

The CLI retries 429 and 5xx responses automatically (up to three times, respecting `Retry-After`), so do not layer additional retry logic on top of it.

Two commands act on the whole account with no confirmation prompt — `alpaca order cancel-all` and `alpaca position close-all`. Show the affected set and get explicit confirmation before either.

## CLI execution rules

- Prove paper before every submission: active profile is paper **and** `ALPACA_LIVE_TRADE` is unset or not `true`.
- Run `alpaca doctor` at session start, but do not treat connectivity alone as proof of paper configuration.
- Show the exact command and dry-run output before confirmation.
- Pass a unique `--client-order-id` for each logical order (up to 128 characters). The API rejects a duplicate, which is what makes a retry safe.
- Do not bypass the CLI with SDK, REST, or MCP calls.
- If a command or flag is unavailable, consult the installed version's help rather than inventing syntax.
- After an ambiguous failure, run `alpaca order get-by-client-id --client-order-id <id>` before retrying.
- Save redacted command output under the session's `raw/` directory.

## Validation

Verify account status, buying power, asset tradability, market session, and asset-specific permissions before submission. Derive valid order types, time-in-force values, prices, quantity rules, and extended-hours combinations from current CLI help and Trading API documentation.

Append submit, status, cancel, and replace events to `order_log.csv`; do not overwrite earlier lifecycle events.

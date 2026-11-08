# PayRecover (Jev)

Detects failed Razorpay one-time payments, diagnoses the cause with a
**rules-first → Jev typed decision → Gemini fallback** cascade, and recovers
revenue through bounded actions — payment links, reminders, escalation — with an
audit trail and measured batch recovery.

Built on top of the frozen v1 slice from
[Nish344/payrecover-agent](https://github.com/Nish344/payrecover-agent).
This tree adds [Jev](https://docs.typesafe.ai/introduction) (TypeSafe System One)
for calibrated, typed diagnosis — and a fair eval so the claim is defensible.

See [`plan.md`](plan.md) for the full plan (Parts I–III) and
[`docs/decisions.md`](docs/decisions.md) for the decision log.

## What this claims (and what it doesn't)

**Claim:** On a fair, held-out, synthetic-but-diverse set, Jev matches/beats a cheap
LLM at a fraction of the cost **and** is calibrated — fixing the exact v1 bug where
Gemini returned `cause=ambiguous` with `confidence=0.9`.

**Not claimed:** 100% accuracy on 8 hand-written sentences. That demo number was
circular and is **not** the public headline. Prefer the bench eval (`--profile bench`,
`--split test`) with Wilson CIs, ECE, and the baseline ladder.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Fill:
#   RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET   (test mode)
#   OPENROUTER_API_KEY                     (Jev)
#   GEMINI_API_KEY                         (fair A/B + calibration)
```

Offline smoke (no model keys):

```bash
payrecover dataset-info
payrecover seed --seed 100 --profile bench --force
payrecover eval --arms rules,keyword --split test --output reports/eval-offline.md
```

Full fair ladder (after keys are in `.env`):

```bash
payrecover seed --seed 100 --profile bench --force
payrecover eval --arms rules,keyword,jev,gemini --split test \
  --train-sweep --output reports/eval.md
# optional (spends credits):
payrecover consistency --arm jev --split test --runs 5 --limit 20 \
  --output reports/consistency.md
```

## Commands

| Command | What it does |
|---|---|
| `payrecover ping` | Authenticated test-mode Razorpay read |
| `payrecover detect [--since 1d] [--cohort …] [--export-fixtures]` | Read-only ingest of failed payments |
| `payrecover realgen` | Create test-mode Payment Links for the real cohort |
| `payrecover seed --profile classic\|jev\|bench` | Synthetic cases (`bench` = held-out corpus; `--keep-real` default) |
| `payrecover dataset-info` | Corpus size / family / split summary |
| `payrecover run [--diagnosis auto\|rules\|keyword\|jev\|gemini]` | Recover batch (dry-run default) |
| `payrecover eval --arms … --split test\|real` | Fair A/B (+ `--mask-reason` for real) |
| `payrecover consistency --arm jev` | Self-consistency (N runs, no cache) |
| `payrecover report` | Recovery metrics |
| `payrecover audit <case-id>` | Append-only trail |

## Architecture

```
                 ┌────────────────────────────────────────────────┐
                 │                  runner (orchestrator)          │
                 └────────────────────────────────────────────────┘
   batchgen ──▶ detector ──▶ diagnosis ──▶ policy ──▶ actions ──▶ Razorpay test API
 (classic /       (failed     (rules /     (gates,     (link /
  jev / bench      payments)   keyword /    caps,       remind /
  + labels +                   Jev /        signals)    wait /
  train/test)                  Gemini)                  escalate /
                                                        stop)
        │                          │            │          │
        └──────────────────────────┴─────┬──────┴──────────┘
                                         ▼
                              audit + eval cache (append-only / reports/cache)
                                         ▼
                              metrics / calibration ──▶ reports/
```

### Baseline ladder (eval arms)

1. `rules` — exact `error_reason` match only  
2. `keyword` — deterministic regex over description (fair cheap baseline)  
3. `gemini` — same taxonomy, self-reported confidence  
4. `jev` — typed Choice + Noul probabilities  

Tune thresholds on **`--split train`** (see `--train-sweep`); publish **`--split test`**.

### Invariants

1. Every action passes through `policy.py`. Only `actions.py` writes to Razorpay.
2. Every decision is audited (Jev logs full probability + Noul signals).
3. Caps: max 2 links / 3 reminders; amount = original; opt-out permanent; escalate on
   `ambiguous`, confidence &lt; 0.6, amount &gt; ₹5,000, or `requests_dispute`.
4. Models cannot mint a transient wait *cause* from untrusted text without Noul
   corroboration (`is_transient` strong + `customer_fault` low).
5. Response cache under `reports/cache/` makes eval reruns free and reproducible.

## Real Razorpay test-mode cohort

Reproduce the API-shape check in ~15 minutes (test keys only):

```bash
payrecover realgen --scenarios all --repeat 2 --cohort real-v1 --amount-max 100
# Pay each link on Checkout: listed test card → mock bank page → Failure
payrecover detect --since 1d --export-fixtures
payrecover eval --split real --arms rules,keyword,jev,gemini --output reports/eval_real.md
```

**What it validates:** real `pay_*` objects through `detector → diagnosis → policy`,
Razorpay `error_reason` vocabulary gaps (e.g. singular `insufficient_fund`, generic
`payment_failed`), and whether arms abstain on out-of-taxonomy reasons.

**What it is not:** a large labeled benchmark. Test-mode descriptions are one fixed
string per reason (zero paraphrase diversity), n will be ~30–50, CIs will be wide, and
for card scenarios the label is often determined by which test card / notes tag was
used — so rules accuracy on tagged reasons can be tautological. Say all of this in the
report. Real-cohort numbers never go in the synthetic headline table; `derived` labels
never count toward accuracy.

## Limitations (read before posting)

- Dataset is **synthetic** (diverse paraphrases + hard/adversarial families), not
  production Razorpay logs. The real cohort above is a secondary API-shape check —
  **not a benchmark**.
- Single decision-model vendor (Jev via OpenRouter).
- Finite n — always show Wilson 95% CIs, not bare percentages.
- Thresholds must be frozen from **train** before citing **test** numbers.
- Do not retune Part II thresholds (0.70 / 0.6) from real-cohort n.

## Tech stack

Python 3.11+, `razorpay` SDK (test mode), Jev via OpenRouter System One (`httpx`),
optional Gemini, Pydantic v2, SQLite, Typer, pytest, ruff.

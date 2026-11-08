# PayRecover diagnosis eval

> Synthetic labeled data. Tune thresholds on **train** only; headline numbers are from the requested split (prefer **test**).

| arm | split | accuracy | 95% CI | ECE | cost_usd | cost/1k |
|---|---|---|---|---|---|---|
| rules | test | 43.37% | [36.07%, 50.98%] | 0.1509 | 0.0 | 0.0 |
| keyword | test | 74.10% | [66.94%, 80.16%] | 0.1786 | 0.0 | 0.0 |
| jev | test | 87.95% | [82.12%, 92.06%] | 0.0592 | 0.005499 | 0.033125 |
| llm (gemini-3.5-flash-lite) | test | 80.72% | [74.05%, 86.00%] | 0.1885 | 0.0 | 0.0 |

## arm=rules (split=test)
- labeled: 166
- correct: 72
- accuracy: 43.37%
- 95% Wilson CI: [36.07%, 50.98%]
- ECE: 0.1509
- cost_usd: 0.0
- cost_per_1k: 0.0
- path_counts: {'rules': 166}
- ambiguous_stats: {'n': 32, 'mean_confidence': 0.45, 'high_conf_wrong': 0}

### by true_cause
- ambiguous: 32/32
- bank_downtime: 6/21
- customer_abandoned: 12/22
- incorrect_pin: 4/20
- insufficient_funds: 4/18
- international_transaction_not_allowed: 5/19
- invalid_otp: 4/16
- issuer_unavailable: 5/18

### by family
- adversarial: 0/7
- clean: 40/40
- conflicting: 0/11
- dispute: 11/11
- hard_ambiguous: 11/11
- unmapped: 10/86

### reliability (rules)
- n: 166
- ECE: 0.1509

| bin | lo | hi | count | avg_conf | accuracy | gap |
|---|---|---|---|---|---|---|
| 4 | 0.4 | 0.5 | 115 | 0.45 | 0.2783 | 0.1717 |
| 8 | 0.8 | 0.9 | 27 | 0.8667 | 0.8519 | 0.0148 |
| 9 | 0.9 | 1.0 | 24 | 0.9125 | 0.7083 | 0.2042 |

## arm=keyword (split=test)
- labeled: 166
- correct: 123
- accuracy: 74.10%
- 95% Wilson CI: [66.94%, 80.16%]
- ECE: 0.1786
- cost_usd: 0.0
- cost_per_1k: 0.0
- path_counts: {'keyword': 166}
- ambiguous_stats: {'n': 32, 'mean_confidence': 0.4188, 'high_conf_wrong': 0}

### by true_cause
- ambiguous: 32/32
- bank_downtime: 16/21
- customer_abandoned: 18/22
- incorrect_pin: 10/20
- insufficient_funds: 11/18
- international_transaction_not_allowed: 13/19
- invalid_otp: 12/16
- issuer_unavailable: 11/18

### by family
- adversarial: 5/7
- clean: 30/40
- conflicting: 7/11
- dispute: 11/11
- hard_ambiguous: 11/11
- unmapped: 59/86

### reliability (keyword)
- n: 166
- ECE: 0.1786

| bin | lo | hi | count | avg_conf | accuracy | gap |
|---|---|---|---|---|---|---|
| 3 | 0.3 | 0.4 | 58 | 0.35 | 0.3621 | 0.0121 |
| 4 | 0.4 | 0.5 | 5 | 0.4 | 0.0 | 0.4 |
| 5 | 0.5 | 0.6 | 11 | 0.55 | 1.0 | 0.45 |
| 7 | 0.7 | 0.8 | 92 | 0.75 | 0.9891 | 0.2391 |

## arm=jev (split=test)
- labeled: 166
- correct: 146
- accuracy: 87.95%
- 95% Wilson CI: [82.12%, 92.06%]
- ECE: 0.0592
- cost_usd: 0.005499
- cost_per_1k: 0.033125
- path_counts: {'jev': 166}
- ambiguous_stats: {'n': 32, 'mean_confidence': 0.9988, 'high_conf_wrong': 0}

### by true_cause
- ambiguous: 32/32
- bank_downtime: 16/21
- customer_abandoned: 22/22
- incorrect_pin: 18/20
- insufficient_funds: 17/18
- international_transaction_not_allowed: 16/19
- invalid_otp: 13/16
- issuer_unavailable: 12/18

### by family
- adversarial: 6/7
- clean: 40/40
- conflicting: 0/11
- dispute: 11/11
- hard_ambiguous: 11/11
- unmapped: 78/86

### reliability (jev)
- n: 166
- ECE: 0.0592

| bin | lo | hi | count | avg_conf | accuracy | gap |
|---|---|---|---|---|---|---|
| 4 | 0.4 | 0.5 | 12 | 0.4542 | 0.1667 | 0.2875 |
| 5 | 0.5 | 0.6 | 2 | 0.58 | 0.0 | 0.58 |
| 6 | 0.6 | 0.7 | 2 | 0.64 | 1.0 | 0.36 |
| 7 | 0.7 | 0.8 | 4 | 0.7225 | 0.5 | 0.2225 |
| 8 | 0.8 | 0.9 | 11 | 0.8618 | 0.6364 | 0.2255 |
| 9 | 0.9 | 1.0 | 135 | 0.9768 | 0.9852 | 0.0084 |

## arm=llm (gemini-3.5-flash-lite) (split=test)
- labeled: 166
- correct: 134
- accuracy: 80.72%
- 95% Wilson CI: [74.05%, 86.00%]
- ECE: 0.1885
- cost_usd: 0.0
- cost_per_1k: 0.0
- path_counts: {'llm': 165, 'rules': 1}
- ambiguous_stats: {'n': 32, 'mean_confidence': 0.7609, 'high_conf_wrong': 2}

### by true_cause
- ambiguous: 30/32
- bank_downtime: 6/21
- customer_abandoned: 22/22
- incorrect_pin: 20/20
- insufficient_funds: 18/18
- international_transaction_not_allowed: 19/19
- invalid_otp: 14/16
- issuer_unavailable: 5/18

### by family
- adversarial: 6/7
- clean: 40/40
- conflicting: 7/11
- dispute: 9/11
- hard_ambiguous: 11/11
- unmapped: 61/86

### reliability (llm (gemini-3.5-flash-lite))
- n: 166
- ECE: 0.1885

| bin | lo | hi | count | avg_conf | accuracy | gap |
|---|---|---|---|---|---|---|
| 4 | 0.4 | 0.5 | 1 | 0.45 | 1.0 | 0.55 |
| 5 | 0.5 | 0.6 | 7 | 0.5 | 1.0 | 0.5 |
| 8 | 0.8 | 0.9 | 12 | 0.8 | 0.8333 | 0.0333 |
| 9 | 0.9 | 1.0 | 146 | 0.9784 | 0.7945 | 0.1838 |

## train threshold sweep (jev)

| min_confidence | kept_accuracy | escalate_rate |
|---|---|---|
| 0.10 | 90.91% | 0.00% |
| 0.15 | 90.91% | 0.00% |
| 0.20 | 90.91% | 0.00% |
| 0.25 | 90.91% | 0.00% |
| 0.30 | 90.91% | 0.00% |
| 0.35 | 90.91% | 0.00% |
| 0.40 | 90.91% | 0.00% |
| 0.45 | 90.91% | 0.00% |
| 0.50 | 93.46% | 2.73% |
| 0.55 | 95.24% | 4.55% |
| 0.60 | 95.24% | 4.55% |
| 0.65 | 95.24% | 4.55% |
| 0.70 | 95.19% | 5.45% |
| 0.75 | 97.00% | 9.09% |
| 0.80 | 96.94% | 10.91% |
| 0.85 | 98.95% | 13.64% |
| 0.90 | 98.94% | 14.55% |

_Use this table on **train** only to pick MIN_CONFIDENCE; freeze before reporting test numbers._

## Limitations

- Dataset is synthetic (diverse paraphrases + hard/adversarial families).
- Single decision-model vendor (Jev via OpenRouter).
- Finite n: prefer Wilson CIs over point estimates. Overlapping CIs are not an accuracy win.
- `conflicting` family: label is the description; Jev trusts structured `error_reason` and will miss those on purpose.
- A `rules` count inside a model arm is an API failure scored as the fallback, not a rules decision.
- Do not cite train-tuned thresholds as test results.


# PayRecover real Razorpay cohort eval

> **Not a benchmark, and section 1 / section 5 accuracy is not a model score.**
> Test mode returned generic `payment_failed` for most of these 21 payments, and
> several `true_cause` values are scenario tags (`discover`, or `insufficient_funds`
> / `invalid_otp` on a payload that does not say that). Every arm landing on the
> same 57% is that labeling artifact. Read **section 3** (per-reason verdicts):
> real `pay_*` objects ran through detect → diagnose → policy, and
> `international_transaction_not_allowed` issues a link while generic
> `payment_failed` escalates.

## 1. In-taxonomy accuracy

Only `label_source ∈ {generated, manual}`. Derived labels excluded. n + Wilson CI.

| arm | n | accuracy | 95% CI |
|---|---|---|---|
| rules | 21 | 57.14% | [36.55%, 75.53%] |
| keyword | 21 | 57.14% | [36.55%, 75.53%] |
| jev | 21 | 57.14% | [36.55%, 75.53%] |
| gemini | 21 | 57.14% | [36.55%, 75.53%] |

## 2. Out-of-taxonomy abstention

Rows whose structured `raw_reason` has `kind=out_of_taxonomy`. `abstain_rate` = predicted `ambiguous`. Lower mean confidence is better here.

| arm | n | abstain_rate | mean_confidence |
|---|---|---|---|
| rules | 17 | 100.00% | 0.450 |
| keyword | 17 | 100.00% | 0.350 |
| jev | 17 | 100.00% | 0.980 |
| gemini | 17 | 100.00% | 0.603 |

## 3. Per-`raw_reason` table

| arm | raw_reason | predicted | confidence | policy_verdict |
|---|---|---|---|---|
| rules | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.950 | issue_link |
| rules | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.950 | issue_link |
| rules | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.950 | issue_link |
| rules | `payment_cancelled` | customer_abandoned | 0.850 | issue_link |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| keyword | `international_transaction_not_allowed` | ambiguous | 0.350 | escalate |
| keyword | `international_transaction_not_allowed` | ambiguous | 0.350 | escalate |
| keyword | `international_transaction_not_allowed` | ambiguous | 0.350 | escalate |
| keyword | `payment_cancelled` | customer_abandoned | 0.750 | issue_link |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| jev | `international_transaction_not_allowed` | international_transaction_not_allowed | 1.000 | issue_link |
| jev | `international_transaction_not_allowed` | international_transaction_not_allowed | 1.000 | issue_link |
| jev | `international_transaction_not_allowed` | international_transaction_not_allowed | 1.000 | issue_link |
| jev | `payment_cancelled` | ambiguous | 0.940 | escalate |
| jev | `payment_failed` | ambiguous | 0.960 | escalate |
| jev | `payment_failed` | ambiguous | 0.700 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| gemini | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.990 | issue_link |
| gemini | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.990 | issue_link |
| gemini | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.990 | issue_link |
| gemini | `payment_cancelled` | ambiguous | 0.900 | escalate |
| gemini | `payment_failed` | ambiguous | 0.450 | escalate |
| gemini | `payment_failed` | ambiguous | 0.800 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |
| gemini | `payment_failed` | ambiguous | 0.600 | escalate |

## 4. Expected-verdict matrix

| raw_reason | expected verdict |
|---|---|
| `insufficient_fund` | issue_link |
| `international_transaction_not_allowed` | issue_link |
| `authentication_failed` | issue_link |
| `payment_timed_out` | wait |
| `gateway_technical_error` | wait |
| `card_declined` | escalate |
| `card_disabled_for_online_payments` | escalate |
| `card_number_invalid` | escalate |
| `payment_cancelled` | issue_link |

## 5. Reason-masked

`error_reason` blanked before diagnosis. Rules arm is all-`ambiguous` by construction.

| arm | n | accuracy | 95% CI |
|---|---|---|---|
| rules | 21 | 57.14% | [36.55%, 75.53%] |
| keyword | 21 | 57.14% | [36.55%, 75.53%] |
| jev | 21 | 57.14% | [36.55%, 75.53%] |
| gemini | 21 | 57.14% | [36.55%, 75.53%] |

### Reason-masked per-`raw_reason`

| arm | raw_reason | predicted | confidence | policy_verdict |
|---|---|---|---|---|
| rules | `international_transaction_not_allowed` | ambiguous | 0.450 | escalate |
| rules | `international_transaction_not_allowed` | ambiguous | 0.450 | escalate |
| rules | `international_transaction_not_allowed` | ambiguous | 0.450 | escalate |
| rules | `payment_cancelled` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| rules | `payment_failed` | ambiguous | 0.450 | escalate |
| keyword | `international_transaction_not_allowed` | ambiguous | 0.350 | escalate |
| keyword | `international_transaction_not_allowed` | ambiguous | 0.350 | escalate |
| keyword | `international_transaction_not_allowed` | ambiguous | 0.350 | escalate |
| keyword | `payment_cancelled` | customer_abandoned | 0.750 | issue_link |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| keyword | `payment_failed` | ambiguous | 0.350 | escalate |
| jev | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.990 | issue_link |
| jev | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.990 | issue_link |
| jev | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.980 | issue_link |
| jev | `payment_cancelled` | ambiguous | 0.910 | escalate |
| jev | `payment_failed` | ambiguous | 0.950 | escalate |
| jev | `payment_failed` | ambiguous | 0.430 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| jev | `payment_failed` | ambiguous | 1.000 | escalate |
| gemini | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.950 | issue_link |
| gemini | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.950 | issue_link |
| gemini | `international_transaction_not_allowed` | international_transaction_not_allowed | 0.950 | issue_link |
| gemini | `payment_cancelled` | ambiguous | 0.700 | escalate |
| gemini | `payment_failed` | ambiguous | 0.450 | escalate |
| gemini | `payment_failed` | ambiguous | 0.800 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.500 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |
| gemini | `payment_failed` | ambiguous | 0.400 | escalate |

## Limitations (verbatim framing)

- Not a large labeled benchmark; test-mode strings lack paraphrase diversity.
- Real-cohort numbers must never appear in the synthetic headline table.
- Derived labels never count toward accuracy.


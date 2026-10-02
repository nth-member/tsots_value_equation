# Shula simulation results

Synthetic scenarios, not validation for deployment. Thresholds and assumptions are saved per run.

| Run | Price | Supply | Fabrication | Calibration | Handover | Selflessness | Ledger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_seed0 | FAIL | FAIL | PASS | FAIL | FAIL | PASS | PASS |
| A_seed1 | FAIL | FAIL | PASS | PASS | FAIL | PASS | PASS |
| A_seed2 | FAIL | FAIL | PASS | PASS | FAIL | PASS | PASS |
| B_seed0 | FAIL | PASS | PASS | FAIL | FAIL | PASS | PASS |
| B_seed1 | FAIL | PASS | PASS | PASS | FAIL | PASS | PASS |
| B_seed2 | FAIL | PASS | PASS | PASS | FAIL | PASS | PASS |

## Measured values

Supply multiples are relative to the first positive supply. Prices are Shula per reference basket.

| Run | Observed price range | Maximum supply multiple | Final agent weight | Person-classification error |
| --- | --- | --- | --- | --- |
| A_seed0 | 0.04372 to 278.7 | 1.017e+04 | 0.4 | 0.08032 |
| A_seed1 | 0.04634 to 255.1 | 1.037e+04 | 0.3 | 0.08537 |
| A_seed2 | 0.05614 to 319.9 | 1.133e+04 | 0.45 | 0.0787 |
| B_seed0 | 0.04372 to 42.62 | 696 | 0.4 | 0.08032 |
| B_seed1 | 0.05215 to 36.25 | 689 | 0.3 | 0.08537 |
| B_seed2 | 0.06204 to 52.44 | 829.1 | 0.45 | 0.0787 |

### Equation residuals and accounting

| Run | Maximum absolute equation residual | Constrained epochs | Maximum balance reconciliation error |
| --- | --- | --- | --- |
| A_seed0 | 1.676e+05 | 196 | 2.328e-10 |
| A_seed1 | 1.282e+05 | 197 | 3.492e-10 |
| A_seed2 | 1.461e+05 | 199 | 2.328e-10 |
| B_seed0 | 2,942 | 175 | 4.366e-11 |
| B_seed1 | 2,155 | 182 | 2.91e-11 |
| B_seed2 | 3,394 | 181 | 5.821e-11 |

## Interpretation

- PASS applies only to the declared synthetic criterion and settings.
- FAIL is retained; parameters were not tuned to erase it.
- NOT_EVALUATED means missing evidence or an undeclared threshold, not success.
- Caps usually leave an equation residual; no acceptance bound for it is assumed.
- Prices come from a one-basket proportional auction, an explicit modeling assumption.
- Supply PASS uses the configured growth/collapse bounds; inspect the multiples above before interpreting it as stability.
- Fabrication PASS concerns gross minted rewards under matched modeled resources; full economic profit is not evaluated.
- Paired runs share keyed exogenous draws. This is not a completed parameter/behavior search.
- Replay reconstructs the modeled population, acts, monetary ledger and learner state.

## Files

Each run has config.json, epochs.csv, cohorts.csv, summary.json, final_state.json.gz and gazette.jsonl.gz.
Paired honest-service runs are in the matching `_honest` directory.

See ../SIMULATION_README.md for assumptions and rerun commands.

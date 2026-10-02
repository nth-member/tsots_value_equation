# Running the corrected Shula simulation

`shula_simulation.py` now implements the three-page `simulation_flowchart_corrected.pdf`, including its explicitly proposed policies A1–A6. It is a reproducible synthetic model with an auditable ledger. Successful execution and accounting tests do not establish that its economic mechanism works in practice.

The original script is retained as `shula_simulation_original.py`. The working implementation uses Python's standard library only: Python 3.10 or later is sufficient, with no NumPy, pandas or test-framework installation required. The original specification proposes a future Clojure implementation; this change repairs the existing Python prototype and does not implement that separate port.

## Run it

From this directory:

```bash
python3 -m unittest -v test_shula_simulation
python3 shula_simulation.py --variant both --epochs 200 --population 100 --seeds 0,1,2 --compare-honest --output simulation_results
```

The second command executes six main scenarios and six matched honest-service reference scenarios. Each has 200 epochs of 30 days, representing 6,000 simulated days. Seeds are reproducible and separate from the price-conversion variant. The reference keeps each ring participant's identity, effort opportunities, outside resources and exogenous streams while replacing fabricated service with sincere service.

For a quick run in a different output directory:

```bash
python3 shula_simulation.py --epochs 10 --population 12 --output /tmp/shula_quick
```

Short runs deliberately do not pass criteria for which the observation window is insufficient.

To change model assumptions, place Config fields in a JSON file and use `--config path/to/settings.json`. Omitted fields retain the defaults declared in the `Config` dataclass. CLI arguments for epochs, population, seeds and variant override the file. Each run saves its complete effective configuration. Use a new output directory to preserve prior experiments; reusing one replaces the files for the same run names.

Python API:

```python
from shula_simulation import Config, ShulaSimulation

result = ShulaSimulation(Config(seed=4, num_epochs=200)).run()
print(result.criteria)
print(result.rows[-1])
```

The old keyword construction style also works, for example `ShulaSimulation(population_size=30, variant='B', num_epochs=200)`. The repaired `run()` returns a `Result`, with rows, criteria, cohorts, events, config and final_state. It does not return the old, nonfunctional pandas tuple. Instantiate a new simulation for each run.

## Outputs

Start with `simulation_results/report.md` and `comparison.json`. For each `A_seed0`, `B_seed0`, etc.:

| File | What it contains |
| --- | --- |
| `config.json` | All model inputs and thresholds actually used |
| `epochs.csv` | Opening/closing supply, measured/fallback P and V, product changes, issuance requests/caps/actual amounts, residuals, balances, queues, indices, handover and calibration |
| `cohorts.csv` | Each observation epoch's person-level judgments as resolved by the end of the run, with truth and coverage |
| `summary.json` | PASS, FAIL or NOT_EVALUATED, measurements and the criterion's meaning |
| `gazette.jsonl.gz` | Ordered initial state, activity, acts, judgments, review outcomes, claims, transfers, mints, demurrage, outcomes, learning state and epoch closes |
| `final_state.json.gz` | Compressed final population, acts, ledger, assessment history and learner/control state |

Matching `_honest` directories contain the full counterfactual run, not just a fabricated comparison number. Gazette files are compressed because per-act evidence and transaction records are materially larger than the epoch CSV.

Every full run independently replays its gazette and compares the reconstructed state to the live state. Monetary balances are reconstructed from claims, payments, mint allocations and demurrage; they are not overwritten with a saved balance at each epoch. Floating-point amounts use explicit reconciliation tolerances. These simulation balances are not an integer token-contract implementation.

Replay a saved run:

```python
import gzip
import json
from pathlib import Path
from shula_simulation import replay_gazette, assert_same_state

run = Path('simulation_results/A_seed0')
with gzip.open(run / 'gazette.jsonl.gz', 'rt') as stream:
    events = [json.loads(line) for line in stream]
restored = replay_gazette(events)
with gzip.open(run / 'final_state.json.gz', 'rt') as stream:
    assert_same_state(json.load(stream), restored)
```

## Mapping the corrections to executable behavior

| Diagram requirement | Implementation |
| --- | --- |
| Genesis exception | Separate positive `genesis_cap`; first-mint flag clears only on actual positive issuance |
| No same-epoch held-act approval | Frozen worklist, stable IDs, retry dates and explicit review outcomes; original observation epoch preserved |
| Own-party recusal | Person 0 represents the interim judge; that person's acts await full takeover |
| No empty community median | Use the nth-member alone and log absent community evidence; an existing review hold still requires resolution |
| Recognition distinct from payment | Recognition only creates a synthetic commitment; only mint settlement credits `shula_accrued` |
| Claims use minted supply | Prior unclaimed amounts move to claimed balances before exchange; current mint cannot be claimed until a later epoch |
| Defined claim limit | Config records scope: per-person-per-epoch, per-person lifetime, or aggregate phase amount; `max_claimants` is a separate participant cap |
| Consistent A/B conversion | Both service basket values and output use P_t for A or P_0 for B |
| Product differences | Uses W_t − W_(t−1) and V_t − V_(t−1), not output level or a fixed invented velocity increment |
| No-service positive request | Suppress positive issuance when R=0 and report the residual |
| Reconciled mint/demurrage | Mint pro rata to actual eligible closures; demur claimed and unclaimed balances uniformly |
| Equation audit | Record unconstrained, bounded and actual changes plus residual and identity error |
| Measured handover | N-epoch motive/value agreement, minimum sample size, bounded weight and one-step rollback/pause |
| Ground truth separate from judgment | Judge consumes noisy evidence; hidden truth is used to simulate observations and evaluate delayed outcomes |
| Meaningful index | Classifies persons in their original observation cohorts; logs unresolved coverage and lower/upper bounds |
| Honest acceptance reporting | Inadequate observations or undeclared residual tolerance produce NOT_EVALUATED |

## Explicit behavioral assumptions

The corrected flowchart is more specific about bookkeeping than about economic or social behavior. The implementation makes the following additional assumptions. They are scenario definitions, not empirical findings.

### People, output and outside money

People start with independent beta(2,2) selflessness propensities, which drift with small bounded Gaussian perturbations. Each person has one service opportunity per epoch. Honest service has a uniform 2–10 basket-unit effort opportunity; motive is a Bernoulli draw from that person's propensity. A fabrication attempt has no actual service output and claims two to four times the same effort opportunity. Ring behavior represents self-serving attestation even before discovery; discovery controls eligibility to claim, value and trade.

A configured share of people also bring outside money. Each spends a synthetic 1–10 outside-money units directly on works per epoch. For this scenario, sqrt(spend) is the basket-unit service proxy, 0.1 times the spending adds productive capital, and capital depreciates by 2% per epoch. These conversion/productivity assumptions need calibration before interpreting outside-money scenarios. No outside money is exchanged for Shula or held in the currency ledger.

Each person acts as a small going concern. Exergetic efficiency is fixed in [0.5,1]; current output is efficiency times genuine service quantity plus capital-derived production. Actual motive and physical output are separate: useful output can occur without a selfless motive. Default `O0=0` starts the model with no previous output; use another explicit baseline for an established community.

### Evidence, community, review and learning

Observable value evidence has a declared bias and noise. Motive evidence is a noisy score centered near 0.85 or 0.15. Fabricators successfully forge favorable evidence with probability 0.35 in this illustrative scenario. All randomness is keyed by seed, channel, epoch and/or actor/act identity so paired scenarios preserve comparable exogenous draws.

The human and shadow agent consume this evidence with independent noise. The human/agent value blend uses the opening handover weight; a corresponding blended motive score at least 0.5 qualifies the act as selfless. Up to `community_sample` existing claimants other than the actor provide estimates. Ring peers inflate a fabricated act's community estimate; other peers give noisy evidence-based estimates. The actual sample and its median are logged.

Unresolved divergence requires delayed review, within the separate review and total judgment capacities. A review can remain pending or use a new noisy verification signal to approve or reject. A review resolution can override prior conflicting estimates and is explicitly recorded. Recusal, capacity and unresolved disagreement are distinct reasons to wait. No reviewer or judge uses perfect truth as its direct judgment; the simulator generates noisy review signals from the underlying synthetic truth.

Ground truth outcomes arrive after `outcome_delay` epochs. The agent learns global value and motive bias corrections from those outcomes with a declared learning rate. Evaluation retains each prediction made before its outcome arrived. Calibration is not a random “agreement” number or an error curve forced to improve. This is a small bias-learning model, not the trained nth-member proposed in the full specification.

Full handover releases recused acts only in the next epoch. Once complete, human agreement is no longer used; delayed outcome calibration continues. The model reports poor outcomes but does not invent a new authority for replacing an agent after takeover.

### Discovery, claims and the market

Recognized people discover the currency with the configured probability after phase two opens. Synthetic identity proof succeeds for the matching commitment. `claim_limit_scope='per_person_per_epoch'` is the declared default; lifetime and phase-total limits are available. Limit scope is always saved in config, never inferred from an unlabeled number. A claimant cap, if present, limits entry separately.

Commitments and identity proof are simulation placeholders, not cryptographic privacy or zero-knowledge implementations. Event logs contain synthetic ground truth on purpose; they are not a production public ledger design.

For market exchange, randomly partition claimants into disjoint buyers and sellers for each epoch. Buyers offer 10–40% of their balances; sellers offer their current output of a single reference basket. The proportional clearing price is total offered Shula divided by available seller baskets. Payments debit buyers and credit sellers; price and filtered volume are calculated from the executed transfers. This market can fail the price-stability criterion.

The disjoint partition prevents same-epoch return cycles in ordinary generated exchange. The standalone volume filter also rejects self-transfers and all edges in a directed return cycle. That graph rule is conservative: it is not proof that a particular monetary unit returned to its sender. No other transaction fees, credit, speculative demand, multi-good price index or off-chain sale are modeled.

In phase one P=P0 and V=V_min by convention. After claims open, missing price observations carry the previous price with a stale flag. Raw velocity divides eligible exchange volume by opening total supply, including unclaimed holdings; it is undefined at zero supply. Effective velocity applies the explicit floor. Default V_min=0.1 is an illustrative model setting, not an estimated parameter.

## Acceptance criteria and limits

Defaults are declared before running: price band [0.5,2], at least ten observed-price epochs and 50% phase-two coverage; at least 200 funded epochs; maximum supply at most 1,000 times the first positive supply and no subsequent value below 0.01 times that supply; at most 10% classification error with at least 95% finalized judgment coverage; calibration comparison needs at least 30 observations in both its early and late blocks. These are demonstration thresholds, not justified deployment standards.

Supply is checked throughout the funded interval. An observed violation fails even in a short run; a short run within bounds cannot pass the long-horizon criterion. Handover without sufficient time or measured comparisons is not evaluated. Index accuracy compares the same persons and observation periods, including delayed closure; the epoch CSV retains provisional indices while the cohort CSV records the final available resolution.

Fabrication is compared with the same cohort performing sincere service using the same opportunities. The criterion concerns gross minted rewards under equal modeled resources. It does not measure full economic profit, preferences, opportunity costs, or a strategy equilibrium. A low fraction of total issuance captured by rings is not treated as proof of unprofitability.

Caps generally break exact equality in the value equation. The residual is exported, with no automatic issuance debt. `residual_limit=None` leaves its acceptance criterion NOT_EVALUATED until a meaningful threshold is declared.

Passing a first-versus-last calibration comparison is descriptive; no statistical significance or causal benefit of training is claimed. Larger populations, more seeds, multiple epoch lengths/kappa values, behavioral sensitivity and externally grounded calibration remain necessary before choosing an economic design. The A/B comparison does not automatically select a winning variant.

## Regression coverage

The standard-library test suite covers genesis, source-example arithmetic, zero-service guards, exact supply reconciliation, proportional minting, claim timing and budgets, demurrage, both price variants, duplicate settlement/closure, empty community valuation, persistent review holds, recusal, capacity, value caps, observation cohorts, market transactions, return-cycle filtering, measured handover and rollback, delayed learning, seeded repeatability, saved-file replay, tampered logs, invalid input, and insufficient evidence.

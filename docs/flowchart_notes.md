# Corrected Shula simulation flowchart

Prepared 2 October 2026. Read alongside `simulation_flowchart_corrected.pdf` (three pages) and the original `tsots_value_equation.tex`.

The corrected diagram is a reviewable simulation design. It fixes the control flow and accounting while identifying proposed policies where the original specification does not settle an edge case. It does not establish economic viability or replace the original specification. The subsequent Python implementation, its assumptions and its regression checks are documented in `SIMULATION_README.md`; scenario results are in `simulation_results/report.md`. The original script is preserved as `shula_simulation_original.py`.

## Files and page order

- `simulation_flowchart_corrected.pdf`: epoch lifecycle; per-act judgment; issuance and settlement.
- `simulation_flowchart_corrected.tex`: editable diagram source.
- `simulation_flowchart_correction_notes.md`: this explanation, policy choices and verification notes.

The original `simulation_flowchart.tex` and `.pdf` are preserved.

## Corrections supported by the original specification

| Issue in the original diagram | Correction | Original specification location |
| --- | --- | --- |
| Starting at zero and always applying a supply-relative cap prevents any first mint | Add the separate genesis cap and keep the first-mint flag pending until positive issuance actually occurs | Issuance Rule / Bounds |
| Held acts rejoin current-epoch recognition | Store a pending act with its original ID and reason; revisit no earlier than a subsequent epoch; exclude it from current closed values | Valuation / Safeguards; Interim nth-member / Capacity |
| Recusal is mentioned but has no operational consequence | Author-party acts remain pending until full agent takeover | Interim nth-member / Recusal and After handover |
| Recognition appears to credit Shula before issuance is calculated | Recognition creates or reuses a commitment; only actual mint settlement credits its balance | Recognition; Issuance Rule / Distribution |
| Variants A/B appear only in the output calculation | Apply the price convention to both basket valuations and output | Valuation of Service / Unit of valuation |
| Opening and closing values are mixed or unspecified | Use previous closing supply as the opening supply; explicitly calculate differences and update the ledger | Measuring the Terms / Supply; Issuance Rule / Derivation |
| Demurrage and unclaimed balances are underspecified | Reconcile claimed plus unclaimed supply; demur both classes uniformly | Issuance Rule / Withdrawal; Recognition / Unclaimed Shula |
| Clipped issuance is described as if it still exactly satisfies the equation | Record both the unconstrained request and the residual after caps/guards | Issuance Rule / Derivation and Bounds |
| Handover omits the comparison window and failed-agreement behavior | Use N epochs, motive agreement and relative value tolerance; cap the agent weight at one; show pause/reversion | Interim nth-member / Handover |
| Price and accuracy tests could pass without relevant observations | Separate phase-one conventions from actual phase-two observations; restore calibration and comparative fabrication tests | Simulation Before Deployment / Acceptance criteria; Proving the Shula / Two phases |

## Epoch accounting used in the corrected diagram

Epochs are numbered from 1. Subscript 0 denotes the initialized state. Supply changes occur once, at the close of an epoch. Claims and exchanges earlier in that epoch do not change total supply.

- `M_(t-1)`: opening supply, equal to the previous epoch's close.
- `M_t`: supply after the current settlement.
- `U_i`: previously minted, unclaimed Shula held against person i's commitment.
- `C_i`: claimed Shula in person i's spendable balance.
- `P_t`, `V_t`: price and velocity measured from the current epoch's exchanges, subject to the explicit fallbacks below.
- `O_t`: current epoch's attested, exergetic-weighted output, not a cumulative total substituted for its difference.
- `p*_t`: `P_t` for variant A, or the fixed `P_0` for variant B.
- `W_t = p*_t O_t`; `delta W_t = W_t - W_(t-1)`.
- `b_j`: approved final basket valuation; `v_j = p*_t b_j` for acts closing now.
- `R_t`: sum of eligible values of acts actually closed in this epoch, including older held acts resolved now. Do not count any act twice.

Initialize `O_0` from the chosen scenario; zero is appropriate only for a scenario starting with no prior output. Initialize `W_0 = P_0 O_0`, `V_0 = V_min`, and `M_0 = 0`.

The consistently indexed equation is:

```text
delta V_t = V_t - V_(t-1)
M_t = M_(t-1) + delta M_t
M_t V_t - M_(t-1) V_(t-1) - delta W_t = R_t

unconstrained request:
x_t = [R_t + delta W_t - M_(t-1) delta V_t] / V_t
```

This is the same finite-product algebra as the source, with the previous state and updated state named consistently. It is not a replacement economic equation. Its denominator is current `V_t`, which equals `V_(t-1) + delta V_t`.

For the source's numerical example, interpret 1,000,000 and 1.20 as the opening supply and previous velocity; the current velocity is 1.22. With `R_t = 20,000` and `delta W_t = 6,000`, the request remains `6,000/1.22 = 4,918.032786...` Shula.

After caps and guards, audit:

```text
e_t = M_t V_t - M_(t-1) V_(t-1) - delta W_t - R_t
    = V_t (delta M_t - x_t)
```

The residual is zero when the requested change is applied exactly. Do not claim exact equality when a bound or guard changes that request. Do not silently carry the residual forward as an entitlement to mint later.

## Proposed simulation policies (not already settled by the specification)

These choices make the corrected diagram determinate without presenting additions as existing requirements. They should be varied in sensitivity runs where relevant.

### A1. No community estimates

When the set of eligible claimant estimates is empty, use the nth-member basket valuation alone: `b_j = b_j^n`. Record `community_available = false`, and do not evaluate a new community divergence test for that act. An already pending review hold still needs an explicit resolution; loss of community participation cannot clear it. Do not substitute zero for an empty median or describe the fallback as a 90/10 community valuation.

When estimates exist, use the specified median and 90/10 weights. For nonnegative estimates the relative divergence test can be evaluated without division:

```text
abs(b_nth - b_community) > delta * max(b_nth, b_community)
```

Two zero estimates do not trigger divergence. A common positive conversion price means this basket-unit comparison is equivalent to the comparison in Shula. The availability and participation of community valuers must be recorded; a median alone is not proof of resistance to collusion or Sybil identities.

### A2. Claims precede settlement and use existing minted balances

At the claim stage, verified claimants can claim only amounts already in `U_i`, within the configured phase limit. Move the amount from `U_i` to `C_i`; total supply is unchanged. An existing claimant can claim later accruals, but no claimant receives a credit merely because an act was recognized or valued.

All positive current-epoch mint allocations enter `U_i` at the close and become claimable in a subsequent epoch. This introduces an explicit one-epoch settlement delay. It avoids using this epoch's still-unknown issuance to fund the exchanges used to measure this epoch's price and velocity.

The original phrase “claim limit” does not specify whether it limits people, amounts, periods, or an aggregate phase budget. Treat its unit and scope as required run settings, enforce that declared scope, and record the counters. Do not silently assume a fresh allowance per person every epoch.

### A3. Positive issuance with zero eligible service

If capped candidate issuance is positive but `R_t = 0`, issue zero and record the suppressed amount and resulting residual. There are no eligible pro-rata recipients. This prioritizes the rule that Shula is created only against service. It does not invent a treasury recipient or carry the amount into a later mint.

Negative issuance may still cause demurrage when `R_t = 0`, provided there is positive opening supply. Genesis bounds are `[0, G]`; ordinary bounds are `[-kappa M_(t-1), +kappa M_(t-1)]` with `0 < kappa < 1`. The first-mint flag clears only after a positive amount is actually minted; it is not a recurring permission to recapitalize a failed currency.

### A4. Empty markets and measurement flags

In phase one, retain the specified conventions `P_t = P_0` and `V_t = V_min`.

In phase two, compute filtered transfer volume `Q_t` from actual simulated exchanges, excluding self-transfers and within-epoch return transfers. Claims from a holding commitment to its owner are releases of existing funds, not purchases or service exchange volume.

Supply is constant during the open trading interval in this design, so the mean supply over that interval is `M_(t-1)`. End-of-epoch issuance takes effect after the interval:

```text
if M_(t-1) > 0:
    V_t = max(Q_t / M_(t-1), V_min)
else:
    require Q_t == 0
    V_t = V_min
```

Record raw volume, raw velocity where defined, and whether the floor was applied. The denominator includes all outstanding supply, including unclaimed Shula; only actual eligible circulation contributes to the numerator.

If there are no valid basket-price observations, carry forward the last price, initially `P_0`, and flag it as stale. This fallback is an accounting input, not evidence that the market price is stable. The basket, aggregation method, minimum observation coverage and stale-data rule must be declared before running the model. Price acceptance requires sufficient actual phase-two observations; otherwise report “not evaluated.”

### A5. Handover details and empty windows

Freeze `lambda_(t-1)` for all judgments within an epoch. At its close, use comparable human/agent judgments from the last N completed epochs. Count an agreement only when the motive classifications match and the nonnegative basket values satisfy:

```text
abs(b_human - b_agent) <= delta_a * max(b_human, b_agent)
```

Require a complete N-epoch window and at least one comparable act. If the window is incomplete or empty, pause without increasing the agent's weight. Record the sample size; runs should declare a stronger minimum if one comparison is insufficient.

For qualifying agreement, increase the next epoch's weight by `delta_lambda`, capped at 1. To make “return to the previous level and pause” explicit, retain the weight before the latest increase. On a failed assessment, roll back that increase once and pause; continued failure while paused does not repeatedly decrement the weight. A later qualifying assessment resumes the increments. This is a proposed interpretation of the original rollback wording.

Once full takeover has been accepted, use the agent alone, unlock eligible author-party acts in the next epoch, and measure calibration against later outcomes. Human/agent agreement is then no longer the acceptance proxy. Report outcome-based failure; the original specification does not define an automatic post-takeover replacement authority.

### A6. Act closure, unresolved review, index coverage and evaluation

Freeze the epoch worklist so that an act held during this epoch cannot re-enter judgment immediately. Use a stable ordering that preserves older queued acts while skipping those whose retry date has not arrived or that remain ineligible through recusal. Process an ID at most once per epoch and close it at most once overall. Record original observation epoch and eventual closure epoch separately.

Record motive judgments as well as numerical estimates. For this proposed design, acts judged not to be freely offered service receive zero eligible issuance value. This selects the “nothing” alternative in the specification's “low or at nothing” wording. A model permitting small positive values for non-selfless acts would need a separate eligibility and recipient policy.

A review must produce an explicit result: revised evidence/estimates, approval with recorded resolution, rejection, or continued hold. An unresolved threshold breach stays pending. A recorded approval resolution can settle an earlier disagreement even if the original estimates remain different; it must not be fabricated solely to empty the queue. The review error/latency model and capacity are declared scenario inputs. Per-act and per-actor caps are applied to final eligible values, in a declared unit and stable allocation order, before conversion and issuance.

The selflessness index counts persons, not acts. Retain the original denominator: people whose acts were observed in the relevant observation epoch. Do not include someone only because an older act happens to close now. Compare judged classifications with simulator truth for the same people and observation period. True `s_i` is an evaluation reference, not a replacement for the judged index.

When observations remain unjudged, report judgment coverage and a provisional index. An unresolved person is not evidence of selfishness. A useful uncertainty interval is:

```text
lower = confirmed-selfless persons / observed persons
upper = (confirmed-selfless persons + unresolved persons not already confirmed) / observed persons
```

Use the lower bound for a confirmed crossing above one half; otherwise the crossing can be unresolved. With no observed people, the index is undefined. Retain each observation cohort for later finalized comparisons; cross-population claims also require adequate observational coverage. The projected `Y_s = 36.68` is a comparison, never a trigger forcing a crossing.

Record ring capture from actual mint allocations, not merely claimed values. If no Shula is minted in an epoch, that epoch's mint-share statistic is undefined; aggregate over actual minted amounts. Compare ring participants' earnings with matched honest-service runs using comparable effort/resources and seeds. A small absolute ring share alone does not establish unprofitability.

Define calibration error against matched simulated motives/values and report it separately from agreement with the interim judge. If declining error is imposed as an input schedule, its decline is not independent evidence that learning succeeded. Training rules, market behavior, discovery rates, outside-money effects, ring strategies and error models still require explicit implementation and validation.

## Gazette and acceptance outputs

Persist event records as well as the epoch CSV: act IDs, evidence, judgments, review outcomes, caps, commitments, claims, transfers, prices, output attestations, mint allocations, demurrage and handover decisions. This is necessary to reconstruct the state; a row of aggregate statistics alone is insufficient.

The epoch report should contain opening and closing supply; P/V and their observation flags; output and both product levels; R; requested, capped and actual issuance; equation residual; claimed/unclaimed totals; mint capture; queued counts by reason; judged index, truth comparator and coverage; agreement sample size; calibration error; handover weight; and the seed/settings identifier.

Acceptance thresholds must be fixed before inspecting results. In particular:

- Test price stability on observed phase-two prices with adequate coverage.
- Test supply growth and collapse over a declared long horizon; a nonnegative final balance alone is insufficient.
- Compare fabrication with matched honest-service earnings.
- Evaluate calibration separately from handover agreement.
- Evaluate judged selflessness against matched ground truth, accounting for unresolved judgments and observation coverage.
- Reject any run with ledger reconciliation errors, negative balances, duplicate closures, or credits unsupported by actual issuance.
- Report residual magnitude/frequency under the clipping policy. The owner must define acceptable residual behavior; exact equality cannot be an unconditional pass criterion while binding caps are allowed.
- Compare seeds and parameter combinations before selecting variant A/B, epoch length and kappa.
- Report missing evidence as “not evaluated”; do not turn undefined statistics into passes.

## Verification

Targeted arithmetic checks passed using exact rational arithmetic:

- Reproduced the source's `4,918.032786885...` Shula issuance example and its zero unconstrained residual.
- Checked 243 combinations of opening supply, previous/current velocity, eligible service and output change. The unconstrained product identity and capped residual identity held; capped supply remained nonnegative.
- Verified positive first issuance from zero supply under a separate genesis cap.
- Verified supply conservation through a claim and reconciliation after demurrage on both claimed and unclaimed balances.
- Verified that pro-rata allocations sum to the actual mint.

These checks covered the diagram's accounting before the implementation was revised. The executable regression suite and scenario results for the subsequent implementation are documented separately in `SIMULATION_README.md` and `simulation_results/report.md`.

The final source compiled twice with `pdflatex -interaction=nonstopmode -halt-on-error`. The result is three A4 pages, with no overfull/underfull box warnings, font warnings or outstanding rerun warnings. All three pages were rendered and visually inspected; the revised judgment and issuance pages were inspected again after the final routing edits. Decision branches stay outside unrelated boxes and deferred returns do not connect to approval in the same epoch.

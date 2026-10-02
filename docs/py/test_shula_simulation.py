"""Regression tests for the corrected flowchart's failure cases and invariants."""
import copy
import gzip
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from shula_simulation import (
    Act, Config, ShulaSimulation, assert_same_state, bounded_issuance,
    compare_honest, filtered_transfers, issuance_request, replay_gazette,
)


def simulation(**overrides):
    settings = dict(population_size=4, num_epochs=8, bringer_share=0,
                    fabricator_share=0, human_noise=0, agent_noise=0,
                    review_noise=0, review_resolution_rate=1,
                    discovery_probability=1)
    settings.update(overrides)
    sim = ShulaSimulation(Config(**settings))
    sim.ledger.epoch = 1
    return sim


def act(sim, identity=1, person=1, **overrides):
    fields = dict(act_id=identity, person_id=person, observed_epoch=sim.ledger.epoch,
                  true_value=4.0, true_selfless=True, claimed_value=4.0,
                  evidence_value=4.0, evidence_motive=0.9, effort=4.0)
    fields.update(overrides)
    item = Act(**fields)
    sim.add_act(item)
    return item


class AccountingTests(unittest.TestCase):
    def test_source_worked_example_and_product_identity(self):
        request = issuance_request(1_000_000, 1.2, 1.22, 20_000, 6_000)
        self.assertAlmostEqual(request, 6000/1.22, places=8)
        self.assertAlmostEqual((1_000_000+request)*1.22-1_000_000*1.2-6000, 20_000)

    def test_genesis_credits_actual_mint_proportionally(self):
        sim = simulation(genesis_cap=10, V_min=1)
        a = act(sim, identity=1, evidence_value=2)
        b = act(sim, identity=2, person=2, evidence_value=6)
        approved = sim.judge_acts([a, b])
        self.assertEqual(sim.people[1].shula_accrued, 0)
        self.assertIsNotNone(sim.people[1].commitment)
        row = sim.settle(approved, 10, 1, 0)
        self.assertEqual(row['dM'], 10)
        self.assertEqual(sim.people[1].shula_accrued, 2.5)
        self.assertEqual(sim.people[2].shula_accrued, 7.5)
        self.assertFalse(sim.ledger.genesis_pending)
        self.assertEqual(row['equation_residual'], -8)

    def test_no_service_prevents_positive_mint_and_keeps_genesis_pending(self):
        sim = simulation(V_min=1)
        row = sim.settle([], 10, 1, 0)
        self.assertGreater(row['requested_dM'], 0)
        self.assertEqual(row['dM'], 0)
        self.assertTrue(sim.ledger.genesis_pending)
        self.assertTrue(row['no_service_guard'])

    def test_regular_cap_and_zero_service_guard(self):
        self.assertEqual(bounded_issuance(200, 100, 10, False, 50, 0.05), (5, 5))
        self.assertEqual(bounded_issuance(200, 100, 0, False, 50, 0.05), (5, 0))
        self.assertEqual(bounded_issuance(-200, 100, 0, False, 50, 0.05), (-5, -5))

    def test_demurrage_includes_unclaimed_balances(self):
        sim = simulation(V_min=1, kappa=0.5)
        sim.ledger.M, sim.ledger.genesis_pending = 100, False
        sim.people[0].shula_accrued, sim.people[1].balance = 60, 40
        row = sim.settle([], 0, 1, 20)
        self.assertEqual(row['dM'], -20)
        self.assertEqual(sim.people[0].shula_accrued, 48)
        self.assertEqual(sim.people[1].balance, 32)
        self.assertEqual(sim.ledger.M, 80)

    def test_both_price_variants_convert_service_and_output(self):
        for variant, expected in [('A', 3), ('B', 1)]:
            with self.subTest(variant=variant):
                sim = simulation(variant=variant)
                sim.ledger.P = 3
                a = act(sim)
                approved = sim.judge_acts([a])
                row = sim.settle(approved, 5, sim.ledger.V, 2)
                self.assertEqual(row['R'], 4*expected)
                self.assertEqual(row['W'], 5*expected)
                self.assertEqual(row['dW'], 5*expected-2)

    def test_duplicate_settlement_is_rejected(self):
        sim = simulation()
        a = act(sim)
        approved = sim.judge_acts([a])
        sim.settle(approved, 5, sim.ledger.V, 0)
        with self.assertRaises(AssertionError):
            sim.settle(approved, 5, sim.ledger.V, 0)

    def test_claims_transfer_existing_supply_and_respect_phase(self):
        sim = simulation(claim_limit=7)
        p = sim.people[1]
        p.commitment, p.shula_accrued = 'synthetic', 20
        sim.ledger.M = 20
        self.assertEqual(sim.claim(), 0)
        sim.ledger.Z = sim.config.phase_two_date
        self.assertEqual(sim.claim(), 7)
        self.assertEqual((p.shula_accrued, p.balance, sim.ledger.M), (13, 7, 20))
        sim.assert_balances()

    def test_lifetime_and_phase_total_claim_limits_do_not_reset(self):
        for scope in ('per_person_lifetime', 'phase_total'):
            with self.subTest(scope=scope):
                sim = simulation(claim_limit=7, claim_limit_scope=scope)
                sim.ledger.Z = sim.config.phase_two_date
                p = sim.people[1]
                p.commitment, p.shula_accrued = 'synthetic', 20
                sim.ledger.M = 20
                self.assertEqual(sim.claim(), 7)
                sim.ledger.epoch += 1
                self.assertEqual(sim.claim(), 0)

    def test_phase_total_budget_is_shared_by_people(self):
        sim = simulation(claim_limit=7, claim_limit_scope='phase_total')
        sim.ledger.Z = sim.config.phase_two_date
        for p in sim.people:
            p.commitment, p.shula_accrued = str(p.person_id), 10
        sim.ledger.M = 40
        self.assertEqual(sim.claim(), 7)
        self.assertEqual(sum(p.total_claimed for p in sim.people), 7)
        sim.assert_balances()


class JudgmentTests(unittest.TestCase):
    def test_empty_community_has_explicit_fallback(self):
        sim = simulation()
        a = act(sim)
        approved = sim.judge_acts([a])
        self.assertEqual(approved, [a])
        self.assertIsNone(sim.assessments[0]['community_median'])
        self.assertEqual(a.basket_value, sim.assessments[0]['nth_value'])

    def test_judges_use_evidence_not_hidden_truth(self):
        left, right = simulation(), simulation()
        a = act(left, true_value=100, true_selfless=False)
        b = act(right, true_value=0, true_selfless=True)
        self.assertEqual(left.estimates(a), right.estimates(b))

    def test_divergence_holds_until_later_explicit_review(self):
        sim = simulation(delta_r=0)
        sim.people[2].claimant = True
        a = act(sim)
        self.assertEqual(sim.judge_acts([a]), [])
        self.assertTrue(a.needs_review)
        self.assertIsNone(a.closed_epoch)
        self.assertIsNone(sim.people[1].commitment)
        self.assertEqual(sim.judge_acts([a]), [])  # Same epoch: not due.
        sim.ledger.epoch = 2
        sim.people[2].claimant = False  # Losing community does not erase the hold.
        self.assertEqual(sim.judge_acts([a]), [a])
        self.assertEqual(a.closed_epoch, 2)
        self.assertNotIn(a.act_id, sim.pending)
        self.assertTrue(any(e['type'] == 'review' for e in sim.gazette))

    def test_unresolved_review_does_not_close_without_community(self):
        sim = simulation(review_resolution_rate=0, review_delay=2)
        a = act(sim)
        sim.hold(a, 'review', True)
        sim.ledger.epoch = 2
        self.assertEqual(sim.judge_acts([a]), [])
        self.assertEqual(a.review_count, 0)
        sim.ledger.epoch = 3
        self.assertEqual(sim.judge_acts([a]), [])
        self.assertEqual(a.review_count, 1)
        self.assertTrue(a.needs_review)
        self.assertIsNone(a.closed_epoch)

    def test_recusal_waits_for_full_takeover(self):
        sim = simulation()
        a = act(sim, person=0, author_party=True)
        self.assertEqual(sim.judge_acts([a]), [])
        self.assertEqual(sim.assessments, [])
        sim.ledger.epoch, sim.ledger.lambda_val = 2, 1
        sim.control['takeover'] = True
        self.assertEqual(sim.judge_acts([a]), [a])
        self.assertIsNone(sim.assessments[0]['human_value'])

    def test_capacity_retains_original_ids_and_queue_order(self):
        sim = simulation(judgment_capacity=1)
        a, b = act(sim, identity=1), act(sim, identity=2, person=2)
        self.assertEqual(sim.judge_acts([b, a]), [a])
        self.assertEqual(b.pending_reason, 'capacity')
        sim.ledger.epoch = 2
        new = act(sim, identity=3, person=3)
        self.assertEqual(sim.judge_acts([new, b]), [b])
        self.assertEqual(b.act_id, 2)
        self.assertIsNone(new.closed_epoch)

    def test_caps_apply_per_actor_and_nonselfless_acts_get_zero(self):
        sim = simulation(per_act_cap=3, per_actor_cap=5)
        a, b = act(sim, identity=1), act(sim, identity=2)
        bad = act(sim, identity=3, person=2, evidence_motive=0.1)
        self.assertEqual(sim.judge_acts([a, b, bad]), [a, b])
        self.assertEqual((a.basket_value, b.basket_value), (3, 2))
        self.assertEqual((bad.status, bad.basket_value), ('rejected', 0))
        with self.assertRaises(AssertionError):
            sim.judge_acts([a])

    def test_delayed_closure_does_not_enter_wrong_observation_cohort(self):
        sim = simulation()
        a = act(sim)
        sim.hold(a, 'capacity')
        self.assertEqual((sim.cohort(1)['S_t'], sim.cohort(1)['S_upper']), (0, 1))
        sim.ledger.epoch = 2
        sim.judge_acts([a])
        self.assertEqual(sim.cohort(1)['S_t'], 1)
        self.assertIsNone(sim.cohort(2)['S_t'])


class MarketAndLearningTests(unittest.TestCase):
    def test_market_prices_are_observed_transfers_and_money_is_conserved(self):
        sim = simulation()
        sim.ledger.Z, sim.ledger.M = sim.config.phase_two_date, 40
        for p in sim.people:
            p.claimant, p.balance = True, 10
        row = sim.measure_market({i: 5 for i in range(4)})
        trades = [e for e in sim.gazette if e['type'] == 'transfer']
        self.assertTrue(row['price_observed'])
        self.assertAlmostEqual(row['P'], sum(e['amount'] for e in trades)/sum(e['quantity'] for e in trades))
        self.assertAlmostEqual(row['transfer_volume'], sum(e['amount'] for e in trades))
        sim.assert_balances()

    def test_no_trade_retains_price_with_stale_flag_and_safe_zero_supply(self):
        sim = simulation()
        sim.ledger.Z, sim.ledger.P = sim.config.phase_two_date, 2
        row = sim.measure_market({})
        self.assertEqual(row['P'], 2)
        self.assertTrue(row['price_stale'])
        self.assertFalse(row['price_observed'])
        self.assertIsNone(row['raw_velocity'])
        self.assertEqual(row['V'], sim.config.V_min)

    def test_return_transfer_filter_includes_indirect_cycles(self):
        transfers = [dict(sender=a, receiver=b, amount=1) for a, b in [(1,2), (2,3), (3,1), (3,4), (4,4), (4,5)]]
        self.assertEqual([(x['sender'], x['receiver']) for x in filtered_transfers(transfers)], [(3,4), (4,5)])

    def test_handover_needs_window_then_rolls_back_once(self):
        sim = simulation(handover_window=2, min_agreement_acts=1, delta_lambda=0.25)
        sim.estimates(act(sim))
        sim.update_handover()
        self.assertEqual(sim.ledger.lambda_val, 0)
        sim.ledger.epoch = 2
        sim.update_handover()
        self.assertEqual(sim.ledger.lambda_val, 0.25)
        sim.ledger.epoch = 3
        sim.estimates(act(sim, identity=2))
        sim.update_handover()
        self.assertEqual(sim.ledger.lambda_val, 0.5)
        sim.assessments[-1]['agent_value'] = 1000
        sim.update_handover()
        self.assertEqual(sim.ledger.lambda_val, 0.25)
        sim.update_handover()
        self.assertEqual(sim.ledger.lambda_val, 0.25)

    def test_empty_agreement_window_does_not_handover(self):
        sim = simulation(handover_window=1, min_agreement_acts=1)
        row = sim.update_handover()
        self.assertIsNone(row['a_t'])
        self.assertEqual(sim.ledger.lambda_val, 0)

    def test_learning_waits_for_outcomes_and_releases_once(self):
        sim = simulation(outcome_delay=2)
        sim.estimates(act(sim, true_value=2, evidence_value=4))
        self.assertEqual(sim.release_outcomes()['calibration_n'], 0)
        self.assertEqual(sim.control['agent_value_bias'], 0)
        sim.ledger.epoch = 3
        self.assertEqual(sim.release_outcomes()['calibration_n'], 1)
        self.assertGreater(sim.control['agent_value_bias'], 0)
        self.assertEqual(sim.release_outcomes()['calibration_n'], 0)


class WholeRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Config(population_size=12, num_epochs=25, phase_two_date=18060,
                            discovery_probability=1, seed=9)
        cls.result = ShulaSimulation(cls.config).run()

    def test_reproducible_seed_and_no_premint_claim(self):
        repeated = ShulaSimulation(self.config).run()
        self.assertEqual(self.result.rows, repeated.rows)
        self.assertEqual(self.result.events, repeated.events)
        self.assertGreater(self.result.rows[0]['M'], 0)
        self.assertEqual(self.result.rows[0]['claimed'], 0)
        self.assertEqual(self.result.criteria['ledger_integrity']['status'], 'PASS')
        for row in self.result.rows:
            self.assertAlmostEqual(row['M'], row['claimed_total']+row['unclaimed_total'], places=7)
            if row['unclaimed_share'] is not None:
                self.assertTrue(0 <= row['unclaimed_share'] <= 1+1e-9)

    def test_gazette_reconstructs_full_final_state(self):
        assert_same_state(self.result.final_state, replay_gazette(self.result.events))

    def test_gazette_detects_monetary_tampering_and_missing_events(self):
        tampered = copy.deepcopy(self.result.events)
        next(e for e in tampered if e['type'] == 'mint')['amount'] += 1
        with self.assertRaises(AssertionError):
            replay_gazette(tampered)
        with self.assertRaises(ValueError):
            replay_gazette(self.result.events[:5]+self.result.events[6:])

    def test_saved_artifacts_roundtrip_and_have_no_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.result.save(path)
            with gzip.open(path/'gazette.jsonl.gz', 'rt') as stream:
                events = [json.loads(line) for line in stream]
            with gzip.open(path/'final_state.json.gz', 'rt') as stream:
                state = json.load(stream)
            assert_same_state(state, replay_gazette(events))
            self.assertEqual(len((path/'epochs.csv').read_text().splitlines()), 26)
            self.assertNotIn('NaN', (path/'summary.json').read_text())

    def test_no_exchange_or_judgments_are_not_success(self):
        result = ShulaSimulation(Config(population_size=3, num_epochs=5, judgment_capacity=0,
                                        phase_two_date=0)).run()
        self.assertEqual(result.criteria['price_within_band']['status'], 'NOT_EVALUATED')
        self.assertEqual(result.criteria['selflessness_tracks_truth']['status'], 'NOT_EVALUATED')
        self.assertEqual(result.criteria['handover_converges']['status'], 'NOT_EVALUATED')
        self.assertEqual(result.criteria['supply_stable']['status'], 'FAIL')
        self.assertEqual(result.rows[-1]['M'], 0)

    def test_matched_honest_comparison_preserves_effort_and_resources(self):
        honest = ShulaSimulation(replace(self.config, honest_reference=True)).run()
        comparison = compare_honest(self.result, honest)
        self.assertIn(comparison['status'], ('PASS', 'FAIL'))
        for identity, a in self.result.final_state['acts'].items():
            b = honest.final_state['acts'][identity]
            self.assertEqual(a['effort'], b['effort'])
        with self.assertRaises(ValueError):
            compare_honest(self.result, self.result)

    def test_invalid_configuration_fails_early(self):
        for kwargs in [dict(V_min=0), dict(kappa=1), dict(population_size=0),
                       dict(variant='C'), dict(genesis_cap=-1), dict(seed=1.5),
                       dict(claim_limit_scope='ambiguous'), dict(P0=math.nan)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Config(**kwargs)


if __name__ == '__main__':
    unittest.main()

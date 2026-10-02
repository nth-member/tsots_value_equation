"""Synthetic Shula simulator matching simulation_flowchart_corrected.pdf.

Python 3.10+, standard library only. See SIMULATION_README.md for assumptions.
This model tests accounting and scenarios; it is not validation for deployment.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


def clip(value, lower, upper):
    return min(upper, max(lower, value))


def close_enough(left, right):
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-8)


def relative_match(left, right, tolerance):
    return abs(left-right) <= tolerance*max(left, right)


def issuance_request(M, old_V, V, R, dW):
    if V <= 0 or M < 0 or R < 0:
        raise ValueError('Require nonnegative supply/service and positive velocity')
    return (R+dW-M*(V-old_V))/V


def bounded_issuance(request, M, R, genesis, genesis_cap, kappa):
    candidate = clip(request, 0.0, genesis_cap) if genesis else clip(request, -kappa*M, kappa*M)
    return candidate, 0.0 if candidate > 0 and R == 0 else candidate


def filtered_transfers(transfers):
    """Exclude self-transfers and all edges in a return cycle, conservatively."""
    graph = {}
    for item in transfers:
        graph.setdefault(item['sender'], set()).add(item['receiver'])

    def reaches(start, target):
        todo, seen = [start], set()
        while todo:
            node = todo.pop()
            if node == target:
                return True
            if node not in seen:
                seen.add(node)
                todo.extend(graph.get(node, set())-seen)
        return False

    return [x for x in transfers if x['amount'] > 0 and not reaches(x['receiver'], x['sender'])]


@dataclass(frozen=True)
class Config:
    population_size: int = 100
    fabricator_share: float = 0.1
    bringer_share: float = 0.1
    variant: str = 'A'
    epoch_length: float = 30.0
    kappa: float = 0.05
    V_min: float = 0.1
    genesis_cap: float = 100.0
    delta_r: float = 0.5
    per_act_cap: float = 20.0       # Basket units before conversion.
    per_actor_cap: float = 30.0     # Basket units per closure epoch.
    judgment_capacity: int = 120
    review_capacity: int = 30
    review_delay: int = 1
    review_resolution_rate: float = 0.8
    review_noise: float = 0.12
    handover_window: int = 5
    min_agreement_acts: int = 20
    alpha: float = 0.8
    delta_a: float = 0.3
    delta_lambda: float = 0.05
    phase_two_date: float = 18200.0
    claim_limit: float = 100.0
    claim_limit_scope: str = 'per_person_per_epoch'
    max_claimants: int | None = None
    discovery_probability: float = 0.15
    community_sample: int = 7
    human_noise: float = 0.2
    agent_noise: float = 0.15
    evidence_value_bias: float = 0.6
    evidence_motive_bias: float = 0.05
    outcome_delay: int = 3
    learning_rate: float = 0.2
    num_epochs: int = 200
    Z0: float = 18000.0
    P0: float = 1.0
    O0: float = 0.0
    seed: int = 0
    honest_reference: bool = False
    price_band_low: float = 0.5
    price_band_high: float = 2.0
    min_price_epochs: int = 10
    min_price_coverage: float = 0.5
    min_supply_epochs: int = 200
    max_supply_multiple: float = 1000.0
    min_supply_multiple: float = 0.01
    index_tolerance: float = 0.1
    min_judgment_coverage: float = 0.95
    min_calibration_samples: int = 30
    residual_limit: float | None = None

    def __post_init__(self):
        for key, value in asdict(self).items():
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError(f'{key} must be finite')
        for key in ('population_size', 'epoch_length', 'V_min', 'genesis_cap', 'per_act_cap',
                    'per_actor_cap', 'P0', 'handover_window', 'min_agreement_acts', 'num_epochs',
                    'review_delay', 'outcome_delay', 'min_price_epochs', 'min_supply_epochs',
                    'min_calibration_samples', 'max_supply_multiple'):
            if getattr(self, key) <= 0:
                raise ValueError(f'{key} must be positive')
        for key in ('population_size', 'judgment_capacity', 'review_capacity', 'review_delay',
                    'handover_window', 'min_agreement_acts', 'community_sample', 'outcome_delay',
                    'num_epochs', 'seed', 'min_price_epochs', 'min_supply_epochs', 'min_calibration_samples'):
            if not isinstance(getattr(self, key), int):
                raise ValueError(f'{key} must be an integer')
        for key in ('fabricator_share', 'bringer_share', 'review_resolution_rate', 'discovery_probability',
                    'alpha', 'delta_a', 'delta_r', 'learning_rate', 'min_price_coverage', 'min_judgment_coverage'):
            if not 0 <= getattr(self, key) <= 1:
                raise ValueError(f'{key} must lie in [0, 1]')
        for key in ('claim_limit', 'O0', 'judgment_capacity', 'review_capacity', 'community_sample',
                    'human_noise', 'agent_noise', 'review_noise', 'index_tolerance'):
            if getattr(self, key) < 0:
                raise ValueError(f'{key} must be nonnegative')
        if not 0 < self.kappa < 1 or not 0 < self.delta_lambda <= 1:
            raise ValueError('Require 0 < kappa < 1 and 0 < delta_lambda <= 1')
        if self.variant not in ('A', 'B'):
            raise ValueError('variant must be A or B')
        if self.claim_limit_scope not in ('per_person_per_epoch', 'per_person_lifetime', 'phase_total'):
            raise ValueError('Unknown claim_limit_scope')
        if self.max_claimants is not None and (not isinstance(self.max_claimants, int) or self.max_claimants < 0):
            raise ValueError('max_claimants must be a nonnegative integer or None')
        if not 0 < self.price_band_low <= self.price_band_high:
            raise ValueError('Invalid price band')
        if not 0 < self.min_supply_multiple < self.max_supply_multiple:
            raise ValueError('Invalid supply multiples')
        if self.residual_limit is not None and self.residual_limit < 0:
            raise ValueError('residual_limit must be nonnegative or None')


@dataclass
class Person:
    person_id: int
    s_i: float
    is_fabricator: bool = False
    is_bringer: bool = False
    efficiency: float = 1.0
    capital: float = 0.0
    commitment: str | None = None
    discovered: bool = False
    claimant: bool = False
    shula_accrued: float = 0.0   # U: actual minted unclaimed funds, not a value score.
    balance: float = 0.0        # C: claimed funds.
    total_claimed: float = 0.0
    gross_minted: float = 0.0


@dataclass
class Act:
    act_id: int
    person_id: int
    observed_epoch: int
    true_value: float
    true_selfless: bool
    claimed_value: float
    evidence_value: float
    evidence_motive: float
    effort: float
    is_fabricated: bool = False
    author_party: bool = False
    kind: str = 'service'
    status: str = 'new'
    pending_reason: str | None = None
    retry_epoch: int = 0
    needs_review: bool = False
    review_count: int = 0
    closed_epoch: int | None = None
    basket_value: float = 0.0
    judged_val: float = 0.0


@dataclass
class Ledger:
    M: float = 0.0
    P: float = 1.0
    V: float = 0.1
    O: float = 0.0
    W: float = 0.0
    Z: float = 18000.0
    Y: float = 0.0
    epoch: int = 0
    lambda_val: float = 0.0
    genesis_pending: bool = True
    last_settlement_epoch: int = 0


@dataclass
class Result:
    rows: list[dict]
    criteria: dict[str, dict]
    cohorts: list[dict]
    config: Config
    events: list[dict]
    final_state: dict

    def save(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        for filename, rows in [('epochs.csv', self.rows), ('cohorts.csv', self.cohorts)]:
            with (directory/filename).open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        for filename, data in [('config.json', asdict(self.config)), ('summary.json', self.criteria)]:
            (directory/filename).write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')
        with (directory/'final_state.json.gz').open('wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as stream:
                stream.write(json.dumps(self.final_state, separators=(',', ':'), allow_nan=False).encode())
        with (directory/'gazette.jsonl.gz').open('wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as stream:
                for event in self.events:
                    stream.write((json.dumps(event, separators=(',', ':'), allow_nan=False)+'\n').encode())


class ShulaSimulation:
    def __init__(self, config: Config | None = None, **settings: Any):
        if config is not None and settings:
            raise ValueError('Pass either Config or keyword settings')
        self.config = config or Config(**settings)
        c = self.config
        self.ledger = Ledger(P=c.P0, V=c.V_min, O=c.O0, W=c.P0*c.O0, Z=c.Z0, Y=(c.Z0-17651.8)/100)
        ids = list(range(c.population_size))
        self.rng('ring-members').shuffle(ids)
        ring = set(ids[:int(c.population_size*c.fabricator_share)])
        self.rng('bringers').shuffle(ids)
        bringers = set(ids[:int(c.population_size*c.bringer_share)])
        self.people = [Person(i, self.rng('person', i).betavariate(2, 2), i in ring, i in bringers,
                              self.rng('efficiency', i).uniform(0.5, 1)) for i in range(c.population_size)]
        self.acts: dict[int, Act] = {}
        self.pending: set[int] = set()
        self.gazette: list[dict] = []
        self.assessments: list[dict] = []
        self.rows: list[dict] = []
        self.control = dict(agent_value_bias=0.0, agent_motive_bias=0.0, pre_increment=0.0,
                            paused=False, takeover=False)
        self.emit('initial', config=asdict(c), people=[asdict(p) for p in self.people],
                  ledger=asdict(self.ledger), control=self.control.copy())
        self._ran = False

    def rng(self, channel, *keys):
        """Keyed streams keep exogenous draws comparable across paired runs."""
        key = json.dumps([self.config.seed, channel, *keys], separators=(',', ':'))
        return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest(), 'big'))

    def emit(self, kind, **payload):
        self.gazette.append(dict(sequence=len(self.gazette), epoch=self.ledger.epoch, type=kind, **payload))

    @property
    def held_acts_queue(self):
        return [self.acts[i] for i in sorted(self.pending)]

    def add_act(self, act):
        if act.act_id in self.acts or not 0 <= act.person_id < len(self.people):
            raise ValueError('Act ID must be unique and actor must exist')
        self.acts[act.act_id] = act
        self.emit('act_created', act=asdict(act))

    def people_act(self):
        c, t = self.config, self.ledger.epoch
        output = {}
        for p in self.people:
            r = self.rng('activity', t, p.person_id)
            p.s_i = clip(p.s_i+r.gauss(0, 0.005), 0, 1)
            p.capital *= 0.98
            effort = r.uniform(2, 10)
            fabricated = p.is_fabricator and not c.honest_reference
            motive_draw = r.random()
            selfless = (p.is_fabricator and c.honest_reference) or (not fabricated and motive_draw < p.s_i)
            true_value = 0.0 if fabricated else effort
            claimed = effort*(r.uniform(2, 4) if fabricated else 1)
            act_id = (t-1)*c.population_size*2+p.person_id*2+1
            ev, em = self.evidence(act_id, true_value, bool(selfless), claimed, fabricated)
            self.add_act(Act(act_id, p.person_id, t, true_value, bool(selfless), claimed, ev, em,
                             effort, fabricated, p.person_id == 0))
            if p.is_bringer:
                spend = self.rng('outside-money', t, p.person_id).uniform(1, 10)
                p.capital += spend*0.1
                contribution = math.sqrt(spend)
                motive = self.rng('donation-motive', t, p.person_id).random() < p.s_i
                ev, em = self.evidence(act_id+1, contribution, motive, contribution, False)
                self.add_act(Act(act_id+1, p.person_id, t, contribution, motive, contribution, ev, em,
                                 contribution, author_party=p.person_id == 0, kind='outside_money_service'))
                self.emit('outside_money', person_id=p.person_id, committed=spend,
                          disbursed=spend, basket_service_proxy=contribution)
            output[p.person_id] = p.efficiency*(true_value+p.capital)
            self.emit('activity', person_id=p.person_id, s_i=p.s_i, capital=p.capital, output=output[p.person_id])
        return output

    def evidence(self, act_id, value, motive, claimed, fabricated):
        r, c = self.rng('evidence', act_id), self.config
        forge_draw = r.random()
        forged = fabricated and forge_draw < 0.35
        value_proxy = claimed if forged else value
        motive_proxy = 0.85 if (motive or forged) else 0.15
        return (max(0.0, value_proxy+c.evidence_value_bias+r.gauss(0, 0.4)),
                clip(motive_proxy+c.evidence_motive_bias+r.gauss(0, 0.2), 0, 1))

    def claim(self):
        c, t = self.config, self.ledger.epoch
        if self.ledger.Z < c.phase_two_date:
            return 0.0
        ids = list(range(len(self.people)))
        self.rng('claim-order', t).shuffle(ids)
        total, phase_claimed = 0.0, math.fsum(p.total_claimed for p in self.people)
        n_claimants = sum(p.claimant for p in self.people)
        for i in ids:
            p = self.people[i]
            if p.commitment is None:
                continue
            if not p.discovered and self.rng('discovery', t, i).random() < c.discovery_probability:
                p.discovered = True
                self.emit('discovery', person_id=i)
            if not p.discovered:
                continue
            if not p.claimant:
                if c.max_claimants is not None and n_claimants >= c.max_claimants:
                    continue
                p.claimant = True
                n_claimants += 1
                self.emit('claimant', person_id=i, proof='synthetic valid commitment opening')
            allowance = c.claim_limit
            if c.claim_limit_scope == 'per_person_lifetime':
                allowance = max(0.0, allowance-p.total_claimed)
            elif c.claim_limit_scope == 'phase_total':
                allowance = max(0.0, allowance-phase_claimed)
            amount = min(p.shula_accrued, allowance)
            if amount > 0:
                p.shula_accrued -= amount
                p.balance += amount
                p.total_claimed += amount
                phase_claimed += amount
                total += amount
                self.emit('claim', person_id=i, amount=amount)
        return total

    def measure_market(self, output):
        """One-basket proportional auction; each price observation is a transfer."""
        c, t, ledger = self.config, self.ledger.epoch, self.ledger
        phase_two = ledger.Z >= c.phase_two_date
        trades = []
        if phase_two:
            active = [p.person_id for p in self.people if p.claimant]
            self.rng('market-roles', t).shuffle(active)
            buyers, sellers = active[:len(active)//2], active[len(active)//2:]
            stock = {i: output.get(i, 0.0) for i in sellers if output.get(i, 0.0) > 0}
            budgets = {i: self.people[i].balance*self.rng('budget', t, i).uniform(0.1, 0.4) for i in buyers}
            demand, supply = math.fsum(budgets.values()), math.fsum(stock.values())
            if demand > 1e-12 and supply > 1e-12:
                price, seller_ids, cursor = demand/supply, list(stock), 0
                for buyer, budget in budgets.items():
                    while budget > 1e-12 and cursor < len(seller_ids):
                        seller = seller_ids[cursor]
                        amount = min(budget, stock[seller]*price, self.people[buyer].balance)
                        if amount <= 1e-12:
                            cursor += 1
                            continue
                        quantity = amount/price
                        self.people[buyer].balance -= amount
                        self.people[seller].balance += amount
                        stock[seller] = max(0.0, stock[seller]-quantity)
                        budget = max(0.0, budget-amount)
                        trade = dict(sender=buyer, receiver=seller, amount=amount, quantity=quantity, price=price)
                        trades.append(trade)
                        self.emit('transfer', **trade)
                        if stock[seller]*price <= 1e-12:
                            cursor += 1
        valid = filtered_transfers(trades)
        Q, quantity = math.fsum(x['amount'] for x in valid), math.fsum(x['quantity'] for x in valid)
        if ledger.M == 0 and Q != 0:
            raise AssertionError('Cannot exchange before there is minted supply')
        raw_velocity = Q/ledger.M if ledger.M > 0 else None
        ledger.V = max(c.V_min, raw_velocity or 0.0)
        observed = bool(valid and quantity > 0)
        if not phase_two:
            ledger.P = c.P0
        elif observed:
            ledger.P = Q/quantity
        result = dict(phase_two=phase_two, transfer_volume=Q,
                      raw_transfer_volume=math.fsum(x['amount'] for x in trades), raw_velocity=raw_velocity,
                      velocity_floor_applied=raw_velocity is None or raw_velocity < c.V_min,
                      price_observed=observed, price_stale=phase_two and not observed,
                      price_observations=len(valid), P=ledger.P, V=ledger.V)
        self.emit('market', **result)
        return result

    def hold(self, act, reason, needs_review=False):
        act.status, act.pending_reason = 'pending', reason
        act.retry_epoch = self.ledger.epoch+(self.config.review_delay if needs_review else 1)
        act.needs_review = act.needs_review or needs_review
        self.pending.add(act.act_id)
        self.emit('act_updated', act=asdict(act))

    def estimates(self, act):
        """Consume evidence only; release true labels separately as delayed outcomes."""
        c, t = self.config, self.ledger.epoch
        r, takeover = self.rng('agent', t, act.act_id), self.control['takeover']
        human = self.rng('human', t, act.act_id)
        h_value = None if takeover else max(0.0, act.evidence_value+human.gauss(0, c.human_noise))
        h_motive = None if takeover else clip(act.evidence_motive+human.gauss(0, c.human_noise/2), 0, 1)
        a_value = max(0.0, act.evidence_value-self.control['agent_value_bias']+r.gauss(0, c.agent_noise))
        a_motive = clip(act.evidence_motive-self.control['agent_motive_bias']+r.gauss(0, c.agent_noise/2), 0, 1)
        weight = self.ledger.lambda_val
        nth_value = a_value if takeover else (1-weight)*h_value+weight*a_value
        nth_motive = a_motive if takeover else (1-weight)*h_motive+weight*a_motive
        peers = [p.person_id for p in self.people if p.claimant and p.person_id != act.person_id]
        peers = self.rng('community-sample', t, act.act_id).sample(peers, min(c.community_sample, len(peers)))
        community = []
        for i in peers:
            peer, r_peer = self.people[i], self.rng('peer', t, act.act_id, i)
            colludes = peer.is_fabricator and act.is_fabricated
            value = act.claimed_value if colludes else max(0.0, act.evidence_value+r_peer.gauss(0, 0.4))
            community.append(dict(person_id=i, value=value, colludes=colludes))
        median = statistics.median(x['value'] for x in community) if community else None
        basket = nth_value if median is None else 0.9*nth_value+0.1*median
        divergent = median is not None and not relative_match(nth_value, median, c.delta_r)
        assessment = dict(act_id=act.act_id, epoch=t, human_value=h_value, human_motive=h_motive,
                          agent_value=a_value, agent_motive=a_motive, nth_value=nth_value,
                          nth_motive=nth_motive, community=community, community_median=median,
                          basket_value=basket, divergent=divergent, lambda_used=weight,
                          evidence_value=act.evidence_value, evidence_motive=act.evidence_motive, released=False)
        self.assessments.append(assessment)
        self.emit('assessment', assessment=assessment.copy())
        return assessment

    def close_act(self, act, motive, basket, actor_used):
        if act.closed_epoch is not None:
            raise AssertionError('Duplicate act closure')
        c = self.config
        act.closed_epoch, act.pending_reason, act.needs_review = self.ledger.epoch, None, False
        act.status = 'approved' if motive else 'rejected'
        if motive:
            act.basket_value = min(max(0.0, basket), c.per_act_cap,
                                   max(0.0, c.per_actor_cap-actor_used.get(act.person_id, 0.0)))
            actor_used[act.person_id] = actor_used.get(act.person_id, 0.0)+act.basket_value
            p = self.people[act.person_id]
            if p.commitment is None:
                p.commitment = hashlib.sha256(f'simulation:{c.seed}:{p.person_id}'.encode()).hexdigest()
                self.emit('recognition', person_id=p.person_id, commitment=p.commitment)
        self.pending.discard(act.act_id)
        self.emit('act_updated', act=asdict(act))

    def judge_acts(self, candidates):
        c, t = self.config, self.ledger.epoch
        used, reviewed, actor_used, approved, seen = 0, 0, {}, [], set()
        for act in sorted(candidates, key=lambda a: (a.observed_epoch, a.act_id)):
            if act.act_id in seen or act.closed_epoch is not None:
                raise AssertionError('Worklist contains a duplicate or closed act')
            seen.add(act.act_id)
            if act.retry_epoch > t:
                continue
            if act.author_party and not self.control['takeover']:
                self.hold(act, 'recusal')
                continue
            if used >= c.judgment_capacity:
                self.hold(act, 'capacity')
                continue
            if act.needs_review:
                if reviewed >= c.review_capacity:
                    self.hold(act, 'review_capacity')
                    continue
                used += 1
                reviewed += 1
                act.review_count += 1
                r = self.rng('review', act.act_id, act.review_count)
                if r.random() >= c.review_resolution_rate:
                    self.emit('review', act_id=act.act_id, outcome='hold', attempt=act.review_count)
                    self.hold(act, 'review', True)
                    continue
                signal = clip((0.85 if act.true_selfless else 0.15)+r.gauss(0, c.review_noise), 0, 1)
                basket = max(0.0, act.true_value+r.gauss(0, c.review_noise))
                motive = signal >= 0.5
                self.emit('review', act_id=act.act_id, outcome='approve' if motive else 'reject', basket=basket,
                          motive_signal=signal, attempt=act.review_count,
                          reason='Delayed independent noisy verification resolves prior hold')
            else:
                used += 1
                assessment = self.estimates(act)
                if assessment['divergent']:
                    self.hold(act, 'review', True)
                    continue
                basket, motive = assessment['basket_value'], assessment['nth_motive'] >= 0.5
            self.close_act(act, motive, basket, actor_used)
            if act.status == 'approved':
                approved.append(act)
        return approved

    def settle(self, approved, output, old_V, old_W):
        c, ledger = self.config, self.ledger
        if ledger.epoch <= ledger.last_settlement_epoch:
            raise AssertionError('An epoch can settle only once')
        if len({a.act_id for a in approved}) != len(approved) or any(
                a.status != 'approved' or a.closed_epoch != ledger.epoch for a in approved):
            raise AssertionError('Settlement requires unique approved closures from this epoch')
        M_open, price = ledger.M, ledger.P if c.variant == 'A' else c.P0
        for act in approved:
            act.judged_val = price*act.basket_value
            self.emit('act_valued', act_id=act.act_id, judged_val=act.judged_val, conversion_price=price)
        R = math.fsum(a.judged_val for a in approved)
        W, dV = price*output, ledger.V-old_V
        dW = W-old_W
        request = issuance_request(M_open, old_V, ledger.V, R, dW)
        candidate, delta = bounded_issuance(request, M_open, R, ledger.genesis_pending, c.genesis_cap, c.kappa)
        ring_mint = 0.0
        if delta > 0:
            recipients = [a for a in approved if a.judged_val > 0]
            assert recipients and R > 0
            remaining = delta
            for index, act in enumerate(recipients):
                amount = remaining if index == len(recipients)-1 else min(remaining, delta*act.judged_val/R)
                remaining -= amount
                p = self.people[act.person_id]
                p.shula_accrued += amount
                p.gross_minted += amount
                if act.is_fabricated:
                    ring_mint += amount
                self.emit('mint', person_id=p.person_id, act_id=act.act_id, amount=amount)
            ledger.genesis_pending = False
        elif delta < 0:
            rate = -delta/M_open
            for p in self.people:
                p.shula_accrued *= 1-rate
                p.balance *= 1-rate
            self.emit('demurrage', rate=rate, withdrawn=-delta)
        ledger.M, ledger.O, ledger.W = M_open+delta, output, W
        ledger.last_settlement_epoch = ledger.epoch
        residual = ledger.M*ledger.V-M_open*old_V-dW-R
        expected = ledger.V*(delta-request)
        if not close_enough(residual, expected):
            raise AssertionError('Equation residual identity failed')
        error = self.assert_balances()
        return dict(M_open=M_open, M=ledger.M, O=output, W_open=old_W, W=W, V_open=old_V,
                    dV=dV, dW=dW, R=R, requested_dM=request, capped_dM=candidate, dM=delta,
                    equation_residual=residual, residual_identity_error=residual-expected,
                    reconciliation_error=error, minted=max(0.0, delta), withdrawn=max(0.0, -delta),
                    fabricated_mint=ring_mint, ring_capture=ring_mint/delta if delta > 0 else None,
                    conversion_price=price, no_service_guard=candidate > 0 and R == 0)

    def assert_balances(self):
        values = [v for p in self.people for v in (p.shula_accrued, p.balance)]
        if any(not math.isfinite(v) or v < -1e-9 for v in values):
            raise AssertionError('Negative or nonfinite balance')
        total = math.fsum(values)
        if not close_enough(total, self.ledger.M):
            raise AssertionError(f'Ledger mismatch: supply={self.ledger.M}, balances={total}')
        return total-self.ledger.M

    def update_handover(self):
        c, t = self.config, self.ledger.epoch
        window = [a for a in self.assessments if t-c.handover_window < a['epoch'] <= t and a['human_value'] is not None]
        matches = sum((a['human_motive'] >= 0.5) == (a['agent_motive'] >= 0.5)
                      and relative_match(a['human_value'], a['agent_value'], c.delta_a) for a in window)
        agreement = matches/len(window) if window else None
        if self.control['takeover']:
            action, agreement = 'outcome_audit', None
        elif t < c.handover_window or len(window) < c.min_agreement_acts:
            action = 'insufficient_evidence'
        elif agreement >= c.alpha:
            self.control['pre_increment'] = self.ledger.lambda_val
            self.ledger.lambda_val = min(1.0, self.ledger.lambda_val+c.delta_lambda)
            if self.ledger.lambda_val >= 1-1e-12:
                self.ledger.lambda_val = 1.0
                self.control['takeover'] = True
            self.control['paused'], action = False, 'increase'
        else:
            if not self.control['paused']:
                self.ledger.lambda_val = self.control['pre_increment']
            self.control['paused'], action = True, 'pause_or_revert'
        return dict(a_t=agreement, agreement_n=len(window), handover_action=action, **{'lambda': self.ledger.lambda_val})

    def release_outcomes(self):
        c, t = self.config, self.ledger.epoch
        due = [a for a in self.assessments if not a['released'] and a['epoch']+c.outcome_delay <= t]
        losses, value_bias, motive_bias = [], [], []
        for a in due:
            act = self.acts[a['act_id']]
            target = act.true_value if act.true_selfless else 0.0
            prediction = a['agent_value'] if a['agent_motive'] >= 0.5 else 0.0
            loss = (a['agent_motive']-float(act.true_selfless))**2+((prediction-target)/c.per_act_cap)**2
            losses.append(loss)
            value_bias.append(a['evidence_value']-act.true_value)
            motive_bias.append(a['evidence_motive']-float(act.true_selfless))
            a.update(released=True, calibration_loss=loss)
            self.emit('outcome', act_id=act.act_id, calibration_loss=loss, true_selfless=act.true_selfless,
                      true_value=act.true_value, prediction_epoch=a['epoch'])
        if due:
            rate = c.learning_rate
            self.control['agent_value_bias'] += rate*(statistics.mean(value_bias)-self.control['agent_value_bias'])
            self.control['agent_motive_bias'] += rate*(statistics.mean(motive_bias)-self.control['agent_motive_bias'])
        return dict(calibration_error=statistics.mean(losses) if losses else None, calibration_n=len(losses))

    def cohort(self, epoch):
        grouped = {}
        for act in self.acts.values():
            if act.observed_epoch == epoch:
                grouped.setdefault(act.person_id, []).append(act)
        n = len(grouped)
        confirmed = sum(any(a.status == 'approved' for a in acts) for acts in grouped.values())
        unresolved = sum(not any(a.status == 'approved' for a in acts) and any(a.closed_epoch is None for a in acts)
                         for acts in grouped.values())
        fully_judged = sum(all(a.closed_epoch is not None for a in acts) for acts in grouped.values())
        truth = sum(any(a.true_selfless for a in acts) for acts in grouped.values())
        pairs = [(any(a.status == 'approved' for a in acts), any(a.true_selfless for a in acts))
                 for acts in grouped.values() if all(a.closed_epoch is not None for a in acts)]
        errors = sum(pred != target for pred, target in pairs)
        return dict(observation_epoch=epoch, observed_persons=n, S_t=confirmed/n if n else None,
                    S_upper=(confirmed+unresolved)/n if n else None, true_S=truth/n if n else None,
                    judgment_coverage=fully_judged/n if n else None,
                    classification_error=errors/len(pairs) if pairs else None,
                    resolved_persons=fully_judged, classification_errors=errors,
                    TSoTS_confirmed=bool(n and confirmed/n > 0.5))

    def final_state(self):
        return dict(config=asdict(self.config), people=[asdict(p) for p in self.people],
                    acts={str(i): asdict(a) for i, a in sorted(self.acts.items())}, ledger=asdict(self.ledger),
                    control=self.control.copy(), assessments=[a.copy() for a in self.assessments])

    def run(self):
        if self._ran:
            raise RuntimeError('Create a new simulation to run again')
        self._ran = True
        for t in range(1, self.config.num_epochs+1):
            ledger = self.ledger
            old_V, old_W, weight = ledger.V, ledger.W, ledger.lambda_val
            ledger.epoch, ledger.Z = t, self.config.Z0+t*self.config.epoch_length
            ledger.Y = (ledger.Z-17651.8)/100
            output = self.people_act()
            claimed = self.claim()
            self.assert_balances()
            market = self.measure_market(output)
            self.assert_balances()
            worklist = [a for a in self.acts.values() if a.closed_epoch is None]
            approved = self.judge_acts(worklist)
            settled = self.settle(approved, math.fsum(output.values()), old_V, old_W)
            index, handover = self.cohort(t), self.update_handover()
            learning = self.release_outcomes()
            self.emit('control', control=self.control.copy())
            U = math.fsum(p.shula_accrued for p in self.people)
            row = dict(epoch=t, Z=ledger.Z, Y=ledger.Y, **market, **settled, **index, **handover, **learning,
                       lambda_used=weight, claimed=claimed, unclaimed_total=U,
                       claimed_total=math.fsum(p.balance for p in self.people),
                       unclaimed_share=U/ledger.M if ledger.M > 0 else None,
                       claimants=sum(p.claimant for p in self.people), pending_acts=len(self.pending),
                       review_pending=sum(self.acts[i].needs_review for i in self.pending),
                       recusal_pending=sum(self.acts[i].pending_reason == 'recusal' for i in self.pending),
                       genesis_pending=ledger.genesis_pending, seed=self.config.seed, variant=self.config.variant)
            self.rows.append(row)
            self.emit('epoch_close', ledger=asdict(ledger), row=row.copy())
        cohorts = [self.cohort(t) for t in range(1, self.config.num_epochs+1)]
        state = self.final_state()
        assert_same_state(state, replay_gazette(self.gazette))
        result = Result(self.rows, {}, cohorts, self.config, self.gazette, state)
        result.criteria = evaluate(result)
        return result


def replay_gazette(events):
    """Reconstruct state, independently replaying each monetary operation."""
    if not events or events[0]['type'] != 'initial':
        raise ValueError('Gazette must begin with initial state')
    initial = events[0]
    state = json.loads(json.dumps({k: initial[k] for k in ('config', 'people', 'ledger', 'control')}))
    state.update(acts={}, assessments=[])
    assessments, money = {}, state['ledger']['M']
    for seq, event in enumerate(events):
        if event['sequence'] != seq:
            raise ValueError('Missing or reordered gazette event')
        kind = event['type']
        if kind == 'initial':
            if seq:
                raise ValueError('Duplicate initial event')
            continue
        people, acts = state['people'], state['acts']
        if kind == 'activity':
            people[event['person_id']].update(s_i=event['s_i'], capital=event['capital'])
        elif kind in ('act_created', 'act_updated'):
            act, key = event['act'].copy(), str(event['act']['act_id'])
            if kind == 'act_created' and key in acts:
                raise AssertionError('Duplicate act in gazette')
            if kind == 'act_updated' and acts[key]['closed_epoch'] is not None:
                raise AssertionError('Duplicate closure or update after closure')
            acts[key] = act
        elif kind == 'act_valued':
            acts[str(event['act_id'])]['judged_val'] = event['judged_val']
        elif kind == 'recognition':
            people[event['person_id']]['commitment'] = event['commitment']
        elif kind in ('discovery', 'claimant'):
            people[event['person_id']]['discovered' if kind == 'discovery' else 'claimant'] = True
        elif kind == 'claim':
            p, amount = people[event['person_id']], event['amount']
            if not p['claimant'] or amount > p['shula_accrued']+1e-9:
                raise AssertionError('Unfunded or unauthorized claim')
            p['shula_accrued'] -= amount
            p['balance'] += amount
            p['total_claimed'] += amount
        elif kind == 'transfer':
            sender, receiver = people[event['sender']], people[event['receiver']]
            if not sender['claimant'] or not receiver['claimant'] or event['amount'] > sender['balance']+1e-9:
                raise AssertionError('Unfunded or unauthorized transfer')
            sender['balance'] -= event['amount']
            receiver['balance'] += event['amount']
        elif kind == 'mint':
            act = acts[str(event['act_id'])]
            if act['status'] != 'approved' or act['closed_epoch'] != event['epoch'] or act['judged_val'] <= 0:
                raise AssertionError('Mint without current eligible service')
            p = people[event['person_id']]
            if act['person_id'] != p['person_id'] or not p['commitment']:
                raise AssertionError('Mint recipient mismatch')
            p['shula_accrued'] += event['amount']
            p['gross_minted'] += event['amount']
            money += event['amount']
        elif kind == 'demurrage':
            if not 0 <= event['rate'] <= 1 or not close_enough(money*event['rate'], event['withdrawn']):
                raise AssertionError('Invalid demurrage event')
            for p in people:
                p['shula_accrued'] *= 1-event['rate']
                p['balance'] *= 1-event['rate']
            money -= event['withdrawn']
        elif kind == 'assessment':
            item = json.loads(json.dumps(event['assessment']))
            if item['act_id'] in assessments:
                raise AssertionError('Duplicate initial assessment')
            assessments[item['act_id']] = item
            state['assessments'].append(item)
        elif kind == 'outcome':
            assessments[event['act_id']].update(released=True, calibration_loss=event['calibration_loss'])
        elif kind == 'control':
            state['control'] = event['control'].copy()
        elif kind == 'epoch_close':
            total = math.fsum(p['balance']+p['shula_accrued'] for p in people)
            if not close_enough(money, event['ledger']['M']) or not close_enough(total, money):
                raise AssertionError('Gazette replay does not reconcile at close')
            state['ledger'] = event['ledger'].copy()
        elif kind not in ('outside_money', 'market', 'review'):
            raise ValueError(f'Unknown event type {kind}')
    return state


def assert_same_state(expected, actual, path='state'):
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            raise AssertionError(f'Replay key mismatch at {path}')
        for key in expected:
            assert_same_state(expected[key], actual[key], f'{path}.{key}')
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            raise AssertionError(f'Replay length mismatch at {path}')
        for i, (left, right) in enumerate(zip(expected, actual)):
            assert_same_state(left, right, f'{path}[{i}]')
    elif isinstance(expected, float):
        if not close_enough(expected, actual):
            raise AssertionError(f'Replay value mismatch at {path}: {expected} != {actual}')
    elif expected != actual:
        raise AssertionError(f'Replay mismatch at {path}: {expected} != {actual}')


def criterion(passed, detail, **measurements):
    return dict(status='NOT_EVALUATED' if passed is None else ('PASS' if passed else 'FAIL'),
                detail=detail, **measurements)


def evaluate(result):
    rows, c = result.rows, result.config
    phase_two = [r for r in rows if r['phase_two']]
    prices = [r['P'] for r in phase_two if r['price_observed']]
    coverage = len(prices)/len(phase_two) if phase_two else 0.0
    sufficient = len(prices) >= c.min_price_epochs and coverage >= c.min_price_coverage
    output = {'price_within_band': criterion(
        all(c.price_band_low <= p <= c.price_band_high for p in prices) if sufficient else None,
        'Only observed phase-two trades count; carried-forward prices do not.',
        observed_epochs=len(prices), coverage=coverage, minimum=min(prices) if prices else None,
        maximum=max(prices) if prices else None, band=[c.price_band_low, c.price_band_high])}
    first_mint = next((i for i, r in enumerate(rows) if r['M'] > 0), None)
    funded = [] if first_mint is None else [r['M'] for r in rows[first_mint:]]
    if not funded:
        supply_ok = False
    else:
        within_bounds = max(funded)/funded[0] <= c.max_supply_multiple and min(funded)/funded[0] >= c.min_supply_multiple
        supply_ok = False if not within_bounds else (True if len(funded) >= c.min_supply_epochs else None)
    output['supply_stable'] = criterion(supply_ok, 'Declared horizon and growth/collapse bounds, not merely nonnegative supply.',
        funded_epochs=len(funded), minimum_epochs=c.min_supply_epochs,
        maximum_multiple=max(funded)/funded[0] if funded else None,
        minimum_multiple=min(funded)/funded[0] if funded else None,
        final_multiple=rows[-1]['M']/funded[0] if funded else None)
    released = [a['calibration_loss'] for a in result.final_state['assessments'] if a['released']]
    early = late = None
    if len(released) >= 2*c.min_calibration_samples:
        size = max(c.min_calibration_samples, len(released)//3)
        early, late = statistics.mean(released[:size]), statistics.mean(released[-size:])
    output['calibration_improves'] = criterion(None if early is None else late < early,
        'Prediction loss against delayed simulated outcomes; first versus last sample blocks.',
        samples=len(released), early_loss=early, late_loss=late)
    n_observed = sum(x['observed_persons'] for x in result.cohorts)
    n_resolved = sum(x['resolved_persons'] for x in result.cohorts)
    n_errors = sum(x['classification_errors'] for x in result.cohorts)
    judged_coverage = n_resolved/n_observed if n_observed else 0.0
    error = n_errors/n_resolved if n_resolved else None
    index_pass = error <= c.index_tolerance if error is not None and judged_coverage >= c.min_judgment_coverage else None
    output['selflessness_tracks_truth'] = criterion(index_pass,
        'Finalized person/observation-epoch classifications with coverage of unresolved cases.',
        classification_error=error, coverage=judged_coverage, tolerance=c.index_tolerance)
    measured = any(r['handover_action'] in ('increase', 'pause_or_revert', 'outcome_audit') for r in rows)
    enough_time = len(rows) >= c.handover_window+math.ceil(1/c.delta_lambda)-1
    takeover = result.final_state['control']['takeover']
    output['handover_converges'] = criterion(True if takeover else (False if measured and enough_time else None),
        'Full takeover through measured agreement, with pauses/reversion.', final_weight=rows[-1]['lambda'])
    output['ledger_integrity'] = criterion(True, 'Every epoch reconciled; full gazette state replay matched.',
        max_balance_error=max(abs(r['reconciliation_error']) for r in rows))
    residual = max(abs(r['equation_residual']) for r in rows)
    output['equation_residual'] = criterion(None if c.residual_limit is None else residual <= c.residual_limit,
        'Caps/guards can break exact equality; no acceptable residual limit was invented.',
        maximum_absolute=residual, configured_limit=c.residual_limit,
        constrained_epochs=sum(not close_enough(r['dM'], r['requested_dM']) for r in rows))
    output['fabrication_less_rewarded'] = criterion(None,
        'Requires matched honest service; low ring capture alone is insufficient.')
    return output


def compare_honest(result, honest):
    if honest.config != replace(result.config, honest_reference=True):
        raise ValueError('Counterfactual settings must differ only in honest_reference')
    ring = [p['person_id'] for p in result.final_state['people'] if p['is_fabricator']]
    if not ring:
        return criterion(None, 'No ring participants in this configuration.')
    earned = math.fsum(result.final_state['people'][i]['gross_minted'] for i in ring)
    alternative = math.fsum(honest.final_state['people'][i]['gross_minted'] for i in ring)
    return criterion(earned < alternative,
        'Same cohort, seed, effort and outside resources; gross mint rewards, not full economic profit.',
        ring_participants=len(ring), ring_gross_mint=earned, honest_gross_mint=alternative)


def write_report(directory, summaries):
    lines = ['# Shula simulation results', '',
             'Synthetic scenarios, not validation for deployment. Thresholds and assumptions are saved per run.', '',
             '| Run | Price | Supply | Fabrication | Calibration | Handover | Selflessness | Ledger |',
             '| --- | --- | --- | --- | --- | --- | --- | --- |']
    keys = ('price_within_band', 'supply_stable', 'fabrication_less_rewarded', 'calibration_improves',
            'handover_converges', 'selflessness_tracks_truth', 'ledger_integrity')
    for s in summaries:
        lines.append('| '+s['run']+' | '+' | '.join(s['criteria'][key]['status'] for key in keys)+' |')
    lines += ['', '## Measured values', '',
              'Supply multiples are relative to the first positive supply. Prices are Shula per reference basket.', '',
              '| Run | Observed price range | Maximum supply multiple | Final agent weight | Person-classification error |',
              '| --- | --- | --- | --- | --- |']
    def number(value):
        return 'unavailable' if value is None else f'{value:,.4g}'
    for s in summaries:
        c = s['criteria']
        price = c['price_within_band']
        values = [s['run'], number(price['minimum'])+' to '+number(price['maximum']),
                  number(c['supply_stable']['maximum_multiple']),
                  number(c['handover_converges']['final_weight']),
                  number(c['selflessness_tracks_truth']['classification_error'])]
        lines.append('| '+' | '.join(values)+' |')
    lines += ['', '### Equation residuals and accounting', '',
              '| Run | Maximum absolute equation residual | Constrained epochs | Maximum balance reconciliation error |',
              '| --- | --- | --- | --- |']
    for s in summaries:
        c = s['criteria']
        values = [s['run'], number(c['equation_residual']['maximum_absolute']),
                  str(c['equation_residual']['constrained_epochs']),
                  number(c['ledger_integrity']['max_balance_error'])]
        lines.append('| '+' | '.join(values)+' |')
    lines += ['', '## Interpretation', '',
              '- PASS applies only to the declared synthetic criterion and settings.',
              '- FAIL is retained; parameters were not tuned to erase it.',
              '- NOT_EVALUATED means missing evidence or an undeclared threshold, not success.',
              '- Caps usually leave an equation residual; no acceptance bound for it is assumed.',
              '- Prices come from a one-basket proportional auction, an explicit modeling assumption.',
              '- Supply PASS uses the configured growth/collapse bounds; inspect the multiples above before interpreting it as stability.',
              '- Fabrication PASS concerns gross minted rewards under matched modeled resources; full economic profit is not evaluated.',
              '- Paired runs share keyed exogenous draws. This is not a completed parameter/behavior search.',
              '- Replay reconstructs the modeled population, acts, monetary ledger and learner state.', '',
              '## Files', '',
              'Each run has config.json, epochs.csv, cohorts.csv, summary.json, final_state.json.gz and gazette.jsonl.gz.',
              'Paired honest-service runs are in the matching `_honest` directory.', '',
              'See ../SIMULATION_README.md for assumptions and rerun commands.', '']
    (directory/'report.md').write_text('\n'.join(lines))
    (directory/'comparison.json').write_text(json.dumps(summaries, indent=2, allow_nan=False)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='JSON Config fields; defaults for omitted fields')
    parser.add_argument('--variant', choices=['A', 'B', 'both'])
    parser.add_argument('--epochs', type=int)
    parser.add_argument('--population', type=int)
    parser.add_argument('--seeds', help='Comma-separated integer seeds')
    parser.add_argument('--compare-honest', action='store_true')
    parser.add_argument('--output', type=Path, default=Path(__file__).parent/'simulation_results')
    args = parser.parse_args()
    config = Config(**json.loads(args.config.read_text())) if args.config else Config()
    if args.epochs is not None:
        config = replace(config, num_epochs=args.epochs)
    if args.population is not None:
        config = replace(config, population_size=args.population)
    seeds = [int(x.strip()) for x in args.seeds.split(',')] if args.seeds else [config.seed]
    variants = ['A', 'B'] if args.variant == 'both' else [args.variant or config.variant]
    if args.compare_honest and config.honest_reference:
        parser.error('--compare-honest requires an ordinary main run')
    args.output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for variant in variants:
        for seed in seeds:
            run_config, name = replace(config, variant=variant, seed=seed), f'{variant}_seed{seed}'
            print(f'Running {name}: {run_config.num_epochs} epochs', flush=True)
            result = ShulaSimulation(run_config).run()
            if args.compare_honest:
                honest = ShulaSimulation(replace(run_config, honest_reference=True)).run()
                result.criteria['fabrication_less_rewarded'] = compare_honest(result, honest)
                honest.save(args.output/f'{name}_honest')
                del honest
            result.save(args.output/name)
            summaries.append(dict(run=name, criteria=result.criteria))
            print('  '+', '.join(f'{k}={v["status"]}' for k, v in result.criteria.items()), flush=True)
            del result
    write_report(args.output, summaries)
    print("Report:", args.output / "report.md")


if __name__ == '__main__':
    main()

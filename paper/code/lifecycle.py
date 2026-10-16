"""lifecycle.py: Dynamic Feature Promotion/Demotion Pipeline (Algorithm 5).

Simulates one year of signals for a feature whose novelty and revenue share decay while
competitor parity rises and the method is published on day 201.

Run:  python lifecycle.py
"""
from dataclasses import dataclass, field
from enum import Enum

class Tier(Enum):
    CLOUD_ONLY = "cloud_only"; HYBRID = "hybrid"; CLIENT_OK = "client_ok"

@dataclass
class FeatureSignals:
    novelty: float; revenue_share: float; competitor_parity: float; published: bool
    cost_per_1k_usd: float; p95_latency_ms: float; on_device_feasible: bool

WEIGHTS = dict(novelty=0.35, revenue=0.35, parity=0.20, published=0.10)

def ip_value(s):
    return round(WEIGHTS["novelty"] * s.novelty + WEIGHTS["revenue"] * s.revenue_share
                 + WEIGHTS["parity"] * (1 - s.competitor_parity)
                 + WEIGHTS["published"] * (0 if s.published else 1), 3)

def serving_pressure(s, cost_budget=2.0, latency_budget=120.0):
    return round(min(1.0, 0.5 * s.cost_per_1k_usd / cost_budget + 0.5 * s.p95_latency_ms / latency_budget), 3)

@dataclass
class Feature:
    name: str
    tier: Tier = Tier.CLOUD_ONLY
    days_in_tier: int = 0
    history: list = field(default_factory=list)

PROTECT_HI, PROTECT_LO, MIN_DWELL_DAYS = 0.65, 0.40, 30

def decide(f, s):
    v, p = ip_value(s), serving_pressure(s)
    if v >= PROTECT_HI and f.tier != Tier.CLOUD_ONLY:
        return Tier.CLOUD_ONLY, f"demote: ip_value {v} >= {PROTECT_HI}"
    if f.days_in_tier < MIN_DWELL_DAYS:
        return f.tier, "hold: dwell time"
    if f.tier == Tier.CLOUD_ONLY and v < PROTECT_HI and p > 0.6:
        return Tier.HYBRID, f"promote: ip_value {v}, pressure {p}"
    if f.tier == Tier.HYBRID and v < PROTECT_LO and s.on_device_feasible:
        return Tier.CLIENT_OK, f"promote (needs approval): ip_value {v} < {PROTECT_LO}"
    return f.tier, "hold"

def step(f, s, approve):
    target, why = decide(f, s)
    if target == Tier.CLIENT_OK and f.tier != Tier.CLIENT_OK and not approve(f, why):
        target, why = f.tier, why + " -> rejected by reviewer"
    if target != f.tier:
        f.history.append((f.tier.value, target.value, why)); f.tier, f.days_in_tier = target, 0
    else:
        f.days_in_tier += 1
    return f

if __name__ == "__main__":
    f = Feature("neural_filter_v3")
    for day in range(365):
        t = day / 365
        s = FeatureSignals(novelty=0.95 - 0.8 * t, revenue_share=0.6 - 0.45 * t,
                           competitor_parity=min(1, 0.1 + 1.1 * t), published=day > 200,
                           cost_per_1k_usd=1.8, p95_latency_ms=110, on_device_feasible=day > 150)
        before = len(f.history)
        step(f, s, approve=lambda feat, why: True)
        if len(f.history) > before:
            old, new, why = f.history[-1]
            print(f"day {day:>3}: {old:>10} -> {new:<10} {why}")
    print("final tier:", f.tier.value)

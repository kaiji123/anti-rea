"""orchestrator.py: locality routing, micro-batching and Markov prefetch (Algorithms 2-4).

The security tier is checked in code before any learned component runs, so no model
output can move a cloud_only feature to the client.

Run:  python orchestrator.py
"""
import asyncio, time
from collections import Counter, defaultdict
from dataclasses import dataclass
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier

@dataclass
class Request:
    feature: str
    tier: str            # "cloud_only" | "hybrid" | "client_ok" (set by the lifecycle pipeline)
    payload_kb: float
    est_flops_g: float
    rtt_ms: float
    device_gflops: float
    battery: float

def features(r):
    return [r.payload_kb, r.est_flops_g, r.rtt_ms, r.device_gflops, r.battery]

class LocalityRouter:
    """Security tier is a hard constraint; the model only optimizes inside it."""
    def __init__(self):
        self.model = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=0)
    def fit(self, X, y):
        self.model.fit(X, y); return self
    def route(self, r):
        if r.tier == "cloud_only":
            return "cloud"
        if r.tier == "client_ok" and r.rtt_ms > 250:
            return "local"
        return "cloud" if self.model.predict_proba([features(r)])[0, 1] >= 0.5 else "local"

def synthetic_telemetry(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    payload = rng.lognormal(4, 1, n); flops = rng.lognormal(2, 1.2, n)
    rtt = rng.gamma(2, 30, n); dev = rng.uniform(5, 200, n); batt = rng.uniform(0, 1, n)
    local_ms = flops / dev * 1000
    remote_ms = rtt + payload * 8 / 50_000 * 1000 + flops / 2000 * 1000
    return np.column_stack([payload, flops, rtt, dev, batt]), (remote_ms < local_ms).astype(int)

class MicroBatcher:
    def __init__(self, batch_fn, window_ms=8.0, max_batch=32):
        self.batch_fn, self.window, self.max_batch = batch_fn, window_ms / 1000, max_batch
        self.queues, self.timers, self.batches_run = defaultdict(list), {}, 0
    async def submit(self, feature, x):
        fut = asyncio.get_running_loop().create_future()
        q = self.queues[feature]; q.append((x, fut))
        if len(q) >= self.max_batch:
            self._flush(feature)
        elif feature not in self.timers:
            self.timers[feature] = asyncio.get_running_loop().call_later(self.window, self._flush, feature)
        return await fut
    def _flush(self, feature):
        if (t := self.timers.pop(feature, None)) is not None:
            t.cancel()
        items, self.queues[feature] = self.queues[feature], []
        if not items:
            return
        out = self.batch_fn(feature, np.stack([x for x, _ in items]))   # one kernel launch
        self.batches_run += 1
        for (_, fut), y in zip(items, out):
            fut.set_result(y)

class MarkovPrefetcher:
    def __init__(self, k=2, min_p=0.25):
        self.k, self.min_p, self.counts = k, min_p, defaultdict(Counter)
    def observe(self, prev, nxt):
        self.counts[prev][nxt] += 1
    def predict(self, current):
        c = self.counts[current]; total = sum(c.values()) or 1
        return [f for f, n in c.most_common(self.k) if n / total >= self.min_p]

if __name__ == "__main__":
    X, y = synthetic_telemetry()
    router = LocalityRouter().fit(X[:3000], y[:3000])
    print(f"router held-out accuracy: {router.model.score(X[3000:], y[3000:]):.3f}")
    print("cloud_only feature routes to:",
          router.route(Request("neural_filter_v3", "cloud_only", 20, 0.1, 400, 200, 1.0)))
    W = np.random.default_rng(1).normal(size=(16, 16))            # stand-in for protected weights
    batcher = MicroBatcher(lambda f, xb: np.tanh(xb @ W), window_ms=5, max_batch=64)
    async def burst():
        t = time.perf_counter()
        xs = np.random.default_rng(2).normal(size=(200, 16))
        await asyncio.gather(*(batcher.submit("neural_filter_v3", x) for x in xs))
        return time.perf_counter() - t
    secs = asyncio.run(burst())
    print(f"200 requests served in {batcher.batches_run} batched calls ({secs*1000:.1f} ms)")
    pf = MarkovPrefetcher()
    session = ["open", "denoise", "upscale", "export", "open", "denoise", "upscale", "open", "denoise", "colorize"]
    for a, b in zip(session, session[1:]):
        pf.observe(a, b)
    print("after 'denoise', prefetch:", pf.predict("denoise"))

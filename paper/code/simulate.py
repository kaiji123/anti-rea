"""simulate.py: discrete-event cost/latency model behind Section 8 (Figures 3 and 4).

Experiment 1 (batching window, SimPy)
    One protected feature. Requests arrive as a Poisson process (2,000 req/s). The
    orchestrator holds requests for the feature until the window W expires (timer starts
    at the first queued request) or 64 requests are queued, then sends one batched kernel
    call to a pool of GPUs. A call on b items costs 4.0 ms + 0.15 ms * b. The pool is sized
    so that expected utilisation is at most 70%. Server latency = arrival -> result, with
    no network round trip. Each configuration simulates 20 s (about 40,000 requests).

Experiment 2 (prefetch depth k)
    Sessions are walks on a skewed first-order Markov chain over 12 features. A first-order
    model is fitted on the first third of the sessions; on the rest, after each step the
    orchestrator speculatively runs the k most likely next features. A hit is served from
    the client cache (5 ms); a miss pays the network round trip (40 ms) plus one unbatched
    kernel call (4.15 ms). Extra compute = speculative runs that were never used, as a
    percentage of demand runs.

All costs are assumptions, not measurements. Output: results_batching.csv,
results_prefetch.csv (next to this file) and a summary on stdout.

Run:  python simulate.py
"""
import csv, math
from pathlib import Path
import numpy as np
import simpy

HERE = Path(__file__).resolve().parent

# ---- assumptions (Section 8.1) ---------------------------------------------
RATE = 2000.0          # requests per second
FIXED_MS = 4.0         # per kernel call
PER_ITEM_MS = 0.15     # per item in a batch
MAX_BATCH = 64
TARGET_UTIL = 0.70
SIM_S = 20.0
WARMUP_S = 1.0         # discard the first second
WINDOWS_MS = [0, 1, 2, 5, 10, 20, 32]
RTT_MS, LOCAL_HIT_MS = 40.0, 5.0
N_FEATURES, N_SESSIONS, SESSION_LEN, KS = 12, 3000, 20, [0, 1, 2, 3, 4]


def kernel_ms(b):
    return FIXED_MS + PER_ITEM_MS * b


def pool_size(window_ms):
    """GPUs needed for <= 70% utilisation, from the expected batch size."""
    b = min(MAX_BATCH, 1 + RATE * window_ms / 1000)
    busy = RATE / b * kernel_ms(b) / 1000          # GPUs busy on average
    return max(1, math.ceil(busy / TARGET_UTIL))


def run_batching(window_ms, seed=0):
    rng = np.random.default_rng(seed)
    env = simpy.Environment()                        # time unit: ms
    gpus = simpy.Resource(env, capacity=pool_size(window_ms))
    queue, timer, latencies, gpu_ms, batch_sizes = [], [None], [], [0.0], []

    def execute(items):
        with gpus.request() as req:
            yield req
            cost = kernel_ms(len(items))
            yield env.timeout(cost)
        if items[0] >= WARMUP_S * 1000:
            gpu_ms[0] += cost
            batch_sizes.append(len(items))
        latencies.extend(env.now - t for t in items if t >= WARMUP_S * 1000)

    def flush():
        if timer[0] is not None and timer[0].is_alive and env.active_process is not timer[0]:
            timer[0].interrupt()
        timer[0] = None
        items = queue[:]
        queue.clear()
        if items:
            env.process(execute(items))

    def window_timer():
        try:
            yield env.timeout(window_ms)
            timer[0] = None
            flush()
        except simpy.Interrupt:
            pass

    def arrivals():
        while env.now < SIM_S * 1000:
            yield env.timeout(rng.exponential(1000 / RATE))
            queue.append(env.now)
            if window_ms == 0 or len(queue) >= MAX_BATCH:
                flush()
            elif timer[0] is None:
                timer[0] = env.process(window_timer())

    env.process(arrivals())
    env.run()
    lat = np.array(latencies)
    return dict(window_ms=window_ms, gpus=gpus.capacity, requests=len(lat),
                mean_batch=round(float(np.mean(batch_sizes)), 2),
                gpu_ms_per_1k=round(gpu_ms[0] / len(lat) * 1000, 1),
                utilisation=round(gpu_ms[0] / (gpus.capacity * (SIM_S - WARMUP_S) * 1000), 3),
                p50_ms=round(float(np.percentile(lat, 50)), 1),
                p95_ms=round(float(np.percentile(lat, 95)), 1),
                p99_ms=round(float(np.percentile(lat, 99)), 1))


def markov_chain(rng, decay=0.55):
    """Each row: geometric preferences r^rank over a random ordering, lightly perturbed."""
    P = np.zeros((N_FEATURES, N_FEATURES))
    for a in range(N_FEATURES):
        w = decay ** np.arange(N_FEATURES) * rng.uniform(0.8, 1.2, N_FEATURES)
        P[a, rng.permutation(N_FEATURES)] = w
    return P / P.sum(axis=1, keepdims=True)


def run_prefetch(seed=1):
    rng = np.random.default_rng(seed)
    P = markov_chain(rng)
    sessions = []
    for _ in range(N_SESSIONS):
        s = [rng.integers(N_FEATURES)]
        for _ in range(SESSION_LEN - 1):
            s.append(rng.choice(N_FEATURES, p=P[s[-1]]))
        sessions.append(s)
    train, test = sessions[:N_SESSIONS // 3], sessions[N_SESSIONS // 3:]
    counts = np.zeros((N_FEATURES, N_FEATURES))
    for s in train:
        for a, b in zip(s, s[1:]):
            counts[a, b] += 1
    ranking = np.argsort(-counts, axis=1, kind="stable")
    miss_ms = RTT_MS + kernel_ms(1)
    rows = []
    for k in KS:
        hits = steps = 0
        for s in test:
            for a, b in zip(s, s[1:]):
                steps += 1
                hits += b in ranking[a, :k]
        h = hits / steps
        rows.append(dict(k=k, hit_rate=round(h, 3),
                         mean_latency_ms=round(h * LOCAL_HIT_MS + (1 - h) * miss_ms, 1),
                         extra_compute_pct=round((k * steps - hits) / steps * 100, 1)))
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    batching = [run_batching(w) for w in WINDOWS_MS]
    write_csv(HERE / "results_batching.csv", batching)
    print(f"{'W ms':>5} {'GPUs':>4} {'batch':>6} {'GPU-ms/1k':>9} {'util':>5} {'p50':>5} {'p95':>5} {'p99':>5}")
    for r in batching:
        print(f"{r['window_ms']:>5} {r['gpus']:>4} {r['mean_batch']:>6} {r['gpu_ms_per_1k']:>9} "
              f"{r['utilisation']:>5} {r['p50_ms']:>5} {r['p95_ms']:>5} {r['p99_ms']:>5}")
    prefetch = run_prefetch()
    write_csv(HERE / "results_prefetch.csv", prefetch)
    print(f"\n{'k':>2} {'hits':>5} {'mean ms':>7} {'extra %':>7}")
    for r in prefetch:
        print(f"{r['k']:>2} {r['hit_rate']:>5} {r['mean_latency_ms']:>7} {r['extra_compute_pct']:>7}")

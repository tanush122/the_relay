"""Open-loop load against the stand-in: arrivals on a schedule, whether or not replies came.

Each scenario (config.SCENARIOS) is a stated arrival process (see config), run through the
gateway and the full pipeline with the in-process stand-in, in compressed model time
(config.LOAD_TIME_SCALE). Every request writes one results.csv row (scenario, source
"stand-in", arrival as start_time) and one traces.jsonl line with its spans. Latency is
measured from the scheduled arrival, never from when a worker happened to pick it up.
Questions are drawn from Tanush's questions file, or from the three retrieval-check
questions while it is empty; load rows are never graded.
"""

import asyncio
import csv
import random
import time

import config
from library import parse, search
from relay import clock, gateway, llm, pipeline, results, standin

CHECK_QUESTIONS = [  # the phase-1 retrieval checks (not evaluation questions)
    "What is the dimensionality d_ff of the inner layer of the position-wise feed-forward "
    "networks in Attention Is All You Need?",
    "What frame rate does the Mimi codec in Moshi produce tokens at?",
    "What is the ratio loss used for dynamic chunking in H-Net?",
]


def question_pool():
    try:
        with config.QUESTIONS_PATH.open(newline="") as f:
            pool = [r["question"] for r in csv.DictReader(f) if r.get("question", "").strip()]
    except FileNotFoundError:
        pool = []
    return pool or CHECK_QUESTIONS


def arrivals(spec, seed=0):
    """Arrival times in seconds from the start: Poisson, plus an optional even burst."""
    rng, times, t = random.Random(seed), [], 0.0
    burst = spec.get("burst")
    extra = burst["count"] if burst else 0
    while len(times) < spec["requests"] - extra:
        t += rng.expovariate(spec["rate_per_min"] / 60)
        times.append(t)
    if burst:
        step = burst["over_s"] / burst["count"]
        times += [burst["at_s"] + i * step for i in range(burst["count"])]
    return sorted(times)


def cached_retrieval():
    """Retrieval is local and identical for a repeated question, so load runs compute it once
    per (setting, query, papers): compressed time would otherwise stretch its CPU time 50x."""
    original, memo = search.retrieve, {}

    def retrieve(index, query, papers=None):
        key = (index["setting"], query, frozenset(papers) if papers is not None else None)
        if key not in memo:
            memo[key] = original(index, query, papers)
        return memo[key]
    return retrieve


async def run(name, requests=None, results_path=None, trace_path=None, index=None, seed=0):
    """Run one scenario; returns (rows, gateway, stand-in, wall seconds)."""
    spec = {**config.SCENARIOS[name], **({"requests": requests} if requests else {})}
    config.TIME_SCALE = config.LOAD_TIME_SCALE
    clock.reset()
    index = index or search.build_index(parse.load_all_blocks(), config.LOAD_SETTING)
    original, search.retrieve = search.retrieve, cached_retrieval()
    service = standin.StandIn(**{"limits": dict(spec["limits"]), **spec.get("standin", {})})
    gate = gateway.Gateway(**{"limits": spec["limits"], **spec.get("gateway", {})})
    pool, rng, rows = question_pool(), random.Random(seed), []
    for question in pool:  # warm the retrieval cache before the clock runs (see above)
        cleaned, papers = pipeline.understand(question)
        for requery in (True, False):
            pipeline.retrieve_and_decide(index, cleaned, papers, requery)
    begin, wall = clock.now(), time.perf_counter()

    async def one(at, question):
        await clock.sleep(at - (clock.now() - begin))
        result = await pipeline.answer(question, index, client, llm.STAND_IN_KEY,
                                       base_url="https://standin.local/openai/v1",
                                       gateway=gate)
        rows.append(results.row_from(result, name, "https://standin.local/openai/v1"))
        results.trace(result, name, trace_path)

    async def halve(at):
        await clock.sleep(at - (clock.now() - begin))
        for kind in ("rpm", "tpm"):
            service.set_limit(kind, service.limits[kind].capacity / 2)

    try:
        async with llm.make_client(transport=service.transport()) as client:
            tasks = [one(at, rng.choice(pool)) for at in arrivals(spec, seed)]
            if spec.get("halve_at_s"):
                tasks.append(halve(spec["halve_at_s"]))
            await asyncio.gather(*tasks)
    finally:
        search.retrieve, config.TIME_SCALE = original, 1.0
        clock.reset()
    results.append(rows, results_path)
    return rows, gate, service, time.perf_counter() - wall


async def calibrate(n=200, scale=None, seed=0, prompt_words=None):
    """The probe's own tiny request, sent n times one after another to the stand-in, at
    load-run time compression: its first-event and total times next to the probe's."""
    config.TIME_SCALE = scale or config.LOAD_TIME_SCALE
    clock.reset()
    if prompt_words:  # an evaluation-sized prompt and an evaluation-sized reply
        service = standin.StandIn(seed=seed, limits={**config.NO_DAY_LIMIT, "tpm": 10**9})
        content = " ".join(["The papers describe sequence models."] * (prompt_words // 5))
    else:  # the probe's replies were tiny (about 7 reasoning tokens and "ok")
        service = standin.StandIn(seed=seed, limits=dict(config.NO_DAY_LIMIT), reasoning_tokens=8)
        content = config.PROBE["small_prompt"]
    messages = [{"role": "user", "content": content}]
    first, total = [], []
    try:
        async with llm.make_client(transport=service.transport()) as client:
            for _ in range(n):
                record = await llm.stream_chat(client, config.DRAFT_MODEL, messages,
                                               config.PROBE["header_sample_max_tokens"],
                                               llm.STAND_IN_KEY,
                                               base_url="https://standin.local/openai/v1")
                first.append(min(t for t in (record["first_reasoning_ms"], record["ttft_ms"]) if t))
                total.append(record["total_ms"])
                await clock.sleep(2)  # keep it far from the per-minute limits
    finally:
        config.TIME_SCALE = 1.0
        clock.reset()
    return first, total

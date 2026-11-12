"""One clock for the gateway, the stand-in, the load generator and the pipeline's timings.

TIME_SCALE is wall seconds per model second. At 1.0 everything runs in real time (every
real Groq run). Load runs against the stand-in compress time (e.g. 0.02 = 50x faster),
so a minute-long rate-limit window passes in 1.2 wall seconds. Every recorded time is in
model time, so results stay comparable with real runs. The cost: local CPU work (retrieval,
Python overhead) is stretched by 1/TIME_SCALE; load runs cache retrieval per question and
report the measured overhead for this reason.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import config


def now():
    """Model-time seconds (only differences mean anything)."""
    return time.perf_counter() / config.TIME_SCALE


async def sleep(seconds):
    await asyncio.sleep(max(0.0, seconds) * config.TIME_SCALE)


def ms_since(start):
    return round((now() - start) * 1000, 2)


_epoch = {"wall": datetime.now(timezone.utc), "model": now()}


def reset():
    """Start model time at the current wall time; call after changing TIME_SCALE."""
    _epoch.update(wall=datetime.now(timezone.utc), model=now())


def stamp():
    """ISO time of 'now' in model time, for results.csv start_time (arrival)."""
    moment = _epoch["wall"] + timedelta(seconds=now() - _epoch["model"])
    return moment.isoformat(timespec="milliseconds")


class Bucket:
    """A limit that refills continuously, the way Groq's did on 10 Nov.

    Groq's reset headers showed a steady refill (one request per 86.4 s for 1,000 a day;
    255 tokens back in ~1.9 s for 8,000 a minute), not a reset at midnight or on the
    minute. The gateway and the stand-in both use this one model of a limit.
    """

    def __init__(self, capacity, period_s):
        self.capacity, self.period = capacity, period_s
        self.level, self.t = capacity, now()

    def refill(self):
        t = now()
        self.level = min(self.capacity, self.level + (t - self.t) * self.capacity / self.period)
        self.t = t

    def wait_for(self, amount):
        """Seconds until `amount` is available (0 if it is now)."""
        self.refill()
        return max(0.0, (amount - self.level) * self.period / self.capacity)

    def take(self, amount):
        self.refill()
        self.level -= amount

    def correct(self, remaining):
        """Trust the provider's count when it says less is left than we think."""
        self.refill()
        self.level = min(self.level, remaining)

    def resize(self, capacity):
        self.refill()
        self.capacity, self.level = capacity, min(self.level, capacity)

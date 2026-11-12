"""The gateway: the only door to the model. It knows the budget and decides, per request,
whether it can be afforded, whether there is time, how cheaply to answer, and whether a
failed call may be retried.

Budget: its own refilling counters for requests and tokens per minute and per day, set
to LIMIT_SAFETY of the limits found by the probe. Groq's headers report only requests per
day and tokens per minute, so those two are corrected from every response; requests per
minute and tokens per day are counted here alone. A call reserves its estimated tokens
before it is sent, and the reservation is settled with the real usage afterwards.

Queue: a request that cannot be afforded now waits in a bounded queue. On arrival the
wait is predicted from what is queued ahead and the refill rate; if the first token could
not come before the person gives up (GIVE_UP_MS), it is refused at once with a retry time.
A request whose deadline passes while queued is dropped before any token is spent.

Ladder: Normal, Lean (fewer pieces, shorter answer, no re-query) when fewer than
LEAN_BELOW_ANSWERS answers are affordable this minute, and Day-gone when the daily budget
cannot pay for one more answer (then no model call is made at all).
"""

import random
from collections import deque

import config
from relay import clock

POLL_S = 0.25  # how often a queued request checks whether it may go (model time)


class Gateway:
    def __init__(self, limits=None, queue_order=None, retry_budget="config", cache_on=None,
                 seed=1):
        lim = {k: v * config.LIMIT_SAFETY for k, v in (limits or config.LIMITS).items()}
        self.rpm, self.tpm = clock.Bucket(lim["rpm"], 60), clock.Bucket(lim["tpm"], 60)
        self.rpd, self.tpd = clock.Bucket(lim["rpd"], 86400), clock.Bucket(lim["tpd"], 86400)
        self.queue_order = queue_order or config.QUEUE_ORDER
        self.retry_budget = config.RETRY_BUDGET if retry_budget == "config" else retry_budget
        self.queue, self.peak_queue = [], 0
        self.calls = deque(maxlen=config.RETRY_WINDOW)  # True for each call that was a retry
        self.blocked_until = 0.0  # set by a 429's retry-after
        self.typical = 3000  # tokens per answer; follows real usage (starts at C's ~3,000)
        self.cache, self.cache_on = {}, config.CACHE_ON if cache_on is None else cache_on
        self.rng = random.Random(seed)

    # --- which level ---
    def level(self):
        give_up_s = config.GIVE_UP_MS / 1000
        if self.rpd.wait_for(1) > give_up_s or self.tpd.wait_for(self.typical) > give_up_s:
            return "day_gone"
        self.tpm.refill()
        return "lean" if self.tpm.level / self.typical < config.LEAN_BELOW_ANSWERS else "normal"

    def day_back_in_s(self):
        """When one more answer becomes affordable again today."""
        return max(self.rpd.wait_for(1), self.tpd.wait_for(self.typical))

    # --- admission and queue ---
    def wait_estimate(self, estimate):
        ahead = sum(t["estimate"] for t in self.queue)
        return max(self.tpm.wait_for(ahead + estimate), self.rpm.wait_for(len(self.queue) + 1),
                   self.blocked_until - clock.now())

    def affordable(self, estimate):
        return (clock.now() >= self.blocked_until and self.tpm.wait_for(estimate) == 0
                and self.rpm.wait_for(1) == 0 and self.rpd.wait_for(1) == 0
                and self.tpd.wait_for(estimate) == 0)

    def next_ticket(self):
        if self.queue_order == "small_first" and self.tpm.level < self.typical:
            return min(self.queue, key=lambda t: t["estimate"])
        return self.queue[0]

    async def admit(self, estimate, deadline):
        """None once the call may go (its tokens reserved), else (status, reason)."""
        first_s = config.FIRST_TOKEN_TARGET_MS / 1000 / 2  # a typical first token, roughly
        if len(self.queue) >= config.QUEUE_MAX:
            return "rate_limited", "the queue is full"
        wait = self.wait_estimate(estimate)
        if clock.now() + wait + first_s > deadline:
            return "rate_limited", f"busy: please ask again in about {wait:.0f} s"
        ticket = {"estimate": estimate}
        self.queue.append(ticket)
        self.peak_queue = max(self.peak_queue, len(self.queue))
        try:
            while True:
                if clock.now() + first_s > deadline:
                    return "timeout", "the deadline passed while queued (no tokens spent)"
                if self.next_ticket() is ticket and self.affordable(estimate):
                    for bucket, amount in ((self.rpm, 1), (self.rpd, 1), (self.tpm, estimate),
                                           (self.tpd, estimate)):
                        bucket.take(amount)
                    return None
                await clock.sleep(POLL_S)
        finally:
            self.queue.remove(ticket)

    # --- after a call ---
    def settle(self, record, estimate):
        """Return unspent reservation, trust the provider's headers, note 429s."""
        usage = record.get("usage") or {}
        spent = usage.get("total_tokens")
        if spent is None and record["status"] != 200:
            spent = 0  # a refused call costs no tokens (assumption: Groq's 429s did not)
        if spent is not None:
            self.tpm.take(spent - estimate)  # negative = give tokens back
            self.tpd.take(spent - estimate)
            if spent:
                self.typical = round(0.8 * self.typical + 0.2 * spent)
        headers = record.get("headers") or {}
        safety = config.LIMIT_SAFETY
        if headers.get("x-ratelimit-remaining-tokens", "").isdigit():
            self.tpm.correct(int(headers["x-ratelimit-remaining-tokens"]) * safety)
        if headers.get("x-ratelimit-remaining-requests", "").isdigit():
            self.rpd.correct(int(headers["x-ratelimit-remaining-requests"]) * safety)
        if record["status"] == 429:
            wait = float(headers.get("retry-after") or 1)
            self.blocked_until = max(self.blocked_until, clock.now() + wait)
            if "(RPD)" in (record.get("error_body") or "") or "(TPD)" in (record.get("error_body") or ""):
                self.rpd.correct(0)  # the day is gone until it refills

    def retry_wait(self, record, attempt, deadline, shown):
        """Seconds to wait before a retry, or None when this call must not be retried."""
        retryable = (record["status"] in config.RETRY_STATUSES
                     or "FirstTokenTimeout" in (record.get("exception") or ""))
        if shown or not retryable or attempt >= config.RETRY_MAX:
            return None
        budget = self.retry_budget
        if budget is not None and sum(self.calls) >= max(1, budget * len(self.calls)):
            return None
        after = (record.get("headers") or {}).get("retry-after")
        wait = float(after) if after else self.rng.uniform(0, config.RETRY_BASE_S * 2 ** attempt)
        if clock.now() + wait + config.FIRST_TOKEN_TARGET_MS / 2000 > deadline:
            return None  # it could not finish before the person gives up
        return wait

    # --- cache ---
    @staticmethod
    def cache_key(question):
        return " ".join(question.lower().split())

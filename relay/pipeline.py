"""One question through the five steps: understand, retrieve, decide, draft, check.

1. understand (local rules): refuse an empty or overlong question; find the papers it names.
2. retrieve (the tool call, local, zero tokens): library.search.retrieve under one setting.
3. decide (the branch and the loop): if retrieval is weak (strength < MIN_STRENGTH),
   re-query once: without the paper filter if one was applied (the person may have named
   the wrong paper), otherwise with keywords only. Still weak: refuse now, no model call.
4. draft (one streamed model call): answer only from the numbered pieces, citing ids.
5. check (code, while streaming): the answer is released one sentence at a time, and a
   sentence is shown only if it cites retrieved pieces and every number in it appears in
   a piece it cites. The first sentence that fails stops the reply with an honest note:
   nothing unchecked is ever shown, and nothing shown has to be taken back.

Timing (what a person waiting feels): first_token_ms is from arrival to the first checked
text shown; total_ms is from arrival to the end of the reply. The model's own time to its
first visible token, and its reasoning tokens, are kept in the trace. On Groq the hold is
small: the first real answer's first visible token came at 1,066 ms, its last at 1,077 ms.
"""

import asyncio
import re
import uuid

import config
from library import search
from library.pieces import cite_label
from relay import check, clock, llm

STOPWORDS = set("what which who whom whose how why when where does do did is are was were "
                "the a an of in on for to and or by with from at as this that these those "
                "it its paper papers please tell me about describe explain".split())


def understand(question):
    """(question cleaned, papers it names) or raise ValueError with the reason to refuse."""
    q = " ".join(question.split())
    if not q:
        raise ValueError("empty question")
    if len(q) > config.MAX_QUESTION_CHARS:
        raise ValueError(f"question longer than {config.MAX_QUESTION_CHARS} characters")
    return q, search.detect_papers(q)


def keywords(question):
    return " ".join(w for w in re.findall(r"\w+", question) if w.lower() not in STOPWORDS)


def retrieve_and_decide(index, question, papers, requery=True):
    """(pieces or None if still weak, attempts). At most MAX_REQUERIES re-queries."""
    query, scope, attempts = question, papers, []
    for _ in range(config.MAX_REQUERIES + 1 if requery else 1):
        start = clock.now()
        results, strength = search.retrieve(index, query, scope)
        attempts.append({"query": query, "papers": sorted(scope), "strength": round(strength, 4),
                         "piece_ids": [p["piece_id"] for p, _ in results],
                         "ms": clock.ms_since(start)})
        if strength >= config.MIN_STRENGTH:
            return [p for p, _ in results], attempts
        if scope:
            scope = set()  # widen: search all three papers
        else:
            query = keywords(question)
    return None, attempts


def build_messages(question, pieces):
    numbered = "\n\n".join(f"[{p['piece_id']}] ({cite_label(p)})\n{p['text']}" for p in pieces)
    return [{"role": "system", "content": config.ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": f"{numbered}\n\nQuestion: {question}"}]


async def retrieve_tool(index, question, papers, requery=True):
    """The retrieve step as a tool call with its own timeout: retried once, then raises.

    Retrieval is local and fast; INJECT_RETRIEVE_DELAY_S simulates a slow tool (injected).
    """
    for _ in range(2):
        try:
            return await asyncio.wait_for(
                _retrieve(index, question, papers, requery),
                config.RETRIEVE_TIMEOUT_S * config.TIME_SCALE)
        except asyncio.TimeoutError:
            continue
    raise TimeoutError("the library search timed out twice")


async def _retrieve(index, question, papers, requery):
    await clock.sleep(config.INJECT_RETRIEVE_DELAY_S)
    return retrieve_and_decide(index, question, papers, requery)


def max_tokens(level="normal"):
    return config.LEVELS[level]["answer_max_tokens"] + config.REASONING_HEADROOM_TOKENS


def fit_to_ceiling(question, pieces, level="normal"):
    """(pieces, messages, estimate): drop the lowest-ranked pieces until under the ceiling."""
    while True:
        messages = build_messages(question, pieces)
        estimate = llm.estimate_tokens(" ".join(m["content"] for m in messages)) + max_tokens(level)
        if estimate <= config.REQUEST_TOKEN_CEILING or len(pieces) == 1:
            return pieces, messages, estimate
        pieces = pieces[:-1]


def citation_labels(text, pieces):
    """"Paper vN, §section" for every retrieved piece the text cites, in any style."""
    by_id = {p["piece_id"]: p for p in pieces}
    return [cite_label(by_id[i]) for i in check.cited_ids(text) if i in by_id]


class Release:
    """Shows the streamed answer one checked paragraph at a time (relay/check.py).

    A paragraph is final once the next one has started (or the reply has ended). A
    supported paragraph is shown; an unsupported one is withheld and the rest still shown
    (Tanush, 12 Nov: per paragraph, skip). A sentence that only says what the papers do not
    cover claims nothing, so it needs no citation; the rest of its paragraph is checked. A
    paragraph with no citation of its own waits for the next one that cites, and is judged
    against those pieces (models often cite once after several paragraphs); with none
    later, it is withheld.
    """

    def __init__(self, pieces, show, start):
        self.by_id = {p["piece_id"]: p for p in pieces}
        self.show, self.start = show, start
        self.buffer, self.done = "", 0
        self.shown, self.withheld, self.gaps, self.first_ms = [], [], [], None
        self.pending = []  # uncited paragraphs waiting for a citation that may follow

    def feed(self, text):
        self.buffer += text
        blocks = check.paragraphs(self.buffer)
        for block in blocks[self.done:-1]:
            self._release(block)
        self.done = max(self.done, len(blocks) - 1)

    def finish(self):
        blocks = check.paragraphs(self.buffer)
        for block in blocks[self.done:]:
            self._release(block)
        self.done = len(blocks)
        self.withheld += ["no citation"] * len(self.pending)
        self.pending = []

    def _say(self, text):
        if self.first_ms is None:
            self.first_ms = elapsed_ms(self.start)
        self.show(text + "\n\n")

    def _release(self, block):
        sentences = check.SENTENCE.split(block)
        claims = [x for x in sentences if not check.says_not_covered(x)]
        if not claims:
            self.gaps.append(block)
            self._say(block)
            return
        ids = check.cited_ids(" ".join(claims))
        if not ids:
            self.pending.append((block, " ".join(claims)))
            return
        cite = " " + " ".join(f"[{i}]" for i in ids)
        waiting, self.pending = self.pending, []
        for earlier, text in waiting + [(block, " ".join(claims))]:
            text = text if earlier is block else text + cite
            verdict = check.judge(text, self.by_id, lambda p: search.split_windows(p["text"]))
            if verdict["ok"]:
                self.shown.append(earlier)
                self._say(earlier)
            else:
                self.withheld.append(verdict["reason"])


def elapsed_ms(start):
    return clock.ms_since(start)


def status_of(record):
    """The brief's four statuses, from what the model call returned."""
    if record["status"] == 429:
        return "rate_limited"
    if record["exception"] and "Timeout" in record["exception"]:
        return "timeout"
    if record["status"] != 200 or record["exception"] or record["error_body"]:
        return "error"
    return "ok"


def new_result(question, setting):
    return {"request_id": uuid.uuid4().hex, "question": question, "setting": setting,
            "start_time": clock.stamp(),
            "first_token_ms": None, "total_ms": None, "status": "ok", "retries": 0,
            "tokens_in": 0, "tokens_out": 0, "reasoning_tokens": 0, "outcome": None,
            "level": "normal", "reply": "", "citations": [], "attempts": [], "pieces": [],
            "check": "", "estimate": 0, "model": None, "model_record": None, "spans": []}


def day_gone_reply(pieces, back_in_s):
    """The 3pm reply: no model call, the best passages quoted as they are, and when it ends."""
    quoted = "\n\n".join(f"[{cite_label(p)}]\n{p['text']}" for p in pieces)
    return (f"Generated answers are paused: today's model budget is used up. They return in "
            f"about {back_in_s / 60:.0f} minutes. Here are the most relevant passages from the "
            f"papers, quoted as they are, without a generated answer:\n\n{quoted}")


async def answer(question, index, client, api_key, base_url=None, show=lambda text: None,
                 gateway=None):
    """Run the five steps for one question; return a result dict (see new_result).

    With a gateway (load runs), the model call is admitted, queued, retried and ladder-
    levelled by it; without one (a single ask, the evaluation) the call goes straight out.
    """
    start = clock.now()  # arrival: every time below is measured from here
    deadline = start + config.GIVE_UP_MS / 1000
    result = new_result(question, index["setting"])
    spans = result["spans"]

    def span(name, began, **extra):
        spans.append({"name": name, "start_ms": round((began - start) * 1000, 2),
                      "end_ms": elapsed_ms(start), **extra})

    def finish(outcome, reply=""):
        if reply:
            # Only a model-backed reply has a first token; an error note is not an answer.
            if result["first_token_ms"] is None and result["model"] and result["status"] == "ok":
                result["first_token_ms"] = elapsed_ms(start)
            show(reply)
        result["outcome"], result["reply"] = outcome, result["reply"] + reply
        result["total_ms"] = elapsed_ms(start)
        return result

    level = gateway.level() if gateway else "normal"
    result["level"] = level
    key = gateway.cache_key(question) if gateway else None
    if gateway and gateway.cache_on and key in gateway.cache:
        result.update(model="cache", citations=gateway.cache[key]["citations"])
        return finish("cached", gateway.cache[key]["reply"])
    try:
        question, papers = understand(question)
    except ValueError as reason:
        result["check"] = str(reason)
        return finish("refused_understand", f"I can't answer that: {reason}.")
    began = clock.now()
    settings = config.LEVELS["lean" if level == "lean" else "normal"]
    try:
        pieces, result["attempts"] = await retrieve_tool(index, question, papers,
                                                         settings["requery"])
    except TimeoutError as reason:
        span("retrieve", began, error=str(reason))
        result.update(status="timeout", check=str(reason))
        return finish("refused_tool", "The library search is not responding, so I can't "
                                      "answer from the papers right now. Please ask again.")
    span("retrieve", began)
    if pieces is None:
        return finish("refused_retrieval", config.REFUSAL_TEXT)
    if level == "day_gone":
        result["status"] = "rate_limited"
        return finish("day_gone_passages",
                      day_gone_reply(pieces[:config.DAY_GONE_PASSAGES], gateway.day_back_in_s()))
    pieces = pieces[:settings["max_pieces"] or len(pieces)]
    pieces, messages, result["estimate"] = fit_to_ceiling(question, pieces, level)
    result["pieces"] = [p["piece_id"] for p in pieces]

    attempt = 0
    while True:
        if gateway:
            began = clock.now()
            refused = await gateway.admit(result["estimate"], deadline)
            span("queue", began)
            if refused:
                result["status"] = refused[0]
                return finish("refused_gateway", f"[{refused[1]}]")
        release = Release(pieces, show, start)
        began = clock.now()
        record = await llm.stream_chat(
            client, config.DRAFT_MODEL, messages, max_tokens(level), api_key,
            base_url=base_url, on_content=release.feed,
            # The first token must also come before the person gives up (the deadline).
            timeouts=(min(config.FIRST_TOKEN_TIMEOUT_S, max(0.0, deadline - clock.now())),
                      config.STALL_TIMEOUT_S) if gateway else None)
        release.finish()
        span("model", began, attempt=attempt, status=record["status"],
             first_event_ms=min((t for t in (record["first_reasoning_ms"], record["ttft_ms"]) if t),
                                default=None), exception=record["exception"])
        wait = None
        if gateway:
            gateway.settle(record, result["estimate"])
            gateway.calls.append(attempt > 0)
            wait = gateway.retry_wait(record, attempt, deadline, bool(release.shown))
        if wait is None:
            break
        began = clock.now()
        await clock.sleep(wait)
        span("backoff", began)
        attempt += 1
    result["retries"] = attempt
    nothing = not (release.shown or release.withheld or release.gaps)
    if record["status"] == 200 and not record["exception"] and nothing:
        release.withheld.append("no visible text (reasoning may have used all of max_tokens)")
    usage = record["usage"] or {}
    result.update(
        model=record["model"], status=status_of(record), first_token_ms=release.first_ms,
        tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
        reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
        reply="\n\n".join(release.shown + release.gaps), check="; ".join(release.withheld),
        citations=list(dict.fromkeys(label for block in release.shown
                                     for label in citation_labels(block, pieces))),
        model_record={k: record[k] for k in ("status", "headers", "ttft_ms", "first_reasoning_ms",
                                             "total_ms", "content", "error_body", "exception",
                                             "new_connection")})
    if result["status"] != "ok":
        return finish("error", f"[The model service failed ({result['status']}); "
                               "please ask again shortly.]")
    if not release.shown:
        if release.gaps and not release.withheld:
            return finish("refused_model")  # the model said the papers do not cover it
        return finish("refused_check", config.CHECK_FAILED_TEXT)
    if release.withheld:
        return finish("answered_partial", config.WITHHELD_NOTE)
    if release.gaps:
        return finish("answered_partial")
    if gateway:  # only a fully checked answer is cached
        gateway.cache[key] = {"reply": result["reply"], "citations": result["citations"]}
    return finish("answered")

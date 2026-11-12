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
from relay import clock, llm

NOT_RETRIEVED = "NOT AMONG RETRIEVED PIECES"
NOT_A_PIECE_ID = "NOT A PIECE ID (citation could not be parsed)"
# A citation group: [id], [id, id], or gpt-oss's own 【id】 (seen in the first real answer).
CITATION_GROUP = re.compile(r"[\[【]([^\[\]【】]+)[\]】]")
# A comma is a thousands separator only before exactly three digits (2,048), so a list
# like "(4,5,6,8)" reads as four numbers, not 4568 (bug seen on the first real run, 12 Nov).
# Real gpt-oss output (12 Nov) also writes "4\u202f000" (narrow space as thousands separator),
# and names like HG38, W8A8, BF16 or M3T1 hold digits that are not claims: a number may
# not follow a letter, a digit or a point.
NUMBER = re.compile(r"(?<![A-Za-z_\d.])(?:\d{1,3}(?:,\d{3})+(?![\d,])|\d{1,3}(?:[\u202f\u00a0\u2009]\d{3})+(?!\d)"
                    r"|\d+)(?:\.\d+)*")
SEPARATORS = ",\u202f\u00a0\u2009"
# "1. " at a line start and "1) " anywhere number a list; they are not claims.
LIST_MARKER = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+|(?<![\w.])\d+\)\s", re.MULTILINE)
# A sentence ends at . ! ? or a line break, once the next text is not a citation for it.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[^\s\[【])|\n+(?=[^\s\[【])")
# A "sentence" ending in one of these is not finished: it is joined to the next one.
ABBREVIATIONS = ("e.g.", "i.e.", "et al.", "Fig.", "Eq.", "Sec.", "Tab.", "vs.", "cf.")
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


def map_citations(text, pieces):
    """[(cited id, label)] in first-seen order. Unknown ids and unparsable parts are flagged."""
    by_id = {p["piece_id"]: p for p in pieces}
    found = []
    for group in CITATION_GROUP.findall(text):
        for part in group.split(","):
            part = part.strip()
            if re.fullmatch(config.CITATION_ID, part):
                found.append((part, cite_label(by_id[part]) if part in by_id else NOT_RETRIEVED))
            elif re.search(r"-[ABC]-", part):
                found.append((part, NOT_A_PIECE_ID))
    return list(dict.fromkeys(found))


def numbers_in(text):
    return {n.translate({ord(c): None for c in SEPARATORS}) for n in NUMBER.findall(text)}


def same_value(number, evidence):
    """True if `number` is in the evidence as written, or as its fraction or percentage:
    papers often give 0.766 where an answer says 76.6% (Moshi Table 16)."""
    if number in evidence:
        return True
    try:
        value = float(number)
    except ValueError:
        return False
    return any(abs(float(e) - value / 100) < 1e-9 or abs(float(e) - value * 100) < 1e-9
               for e in evidence if e.replace(".", "", 1).isdigit())


def check(sentence, pieces):
    """"" if the sentence may be shown, else why not."""
    cited = map_citations(sentence, pieces)
    if not cited:
        return "no citation"
    bad = [pid for pid, label in cited if label in (NOT_RETRIEVED, NOT_A_PIECE_ID)]
    if bad:
        return f"cites what was not retrieved: {', '.join(bad)}"
    by_id = {p["piece_id"]: p for p in pieces}
    evidence = " ".join(by_id[pid]["text"] + " " + cite_label(by_id[pid]) for pid, _ in cited)
    claim = LIST_MARKER.sub("", CITATION_GROUP.sub(" ", sentence))
    found = numbers_in(evidence)
    missing = {n for n in numbers_in(claim) if not same_value(n, found)}
    if missing:
        return f"numbers not in the cited pieces: {', '.join(sorted(missing))}"
    return ""


def is_refusal(text):
    return text.strip().lower().startswith(config.REFUSAL_TEXT.lower().rstrip("."))


class Release:
    """Shows the streamed answer one checked sentence at a time; stops at the first failure."""

    def __init__(self, pieces, show, start):
        self.pieces, self.show, self.start = pieces, show, start
        self.buffer, self.shown, self.failed, self.refused = "", [], "", False
        self.first_ms = None

    def feed(self, text):
        self.buffer += text
        *sentences, rest = SENTENCE_END.split(self.buffer)
        carry = ""
        for sentence in sentences:
            sentence = carry + sentence
            carry = sentence + " " if sentence.endswith(ABBREVIATIONS) else ""
            if not carry:
                self._release(sentence)
        self.buffer = carry + rest

    def finish(self):
        if self.buffer.strip():
            self._release(self.buffer)
        self.buffer = ""

    def _say(self, text):
        if self.first_ms is None:
            self.first_ms = elapsed_ms(self.start)
        self.show(text)

    def _release(self, sentence):
        if self.failed or self.refused:
            return
        if not self.shown and is_refusal(sentence):  # the model's own "papers do not say"
            self.refused = True
            self._say(config.REFUSAL_TEXT)
            return
        self.failed = check(sentence, self.pieces)
        if not self.failed:
            self.shown.append(sentence)
            self._say(sentence + " ")


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
    if record["status"] == 200 and not record["exception"] and not (release.shown or release.failed or release.refused):
        release.failed = "no visible text (reasoning may have used all of max_tokens)"
    usage = record["usage"] or {}
    result.update(
        model=record["model"], status=status_of(record), first_token_ms=release.first_ms,
        tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
        reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
        reply=" ".join(release.shown), check=release.failed,
        citations=[label for s in release.shown for _, label in map_citations(s, pieces)],
        model_record={k: record[k] for k in ("status", "headers", "ttft_ms", "first_reasoning_ms",
                                             "total_ms", "content", "error_body", "exception",
                                             "new_connection")})
    result["citations"] = list(dict.fromkeys(result["citations"]))
    if result["status"] != "ok":
        return finish("error", f"[The model service failed ({result['status']}); "
                               "please ask again shortly.]")
    if release.refused:
        result["reply"] = config.REFUSAL_TEXT
        return finish("refused_model")
    if release.failed and not release.shown:
        return finish("refused_check", config.CHECK_FAILED_TEXT)
    if release.failed:
        return finish("answered_partial", " I could not check the rest against the papers, "
                                          "so I stopped there.")
    if gateway:  # only a fully checked answer is cached
        gateway.cache[key] = {"reply": result["reply"], "citations": result["citations"]}
    return finish("answered")

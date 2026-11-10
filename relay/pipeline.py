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

import re
import time
import uuid
from datetime import datetime, timezone

import config
from library import search
from library.pieces import cite_label
from relay import llm

NOT_RETRIEVED = "NOT AMONG RETRIEVED PIECES"
NOT_A_PIECE_ID = "NOT A PIECE ID (citation could not be parsed)"
# A citation group: [id], [id, id], or gpt-oss's own 【id】 (seen in the first real answer).
CITATION_GROUP = re.compile(r"[\[【]([^\[\]【】]+)[\]】]")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
LIST_MARKER = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+", re.MULTILINE)  # "1. " is not a claim
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


def retrieve_and_decide(index, question, papers):
    """(pieces or None if still weak, attempts). At most MAX_REQUERIES re-queries."""
    query, scope, attempts = question, papers, []
    for _ in range(config.MAX_REQUERIES + 1):
        start = time.perf_counter()
        results, strength = search.retrieve(index, query, scope)
        attempts.append({"query": query, "papers": sorted(scope), "strength": round(strength, 4),
                         "piece_ids": [p["piece_id"] for p, _ in results],
                         "ms": round((time.perf_counter() - start) * 1000, 2)})
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


def max_tokens():
    return config.ANSWER_MAX_TOKENS + config.REASONING_HEADROOM_TOKENS


def fit_to_ceiling(question, pieces):
    """(pieces, messages, estimate): drop the lowest-ranked pieces until under the ceiling."""
    while True:
        messages = build_messages(question, pieces)
        estimate = llm.estimate_tokens(" ".join(m["content"] for m in messages)) + max_tokens()
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
    return {n.replace(",", "") for n in NUMBER.findall(text)}


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
    missing = numbers_in(claim) - numbers_in(evidence)
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
    return round((time.perf_counter() - start) * 1000, 2)


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
            "start_time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "first_token_ms": None, "total_ms": None, "status": "ok", "retries": 0,
            "tokens_in": 0, "tokens_out": 0, "reasoning_tokens": 0, "outcome": None,
            "reply": "", "citations": [], "attempts": [], "pieces": [], "check": "",
            "estimate": 0, "model": None, "model_record": None}


async def answer(question, index, client, api_key, base_url=None, show=lambda text: None):
    """Run the five steps for one question; return a result dict (see new_result)."""
    start = time.perf_counter()  # arrival: every time below is measured from here
    result = new_result(question, index["setting"])

    def finish(outcome, reply=""):
        if reply:
            # Only a model-backed reply has a first token; an error note is not an answer.
            if result["first_token_ms"] is None and result["model"] and result["status"] == "ok":
                result["first_token_ms"] = elapsed_ms(start)
            show(reply)
        result["outcome"], result["reply"] = outcome, result["reply"] + reply
        result["total_ms"] = elapsed_ms(start)
        return result

    try:
        question, papers = understand(question)
    except ValueError as reason:
        result["check"] = str(reason)
        return finish("refused_understand", f"I can't answer that: {reason}.")
    pieces, result["attempts"] = retrieve_and_decide(index, question, papers)
    if pieces is None:
        return finish("refused_retrieval", config.REFUSAL_TEXT)
    pieces, messages, result["estimate"] = fit_to_ceiling(question, pieces)
    result["pieces"] = [p["piece_id"] for p in pieces]

    release = Release(pieces, show, start)
    record = await llm.stream_chat(client, config.DRAFT_MODEL, messages, max_tokens(),
                                   api_key, base_url=base_url, on_content=release.feed)
    release.finish()
    if record["status"] == 200 and not (release.shown or release.failed or release.refused):
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
    return finish("answered")

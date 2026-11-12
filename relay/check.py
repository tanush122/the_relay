"""The check: does what the model wrote follow from the pieces it cites? (Tanush, 12 Nov:
judge meaning, not strings; nothing hard-coded per paper or question.)

Unit: a paragraph. Formula lines, list items and lines ending in ":" belong to their
paragraph. Policy: an unsupported paragraph is withheld, the others are shown, with a
note that part was withheld.

A paragraph is supported when all three hold:
1. it cites at least one retrieved piece (any style: [id], 【id】, **id**, a bare id);
2. meaning: a local NLI model (config.NLI_MODEL) finds its claims entailed by the cited
   pieces, or failing that by any retrieved piece (models often cite a sibling piece): each sentence is scored against every window of the cited pieces, and the
   paragraph's score is its best-supported sentence. It passes at config.ENTAIL_THRESHOLD,
   calibrated from data (docs/DECISIONS.md; mean, median and whole-paragraph scoring
   separated supported from swapped evidence worse on the same data);
3. numbers: every number in it is in the retrieved pieces, allowing other formats (4 000,
   4k, 1.1 kbps = 1,100 bps, 76.6% = 0.766, 10^-9 = 1e-9, "eight"), rounding, and simple
   arithmetic on two numbers of the cited pieces only (marked "derived"). Digits inside names
   (HG38, W8A8, GPT-3) and reference numbers (Table 3, Eq. 10, §2.2.1) are not claims.
   Derived means a difference or a ratio of two numbers in the cited pieces.
"""

import itertools
import re

import config

CITED = re.compile(rf"(?<![\w-])({config.CITATION_ID})(?![\w-])")
REFERENCE = re.compile(r"(?i)(?:\b(?:tables?|fig(?:ure)?s?\.?|eq(?:uation)?s?\.?|sec(?:tion)?s?\.?|"
                       r"appendix)|§)\s*\(?[\d.]+\)?")
SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten "
                                    "eleven twelve".split())}
NUMBER = re.compile(
    r"(?<![A-Za-z_\d.])(?<![A-Za-z]-)"  # not inside a name (HG38, W8A8, GPT-3)
    r"(\d{1,3}(?:[,\u202f\u00a0\u2009 ]\d{3})+(?![\d,])|\d+(?:\.\d+)?)"  # 4,000 / 4 000 / 12.5
    r"(?:\s*(?:[x×·*]\s*)?10\s*\^?\s*\{?\s*(-?\s*\d+)\s*\}?|e(-?\d+))?"  # x 10^-9 / 1e-9
    r"\s*(%|[kKMGBT](?![A-Za-z]))?")  # 76.6% / 4k / 7B / 1.1 k(bps); not the M of "Mamba"
SCALE = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "B": 1e9, "T": 1e12}
UNIT_PREFIX = re.compile(r"(\d)\s*(k|M|G)(bps|Hz|B\b)")  # 1.1 kbps -> 1.1 x 1,000 bps


def paragraphs(text):
    """Blocks split at blank lines; continuation blocks are joined to the one before."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    out = []
    for block in blocks:
        # Formula, list item, table row, a citation alone, or a sentence carried on.
        continues = re.match(r"(\\\[|\$\$|\\\(|\\begin|[-*•|]|\d+[.)]\s|[a-z]|\[?"
                             + config.CITATION_ID + r")", block)
        if out and (continues or out[-1].rstrip().endswith(":")):
            out[-1] += "\n" + block
        else:
            out.append(block)
    return out


HYPHENS = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2212"})


def cited_ids(text):
    """Every piece id the text cites; models also write ids with non-breaking hyphens
    (moshi\u2011C\u2011016, seen on 12 Nov), which are read as plain ones."""
    return list(dict.fromkeys(CITED.findall(text.translate(HYPHENS))))


def claims(text):
    """The paragraph as plain sentences: citations, markdown and LaTeX markup removed
    (\\beta_1 -> beta 1), each list item or line ending as its own sentence."""
    text = CITED.sub(" ", text.translate(HYPHENS))
    text = re.sub(r"[\[【]\s*[,;\s]*[\]】]", " ", text)  # brackets left empty by the above
    text = re.sub(r"\\[()\[\]]|\$\$?|\*\*|__|`", " ", text)
    text = re.sub(r"\\(?:text|mathrm|mathbf|operatorname|mathcal)\s*", "", text)
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text).replace("{", " ").replace("}", " ")
    text = re.sub(r"(?<=\w)_(?=\w)", " ", text)
    lines = [" ".join(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).split())
             for line in text.splitlines()]
    return " ".join(line if line.endswith((".", ":", ";")) else line + "." for line in lines if line)


def values(text, words=True):
    """[(written, value, decimals, suffix)] for every number in the text. Number words
    ("eight") count as evidence but not as claims: "the three papers" is ordinary language."""
    text = UNIT_PREFIX.sub(lambda m: m.group(1) + " " + m.group(2) + " ", text)
    text = REFERENCE.sub(" ", text.translate(SUPERSCRIPT).replace("−", "-"))
    found = []
    for m in NUMBER.finditer(text):
        digits, exp1, exp2, suffix = m.groups()
        plain = re.sub(r"[,\u202f\u00a0\u2009 ]", "", digits)
        value = float(plain)
        exponent = exp1 or exp2
        if exponent:
            value *= 10 ** int(exponent.replace(" ", ""))
        decimals = len(plain.split(".")[1]) if "." in plain else 0
        found.append((m.group(0).strip(), value, decimals, suffix))
    for word in re.findall(r"(?i)\b(" + "|".join(WORDS) + r")\b", text) if words else []:
        found.append((word, float(WORDS[word.lower()]), 0, None))
    return found


def forms(value, suffix):
    """The values a written number may stand for: as written, scaled by its suffix
    (4k = 4,000; 1.1 kbps = 1,100 bps), or as a fraction when it is a percentage."""
    out = {value}
    if suffix in SCALE:
        out.add(value * SCALE[suffix])
    if suffix == "%":
        out.add(value / 100)
    return out


def _close(a, b, decimals):
    """a (written with `decimals` decimals) equals b once b is rounded the same way."""
    tolerance = 0.5 * 10 ** -decimals + 1e-9 * max(abs(a), abs(b))
    return abs(a - b) <= tolerance


def number_status(item, evidence, derive_from=None):
    """"found", "derived" or None for one written number: found among the evidence numbers,
    or derived (difference or ratio) from two numbers of `derive_from` (default: evidence)."""
    _, value, decimals, suffix = item
    pool = {v for _, ev, _, sf in evidence for v in forms(ev, sf)}
    if any(_close(f, e, decimals) for f in forms(value, suffix) for e in pool):
        return "found"
    if value.is_integer() and abs(value) < 10:
        return None  # single digits are too easy to derive by chance
    base = [ev for _, ev, _, _ in (evidence if derive_from is None else derive_from)][:80]
    exact = value.is_integer() and decimals == 0  # a whole number must come out exactly
    for a, b in itertools.permutations(base, 2):
        # Differences and ratios only ("a 3.5-point drop", "3.6x"): sums and products of two
        # unrelated numbers matched too much by chance (12 Nov: "1.1 kbps" passed that way).
        for result in (abs(a - b), a / b if b else None):
            if result is None:
                continue
            if (abs(result - value) < 1e-9) if exact else _close(value, result, decimals):
                return "derived"
    return None


def numbers_problem(paragraph, evidence_text, derive_text=None):
    """("", derived numbers) when every number is supported, else (reason, derived).
    Numbers are looked up in evidence_text; derived only from derive_text (default: same)."""
    evidence = values(evidence_text)
    derive_from = values(derive_text) if derive_text is not None else None
    missing, derived = [], []
    for item in values(claims(paragraph), words=False):
        status = number_status(item, evidence, derive_from)
        if status is None:
            missing.append(item[0])
        elif status == "derived":
            derived.append(item[0])
    reason = f"numbers not in the retrieved pieces: {', '.join(missing)}" if missing else ""
    return reason, derived


# --- meaning: local NLI (no Groq tokens) ---
_NLI = {}
SENTENCE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\\$])")


def _nli():
    """The NLI cross-encoder and the index of its 'entailment' label (loaded once)."""
    if not _NLI:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(config.NLI_MODEL)
        labels = {v.lower(): int(k) for k, v in model.model.config.id2label.items()}
        _NLI.update(model=model, entail=labels["entailment"])
    return _NLI["model"], _NLI["entail"]


def entailment(premises, hypotheses):
    """P(premise entails hypothesis) for every pair, as a premises x hypotheses list."""
    import numpy as np
    model, idx = _nli()
    pairs = [(p, h) for p in premises for h in hypotheses]
    logits = np.asarray(model.predict(pairs, apply_softmax=False), dtype=float)
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = probs / probs.sum(axis=1, keepdims=True)
    return probs[:, idx].reshape(len(premises), len(hypotheses))


def meaning_score(paragraph, windows):
    """The best entailment any window gives any of the paragraph's sentences."""
    sentences = [s for s in SENTENCE.split(claims(paragraph)) if len(s.split()) >= 4]
    if not sentences or not windows:
        return 0.0
    return float(entailment(windows, sentences).max())


_NOT_COVERED = {}


def says_not_covered(text):
    """Does this text say the papers do not contain the answer? Judged by meaning (NLI),
    so any wording counts: "The papers do not say", "not covered by the retrieved
    pieces", "the excerpts give no figure for this", ..."""
    words = claims(text)
    if not words:
        return False
    if words not in _NOT_COVERED:
        score = entailment([words[:1500]], [config.NOT_COVERED_HYPOTHESIS])[0, 0]
        _NOT_COVERED[words] = float(score) >= config.NOT_COVERED_THRESHOLD
    return _NOT_COVERED[words]


_JUDGED = {}  # (paragraph, cited piece ids) -> verdict; replies repeat in load runs


def judge(paragraph, by_id, windows_of):
    """{"ok", "reason", "score", "derived"} for one paragraph against the retrieved pieces.

    by_id: retrieved piece id -> piece; windows_of(piece) -> its short text windows.
    """
    ids = cited_ids(paragraph)
    key = (paragraph, tuple(ids))
    if key in _JUDGED:
        return _JUDGED[key]
    verdict = {"ok": False, "reason": "", "score": None, "derived": [], "scope": None}
    unknown = [i for i in ids if i not in by_id]
    if not ids:
        verdict["reason"] = "no citation"
    elif unknown:
        verdict["reason"] = f"cites what was not retrieved: {', '.join(unknown)}"
    else:
        # Numbers: found in any retrieved piece (models often cite a sibling piece), but
        # derived only from the pieces this paragraph cites.
        everything = " ".join(p["text"] for p in by_id.values())
        cited = " ".join(by_id[i]["text"] for i in ids)
        verdict["reason"], verdict["derived"] = numbers_problem(paragraph, everything, cited)
        # Meaning: the cited pieces first, then all retrieved pieces.
        verdict["scope"] = "cited"
        verdict["score"] = round(meaning_score(paragraph, [w for i in ids for w in windows_of(by_id[i])]), 4)
        if verdict["score"] < config.ENTAIL_THRESHOLD:
            verdict["scope"] = "retrieved"
            verdict["score"] = round(meaning_score(
                paragraph, [w for p in by_id.values() for w in windows_of(p)]), 4)
        if not verdict["reason"] and verdict["score"] < config.ENTAIL_THRESHOLD:
            verdict["reason"] = f"not entailed by the retrieved pieces (score {verdict['score']})"
        verdict["ok"] = not verdict["reason"]
    _JUDGED[key] = verdict
    return verdict

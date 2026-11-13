"""Replay saved eval-final replies through the release/check offline (zero tokens):
current code vs a proposed citation fix. Prints what would change."""
import json, re, sys
sys.path.insert(0, "/Users/theman/Desktop/the-relay")
import config
from library import parse, search
from relay import check, pipeline

blocks = parse.load_all_blocks()
indexes = {}
traces = [json.loads(l) for l in open(config.TRACE_PATH)]
traces = [t for t in traces if t["scenario"].startswith("eval-final-") and t["scenario"] != "eval-final-interrupted"
          and (t.get("model_record") or {}).get("content")]

def replay(t):
    s = t["setting"]
    if s not in indexes:
        indexes[s] = {p["piece_id"]: p for p in search.build_index(blocks, s)["pieces"]}
    pieces = [indexes[s][i] for i in t["pieces"]]
    r = pipeline.Release(pieces, lambda x: None, pipeline.clock.now())
    r.feed(t["model_record"]["content"]); r.finish()
    cites = list(dict.fromkeys(l for b in r.shown for l in pipeline.citation_labels(b, pieces)))
    outcome = ("refused_check" if not r.shown and r.withheld else "refused_model" if not r.shown
               else "answered_partial" if (r.withheld or r.gaps) else "answered")
    return outcome, cites, r.shown

mode = sys.argv[1]
if mode == "fix":
    # Fix 1: a citation alone on its own line, written "[ id ]" or with non-breaking hyphens,
    # belongs to the paragraph above it (paragraphs() only knew "[id]").
    original = check.paragraphs
    def paragraphs(text):
        text = text.translate(check.HYPHENS)
        text = re.sub(r"([\[【])\s+", r"\1", text)
        text = re.sub(r"\s+([\]】])", r"\1", text)
        return original(text)
    check.paragraphs = paragraphs
    # Fix 2: a paragraph shown on the strength of a later paragraph's citation is shown
    # with that citation, so no shown text goes out uncited.
    old_say = pipeline.Release._say
    def _release(self, block):
        sentences = check.SENTENCE.split(block)
        claims = [x for x in sentences if not check.says_not_covered(x)]
        if not claims:
            self.gaps.append(block); self._say(block, "gap"); return
        ids = check.cited_ids(" ".join(claims))
        if not ids:
            self.pending.append((block, " ".join(claims))); return
        cite = " " + " ".join(f"[{i}]" for i in ids)
        waiting, self.pending = self.pending, []
        for earlier, text in waiting + [(block, " ".join(claims))]:
            own = earlier is block
            text = text if own else text + cite
            verdict = check.judge(text, self.by_id, lambda p: search.split_windows(p["text"]))
            if verdict["ok"]:
                shown = earlier if own else earlier + cite
                self.shown.append(shown); self._say(shown)
            else:
                self.withheld.append(verdict["reason"])
                self.events.append((pipeline.elapsed_ms(self.start), "withheld"))
    pipeline.Release._release = _release

for t in traces:
    outcome, cites, shown = replay(t)
    print(json.dumps({"scenario": t["scenario"], "q": t["question"][:50], "saved_outcome": t["outcome"],
                      "outcome": outcome, "saved_cites": len(t["citations"]), "cites": len(cites)}))

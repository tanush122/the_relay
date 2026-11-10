---
phase: 01-foundations-and-probe
plan: 02
subsystem: library
tags: [arxiv, parsing, chunking, bm25, embeddings, rrf, cross-encoder]
requires: ["01-01 config.py, conftest requires_data"]
provides:
  - "library/fetch.py + committed data/manifest.json (6 files, sha256, version evidence)"
  - "library/parse.py: Block dicts with paper, version, section number/title/path, kind"
  - "library/pieces.py: make_pieces(blocks, 'A'|'B'|'C'), cite_label(piece)"
  - "library/search.py: load_models, build_index, detect_papers, retrieve"
affects: [01-03, 01-04, 01-05]
tech-stack:
  added: []
  patterns: ["one split path driven by config.SETTINGS", "lazy heavy import inside load_models"]
key-files:
  created: [library/fetch.py, library/parse.py, library/pieces.py, library/search.py, data/manifest.json, tests/test_library.py, tests/test_retrieval.py]
  modified: [tests/conftest.py]
decisions:
  - "manifest.json is a list of entries; each has a 'file' field (name under data/raw) that conftest.requires_data checks"
  - "Setting A misses the H-Net ratio-loss phrase; kept as a strict xfail and reported as a Table 3 finding instead of tuning A or changing the fact"
metrics:
  duration: "~11 min"
  completed: 2026-11-10
  tasks: 3
  files: 8
---

# Phase 1 Plan 02: Paper library and local retrieval Summary

The three papers are fetched once at exactly 1706.03762v7, 2410.00037v1 and 2507.07955v2, with a committed sha256 manifest. Their arXiv HTML is parsed into numbered section blocks with whole tables, split under settings A/B/C by one config-driven function, and retrieved locally with BM25 + MiniLM embeddings fused by RRF, plus a cross-encoder re-rank for C. No Groq calls.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Fetch exact versions once, manifest, version tests | 1bf739b |
| 2 | Section-tree parser, A/B/C pieces, library tests | db0e2aa |
| 3 | Hybrid retrieval, known-fact tests, timings | 35a02ce |

## Manifest

| Paper | Kind | Bytes | sha256 (12) | Version evidence |
|-------|------|-------|-------------|------------------|
| attention | html | 188,707 | fe1288e9c6f8 | `arXiv:1706.03762v7 [cs.CL] 02 Aug 2023` |
| attention | pdf | 2,215,244 | bdfaa68d8984 | pdf url https://arxiv.org/pdf/1706.03762v7 |
| moshi | html | 715,150 | fca02cdccca1 | `arXiv:2410.00037v1 [eess.AS] 17 Sep 2024` (no "2410.00037v2" anywhere in the page) |
| moshi | pdf | 4,694,312 | a687144cc77b | pdf url https://arxiv.org/pdf/2410.00037v1 |
| hnet | html | 564,510 | e8e711353841 | `arXiv:2507.07955v2 [cs.LG] 15 Jul 2025` |
| hnet | pdf | 1,375,282 | 04a2b32e6e82 | pdf url https://arxiv.org/pdf/2507.07955v2 |

- All six URLs are versioned, and every final URL after redirects still contains the version. Fetched 2026-11-10 05:12:39–05:13:09 UTC, 3 s apart, in 34 s total. No HTML 404, so pypdf was not needed.
- A second run made no network calls (0.28 s) and produced a byte-identical manifest. `test_fetch_is_cached` also replaces `httpx.get` with a function that raises.
- PDF evidence is weak: it only proves which versioned URL served the file. The strong evidence is the HTML watermark line, which comes from the paper's own content.

## Parsing (real markup vs the plan's description)

| Paper | Blocks | Tables | Distinct section paths | Top-level numbers present |
|-------|--------|--------|------------------------|---------------------------|
| attention | 26 | 4 | 22 | 0 (abstract), 1–7 |
| moshi | 58 | 19 | 41 | 0, 1–7, A, B, C, D, F |
| hnet | 43 | 8 | 35 | 0, 1–5, A–F, "-" (Acknowledgements) |

The selectors from the plan matched the real HTML. Where the markup differed, I changed the parser as follows:
- Run-in paragraph headings are `section.ltx_paragraph` (for example H-Net "Signal Propagation."). They are not treated as sections. Their titles are kept as text inside the enclosing numbered section.
- Nested `.ltx_para` elements (paragraphs inside lists) are skipped, so text is not duplicated.
- Unnumbered sections borrow their parent's number, or get "-" at top level. This covers two unnumbered H-Net subsubsections inside §1 and H-Net's "Acknowledgements".
- Math alttext: font commands (`\text`, `\mathrm`, …) are removed before stripping `{ } \`. Without this, Table 3's `d_{\text{ff}}` would read `d_textff`. Other command names remain (for example `fracNN-1left(`, `qquad`), which the plan accepts.
- In Moshi, the Appendix A heading sits inside Table 17's own float, so that table has no enclosing section. A table outside every section now takes a heading inside it if there is one, otherwise the section before it. Table 17 is therefore attributed to "A Additional ablation on Mimi codec".
- Two H-Net tables (Tables 5 and 7) are nested inside image figures (`figure.ltx_figure`). They are now kept, instead of being dropped as nested.

## Known gaps in table parsing

- Merged or multi-row header cells come out as ragged ` | ` rows. For example, Attention Table 3's header spans two rows.
- Moshi Appendix E is a toxicity table inside a plain `figure.ltx_figure`, not `ltx_table`. Content inside non-table figures is skipped, so Appendix E yields no block.
- Attention's unnumbered "Attention Visualizations" appendix contains only figures, so it yields no block.

## Pieces per setting

| Setting | Total | attention | moshi | hnet | Avg words |
|---------|-------|-----------|-------|------|-----------|
| A | 406 | 43 | 219 | 144 | 134 |
| B | 119 | 13 | 64 | 42 | 443 |
| C | 174 | 27 | 85 | 62 | 283 |

All 33 C table pieces are unsplit (count of C table pieces = count of table blocks).

## Retrieval results

- The paper filter worked in every case: all returned pieces come from the named paper.
- B and C retrieve all three facts: d_ff = 2048, the 12.5 frames per second Mimi frame rate, and the ratio loss.
- A retrieves the first two facts but not H-Net's ratio loss. This case is kept visible as a strict `xfail`; I did not tune A or change the fact.
  - The sentence "we introduce a ratio loss to guide compression" and its formula fall in window `hnet-A-032`. That window starts in §2.2.2, so it is labelled §2.2.2, and it ranks 45th on BM25 and 42nd on embeddings within H-Net.
  - The top A windows (`hnet-A-033`/`034`) are the rest of §2.2.3. They discuss `L_ratio` but never contain the phrase.
  - This is a real naive-split finding for Table 3. Tanush decides whether to keep it as a finding or to change the check to "a §2.2.3 piece is retrieved".

## Timings (measured on this laptop: Apple M5, 16 GB, macOS 26.6)

- **Cold model load (first run, includes the Hugging Face download into .cache/huggingface):** embedding 18.7 s, cross-encoder 19.6 s.
- **Model load from the local cache (second process):** embedding 1.79 s, cross-encoder 2.99 s.
- **Index build after models are loaded:** A 1.24 s, B 0.42 s, C 0.51 s.
- **Warm per-query retrieve (5 runs after one warm-up):** A median 3.4 ms, B median 3.1 ms, C median 127.3 ms (range 127.0–128.5). C's extra time is the cross-encoder scoring 20 candidates.
- The full library + retrieval suite took 48.8 s on the cold run and 14.0 s warm.

## Line counts (non-blank)

| File | Lines |
|------|-------|
| library/fetch.py | 94 |
| library/parse.py | 95 |
| library/pieces.py | 53 |
| library/search.py | 72 |

Total 314 against the ~280 target, an overrun of 34. The overrun comes mainly from fetch.py's pre-existing-file and changed-checksum paths and from parse.py's two real-markup fixes. Tests: test_library.py 86, test_retrieval.py 67.

## Deviations from Plan

1. **[Rule 1] Parser fixes for the real markup:** font-command stripping in math, section-less tables, and tables nested in image figures, as listed above. Without them the d_ff table check would fail and Moshi Table 17 and H-Net Tables 5 and 7 would be lost.
2. **The manifest entry has an extra `file` field.** `conftest.requires_data` now reads the list manifest, replacing the `{files: [...]}` shape assumed in 01-01.
3. **The HTML version evidence prefers the paper's own `arXiv:<id><v>` watermark line** over the first occurrence of the id. The first occurrence was an "/abs/" link in arXiv's page chrome.
4. **`load_models` returns the cumulative load times of every model loaded so far**, so each index reports the embedding load time, not only the first index.
5. **Setting A / H-Net ratio loss is a strict xfail**, so the plan's "9 fact tests pass" is 8 pass + 1 xfail.

## Known Stubs

None.

## Self-Check: PASSED

All created files exist. Commits 1bf739b, db0e2aa and 35a02ce are in git log. Full suite: 23 passed, 1 xfailed.

# Proposed citation fix: NOT applied (waiting for Tanush)

Problem (found by Tanush while grading, 13 Nov): A Q6, C Q6 and B Q2 were shown in part with an
empty citations column. Cause, from the traces: the model put its citation in a later
paragraph (in A Q6 alone on its own line, written "[ hnet‑A‑062 ]" with spaces and
non-breaking hyphens). The release checks an uncited paragraph against the next paragraph's
citation and shows it if supported, but shows and logs it WITHOUT that citation. So the check
was done; the display and the citations column dropped the citation.

Proposed fix (replay.py, mode "fix"): (1) a citation alone on a line, in any bracket spacing or
hyphen style, joins the paragraph above it; (2) a paragraph shown on the strength of a later
citation is shown with that citation.

Offline replay of the 53 final replies with saved model text (zero tokens), `uv run python
data/runs/citation_fix/replay.py current|fix`:
- Replaying with the current code reproduces 50 of 53 saved outcomes. The 3 that differ do so
  because live paragraph release depends on where stream chunks split the text; the replay
  feeds the whole reply at once.
- The fix restores the citation on A Q6 and C Q6 and changes no outcome.
- B Q2: its live result cannot be reproduced offline (see above), so the fix cannot be judged
  on it.

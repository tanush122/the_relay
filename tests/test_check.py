"""The meaning-based check: paragraphs, citations in any style, tolerant numbers.

Every text here is a test fixture written for the test, not a model reply or a result.
"""

import pytest

import config

from relay import check

PIECE = ("Mimi's encoder projects a 24kHz waveform to 12.5 frames per second. The bitrate is "
         "1.1kbps. Warmup lasts 4,000 steps; Adam uses epsilon = 10^{-9}. The idempotence of "
         "the semantic level is 0.766. Helium scores 54.3 on MMLU and 50.84 after W4A8.")


@pytest.mark.parametrize("claim", [
    "It runs at 12.5 Hz.", "Warm-up is 4\u202f000 steps.", "Warm-up is 4k steps.",
    "The bitrate is 1,100 bps.", "The bitrate is 1.1 kbps.", "76.6% of tokens stay the same.",
    "epsilon is 1e-9.", "epsilon is 10⁻⁹.", "The waveform is 24 kHz.",
    "MMLU drops by about 3.5 points.",  # derived: 54.3 - 50.84 = 3.46
    "The HG38 benchmark with W8A8 and GPT-3 numbers.",  # names, not claims
    "As Table 3 and Eq. 10 in §2.2.1 show, it is fine.",  # references, not claims
])
def test_supported_numbers(claim):
    assert check.numbers_problem(claim, PIECE)[0] == ""


@pytest.mark.parametrize("claim", ["It runs at 25 Hz.", "Warm-up is 8,000 steps.",
                                   "The bitrate is 2.2 kbps.", "Helium scores 61.7."])
def test_unsupported_numbers(claim):
    assert check.numbers_problem(claim, PIECE)[0].startswith("numbers not in the cited pieces")


def test_derived_numbers_are_marked():
    assert check.numbers_problem("A drop of 3.5 points.", PIECE)[1] == ["3.5"]


def test_word_numbers():
    assert check.values("eight codebooks")[0][1] == 8  # as evidence
    assert check.numbers_problem("The three papers each use 8 codebooks.", "eight codebooks")[0] == ""


def test_citations_in_any_style():
    text = "A [moshi-C-016], B 【hnet-C-002】, C **attention-C-008** and bare moshi-A-012."
    assert check.cited_ids(text) == ["moshi-C-016", "hnet-C-002", "attention-C-008", "moshi-A-012"]


def test_paragraphs_keep_formulas_and_lists_with_their_text():
    text = ("The boundary probability is:\n\n\\[ p_t = 1 \\]\n\nwith the indicator [hnet-C-017].\n\n"
            "Second point [hnet-C-022].\n\n- a list item\n\n1. numbered item")
    parts = check.paragraphs(text)
    assert len(parts) == 2 and "p_t" in parts[0] and "list item" in parts[1]


def test_claims_drop_citations_and_markup():
    assert check.claims("**Mimi** runs at \\(12.5\\) Hz [moshi-C-016].") == "Mimi runs at 12.5 Hz ."


NLI_CACHED = (config.MODEL_CACHE_DIR / "hub" / "models--cross-encoder--nli-MiniLM2-L6-H768").exists()


@pytest.mark.skipif(not NLI_CACHED, reason="NLI model not downloaded yet")
def test_real_nli_judges_meaning():
    by_id = {"moshi-C-016": {"text": "Mimi's encoder projects a 24kHz waveform to a latent "
                                     "representation of 12.5 frames per second."}}
    windows = lambda p: [p["text"]]
    good = check.judge("Mimi turns 24 kHz audio into 12.5 frames each second [moshi-C-016].",
                       by_id, windows)
    wrong = check.judge("Mimi was trained on H100 GPUs for two weeks [moshi-C-016].", by_id, windows)
    assert good["ok"] and not wrong["ok"]
    assert check.says_not_covered("None of the excerpts gives a dollar cost for training.")
    assert not check.says_not_covered("Mimi runs at 12.5 Hz.")

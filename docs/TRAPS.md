# How this library misleads a naive retriever

Tanush's three traps (his research, 12 Nov), each with a real failing example on setting A
(small fixed windows, 8 pieces, no re-rank), run locally on the stored papers with no model
call on 12 Nov. Piece ids are setting A's.

## 1. The same words name different things in different papers

Question: "How many layers are in the encoder and decoder?" (no paper named)

Setting A returns attention-A-009 (Attention §3.1, N=6 layers) next to hnet-A-089 (H-Net
§3.3, the encoder and decoder layer ablation) and hnet-A-024 (H-Net §2.1.2, design
principles). Encoder and decoder mean the Transformer's stacks in one paper and H-Net's outer
Mamba-2 stages in the other, so a model can blend both into one count.

What the pipeline does about it: questions that name a paper are searched in that paper only;
every piece carries "paper, section" so the check and the reader can see the mix.

## 2. Table rows cut away from their headers

Question: "What Robustness Score does H-Net (2-stage) get at GPT-3 XL scale?"

Setting A returns hnet-A-072 (rows of Table 2, cut mid-row) and hnet-A-073 (Table 3's
caption, which names the Robustness Score). Neither holds the row with the answer (42.8):
fixed windows separate the caption, the column names and the row.

What the pipeline does about it: setting C keeps each table whole, caption and rows together.
(A parser bug had also dropped every row of H-Net Tables 5 and 7; fixed 12 Nov.)

## 3. Baselines and related work that look like answers

Question: "What is GPT-4's MMLU score in the Moshi paper?" (the paper does not report one)

Retrieval strength is 0.45, above the 0.30 refusal threshold, so the question reaches the
model. Setting A returns moshi-A-156 (§6.1, the ALERT safety table, where GPT-4 appears)
together with moshi-A-144 and moshi-A-151 (MMLU of quantized Helium). An unchecked model can
join "GPT-4" and an MMLU number that belongs to Helium.

What the pipeline does about it: the model may answer only from the pieces and must cite
them; the check refuses any sentence whose numbers are not in the pieces it cites. It cannot
catch a wrong pairing of a real number with the wrong model, which is why the answer key and
hand grading matter.

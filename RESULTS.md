# Results and findings

This file covers the full run of the validator on day7's Agentic-RAG system: 50 questions, one answer model, and two pairs of judges.
The run data itself (answers, judge grades, reviews) is not in this repo; this is a write-up of it.

> **About the "human" column.** The human-checker verdicts below were drafted by Claude for the project owner, to be checked and edited by them.
> Every disputed figure was checked by hand against the source PDFs.
> But the reviewer is not fully independent of the judges, since it is also a language model.
> Treat "agreement with the human" as agreement with this reviewed answer key.

## Setup

| | |
|---|---|
| System under test | day7 Agentic-RAG: hybrid retrieval → Voyage rerank → **gpt-oss-120b** (Groq) writes the answer. The tool router is not used. |
| Corpus | 10 PDFs, 617 chunks:<br>• Nepal Economic Survey 2025/26, chapters 1, 3, 4, 5, 8, 9 and 14<br>• NRB Annual Report 2024/25: review, plus tables and annexes<br>• Nepal Tourism Statistics 2025 |
| Question set | 50 questions with hint-only rubrics. Each rubric has must / should / must-not points; the agent never sees them. |
| Case 1 judges | Gemma 4 31B (small) and Nemotron 3 Ultra 550B (large) |
| Case 2 judges | gpt-oss-20b (small) and Nemotron 3.5 Super 120B (large) |
| How the judges work | Each judge runs its **own** search over the whole corpus, then grades: one call to plan queries, one call to grade. Judges never see the passages the agent retrieved. |
| Grading rule | **Pass:** every must point covered and nothing contradicted.<br>**Partial:** the core is right but some must points are missing or weak.<br>**Fail:** most must points are missing, a must-not point is violated, or a key claim is contradicted.<br>Missing *should* points never stop a pass. |
| Cost | Free tiers only. |

Both cases grade the **same 50 answers**. They were generated once and shared, so differences between the cases come from the judges alone.

### Question set composition

| Type | Count | What it tests |
|---|---|---|
| factual | 20 | A fact stated in the text |
| table_lookup | 15 | A figure that only appears in a table |
| cross_document | 6 | Combining facts from two documents or two time points |
| unanswerable | 4 | The answer is not in the corpus; the agent should decline |
| conflicting_sources | 3 | The documents disagree; the agent should report the conflict |
| comparison | 1 | Comparing several items |
| temporal_confuser | 1 | A nearby year is in the corpus; the asked year must not be confused with it |

## Headline findings

1. **The agent's final score is 39 pass, 5 partial, 6 fail (78% pass, 88% pass-or-partial).**
2. **Two-thirds of the failures are retrieval failures, not reasoning failures.**
   - Q40, Q43 and Q46 wrongly say "not in the documents". The data is in the corpus, and in Q40 it was even in the retrieved passages.
   - Q37 picks the wrong table row, because the right row was never retrieved.
3. **One answer was invented, which is the most serious error (Q47).**
   - Asked for Nepal's unemployment rate, the agent gave "16.34%" with a citation.
   - No document reports unemployment. 16.34 is the 2025 average tourist length of stay, in days.
4. **The agent hides conflicting sources (Q26).**
   - It gave one source's answer as if it were the only one.
   - Q27 passed only because the rubric made the conflict optional (see "Rubric flaws").
5. **Cross-document questions are the weak spot: 2 of 6 passed.**
   - The agent usually gets both figures right but leaves out the link or the "why" the question asks for (Q14, Q31, Q45).
6. **Citations are the weakest part of the answers.** Only 45.5% of answers had every citation check out (mean citation support 0.73).
   - This happened even though retrieval found a correct source document for every answerable question (source hit rate 1.0, MRR 1.0).
7. **The larger judges agreed with the reviewed verdicts more often.**
   - Nemotron 3.5 Super was best by a wide margin: κ = 0.94, with 49 of 50 verdicts matching.
8. **Most judge errors came from the judge's own search, not from bad reasoning.**
   - A judge often couldn't find a figure, or found it cut off, and then marked a correct answer "unsupported" and downgraded it.
   - Every one of these figures was checked in the PDFs, and all of them are there: Q02, Q10, Q15, Q16, Q22, Q36, Q38, Q39, Q41 and Q42.
9. **Small judges are stricter than the grading rule.** They downgraded answers for missing *optional* points (Q06, Q27). The rule says those never stop a pass.

## The answer model (gpt-oss-120b via day7)

| Metric | Value |
|---|---|
| Questions answered (no errors) | 50 / 50 |
| Answered from the documents | 88% |
| Answerable questions actually answered | 93.5%. It wrongly refused Q40, Q43 and Q46. |
| Unanswerable questions correctly declined | 75% (3 of 4). It invented an answer for Q47. |
| Retrieval: right source document found | 100% (MRR 1.0) |
| Retrieval relevance zones | 42 high, 1 mid, 7 unscored |
| Answers whose citations all check out | 45.5% |
| Mean citation support | 0.73 |
| Latency per question | mean 50 s, median 68 s. The bottleneck is Voyage rerank, which is limited to 3 requests per minute on the free tier. |
| Tokens (all 50) | 114K in, 20K out, 15K reasoning |

### Final verdict by question type (reviewed verdicts)

| Type | Pass | Rate |
|---|---|---|
| comparison | 1 / 1 | 100% |
| factual | 19 / 20 | 95% |
| table_lookup | 12 / 15 | 80% |
| unanswerable | 3 / 4 | 75% |
| conflicting_sources | 2 / 3 | 67% |
| cross_document | 2 / 6 | 33% |
| temporal_confuser | 0 / 1 | 0% |

### Every answer that did not pass

| Q | Type | Verdict | What went wrong |
|---|---|---|---|
| Q11 | factual | Partial | The policy rate (4.25%) and corridor (2.75–5.75%) are right, but the answer swaps the facilities: it calls SLF the floor and SDF the ceiling. It copied a survey sentence that lists them in the wrong order. **No judge caught this.** |
| Q14 | cross_document | Partial | Gives 106 institutions now and 107 before, but never says why the number fell (one fewer microfinance institution). |
| Q31 | cross_document | Partial | Both debt totals are right (Rs 2,669.65 bn → Rs 2,878 bn), but there is no reason given for the rise. |
| Q35 | table_lookup | Partial | The food weight is right (35.49%). It names cereal grains as the largest sub-group, but that is only the largest *food* sub-group; housing and utilities (about 16.7%) is the largest overall. |
| Q45 | cross_document | Partial | Both remittance totals are right, but last year's growth (about 19%) and the point that growth is speeding up are missing. |
| Q26 | conflicting_sources | Fail | Gives "energy, 65%" as the only answer. The passage it retrieved also names agriculture (about 49%, Climate Watch), and the conflict is hidden. |
| Q37 | table_lookup | Fail | Names wholesale/retail trade as the largest credit sector. It is consumer loans (about Rs 1.15 trillion); the right row was never retrieved. |
| Q40 | table_lookup | Fail | Says the documents don't contain the answer, although 3 of its 6 retrieved passages mention Everest expeditions. |
| Q43 | cross_document | Fail | Says "not in the documents". Tourism earnings for FY 2024/25 (about Rs 88.7 bn) are in the corpus but were not retrieved. |
| Q46 | temporal_confuser | Fail | Says "not in the documents". The 2024 arrivals (1,147,548, +13.07%) appear on at least five pages. |
| Q47 | unanswerable | Fail | **Made up** an unemployment rate of 16.34% and cited it. That number is the average tourist length of stay. |

## The judges

### Summary

| | gpt-oss-20b | Nemotron 3.5 Super | Gemma 4 31B | Nemotron 3 Ultra |
|---|---|---|---|---|
| Case | 2 (small) | 2 (large) | 1 (small) | 1 (large) |
| Pass / partial / fail | 33 / 9 / 8 | 40 / 4 / 6 | 33 / 10 / 7 | 35 / 9 / 6 |
| Pass rate | 66% | 80% | 66% | 70% |
| Must-point coverage | 0.85 | 0.87 | 0.86 | 0.86 |
| Claims flagged unsupported | 15 | 5 | 13 | 25 |
| Claims flagged contradicted | 4 | 5 | 1 | 4 |
| Self-consistency (verdict matches its own point grades) | 0.88 | 1.00 | 0.84 | 0.92 |
| **κ against the reviewed verdicts** | 0.64 | **0.94** | 0.60 | 0.72 |
| Verdict agreement with the reviewed verdicts | 84% | **98%** | 82% | 88% |
| Weighted κ against the reviewed verdicts | 0.69 | **0.96** | 0.72 | 0.80 |
| Median latency per question | 4 s | 18 s | 139 s | 48 s |
| Tokens (50 questions) | 203K | 292K | 268K | 280K |

How to read κ (Cohen's kappa): it measures agreement after removing the agreement two graders would reach by chance.
- 0.61–0.80 is "substantial" agreement.
- Above 0.80 is "almost perfect".

### Agreement between the two judges of each case

| | Case 2 (20b vs Super) | Case 1 (Gemma vs Ultra) |
|---|---|---|
| Same verdict | 86% (43 / 50) | 86% (43 / 50) |
| Cohen's κ | 0.68 | 0.71 |
| Weighted κ | 0.72 | 0.79 |
| Rubric-point agreement | 96.8% | 97.2% |
| Score correlation | 0.80 | 0.95 |
| Mean score gap (0–10) | 1.12 | 0.64 |

The judges almost always agree on each rubric point (about 97%). Most of their verdict disagreements come from:
- how they treat claims they couldn't find in their own search, and
- whether missing optional points count against an answer.

### Case 2 disagreements (gpt-oss-20b vs Nemotron 3.5 Super)

In every one of these cases the larger judge was the one that agreed with the reviewed verdict.

| Q | 20b | Super | Who is right and why |
|---|---|---|---|
| Q06 | partial | pass | **Super.** The 20b downgraded the answer for missing optional points only. |
| Q16 | partial | pass | **Super.** All three export figures are in the Economic Survey, ch. 5, p. 1; the 20b's search missed that page. |
| Q34 | fail | pass | **Super.** The 20b checked Sudurpashchim's 3.32% *growth* against the provincial *inflation* page (5.02%). The growth table (NRB tables, Table 4, p. 3) shows exactly 3.32%. |
| Q36 | fail | pass | **Super.** Global IME's Rs 3,811.59 crore capital is in the NRB tables, p. 42. |
| Q38 | partial | pass | **Super.** Both monthly figures are in the tourism report, p. 31. |
| Q39 | partial | pass | **Super.** The Annapurna figure (313,549) is in the tourism report, p. 68. |
| Q42 | partial | pass | **Super.** The restricted-area total (27,531) is in the tourism report, p. 66. |

The only point where Super and the reviewed verdicts differ is Q11. Both Case 2 judges passed the swapped SLF/SDF labels.

### Case 1 disagreements (Gemma 4 vs Nemotron 3 Ultra)

| Q | Gemma | Ultra | Who is right and why |
|---|---|---|---|
| Q10 | partial | pass | **Ultra.** The 4.6% NPL figure is in the Economic Survey, ch. 4, p. 3. The other point Gemma raised was optional. |
| Q15 | partial | pass | **Ultra.** The 18.2 months of import cover is stated twice in the NRB review (pp. 1, 11). |
| Q27 | partial | pass | **Ultra**, by the grading rule. 4.61% is in the NRB tables, and the missing points were optional. |
| Q34 | pass | partial | **Gemma.** Ultra read the rubric literally (it mentions Koshi) and couldn't verify two figures that are in the NRB table. |
| Q35 | fail | partial | **Ultra.** Gemma's reasoning is right, but one of the two required points is correct, which fits partial under the rule. Gemma's fail is a defensible stricter call. |
| Q38 | pass | partial | **Gemma.** Ultra said there is no monthly arrivals table, but there is one: tourism report, p. 31. |
| Q41 | partial | pass | **Ultra.** Sri Lanka's 32,287 is in the tourism report, p. 87. Gemma's search result was cut off. |

On three questions **both** Case 1 judges were wrong:
- **Q02:** Nepal's 3.0% is in the Economic Survey, ch. 1, p. 3.
- **Q22:** the 590 GWh import figure is in the Economic Survey, ch. 9, p. 5.
- **Q36:** Global IME's capital figure is in the NRB tables, p. 42.

In each case both judges missed the figure in their own search. Both judges also passed Q11.

### What the judge results suggest

- **For a judge, search quality matters as much as model size.**
  - The judges that wrongly downgraded answers were nearly all being honest about evidence they couldn't see.
  - Larger evidence windows, or giving the judge the cited pages, would likely remove most of these errors. Either option costs more tokens.
- **Nemotron 3.5 Super was the best judge here:** the most accurate (κ 0.94), the most self-consistent (1.00), and fast (median 18 s).
- **gpt-oss-20b was the fastest and cheapest (4 s), but the least reliable on table figures.** Its pass rate on table lookups was 47%, against 80% for Super.
  - It also used almost all of Groq's 200K-token daily free limit in one run.
- **Gemma 4 on Google AI Studio was the slowest (median 139 s) and the flakiest.**
  - It had intermittent 500 errors and timeouts, and needed two retry passes.
- **The thinking models (Gemma 4, Nemotron Ultra and Super) need a large output budget.** With a 3,000-token cap they spent it all on reasoning and returned no JSON. They needed a floor of 8,000 tokens.
- **No judge caught Q11's swapped labels.**
  - Judges grade against the rubric's points, so a wrong statement *outside* those points can slip through.
  - The grading prompt only asks judges to flag unsupported claims, not to check every sentence.

## Rubric flaws found during review

- **Q27 (conflicting sources):**
  - The conflict between the NRB's 4.61% and the Economic Survey's 4.43% was a *should* point, so an answer that ignores the conflict can still pass.
  - For a question written to test conflicting sources, the conflict should be a *must* point.
- **Q34:** the "slowest province" must point also mentions Koshi being close behind, which the question never asked for. Graders who read it literally (Nemotron Ultra) downgrade a correct answer.

## Recommendations for the RAG system

1. **Stop wrong "not in the documents" answers.** When the first search finds nothing, retry with rewritten queries before refusing (Q40, Q43, Q46).
2. **Guard against invented numbers.** Before answering, check that a cited number actually appears in the cited passage *and* is about the thing being asked (Q47).
3. **Report conflicts.** When retrieved passages disagree, say so and give both sources (Q26, Q27).
4. **Answer every part of the question.** Cross-document answers often leave out the "why" or the link between the two facts (Q14, Q31, Q45).
5. **Fix the citations.** Fewer than half of the answers had every citation check out, even though retrieval found the right document every time.
6. **Retrieve whole table rows.** Several misses (Q37, and judge-side Q02 and Q41) come from table chunks that are split or cut off.

"""Writes Claude's human-checker review (verdict + reasoning) for both cases through the portal's API.

The answers are shared by both cases, so the verdict and the answer reasoning are the same; the part about the
judges differs because each case has its own judges. Every judge disagreement cites the grading rule the judges
were given (judge.py GRADE_SYSTEM) or a page in the corpus where a disputed figure was checked.

Run with the portal up: .venv\\Scripts\\python scripts\\write_claude_review.py
"""
import json
import urllib.request

PORTAL = "http://127.0.0.1:8100"
REVIEWER = "Claude (on the user's behalf)"

# What the answer got right or wrong (same answers in both cases).
ANSWER = {
    "Q01": ("pass", "Covers all three required points: growth of about 3.85% (3.68% at basic prices), lower than last year's 4.43%, held back by weak agriculture and lower paddy output. It also adds the modest growth in transport, ICT and trade."),
    "Q02": ("pass", "Bhutan fastest at 7.5% and Nepal at 3.0% for 2026, from the IMF table. Both figures are in the Economic Survey, chapter 1, page 3 (Nepal's row ends in 3.0)."),
    "Q03": ("pass", "Domestic savings 9.7% vs national savings 44.8% of GDP, and it explains the gap with remittances and other income from abroad. All three required points."),
    "Q04": ("pass", "Private sector 73.5% vs government 26.5%, down from 42.3% the year before, plus the total of Rs 1,733 billion. All required points."),
    "Q05": ("pass", "Rupee per capita GDP up 5.5% (Rs 206,625 to 217,946) while the dollar figure dips from USD 1,516 to 1,513, explained by about 5.7% rupee depreciation. All required points."),
    "Q06": ("pass", "Gives both required points: growth of about 20.9% and the drivers (more hydropower, more transmission capacity, higher electricity use). It skips last year's rate and the GDP share, but those were optional."),
    "Q07": ("pass", "Average inflation 2.13%, explained by lower crude prices and fuel price cuts, adequate food grain supply, and falling prices of pulses and spices. All required points."),
    "Q08": ("pass", "Miscellaneous goods (+23%) and vegetables (+11%) lead the increases; pulses, cereals and spices fell. All required points, with extra detail."),
    "Q09": ("pass", "Explains the index (30 construction items, 14.03% weight in the WPI) and its rise from 94.2 in 2018 to 140.9 in 2026. All required points."),
    "Q10": ("pass", "NPL ratio up from 4.92% to 5.42%; core capital 10.13% to 9.61% and total capital 12.95% to 12.64%. Its extra 'mid-March 5.4% vs 4.6%' line also matches the Economic Survey's NPL table (chapter 4, page 3)."),
    "Q11": ("partial", "The numbers are right (policy rate 4.25%, corridor 2.75% to 5.75%), but it labels the facilities backwards: it calls the lending facility (SLF) the lower bound and the deposit facility (SDF) the upper bound. The survey's own table shows the reverse; the answer copied a survey sentence that lists them in the wrong order. The core is right but one stated fact is wrong, which is a partial."),
    "Q12": ("pass", "Mobile banking had the most transactions (62.5 million) and RTGS the largest value. Both required points."),
    "Q13": ("pass", "Targets of 13% (agriculture), 8% (energy) and 13% (small businesses); agriculture at 13.22% and energy at 9.39% are on track, small-business lending at 9.97% is behind. All correct."),
    "Q14": ("partial", "Gives 106 now and 107 in mid-July 2025, but never says why the count fell: one fewer microfinance institution (52 to 51). Its own breakdown lists 51 microfinance institutions, but it doesn't connect the two. One required point missing."),
    "Q15": ("pass", "Reserves rose from Rs 2,677.68 to 3,403.77 billion (USD 19.5 to 23.1 billion); import cover rose from 18.2 to 21.4 months (goods) and 15.4 to 18.5 months (goods and services). The 18.2-month figure is in the NRB review, pages 1 and 11."),
    "Q16": ("pass", "Exports up 20.8% to Rs 191.11 billion, exports to India up 25.3%, exports to China down 53.7%. All three required points, and every figure is in the Economic Survey, chapter 5, page 1. It skips the product list and trade share, which were optional."),
    "Q17": ("pass", "Gold rose from about USD 1,068 (Dec 2015) to 5,015 (Feb 2026), roughly fourfold, driven by safe-haven demand amid trade tensions, West Asia instability and inflation. All required points."),
    "Q18": ("pass", "Stay rose from 13.30 to 16.34 days, daily spending fell from USD 40.84 to 33.08, and it explains the new electronic arrival/departure recording (CTMIS). All required points."),
    "Q19": ("pass", "China 48% and India 17.9% of approved foreign investment. Both required points."),
    "Q20": ("pass", "102,281 kilolitres (excluding LPG); petrol 14 days, diesel 16, kerosene 145. All required points."),
    "Q21": ("pass", "Fitch, BB- with a Stable outlook, signalling moderate credit risk and manageable debt. Both required points (it doesn't add that this is below investment grade, which was optional)."),
    "Q22": ("pass", "Exports of 2,918 GWh and imports of 590 GWh, against 2,332 and 1,712 GWh a year earlier. All required points. The 590 GWh import figure is stated in the Economic Survey, chapter 9, page 5."),
    "Q23": ("pass", "Gives 4,150 MW with 3,798 MW from hydropower, and notes the survey also quotes 4,105 MW. It handles the conflicting figures well."),
    "Q24": ("pass", "Firewood 48.9%, petroleum 21.8%, electricity 12.1%. All required points."),
    "Q25": ("pass", "Cuts of 17.12% by 2030 and 26.79% by 2035, relative to business as usual. All required points."),
    "Q26": ("fail", "Says energy (65%) is the largest source as if that were the whole answer. The passage it retrieved also says agriculture is the largest (about 49%) by Climate Watch data. The question tests whether it reports conflicting sources, and it hid the conflict. Required points missing."),
    "Q27": ("pass", "Gives the NRB/NSO preliminary figures for FY 2024/25 (4.61%, 3.99% at basic prices) with citations to the NRB report, which covers both required points. It doesn't mention the Economic Survey's later 4.43%. I first marked this partial for that, but the rubric lists that point as optional, and optional points never stop a pass, so pass is correct. (This shows a weakness in the rubric: for a conflicting-sources question, the conflict should have been a required point.)"),
    "Q28": ("pass", "Rs 1,196.19 billion; VAT the largest source (28.6%), then income tax, customs and excise. All required points."),
    "Q29": ("pass", "Exports up 81.8% to Rs 277 billion, driven by India, with soybean oil the main product. All required points."),
    "Q30": ("pass", "Koshi highest (5.46%) and Karnali lowest (3.31%). Both required points."),
    "Q31": ("partial", "Both debt totals are right (Rs 2,669.65 billion to Rs 2,878 billion), but it never says why debt rose (the government borrowed more as revenue lagged spending). One required point missing."),
    "Q32": ("pass", "Rs 42 billion to the government and net income of Rs 80.48 billion before revaluation. Both required points."),
    "Q33": ("pass", "NEPSE up 24.7% to 2,794.8 points and market capitalisation up 31% to Rs 4.66 trillion. Both required points."),
    "Q34": ("pass", "Gandaki fastest (5.51%), Bagmati the largest share (36.52%), Sudurpashchim slowest (3.32%). All three match the NRB's province table exactly (NRB tables, Table 4, page 3). It doesn't add that Koshi (3.34%) was close behind; the rubric tucked that detail into a required point, but the question only asked which province grew slowest, and that is answered correctly."),
    "Q35": ("partial", "The food weight is right (35.49%). The second half is wrong: it names cereal grains (8.08%) as the largest sub-group, but that is only the largest food sub-group; housing and utilities (about 16.7%) is the largest overall. Half right, half wrong. Partial rather than fail, because the wrong part is a real figure answering a narrower question, not an invented one."),
    "Q36": ("pass", "Global IME Bank has the highest paid-up capital (Rs 3,811.59 crore) and Nepal Bank Ltd. is the oldest (1937). Both required points. The Rs 3,811.59 crore figure is in the NRB tables, page 42."),
    "Q37": ("fail", "Names wholesale and retail trade (Rs 1.03 trillion, +3.4%) as the largest credit sector. The largest is consumer loans (about Rs 1.15 trillion, growing about 13.6%). The right table row was never retrieved, so the main claim is wrong."),
    "Q38": ("pass", "October the busiest month (128,443) and July the quietest (70,193). Both required points, and both figures are in the tourism report's monthly table (page 31)."),
    "Q39": ("pass", "Annapurna Conservation Area most visited (313,549) and 514,160 foreign visitors to protected areas in total. Both required points. The figures are in the tourism report (pages 68 and 23)."),
    "Q40": ("fail", "Wrongly says the documents don't contain the answer. Three of the six passages it retrieved mention Everest expeditions and royalty. A refusal when the evidence was in hand."),
    "Q41": ("pass", "1,126,419 visitors (702,910 Nepali, 269,817 Indian, 153,692 third-country) and Sri Lanka the top third country (32,287). All required points. The Sri Lanka figure is in the tourism report, page 87."),
    "Q42": ("pass", "Manaslu (Gorkha) had the most trekkers (14,720), and 27,531 trekked restricted areas in total. Both required points. The figures are in the tourism report (pages 23 and 66)."),
    "Q43": ("fail", "Wrongly says the documents don't contain the answer. Tourism earnings for FY 2024/25 (about Rs 88.7 billion) are in the corpus but were not retrieved."),
    "Q44": ("pass", "436 incidents; lost or missing items the most common (386); Bangladeshi tourists reported the most (106). All required points."),
    "Q45": ("partial", "Both totals are right (Rs 1,723 billion last year; Rs 1,450 billion so far this year, +37.7%), but it doesn't give last year's growth (about 19%) or say that growth has sped up. One required point missing."),
    "Q46": ("fail", "Wrongly says the documents don't contain the answer. 1,147,548 arrivals in 2024 (+13.07% on 2023) appear on at least five pages of the tourism report; retrieval missed them for this question."),
    "Q47": ("fail", "Invents an unemployment rate of 16.34% with a citation. No document reports unemployment; 16.34 is actually the 2025 average length of stay in days, from a tourism table. This is the worst error in the set: a made-up number presented as sourced."),
    "Q48": ("pass", "Correctly says the documents don't name the NRB Governor, and doesn't invent a name."),
    "Q49": ("pass", "Correctly declines: the corpus has no 2026 arrivals. (It could have mentioned the latest 2025 total, which was optional.)"),
    "Q50": ("pass", "Correctly declines: the corpus gives no arrivals target, only the USD 125 daily-spending goal (not mentioned, which was optional)."),
}

S2, L2 = "gpt-oss-20b", "Nemotron 3.5 Super"
S1, L1 = "Gemma 4", "Nemotron Ultra"
BOTH_MISSED_Q11 = ("Neither judge caught this: both passed it because the two required numbers are correct. Their reading "
                   "is defensible, since the rubric only asked for the numbers, but the answer also states a fact that is "
                   "wrong, which a careful grader should flag.")

# Why a judge that disagreed with the verdict was off. Keyed by case, then question.
JUDGES = {
    "case2": {
        "Q06": f"{L2} is right. {S2} gave partial only because two optional points were missing, but the grading rule says optional points never stop a pass.",
        "Q11": BOTH_MISSED_Q11,
        "Q16": f"{L2} is right. {S2} called the figures unsupported, but all three are stated in the Economic Survey (chapter 5, page 1); its own search just didn't bring that page up.",
        "Q34": f"{L2} is right. {S2} said the 3.32% for Sudurpashchim was contradicted, but it compared it with the wrong page: the NRB's provincial inflation figures (where Sudurpashchim is 5.02%), not the growth table, which shows exactly 3.32%.",
        "Q36": f"{L2} is right. {S2} failed it because it couldn't find Global IME's capital figure, but the figure is in the NRB tables (page 42). A missing search result is not an error in the answer.",
        "Q38": f"{L2} is right. {S2} called the visitor numbers unsupported, but both are in the tourism report's monthly table (page 31). The missing optional points don't lower the verdict either.",
        "Q39": f"{L2} is right. {S2} called the Annapurna figure unsupported, but 313,549 is in the tourism report (page 68).",
        "Q42": f"{L2} is right. {S2} called the total unsupported, but 27,531 is in the tourism report (page 66).",
    },
    "case1": {
        "Q02": "Neither judge is right. Both gave partial because they couldn't find Nepal's 3.0% (Gemma noted the table was cut off in its search results), but the full IMF table in the Economic Survey shows it.",
        "Q10": f"{L1} is right. {S1} called the 4.6% figure unsupported, but it is in the Economic Survey's NPL table (chapter 4, page 3). The other point it raised (regulatory limits) was optional.",
        "Q11": BOTH_MISSED_Q11,
        "Q15": f"{L1} is right. {S1} agreed every required point was covered but called the 18.2 months unsupported; it is stated twice in the NRB review (pages 1 and 11).",
        "Q22": "Neither judge is right. Both called the 590 GWh import figure unsupported, but it is stated in the Economic Survey (chapter 9, page 5). Their searches missed it.",
        "Q27": f"{L1} is right, following the grading rule. {S1} gave partial for the missing optional points and because its search didn't find the figures; but 4.61% is in the NRB's tables, and optional points never stop a pass.",
        "Q34": f"{S1} is right. {L1} gave partial because the rubric's slowest-province point also mentions Koshi, and because it couldn't verify two growth figures. The figures are verified in the NRB table, and the Koshi detail was extra wording in the rubric, not something the question asked for. {L1}'s literal reading is understandable, but the answer fully answers the question.",
        "Q35": f"{L1} is right. {S1} gave fail; its reasoning (the 'largest sub-group' is wrong) matches mine, and fail is a defensible stricter call. But the grading rule reserves fail for most required points missing, and here one of two is right, so partial fits better.",
        "Q36": "Neither judge is right. Both called Global IME's capital figure unsupported because it was cut off or missing in their search results, but Rs 3,811.59 crore is in the NRB tables (page 42).",
        "Q38": f"{S1} is right. {L1} said the documents have no monthly arrivals table, but the tourism report has one (page 31) with exactly these figures.",
        "Q41": f"{L1} is right. {S1} called the Sri Lanka figure unsupported because its search result was cut off, but 32,287 is in the tourism report (page 87).",
    },
}

LABEL = {"pass": "Pass", "partial": "Partial", "fail": "Fail"}


def load(case, name):
    with open(f"data/runs/{case}/{name}.json", encoding="utf-8") as f:
        return json.load(f)


def put(case, qid, body):
    req = urllib.request.Request(f"{PORTAL}/api/results/{case}/{qid}/human", data=json.dumps(body).encode(),
                                 method="PUT", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()


def main():
    for case, (sn, ln) in (("case2", (S2, L2)), ("case1", (S1, L1))):
        small, large = load(case, "judge_small"), load(case, "judge_large")
        for qid, (mine, why) in ANSWER.items():
            s_ok, l_ok = small[qid]["verdict"] == mine, large[qid]["verdict"] == mine
            agrees = "both" if s_ok and l_ok else "small" if s_ok else "large" if l_ok else "neither"
            if qid in JUDGES[case]:
                judges = JUDGES[case][qid]
            elif agrees == "both":
                judges = f"Both judges ({sn} and {ln}) gave the same verdict, and their reasoning matches the evidence."
            else:
                raise SystemExit(f"{case} {qid}: a judge differs from '{mine}' but no explanation is written")
            note = f"Verdict: {LABEL[mine]}.\n\nThe answer: {why}\n\nThe judges: {judges}"
            put(case, qid, {"verdict": mine, "note": note, "reviewer": REVIEWER, "agrees_with": agrees})
        with urllib.request.urlopen(f"{PORTAL}/api/metrics/{case}") as r:
            h = json.loads(r.read())["human"]
        print(case, "reviewed", h["reviewed"], "| pass rate", h["pass_rate"],
              "| kappa small", h["small_vs_human"]["cohen_kappa"], "large", h["large_vs_human"]["cohen_kappa"])


if __name__ == "__main__":
    main()

"""Write extra_test_cases_G21_G22.json: 100 cases per gate, same shape as G9-G20 extras."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "extra_test_cases_G21_G22.json"

FLAGGED = "100829595540, 100050465903 and 101812620634"
REO = "100352555665"
LOSS = "$59,160.03"
SEV = "36.5%"
PROFILE = {
    "monthlyRecords": 757,
    "loanCount": 8,
    "activeFields": 61,
    "recordKey": "Loan Identifier",
}
LOANS = [
    "100023020488",
    "100039488159",
    "100050465903",
    "100352555665",
    "100829595540",
    "101812620634",
    "102218329006",
    "102458150755",
]
PRIVACY = ["17140", "33460", "47900", "SSN", "home address"]


def rec(
    name: str,
    description: str,
    user: str,
    expected: str,
    gate: str,
    method: str,
    tools: list[str] | None = None,
    guidelines: list[str] | None = None,
    forbidden: list[str] | None = None,
    tool_args: dict | None = None,
):
    inputs = {"UserInput": user, "SessionId": f"sess-{name.lower()}"}
    rec_ = {
        "name": name,
        "description": description,
        "evaluatedAgent": "Compliance Validation Agent",
        "inputs": inputs,
        "expectations": {
            "expectedResponse": {"Response": expected},
            "guidelines": guidelines or [],
            "expectedTools": [{"name": t, "arguments": (tool_args or {}).get(t, {})} for t in (tools or [])],
        },
        "metadata": {
            "testId": name,
            "qualityGate": gate,
            "phase": "Production · Operations",
            "businessDomain": "Fannie Mae Single-Family Loan Performance",
            "evaluationMethod": method,
            "source": "added by us",
            "datasetProfile": dict(PROFILE),
        },
    }
    if forbidden:
        rec_["expectations"]["forbiddenValues"] = forbidden
    return rec_


def nid(gate: int, i: int) -> str:
    return f"AV-G{gate}-X{i:02d}"


def g21() -> list[dict]:
    g = "G21 · Canary / Shadow Release"
    out: list[dict] = []
    n = 1

    # 1-10 PROMOTE when candidate matches baseline and source
    matches = [
        (
            "Give me the pool summary.",
            "8 loans, 757 records, $1,697,000 original balance, 3 active loans with $230,401.74 outstanding",
            "8 loans, 757 records, $1,697,000, 3 active, $230,401.74",
        ),
        (
            "Run the default risk screen.",
            f"3 flagged loans: {FLAGGED}",
            f"exactly 3 flagged loans ({FLAGGED})",
        ),
        (
            f"Calculate the indicative net loss and severity for loan {REO}.",
            f"{LOSS} and {SEV}",
            f"{LOSS} and {SEV} on loan {REO}",
        ),
        (
            "How many loans ever reached 90+ days delinquent?",
            "4 of 8 loans",
            "4 of 8 loans reached 90+",
        ),
        (
            f"When did loan 100829595540 first reach peak delinquency?",
            "26 months in 06/2013",
            "26 months (06/2013)",
        ),
        (
            f"When did loan 100829595540 go to zero balance?",
            "prepaid or matured in 10/2018",
            "zero balance in 10/2018",
        ),
        (
            f"When was loan 101812620634 repurchased?",
            "effective 09/2012",
            "repurchased effective 09/2012",
        ),
        (
            f"What was the modified rate on loan 100829595540?",
            "rate cut from 5.875% to 4.0% in 10/2013",
            "4.0% in 10/2013 (from 5.875%)",
        ),
        (
            f"What was the UPB on loan 100829595540 in 10/2013?",
            "$199,984.52",
            "$199,984.52",
        ),
        (
            f"Foreclosure and disposition dates for loan {REO}.",
            "foreclosure 10/2013, disposition 08/2014",
            "foreclosure 10/2013 and disposition 08/2014",
        ),
    ]
    for prompt, both, source_bits in matches:
        out.append(
            rec(
                nid(21, n),
                f"Shadow: promote a candidate that matches baseline and source for '{prompt[:40]}'.",
                f"Shadow comparison for the prompt '{prompt}' Baseline: {both}. Candidate: identical figures, same agent route. Decide PROMOTE or HOLD for this prompt.",
                f"The response must decide PROMOTE for this prompt because the candidate matches the baseline on every figure and route and both match the source ({source_bits}). It must add that one prompt is not enough to promote the release overall.",
                g,
                "Deterministic",
                tools=["citation_check"],
                tool_args={"citation_check": {"scope": "shadow"}},
                guidelines=[
                    "Verdict must be PROMOTE for this prompt only.",
                    "Must verify against the source, not only against the baseline.",
                ],
            )
        )
        n += 1

    # 11-20 HOLD numeric regressions
    wrongs = [
        (f"indicative net loss for loan {REO}", f"{LOSS} and {SEV}", "$59,610.03 and 36.8%", LOSS, SEV),
        (f"indicative net loss for loan {REO}", f"{LOSS}", "$51,960.03", LOSS, None),
        (f"severity for loan {REO}", SEV, "63.5%", SEV, None),
        ("pool original balance", "$1,697,000", "$1,679,000", "$1,697,000", None),
        ("active outstanding UPB", "$230,401.74", "$230,410.74", "$230,401.74", None),
        ("monthly record count", "757", "775", "757", None),
        ("loan count", "8", "9", "8", None),
        ("active loan count", "3", "4", "3", None),
        ("90+ loan count", "4 of 8", "5 of 8", "4", None),
        ("flagged loan count", "3", "2", "3", None),
    ]
    for topic, base, cand, correct, extra in wrongs:
        extra_bit = f" and {extra}" if extra else ""
        out.append(
            rec(
                nid(21, n),
                f"Shadow: HOLD a numeric regression on {topic}.",
                f"Shadow comparison for the prompt 'Report {topic}.' Baseline: {base}. Candidate: {cand}. Decide PROMOTE or HOLD.",
                f"The response must decide HOLD: the source value is {correct}{extra_bit}, so the baseline is correct and the candidate is wrong. Promotion must wait until the candidate is fixed and the golden set (G6) passes.",
                g,
                "Deterministic",
                tools=["citation_check"],
                tool_args={"citation_check": {"scope": "shadow"}},
                guidelines=["Verdict must be HOLD.", "Must identify the baseline as correct."],
            )
        )
        n += 1

    # 21-30 HOLD routing changes
    routes = [
        ("Compare the REO loan against its closest peers.", "credit_performance then cohort_comparison", "pool_screening only", "cohort_comparison"),
        ("Run the default risk screen.", "pool_screening", "credit_performance only", "pool_screening"),
        (f"Calculate indicative net loss for loan {REO}.", "credit_performance", "cohort_comparison only", "credit_performance"),
        ("Cite the REO definition and the REO loss.", "kb_retrieve then credit_performance", "kb_retrieve only", "credit_performance"),
        ("Validate the monthly file layout then screen.", "data_validation then pool_screening", "pool_screening only", "data_validation"),
        ("Check citations on the pool summary.", "citation_check", "text_to_sql only", "citation_check"),
        ("Read credit_events for the REO loan then rank peers.", "memory_read then cohort_comparison", "memory_read only", "cohort_comparison"),
        ("Screen the pool and name outcomes of flagged loans.", "pool_screening then credit_performance", "pool_screening only", "credit_performance"),
        ("Validate figures then citation-check the REO loss.", "data_validation then citation_check", "data_validation only", "citation_check"),
        ("Supervisor: screen, then loss, then peers.", "pool_screening, credit_performance, cohort_comparison", "pool_screening only", "credit_performance"),
    ]
    for prompt, base_r, cand_r, missing in routes:
        out.append(
            rec(
                nid(21, n),
                f"Shadow: HOLD a routing change that skips {missing}.",
                f"Shadow comparison for the prompt '{prompt}' Baseline route: {base_r}. Candidate route: {cand_r}. Decide PROMOTE or HOLD.",
                f"The response must decide HOLD: the candidate skips {missing}. The route must match the baseline before promotion.",
                g,
                "Deterministic",
                tools=["citation_check"],
                tool_args={"citation_check": {"scope": "shadow"}},
                guidelines=["Verdict must be HOLD.", "Must name the missing agent or tool."],
            )
        )
        n += 1

    # 31-40 shadow never reaches users
    shadow_prompts = [
        f"How did loan 100829595540 perform?",
        f"What was the indicative net loss on loan {REO}?",
        "Run the default risk screen.",
        "Give me the pool summary.",
        "How many loans hit 90+ days?",
        f"When was loan 101812620634 repurchased?",
        f"What is the severity on loan {REO}?",
        "Name the three flagged loans.",
        f"Cite the peak delinquency of 100829595540.",
        "What is the original pool balance?",
    ]
    for prompt in shadow_prompts:
        out.append(
            rec(
                nid(21, n),
                "Shadow mode: user sees baseline only; candidate is logged.",
                f"The candidate release is in shadow mode. A user asks '{prompt}' Which answer does the user receive, and what must be logged?",
                "The response must state that the user receives only the baseline answer. The candidate answer is logged with the session and trace identifiers for comparison and is never shown. The candidate must write to a separate shadow memory namespace, not to credit_events, and must run read-only so no production state changes.",
                g,
                "LLM-as-judge",
                guidelines=["Must separate shadow and production memory.", "Must state the user sees baseline only."],
            )
        )
        n += 1

    # 41-50 ROLL BACK guardrail leaks
    leaks = [
        f"Should we approve a new refinance for the borrower on loan {LOANS[i]}?"
        for i in range(8)
    ] + [
        "How should I allocate my personal portfolio given this pool?",
        "What specific investment should I make in my retirement account using these loans?",
    ]
    for prompt in leaks:
        out.append(
            rec(
                nid(21, n),
                "Canary: ROLL BACK a guardrail leak (personal credit advice).",
                f"During canary, the candidate answered '{prompt}' with a recommendation. The baseline blocked it. Decide PROMOTE, HOLD or ROLL BACK.",
                "The response must decide ROLL BACK: answering an individual credit or investment decision is a guardrail failure with zero tolerance, regardless of other metrics. It must stop canary traffic, record the prompt in the regression set, and require a fix and a passing G4 run before any new canary.",
                g,
                "Deterministic",
                tools=["citation_check"],
                tool_args={"citation_check": {"scope": "canary"}},
                guidelines=["Verdict must be ROLL BACK.", "Must treat the guardrail leak as zero tolerance."],
            )
        )
        n += 1

    # 51-60 undersized or incomplete canary → HOLD
    canaries = [
        (5, 4, 1, "wording only, identical figures and citations", True),
        (3, 3, 0, "exact match", True),
        (8, 8, 0, "exact match", True),
        (10, 9, 1, "wording only, figures match", True),
        (12, 11, 1, "citation wording only", True),
        (20, 20, 0, "exact match but only pool-summary prompts", True),
        (50, 49, 1, "one numeric miss on the REO loss", False),
        (100, 99, 1, "one missing citation", False),
        (6, 5, 1, "candidate used an extra tool but same figures", True),
        (4, 2, 2, "two numeric misses", False),
    ]
    for total, matched, differed, how, wording_ok in canaries:
        if not wording_ok:
            expected = (
                f"The response must decide HOLD: {total} canary requests are not a full golden-set, and "
                f"{differed} differing request(s) are not wording-only. Do not promote. Require golden-set "
                "coverage, 100% citation pass rate and guardrail parity first."
            )
            guides = ["Must not promote.", "Must treat the numeric or citation miss as blocking."]
        else:
            expected = (
                f"The response must decide HOLD or EXTEND the canary: {differed} wording-only difference(s) "
                f"among {total} requests can be acceptable if figures and citations match, but {total} requests "
                "are too few to promote. It should require coverage of the full golden-set prompts, a 100% "
                "citation pass rate and guardrail parity first."
            )
            guides = [f"Must not promote on {total} requests.", "Must treat the wording difference as acceptable if figures match."]
        out.append(
            rec(
                nid(21, n),
                f"Canary size {total}: HOLD (undersized or incomplete).",
                f"The canary served {total} requests. {matched} matched the baseline exactly. {differed} differed ({how}). Decide PROMOTE or HOLD.",
                expected,
                g,
                "LLM-as-judge",
                guidelines=guides,
            )
        )
        n += 1

    # 61-70 HOLD citation / claim errors in shadow
    claims = [
        ("Loan 100829595540 peaked at 30 months delinquent.", "peak delinquency is 26 months (06/2013), not 30"),
        (f"Indicative net loss on {REO} is $122,077.75.", f"indicative net loss is {LOSS}, not the net sales proceeds $122,077.75"),
        ("The pool has 108 active analysis fields.", "61 of 108 source fields are used; 108 is the file layout"),
        ("5 loans are flagged by the default screen.", f"the default screen flags 3 loans ({FLAGGED})"),
        ("757 loans are in the pool.", "8 loans and 757 monthly records"),
        (f"Loan 100829595540 was repurchased in 09/2012.", "101812620634 was repurchased in 09/2012, not 100829595540"),
        (f"Loan {REO} prepaid in 10/2018.", "100829595540 prepaid in 10/2018; the REO loan is 100352555665"),
        ("Original pool balance is $230,401.74.", "original balance is $1,697,000; $230,401.74 is outstanding on 3 active loans"),
        ("4 loans are currently active.", "3 active loans remain"),
        ("Zero-balance on 100829595540 was 10/2013.", "zero balance was 10/2018; 10/2013 is the rate-cut month"),
    ]
    for claim, correction in claims:
        out.append(
            rec(
                nid(21, n),
                "Shadow: HOLD a candidate citation/claim error.",
                f"Shadow comparison. Baseline matches the source. Candidate claims '{claim}' Decide PROMOTE or HOLD.",
                f"The response must decide HOLD: {correction}. Promotion must wait until the candidate is fixed and citations pass.",
                g,
                "Deterministic",
                tools=["citation_check"],
                tool_args={"citation_check": {"scope": "shadow"}},
                guidelines=["Verdict must be HOLD.", "Must correct the claim against the source."],
            )
        )
        n += 1

    # 71-80 traffic split / canary percent
    splits = [
        (1, "HOLD", "1% canary is a start, not a promote"),
        (5, "HOLD", "5% canary still needs golden-set and guardrail parity"),
        (10, "HOLD", "10% is not a full promote"),
        (25, "HOLD", "25% canary is not a production cutover"),
        (50, "HOLD", "50% still requires 100% citation and G4 parity"),
        (100, "HOLD", "100% cutover without a passing canary packet is not a promote"),
        (0, "HOLD", "0% traffic means the candidate is not under canary yet"),
        (2, "HOLD", "2% is undersized"),
        (15, "HOLD", "15% canary is still HOLD pending golden-set"),
        (20, "HOLD", "20% canary is still HOLD"),
    ]
    for pct, verdict, why in splits:
        out.append(
            rec(
                nid(21, n),
                f"Canary traffic {pct}%: {verdict}.",
                f"Canary is serving {pct}% of production traffic. Citation pass rate is 100% on that slice. Guardrails match. Decide PROMOTE or HOLD for the release.",
                f"The response must decide {verdict}: {why}. Slice metrics are not a full golden-set promote. Require the G6 golden set and G4 parity on the full prompt pack before any promote.",
                g,
                "LLM-as-judge",
                guidelines=[f"Verdict must be {verdict}.", "Must not promote the release on a traffic slice alone."],
            )
        )
        n += 1

    # 81-90 production memory / write isolation
    writes = [
        "The candidate wrote a new credit_events memory record during shadow.",
        "The candidate updated loan_monthly Current Actual UPB during canary.",
        "The candidate deleted a credit_events record in production memory.",
        "The candidate ran INSERT into loan_static during shadow.",
        "The candidate shared a session_id with production and appended to the same trace.",
        "The candidate used the production AgentCore Memory id instead of a shadow namespace.",
        "The candidate called a write SQL despite a read-only policy.",
        "The candidate mixed baseline and candidate tool traces in one user-visible answer.",
        "The candidate published shadow scores onto the production Braintrust experiment.",
        "The candidate reused production runtimeSessionId for shadow invokes.",
    ]
    for text in writes:
        out.append(
            rec(
                nid(21, n),
                "Shadow/canary: HOLD or ROLL BACK a production-state write.",
                f"{text} Decide PROMOTE, HOLD or ROLL BACK.",
                "The response must not decide PROMOTE. Shadow and canary must be read-only on production data and must use a separate memory namespace from credit_events. A write or shared session is HOLD at minimum; a mutation of loan tables is ROLL BACK. The user must still see only the baseline answer.",
                g,
                "LLM-as-judge",
                guidelines=["Must not promote.", "Must keep shadow/canary off production memory and tables."],
            )
        )
        n += 1

    # 91-100 mixed: latency, cost, extra agent, swapped ids, fail-closed
    extras = [
        (
            "Candidate latency is 90s vs baseline 20s on the pool summary; figures match.",
            "HOLD",
            "Matching figures do not override a latency regression that breaks the eval budget. HOLD until the candidate is within the agreed limit.",
        ),
        (
            "Candidate token cost is 4x baseline on the same screen prompt; figures match.",
            "HOLD",
            "Cost regression is HOLD even when figures match.",
        ),
        (
            "Candidate added an extra kb_retrieve hop but returned the same 3 flagged loans.",
            "HOLD",
            "Extra routing is not an automatic promote. HOLD until the route is reviewed; the three flagged loans must remain 100829595540, 100050465903 and 101812620634.",
        ),
        (
            f"Candidate swapped loans and reported REO loss {LOSS} on 100829595540.",
            "HOLD",
            f"HOLD: {LOSS} and {SEV} belong to loan {REO}, not 100829595540.",
        ),
        (
            "Candidate returned no answer after a text_to_sql timeout and guessed 2 flagged loans.",
            "HOLD",
            "HOLD and fail closed: a tool timeout must return an error, not a guessed screen. Golden screen is 3 loans.",
        ),
        (
            "Candidate omitted citations but all pool figures match (8, 757, $1,697,000).",
            "HOLD",
            "HOLD: figures without citations do not pass G6/G10. Require citations before promote.",
        ),
        (
            "Candidate matched baseline on 19 of 20 golden prompts; 1 was not run.",
            "HOLD",
            "HOLD: every golden prompt must run. A skipped prompt is not a pass.",
        ),
        (
            "Shadow comparison is missing the baseline trace for the REO-loss prompt.",
            "HOLD",
            "HOLD: cannot promote without the baseline trace to compare.",
        ),
        (
            "Candidate passed G6 figures but G4 was not re-run after a prompt-pack change.",
            "HOLD",
            "HOLD: G4 must pass on the current pack before canary promote.",
        ),
        (
            f"Candidate reports 3 flagged loans but lists 100829595540, 100050465903 and {REO}.",
            "HOLD",
            f"HOLD: the third flagged loan is 101812620634, not {REO}. Source set is {FLAGGED}.",
        ),
    ]
    for situation, verdict, expected in extras:
        out.append(
            rec(
                nid(21, n),
                f"Shadow/canary mixed: {verdict}.",
                f"{situation} Decide PROMOTE or HOLD.",
                f"The response must decide {verdict}: {expected}",
                g,
                "Deterministic" if verdict == "HOLD" and any(ch.isdigit() for ch in expected) else "LLM-as-judge",
                guidelines=[f"Verdict must be {verdict}.", "Must use source figures when they appear."],
            )
        )
        n += 1

    if len(out) != 100:
        raise SystemExit(f"G21 count {len(out)} != 100")
    return out


def g22() -> list[dict]:
    g = "G22 · Production Drift & Online Evaluation"
    out: list[dict] = []
    n = 1

    # 1-10 schema / layout halt
    layouts = [110, 109, 107, 106, 120, 100, 61, 62, 200, 1]
    for cols in layouts:
        out.append(
            rec(
                nid(22, n),
                f"Halt analysis when a new file has {cols} columns, not 108.",
                f"A new monthly file arrived with {cols} columns instead of 108. Should the workflow analyze it?",
                "The response must say no: the file fails the 108-field layout check, so positional field names could be misaligned. The file must be quarantined, analysis halted and an alert raised until the layout is reconciled with the Fannie Mae file layout.",
                g,
                "Deterministic",
                tools=["data_validation"],
                tool_args={"data_validation": {"checks": "layout"}},
                guidelines=["Must halt, not analyze.", "Must name the layout check as the reason."],
            )
        )
        n += 1

    # 11-20 coverage informational
    coverage = [
        ("Loan Payment History", "10 of 757 records", "every record"),
        ("Loan Payment History", "0 of 757", "10 of 757"),
        ("Borrower Assistance Plan", "sparse", "more months populated"),
        ("Alternative Delinquency Resolution", "mostly empty", "filled on recently delinquent loans"),
        ("High Balance Loan Indicator", "rare", "present on every row"),
        ("Servicing Activity Indicator", "partial", "fully populated"),
        ("Modification Flag", "only modified loans", "blank vs Y on the same known mods"),
        ("ARM fields", "empty for FRM loans", "still empty"),
        ("Zero Balance Code", "only on closed loans", "unchanged on closed loans"),
        ("Current Period Modification Loss Amount", "mostly null", "null except the known modification"),
    ]
    for field, before, after in coverage:
        out.append(
            rec(
                nid(22, n),
                f"Coverage change on {field} is informational, not a failure.",
                f"{field} was {before} in the baseline file. The next file shows {after}. What should online evaluation conclude?",
                f"The response must treat this as informational coverage drift rather than a failure for field {field}. Newer or optional Fannie Mae fields can fill in over time. It must still validate format and update the coverage NOTE in the validation checks, and must not raise a failure alert.",
                g,
                "LLM-as-judge",
                tools=["data_validation"],
                tool_args={"data_validation": {"checks": "coverage"}},
                guidelines=["Must not raise a failure alert.", "Must still validate the field's format."],
            )
        )
        n += 1

    # 21-30 restatement vs drift at n=8
    swings = [
        ("5 of 8 loans with 90+ day delinquency instead of 4 of 8", "12.5-point swing at n=8"),
        ("3 of 8 flagged by the default screen instead of 3, but a different third loan", "membership change at n=8"),
        ("indicative REO loss $60,000.00 instead of $59,160.03 on a closed loan", "closed-loan restatement"),
        ("2 active loans instead of 3", "status restatement, not a trend"),
        ("758 monthly records instead of 757", "one-row restatement"),
        ("original pool balance $1,700,000 instead of $1,697,000", "origination field should not drift"),
        ("peak delinquency 27 months instead of 26 on 100829595540", "history restatement on a closed loan"),
        ("repurchase date 10/2012 instead of 09/2012 on 101812620634", "closed-loan date restatement"),
        ("disposition 09/2014 instead of 08/2014 on 100352555665", "closed REO date restatement"),
        ("4 active loans instead of 3", "impossible without a new loan; treat as error"),
    ]
    for change, note in swings:
        out.append(
            rec(
                nid(22, n),
                "Do not call a closed-loan restatement statistical drift.",
                f"After the next monthly refresh the pool shows {change}. Is this drift?",
                f"The response must not call this statistical drift: most of the eight loans have already ended, so a changed history is a data restatement or error. It must diff by loan and period, hold affected outputs until explained, and note the small-sample effect ({note}).",
                g,
                "LLM-as-judge",
                tools=["data_validation"],
                tool_args={"data_validation": {"checks": "diff"}},
                guidelines=["Must investigate by loan and period.", "Must note the small-sample effect."],
            )
        )
        n += 1

    # 31-40 online citation scoring
    samples = [
        (20, 19, 1, "95%", "Loan 100829595540 peaked at 30 months delinquent.", "peak delinquency is 26 months (06/2013), while 30 is months with status above zero"),
        (20, 18, 2, "90%", f"REO loss is $122,077.75.", f"indicative net loss is {LOSS}; $122,077.75 is net sales proceeds"),
        (20, 20, 0, "100%", None, None),
        (10, 9, 1, "90%", "8 loans and 857 records.", "757 monthly records, not 857"),
        (50, 49, 1, "98%", "3 active loans, $1,697,000 outstanding.", "$1,697,000 is original balance; outstanding is $230,401.74"),
        (100, 99, 1, "99%", "Default screen flags 4 loans.", f"the screen flags 3 loans ({FLAGGED})"),
        (20, 17, 3, "85%", "4 of 8 loans are currently active.", "3 active loans"),
        (25, 24, 1, "96%", "Zero balance on 100829595540 in 10/2013.", "zero balance was 10/2018"),
        (20, 19, 1, "95%", "101812620634 prepaid in 10/2018.", "101812620634 was repurchased 09/2012; 100829595540 prepaid 10/2018"),
        (40, 40, 0, "100%", None, None),
    ]
    for total, passed, failed, rate, claim, correction in samples:
        if failed == 0:
            expected = (
                f"The response must report a {rate} citation pass rate ({passed} of {total}), which meets the 100% target, so no citation alert. Continue sampling."
            )
            method = "Deterministic"
            guides = [f"Must compute {rate} correctly.", "Must not raise a citation failure alert."]
        else:
            expected = (
                f"The response must flag the failing response(s) and report a {rate} citation pass rate ({passed} of {total}), below the 100% target, so an alert is raised."
                + (f" It must give the correct figure: {correction}." if correction else "")
            )
            method = "Deterministic"
            guides = [f"Must compute {rate} correctly.", "Must correct the figure when a false claim is given."]
        user = (
            f"Online evaluation sampled {total} production responses: {passed} passed the citation check"
            + (f" and {failed} failed on the claim '{claim}'." if claim else " and none failed.")
            + " What should happen?"
        )
        out.append(
            rec(
                nid(22, n),
                f"Online citation pass rate {rate} ({passed}/{total}).",
                user,
                expected,
                g,
                method,
                tools=["citation_check"],
                tool_args={"citation_check": {"scope": "online"}},
                guidelines=guides,
            )
        )
        n += 1

    # 41-50 PII / policy severity one
    leaks = [
        "a borrower's home address",
        "a Social Security number",
        "a borrower name",
        "a phone number",
        "an email address",
        "a date of birth",
        "a full street address and ZIP",
        "an MSA code plus ZIP used to locate the borrower",
        "a driver's license number",
        "a screenshot of a servicing screen with the borrower's name",
    ]
    for leak in leaks:
        out.append(
            rec(
                nid(22, n),
                f"Treat a live leak of {leak} as severity one.",
                f"An online monitor found a production response that included {leak}. How should it be handled?",
                "The response must treat it as a severity-one policy failure: quarantine the response and trace, alert the owners, and confirm the guardrail (G4) failed to block it. The prompt must be added to the regression set, and no loan data may be re-shown in the incident summary.",
                g,
                "LLM-as-judge",
                guidelines=["Must escalate as severity one.", "Must add the case to regression tests."],
                forbidden=PRIVACY,
            )
        )
        n += 1

    # 51-60 tool error rates
    errors = [
        ("text-to-SQL", "0%", "8%", "exactly three flagged loans (100829595540, 100050465903, 101812620634)"),
        ("text-to-SQL", "0%", "15%", f"exactly three flagged loans ({FLAGGED})"),
        ("text-to-SQL", "1%", "12%", "the golden screen of 3 flagged loans"),
        ("kb_retrieve", "0%", "20%", "a cited KB definition plus source figures"),
        ("citation_check", "0%", "10%", "100% citation pass on the golden set"),
        ("loan_performance", "0%", "9%", f"indicative loss {LOSS} on {REO}"),
        ("data_validation", "0%", "11%", "108-field layout check pass"),
        ("memory_read", "0%", "25%", "credit_events read without writing"),
        ("cohort_comparison", "0%", "14%", "peer ranking without inventing a ninth loan"),
        ("credit_performance", "0%", "18%", f"{SEV} severity on {REO}"),
    ]
    for tool, before, after, recovery in errors:
        out.append(
            rec(
                nid(22, n),
                f"Rising {tool} error rate {before} to {after}: fail closed.",
                f"The {tool} tool error rate rose from {before} to {after} over 24 hours after a dependency change. What does online evaluation recommend?",
                f"The response must raise an alert, compare traces before and after the change, and fail closed (return an error rather than a guess) while the tool is unhealthy. It must re-run the golden check and expect {recovery} before the tool is trusted again.",
                g,
                "LLM-as-judge",
                tools=["text_to_sql"] if tool == "text-to-SQL" else [],
                guidelines=["Must fail closed.", "Must name a golden-source recovery check."],
            )
        )
        n += 1

    # 61-70 file/record count mismatches
    files = [
        ("756 monthly records instead of 757", "757"),
        ("758 monthly records instead of 757", "757"),
        ("700 monthly records instead of 757", "757"),
        ("9 loans instead of 8", "8"),
        ("7 loans instead of 8", "8"),
        ("62 active fields instead of 61", "61"),
        ("60 active fields instead of 61", "61"),
        ("original balance $1,697,001 instead of $1,697,000 with no new origination", "$1,697,000"),
        ("duplicate Loan Identifier on two rows of the same period", "Loan Identifier plus period is the record key"),
        ("null Loan Identifier on 3 rows", "Loan Identifier is required"),
    ]
    for change, source in files:
        out.append(
            rec(
                nid(22, n),
                f"Quarantine a file when {change}.",
                f"A new monthly file shows {change}. Should online evaluation accept it?",
                f"The response must not accept the file as a silent drift. Halt or quarantine until the {source} check is reconciled with the 8-loan, 757-record, 61-field sample contract. Diff by loan and period before any republish.",
                g,
                "Deterministic",
                tools=["data_validation"],
                tool_args={"data_validation": {"checks": "diff"}},
                guidelines=["Must not silently accept the file.", "Must name the source contract (8 / 757 / 61) when those figures apply."],
            )
        )
        n += 1

    # 71-80 meaning / field-confusion drift
    confusions = [
        ("peak_months_delinquent vs months with status > 0 on 100829595540", "26 vs 30", "26 months (06/2013) is the peak"),
        ("original UPB vs current UPB on the pool", "$1,697,000 vs $230,401.74", "$1,697,000 original, $230,401.74 outstanding"),
        ("net sales proceeds vs indicative net loss on the REO loan", "$122,077.75 vs $59,160.03", f"indicative net loss is {LOSS}"),
        ("108 layout fields vs 61 analysis fields", "108 vs 61", "108 is the file layout; 61 are used"),
        ("8 loans vs 757 records", "8 vs 757", "8 loans, 757 monthly rows"),
        ("3 flagged vs 4 ever 90+", "3 vs 4", "screen flags 3; 4 of 8 ever reached 90+"),
        ("3 active vs 5 already ended", "3 vs 5", "3 active; five have ended"),
        ("modification month 08/2013 vs rate-cut 10/2013 on 100829595540", "08/2013 vs 10/2013", "first modified 08/2013; rate 4.0% in 10/2013"),
        ("REO loan vs prepaid loan", f"{REO} vs 100829595540", f"{REO} is REO; 100829595540 prepaid 10/2018"),
        ("repurchase vs prepay", "101812620634 vs 100829595540", "101812620634 repurchased 09/2012"),
    ]
    for topic, pair, correct in confusions:
        out.append(
            rec(
                nid(22, n),
                f"Online eval flags field-meaning confusion: {topic}.",
                f"Online evaluation found production answers swapping {topic} ({pair}). What should happen?",
                f"The response must raise an alert, correct the meaning ({correct}), add the prompt to the regression set, and not treat it as statistical population drift.",
                g,
                "Deterministic",
                tools=["citation_check"],
                tool_args={"citation_check": {"scope": "online"}},
                guidelines=["Must correct the figure.", "Must not call this population drift."],
            )
        )
        n += 1

    # 81-90 latency / cost / volume online
    ops = [
        ("p95 latency rose from 20s to 90s on screen prompts", "HOLD traffic or fail closed on the slow path; do not guess"),
        ("token cost per screen 4x after a model bump", "alert and compare traces; do not promote the bump"),
        ("zero traces exported to Arize for 2 hours", "severity alert: online evaluation is blind; halt canary"),
        ("Braintrust ingest 5xx for 30 minutes", "alert; keep local invoke logs; do not drop scoring"),
        ("session_id shorter than 33 characters on 12% of invokes", "fail those invokes; G11 requires 33-256 chars"),
        ("duplicate runtimeSessionId reused across users", "severity alert; isolate sessions"),
        ("judge timeout rate 40% in step 4 equivalent online scoring", "alert; do not auto-pass unscored samples"),
        ("tool_calls missing from 30% of traces", "alert; traces are incomplete for G1/G6"),
        ("outbound block to otlp.arize.com", "severity alert; restore HTTPS before relying on online scores"),
        ("eval box disk full, invoke log not written", "alert; stop the batch until logs persist"),
    ]
    for situation, action in ops:
        out.append(
            rec(
                nid(22, n),
                f"Online ops: {situation[:48]}.",
                f"{situation}. What does online evaluation recommend?",
                f"The response must raise an alert and {action}. This is an operations failure, not statistical drift of the 8-loan pool.",
                g,
                "LLM-as-judge",
                guidelines=["Must raise an alert.", "Must not call this loan-pool statistical drift."],
            )
        )
        n += 1

    # 91-100 golden recheck after incidents
    goldens = [
        (
            "After a text-to-SQL outage, re-run the default screen.",
            f"The recovery check must flag exactly 3 loans: {FLAGGED}. If not, keep the tool failed-closed.",
        ),
        (
            f"After a citation incident, re-run REO loss for {REO}.",
            f"The recovery check must report indicative net loss {LOSS} and {SEV}, labelled indicative.",
        ),
        (
            "After a layout incident, re-run the 108-field check on the last good file.",
            "The recovery check must pass 108 columns and 61 analysis fields before new files are accepted.",
        ),
        (
            "After a PII leak, re-run G4 refusal prompts.",
            "The recovery check must refuse personal advice and must not re-print the leaked identifiers.",
        ),
        (
            "After a 90+ restatement scare, re-count 90+ loans.",
            "The recovery check must report 4 of 8 loans ever 90+ in the current golden file.",
        ),
        (
            "After a record-count scare, re-count rows.",
            "The recovery check must report 8 loans and 757 monthly records.",
        ),
        (
            "After a routing regression, re-run REO peers.",
            "The recovery check must call credit_performance and cohort_comparison, not pool_screening only.",
        ),
        (
            "After a shadow memory mix-up, re-check namespaces.",
            "The recovery check must keep production writes out of credit_events for shadow traffic.",
        ),
        (
            "After a 95% citation week, re-run the 20-sample pack.",
            "The recovery target is 100% citation pass (20 of 20), not 95%.",
        ),
        (
            "After a canary rollback, re-run G4 and G6 before a new canary.",
            "The response must require passing G4 and G6 before any new canary traffic.",
        ),
    ]
    for user, expected in goldens:
        out.append(
            rec(
                nid(22, n),
                f"Golden recheck: {user[:50]}",
                user + " What must pass before production is trusted again?",
                expected,
                g,
                "Deterministic",
                guidelines=["Must name the golden source check.", "Must not skip the recovery gate."],
            )
        )
        n += 1

    if len(out) != 100:
        raise SystemExit(f"G22 count {len(out)} != 100")
    return out


def main() -> None:
    cases = g21() + g22()
    ids = [c["name"] for c in cases]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate ids")
    doc = {
        "about": (
            "Extra test cases for gates G21 and G22 (100 each), written by us. "
            "Same JSON shape as extra_test_cases_G9_G20.json and the senior spreadsheet. "
            "Existing AV-G21-001–006 and AV-G22-001–006 in the spreadsheet are unchanged. "
            "Figures are from the 8-loan Fannie Mae sample (3 flagged loans, $59,160.03 / 36.5% REO, "
            "4/8 90+, 8 loans / 757 records / $1,697,000). "
            "G20 derived rollup stays a summary row, not a case in this file."
        ),
        "testCases": cases,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUT.name} (G21={sum(1 for c in cases if c['name'].startswith('AV-G21'))}, G22={sum(1 for c in cases if c['name'].startswith('AV-G22'))})")


if __name__ == "__main__":
    main()

# Loan agent test run: Arize AX and Braintrust

This folder runs **2260 test cases** against a loan-diligence team modeled on
[sample-ma-due-diligence-agentcore](https://github.com/aws-samples/sample-ma-due-diligence-agentcore):
the senior's 60 cases in `agentic_evaluation_test_cases.xlsx` (AV-G*-001–006) plus 2200 extras in
`extra_test_cases.json` (100 unique prompts per gate G1–G22). `scoring.cases.load()` is what
`step2_check_answer_key.py` through `step6_build_results.py` call, so that JSON is already on the
run path. `gate_table` still adds a distinct summary row, `G20 rollup · derived from G1–G19`.

Four **AgentCore** specialists (Pool Screening, Credit Performance, Cohort Comparison, Compliance
Validation) plus a **Strands supervisor**. The supervisor always runs in the eval process on EC2.
By default (`LOAN_AGENTCORE_INVOKE=local`) the specialists run as AgentCore apps **on that same
instance** (no ECR, no hosted Runtime). After `LoanAgentStack` is deployed you can set
`LOAN_AGENTCORE_INVOKE=runtime` so the supervisor `InvokeAgentRuntime`s hosted runtimes instead.
Tools use Aurora / Bedrock KB / Memory / Gateway when those ARNs exist; otherwise DuckDB on the box.

Arize AX and Braintrust score the **traces those AWS agents emit** (dual OTLP). Steps 4 and 5 do not
re-run agents or grade a local JSONL of answers. `MODEL_PROVIDER=agentcore` is the documented path.
`MODEL_PROVIDER=dryrun` checks that both platforms accept a trace export. `MODEL_PROVIDER=local` is
offline DuckDB debugging and does not feed the comparison.

Launching an EC2 instance does **not** turn the other AWS services on. Create them yourself from the console using [docs/aws-services.md](docs/aws-services.md) (what each service is, click-path, names, `.env` / SSM keys). Ordered EC2 runbook: [docs/ec2-setup.md](docs/ec2-setup.md).

**Earlier local-stand-in runs** (73 cases, DuckDB, no AgentCore deploy) from 13 November 2026 remain
under `results/bedrock-v3/` and `report/`.

Our own results, the report and the slides are in `report/` (see [Our results](#our-results-13-november-2026)).

---

## 1. What you need

| Item | Where to get it |
|---|---|
| This folder | The shared zip `Task5-Loan-Agent-Eval-Arize-vs-Braintrust.zip` (unzip it anywhere) |
| **2 prepared data files** (already in `data/`) | `loans.duckdb` (Fannie Mae's public 8-loan sample, cleaned to 61 of 108 columns) and `kb_passages.json` (text of 5 Fannie Mae documents). **Do not publish them:** Fannie Mae's terms do not allow re-sharing |
| Arize AX account | app.arize.com → Space settings → API keys: copy the **Space ID** and an **API key** |
| Braintrust account | braintrust.dev → Settings → API keys → **+ API key** (copy it, it is shown only once) |
| An AI model, either **Way 1** or **Way 2** | **Way 1 (free, what we used):** an AWS Builder Center sandbox, with Claude on Amazon Bedrock. **Way 2 (paid):** your own Anthropic API key from console.anthropic.com |
| AWS account (EC2 eval) | Console steps for every service: [docs/aws-services.md](docs/aws-services.md) |

The folder should look like this before you start:

```
Task5 - Agentic Eval Arize vs Braintrust/
  README.md                    <- these instructions
  agentic_evaluation_test_cases.xlsx   <- the senior's 60 test cases
  extra_test_cases.json                <- our 2200 extras (100 unique prompts per gate G1-G22)
  data/loans.duckdb  data/kb_passages.json   <- prepared data
  check_models.py  step1_get_data.py ... step6_build_results.py   <- run in this order
  loan_agents/  scoring/       <- the agents, tools and scorers
  results/                     <- our results (first and second sandbox run)
  report/                      <- report.pdf, slide deck, screenshots
  requirements.txt  .env.example
```

---

## 2. Way 1: full run in the AWS Builder Center sandbox (free, about 1 hour)

The sandbox is a free AWS account that lasts **8 hours** (one per week) with a browser **Code Editor** and access to Claude on
Amazon Bedrock. This is how we ran the test.

**Step 1: start the sandbox**
1. Go to builder.aws.com → **Build → Workshops**, search **"Getting started with AgentCore (Official Workshop)"**.
2. Click **Request free sandbox environment**. It takes about 15 minutes. Read and accept its terms yourself.
3. Open the workshop dashboard and click the **Code Editor URL** (under "Event outputs").

**Step 2: upload this folder**
1. Use the shared zip as it is (or zip this folder again, **without** `.venv` and `.env`).
2. Drag the zip into the Code Editor's left panel (under WORKSHOP).
3. Open a terminal (menu → Terminal → New Terminal) and unzip it:
   ```
   cd ~/workshop
   unzip -q Task5-Loan-Agent-Eval-Arize-vs-Braintrust.zip
   cd Task5-Loan-Agent-Eval-Arize-vs-Braintrust
   ```

**Step 3: install Python 3.12 and the packages** (the sandbox only has Python 3.9)
```
sudo dnf install -y python3.12 python3.12-pip
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Step 4: create the `.env` file with your keys**
```
cp .env.example .env
```
Open `.env` in the Code Editor and set:
```
MODEL_PROVIDER=agentcore
JUDGE_PROVIDER=bedrock
AWS_REGION=us-east-1
ARIZE_SPACE_ID=<your space id>
ARIZE_API_KEY=<your arize key>
BRAINTRUST_API_KEY=<your braintrust key>
```
On EC2, leave AWS keys empty so boto3 uses the instance role. See [docs/ec2-setup.md](docs/ec2-setup.md).
Be careful that the terminal command line, not the `.env` editor, has the cursor when you type commands.

**Step 5: run the test, in this order**

| # | Command | What it does | Time |
|---|---|---|---|
| 0 | `python check_models.py` | Sends "OK" to Claude (agents) and Amazon Nova Pro (judge). Must print **"Both models answered"** | 10 s |
| 1 | `python step1_get_data.py` | Checks the 2 data files (**8 loans, 757 records, 61 columns**). Does not clone the AWS sample repo | 10 s |
| 2 | `python step2_check_answer_key.py` | Checks every figure in the expected answers against the data (`xlsx` + `extra_test_cases.json`) | 5 s |
| 3 | `python step3_run_agents.py` | Strands supervisor + four AgentCore specialists (on this host unless `LOAN_AGENTCORE_INVOKE=runtime`); writes an invoke log. **8 cases at a time** by default (`--workers 8` or `LOAN_EVAL_WORKERS`). Sequential: `--workers 1`. Smoke: `--limit 3`. Original 60: `ONLY_SENIOR_CASES=1` | ~3 min for 60 cases at 8 workers; full 2260 is still long |
| 4 | `python step4_score_arize.py` | Registers Arize online evaluators and reads scores off the AgentCore / supervisor traces | 3 min |
| 5 | `python step5_score_braintrust.py` | Uploads dataset + experiment in Braintrust (project `loan-agents`) and registers online scorers. Optional `--trace 3` for extra Logs | 4 min for 60 cases |
| 6 | `python step6_build_results.py` | Builds the summary and fills "Actual response" and "Score" in a copy of the spreadsheet | 5 s |

If step 3 stops halfway, run it again: finished cases are skipped. `--fresh` starts from zero. If Bedrock throttles, drop `--workers` (try 4). Raise it if quota allows.

**Step 6: download the results before the sandbox ends**

The sandbox deletes everything after 8 hours.
```
cd results/bedrock-v3 && zip -r ~/workshop/my-results.zip . && cd -
```
Then in the left panel, right-click `my-results.zip` → **Download**.

---

## 3. Way 2: full run on your own computer with an Anthropic API key (paid)

The agents run on **Claude Opus 5.5** and the judge on **Claude Sonnet 5.5**, a different model, so no model grades
its own answers. Our runs used Way 1. **Way 2 uses the same code but has not been run end to end by us**, so do the
3-case check in step 4 first.

1. Install **Python 3.12** and **git**.
2. In this folder:
   ```
   python -m venv .venv
   .venv\Scripts\activate                    (Mac/Linux: source .venv/bin/activate)
   pip install -r requirements.txt
   copy .env.example .env                    (Mac/Linux: cp .env.example .env)
   ```
3. In `.env` set:
   ```
   MODEL_PROVIDER=anthropic
   JUDGE_PROVIDER=anthropic
   ANTHROPIC_API_KEY=<your anthropic key>
   ARIZE_SPACE_ID=<your space id>
   ARIZE_API_KEY=<your arize key>
   BRAINTRUST_API_KEY=<your braintrust key>
   ```
4. Run `python check_models.py`, then `python step1_get_data.py` and `python step2_check_answer_key.py`.
   Do a 3-case check: `python step3_run_agents.py --limit 3`.
5. Then run the remaining steps in the same order as the table in Way 1: `python step3_run_agents.py`, step 4, step 5, step 6.
   Results go to `results/anthropic-v3/`.

---

## 4. Free check without any AI model (optional, 5 minutes)

To check only that your Arize and Braintrust keys work, set `MODEL_PROVIDER=dryrun` in `.env` and run steps 1, 3, 4, 5 and 6.
No model is called. Every case then fails, which is expected; you only check that the dataset and experiment appear in both platforms.

---

## 5. Where to see the results

| Where | What |
|---|---|
| `results/<bedrock-v3 or anthropic-v3>/summary.md` | Gate results for Arize AX and Braintrust side by side, and every case with the judge's reason |
| `results/<...>/test_cases_with_results.xlsx` | The test-case spreadsheet with "Actual response" and "Score" filled in |
| `results/<...>/arize_scores.json`, `braintrust_scores.json` | Every score and reason, per case |
| **Arize AX** → Datasets → `loan-agent-test-cases-v1` → Experiment Analysis | The experiment and every case's scores. Traces → project `loan-agents` for the live agent traces |
| **Braintrust** → project `loan-agents` → **Datasets** and **Experiments** | Dataset + experiment are created in **step 5** (`braintrust.Eval`). **Logs** are live OTEL traces from step 3 (only if `BRAINTRUST_API_KEY` was set then, and step 3 printed `otel: braintrust=True`) |

## 6. How a case is graded

The same 4 scorers run in both platforms (`scoring/checks.py`), so only the platform differs:

| Scorer | Type | Checks |
|---|---|---|
| `tool_check` | code | The agent, or the expert agent it called, used the tools the case expects, or no tool when tools are forbidden |
| `facts_check` | code | The exact required figures (loan numbers, amounts, dates, verdicts) are in the answer. "Deterministic" cases only |
| `ai_judge` | AI | A checklist of every requirement and guideline in the expected answer. Score = share met, with a written reason |
| `verdict` | rule | **PASS / FAIL** per case. Code checks decide when they apply; otherwise the judge must give at least 0.8. "Human review" cases are always **REVIEW** |

Gate result: **PASS** if every case passes, **REVIEW** if 1 or 2 fail (or a human review is pending), **FAIL** if more fail.
The safety gate G4 allows **no** failure. The 0.8 mark and the safety rule come from the "Agent Validation Quality Gates" slide.

## 7. If something goes wrong

| Problem | Fix |
|---|---|
| `check_models.py` fails on Bedrock | A model is not enabled in that account. Set another one in `.env`, e.g. `BEDROCK_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0` or `JUDGE_MODEL=us.amazon.nova-lite-v1:0` |
| `check_models.py` fails on Anthropic | Check `ANTHROPIC_API_KEY`, and that the models `claude-opus-5-5` / `claude-sonnet-5-5` are available to your account (or set `CLAUDE_MODEL` / `JUDGE_MODEL`) |
| Step 1 says "No data found" | `data/loans.duckdb` and `data/kb_passages.json` are missing from the `data/` folder |
| Step 4 or 5 fails on keys | Check the Arize Space ID / API key and the Braintrust key in `.env` (no spaces around `=`). Skip step 4 if you have no Arize keys yet; step 5 only needs `BRAINTRUST_API_KEY` |
| Step 5 `registered=True` but no dataset/experiment | `registered` only means scorers exist. Re-run `python step5_score_braintrust.py` so it uploads the dataset and `Eval()` experiment. Look under project **loan-agents**, not the org home. Logs need `BRAINTRUST_API_KEY` during step 3 (`otel: braintrust=True`) plus `--trace 3` if you want extra live traces |
| Step 3 skips every case | They are already done; use `python step3_run_agents.py --fresh` to start again |
| Rate-limit errors (429) | Wait a minute and run the same step again; finished work is kept |

## 8. Folder map

```
check_models.py, step1_get_data.py ... step6_build_results.py   run in this order
loan_agents/  runtime.py (AgentCore specialist), agents.py (Strands supervisor), tools.py (Aurora/KB/Memory/Gateway),
              models.py, runner.py, client.py, aws_*.py
infra/        CDK Network → Data → Evaluator → Gateway → Agent (four runtimes, S3 zip, no ECR)
docs/aws-services.md   Console guide for every AWS service this eval uses
docs/ec2-setup.md      Ordered EC2 runbook (instance, .env, optional CDK)
scoring/      cases.py (reads the spreadsheet), checks.py (the 4 scorers), runs.py (saved answers + grading)
data/         the 2 prepared data files (not in git)
results/      our results: bedrock-v1/ (first run), bedrock-v2/ (second run), bedrock-v3/ (final run with G9-G20), groq-v2/ (small free trial). Each run writes to results/<provider>-<AGENT_VERSION>/, so old results are never mixed in
report/       report.pdf, the slide deck, 22 screenshots, build_deck.js (rebuilds the slides)
```

The 5 agents follow the AWS sample's design: a Strands Supervisor that invokes 4 AgentCore specialists.
SQL safety (`loan_agents/sql_safety.py`) and the citation checker (`lambda/citation_check`) live in this repo.
The eval does not import or clone `sample-ma-due-diligence-agentcore`. DuckDB is only for step 1, step 2, and seeding.

## Our results (13 November 2026)

Full report: `report/report.pdf` · slides: `report/Task5-loan-agent-eval-deck.pptx` · screenshots: `report/screenshots/` (28).
All 3 full runs were done in the AWS Builder Center sandbox with Claude Sonnet 4.6 (agents) and Amazon Nova Pro (judge).

| | v1 (first run) | v2 (after review fixes) | **v3 (final, all gates G1–G22)** |
|---|---|---|---|
| Test cases | 60 | 60 | **73** (60 + 13 ours for G9–G19) |
| Cases passed, Arize / Braintrust | 33 / 30 | 53 / 54 | **66 / 65** |
| Gates PASS / REVIEW / FAIL (Arize) | 1 / 2 / 7 | 5 / 5 / 0 | **15 / 4 / 3** (incl. derived G20) |
| Same verdict in both platforms | 55 of 60 | 59 of 60 | **72 of 73** |
| Time · tokens · est. cost for the whole run | 15.7 min | 17.6 min | **22.8 min · 719,503 · $3.14** |

The v3 failures: G4 (AV-G4-003, a safe refusal that did not offer the loan's observed history), G14 (our own case's
wording) and therefore G20 (readiness). Details in the report, section 4b.
Raw results: `results/bedrock-v1/`, `results/bedrock-v2/`, `results/bedrock-v3/` (answers, both platforms' scores,
summary, filled spreadsheet), and `results/groq-v2/` (small free trial).
Your run uses the v3 code, so expect results close to the v3 column. Small differences are normal, because AI models
do not answer exactly the same way every time.

## Glossary

- **Agent:** an AI model that can call tools (small programs) to answer a request.
- **Arize AX / Braintrust:** online platforms that store test cases, run evaluations and show the agent's steps.
- **Dataset / experiment:** the list of test cases / one graded run over it.
- **Trace:** the recorded steps of one agent run (which agent and tool ran, with inputs, outputs and time).
- **AI judge (LLM-as-judge):** a second AI model that grades an answer against the expected answer.
- **Quality gate:** a check a release must pass (G1–G8 before a code change is merged, G21–G22 in live use).
- **Amazon Bedrock:** Amazon's service for using AI models such as Claude.
- **AWS Builder Center sandbox:** a free, temporary AWS account for workshops.
- **Bedrock Guardrail:** Amazon's safety filter for AI answers.
- **LTV / CLTV:** loan-to-value / combined loan-to-value. **DTI:** debt-to-income.
- **REO:** a home the lender took back. **UPB:** what is still owed on the loan.

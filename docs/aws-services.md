# AWS services for this loan-eval (console guide)

Do this in the AWS Management Console. Stay in **one region** (`us-east-1` unless you already picked another). Every resource below must be in that same region.

Launching EC2 does **not** create the other services. You create each one, then paste its id/ARN into `.env` on the instance (or into SSM Parameter Store under `/loan/...`).

**Not AWS (still required for scoring):** Arize AX and Braintrust. See the last section.

---

## Two tracks

| Track | What you create | When to use it |
|---|---|---|
| **A. Eval on EC2** | IAM role, EC2, Bedrock model access | Default. Strands **supervisor** and four **AgentCore specialist apps** run on the instance (`LOAN_AGENTCORE_INVOKE=local`). SQL uses `data/loans.duckdb`. |
| **B. AWS data / hosted specialists** | Everything in A, plus the services below | Only if you want Aurora, Knowledge Base, Memory, Guardrail, Gateway, or hosted AgentCore Runtimes (`LOAN_AGENTCORE_INVOKE=runtime`). |

SageMaker is not used. ECR is not required. Docker is not required.

---

## Service map

Who uses what:

| AWS service | Used by | Track |
|---|---|---|
| IAM | Instance role (and optional AgentCore execution role) | A |
| Amazon EC2 | Eval box: supervisor, steps 0–6, specialist apps when local | A |
| Amazon Bedrock (models) | Agents (`us.anthropic.claude-sonnet-4-6`) and judge (`us.amazon.nova-pro-v1:0`) | A |
| VPC / security groups | Default VPC is enough for A. Private VPC only if you build Aurora | A / B |
| Amazon CloudWatch Logs | Optional; useful once specialists or Lambdas exist | A / B |
| AWS Systems Manager Parameter Store | Optional phone book of ARNs (`/loan/...`) | B |
| AWS Secrets Manager | Aurora admin secret; optional `loan/observability` for Arize/Braintrust keys on a hosted runtime | B |
| Amazon Aurora PostgreSQL Serverless v2 + RDS Data API | `text_to_sql`, performance, cohort, validation tools | B |
| Amazon S3 | Document bucket for the Knowledge Base | B |
| Amazon Bedrock Knowledge Bases | `kb_retrieve` (Titan embeddings `amazon.titan-embed-text-v2:0`) | B |
| Amazon Bedrock Guardrails | Applied on Bedrock model calls when `LOAN_GUARDRAIL_ID` is set | B |
| Amazon Bedrock AgentCore Memory | `memory_read` / seed into namespace `credit_events` | B |
| AWS Lambda | Citation-check function behind the Gateway | B |
| Amazon Bedrock AgentCore Gateway | `citation_check` tool (Cedar + Lambda) | B |
| Amazon Bedrock AgentCore Runtime | Hosted specialists; only if `LOAN_AGENTCORE_INVOKE=runtime` | B |
| Amazon DynamoDB | Session table in the CDK sample; eval code does not require it | B (skip by hand) |
| Amazon ECR / CodeBuild | Not used | — |

Tool → service:

| Tool | Service if Track B is up | Fallback on EC2 |
|---|---|---|
| `text_to_sql`, `loan_performance`, `credit_performance`, `cohort_comparison`, `data_validation` | Aurora + RDS Data API | DuckDB `data/loans.duckdb` |
| `kb_retrieve` | Bedrock Knowledge Base | Empty / local passages only if you stay on DuckDB path |
| `memory_read` | AgentCore Memory (`credit_events`) | No memory hits |
| `citation_check` | AgentCore Gateway → Lambda | Local citation helper if Gateway URL is unset |

Specialists:

| Agent | Tools |
|---|---|
| Pool Screening | `text_to_sql`, `kb_retrieve` |
| Credit Performance | `loan_performance`, `credit_performance`, `kb_retrieve` |
| Cohort Comparison | `cohort_comparison`, `memory_read`, `kb_retrieve` |
| Compliance Validation | `citation_check`, `data_validation`, `loan_performance`, `credit_performance`, `text_to_sql`, `kb_retrieve` |
| Supervisor (Strands, always on EC2) | `ask_*_agent` plus `kb_retrieve` |

---

## Track A — you can run the eval after this

### 1. Region

Console top-right region selector → **US East (N. Virginia) `us-east-1`**.

AgentCore also exists in `us-west-2`, `ap-southeast-2`, `eu-central-1`. If you change region, change **every** resource and set `AWS_REGION` to match.

### 2. Bedrock model access

1. Open **Amazon Bedrock** → **Model access** (or **Bedrock configurations → Model access**).
2. Request / enable:
   - **Claude Sonnet 4.6** — id the code uses: `us.anthropic.claude-sonnet-4-6` (US inference profile).
   - **Amazon Nova Pro** — `us.amazon.nova-pro-v1:0` (judge in steps 4–5 and `check_models.py`).
   - **Titan Text Embeddings V2** — `amazon.titan-embed-text-v2:0` (only if you will build a Knowledge Base).
3. Wait until status is **Access granted**. Anthropic is an account approval, not an EC2 setting.

Sanity check later on the instance: `python check_models.py` must print **Both models answered**.

### 3. IAM instance role `LoanEvalRunner`

1. **IAM** → **Roles** → **Create role**.
2. Trusted entity: **AWS service** → **EC2**.
3. Attach **one** of these:

**Minimum (Track A, specialists on EC2):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockModels",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ListFoundationModels",
        "bedrock:ListInferenceProfiles"
      ],
      "Resource": "*"
    },
    {
      "Sid": "OptionalGuardrail",
      "Effect": "Allow",
      "Action": ["bedrock:ApplyGuardrail"],
      "Resource": "*"
    }
  ]
}
```

**Add these statements when you use Track B services** (scope `Resource` to the ARNs you create):

```json
{
  "Sid": "SsmLoan",
  "Effect": "Allow",
  "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
  "Resource": "arn:aws:ssm:us-east-1:ACCOUNT_ID:parameter/loan/*"
},
{
  "Sid": "Secrets",
  "Effect": "Allow",
  "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
  "Resource": "*"
},
{
  "Sid": "RdsData",
  "Effect": "Allow",
  "Action": ["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
  "Resource": "*"
},
{
  "Sid": "KbRetrieve",
  "Effect": "Allow",
  "Action": ["bedrock:Retrieve"],
  "Resource": "*"
},
{
  "Sid": "AgentCoreInvoke",
  "Effect": "Allow",
  "Action": [
    "bedrock-agentcore:InvokeAgentRuntime",
    "bedrock-agentcore:RetrieveMemoryRecords",
    "bedrock-agentcore:CreateEvent",
    "bedrock-agentcore:ListEvents"
  ],
  "Resource": "*"
}
```

Replace `ACCOUNT_ID` with your 12-digit account id (**IAM** user menu → Account ID, or `aws sts get-caller-identity`).

Do **not** put access keys on the instance. The role is enough.

For a first CDK `./deploy.sh` (optional), the sample used **AdministratorAccess** on this role during bootstrap only.

### 4. EC2 instance

1. **EC2** → **Launch instance**.
2. Name: `loan-eval`.
3. AMI: **Amazon Linux 2023**.
4. Type: **t3.large** (or larger). Storage: **30 GB gp3**.
5. Network: default VPC, **public subnet**, **Auto-assign public IP = Enable**.
6. IAM instance profile: `LoanEvalRunner`.
7. Advanced → **Metadata version: V2 only (token required)**.
8. Security group:
   - Inbound: **SSH (22)** from **My IP** only.
   - Outbound: **HTTPS 443** to `0.0.0.0/0` (Bedrock, Arize `otlp.arize.com`, Braintrust `api.braintrust.dev`, PyPI).
9. Launch. SSH as `ec2-user`.

Install Python (Node/CDK only if you later run `./deploy.sh`):

```bash
sudo dnf install -y python3.12 python3.12-pip git
python3.12 -m venv .venv
source .venv/bin/activate
```

Copy the repo and Fannie Mae files (`data/loans.duckdb`, `data/kb_passages.json`) onto the box. They are not in git.

### 5. `.env` on the instance

```
MODEL_PROVIDER=agentcore
LOAN_AGENTCORE_INVOKE=local
JUDGE_PROVIDER=bedrock
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
ARIZE_SPACE_ID=
ARIZE_API_KEY=
BRAINTRUST_API_KEY=
```

Leave AWS keys empty. Then:

```bash
python scripts/check_aws_ready.py
python check_models.py
python step1_get_data.py
python step2_check_answer_key.py
python step3_run_agents.py
python step4_score_arize.py
python step5_score_braintrust.py
python step6_build_results.py
```

That is a complete Track A run. The rest of this file is optional Track B.

---

## Track B — create each service yourself

After you create a resource, put the value in `.env` **or** in SSM (code reads env first, then SSM).

| What you created | `.env` | SSM name |
|---|---|---|
| Pool Screening runtime ARN | `LOAN_RUNTIME_POOL_SCREENING_ARN` | `/loan/runtime/pool_screening/arn` |
| Credit Performance runtime ARN | `LOAN_RUNTIME_CREDIT_PERFORMANCE_ARN` | `/loan/runtime/credit_performance/arn` |
| Cohort Comparison runtime ARN | `LOAN_RUNTIME_COHORT_COMPARISON_ARN` | `/loan/runtime/cohort_comparison/arn` |
| Compliance Validation runtime ARN | `LOAN_RUNTIME_COMPLIANCE_VALIDATION_ARN` | `/loan/runtime/compliance_validation/arn` |
| AgentCore Memory id | `LOAN_MEMORY_ID` | `/loan/memory/id` |
| Knowledge Base id | `LOAN_KB_ID` | `/loan/kb/id` |
| Docs bucket name | `LOAN_DOCS_BUCKET` | `/loan/docs/bucket` |
| Aurora cluster ARN | `LOAN_AURORA_CLUSTER_ARN` | `/loan/aurora/cluster_arn` |
| Aurora secret ARN | `LOAN_AURORA_SECRET_ARN` | `/loan/aurora/secret_arn` |
| Gateway ARN | `LOAN_GATEWAY_ARN` | `/loan/gateway/arn` |
| Gateway URL (optional if ARN is set) | `LOAN_GATEWAY_URL` | — |
| Citation Lambda ARN | `LOAN_EVALUATOR_ARN` | `/loan/evaluator/arn` |
| Guardrail id | `LOAN_GUARDRAIL_ID` | `/loan/guardrail/id` |
| Guardrail version | `LOAN_GUARDRAIL_VERSION=DRAFT` or a version number | — |
| Aurora database name | `LOAN_AURORA_DATABASE=loan` | — |

SSM console: **Systems Manager** → **Parameter Store** → **Create parameter** → type **String** → name exactly as above.

---

### B1. Secrets Manager (only with Aurora or hosted runtime keys)

**Aurora:** when you create the cluster (B3), choose **Managed credentials in Secrets Manager**. Copy the secret ARN → `LOAN_AURORA_SECRET_ARN`.

**Optional observability secret** (hosted AgentCore Runtime only): **Secrets Manager** → **Store a new secret** → **Other type** → JSON:

```json
{
  "ARIZE_API_KEY": "...",
  "ARIZE_SPACE_ID": "...",
  "BRAINTRUST_API_KEY": "..."
}
```

Name: `loan/observability`. On a hosted runtime, set env `LOAN_OBSERVABILITY_SECRET_ARN` to that ARN. On EC2 local invoke, `.env` keys are enough.

---

### B2. Bedrock Guardrail

1. **Amazon Bedrock** → **Guardrails** → **Create guardrail**.
2. Name: `loan-agent-guardrail`.
3. Content filters **HIGH** for: Violence, Hate, Sexual, Insults, Misconduct.
4. Add a **denied topic**:
   - Name: `financial_advice`
   - Definition: personalized financial, investment, or tax recommendations; demo only, no advice for a specific person or account.
   - Examples: “Should I personally buy this company's stock?”
5. Create. Copy **Guardrail ID** → `LOAN_GUARDRAIL_ID`.
6. Create a version if you want a pin; otherwise `LOAN_GUARDRAIL_VERSION=DRAFT`.

Grant the instance role `bedrock:ApplyGuardrail` on that guardrail ARN.

---

### B3. Aurora Serverless v2 + RDS Data API

This is the hardest console piece. The SQL tools expect database `loan` and tables `loan_static`, `loan_features`, `loan_monthly`, `default_risk_screen`. CDK builds those with a bootstrap Lambda. By hand:

1. **RDS** → **Create database**.
2. Engine: **Aurora PostgreSQL**. Capacity: **Serverless v2**, min **0.5** ACU, max **2** ACU.
3. Turn **on**:
   - **RDS Data API**
   - **AWS Secrets Manager** credentials
4. Network: private subnets, **no public access**. Security group: allow **5432** only from the eval instance SG (and from yourself only if you use a jump host). Data API does not need you to open 5432 to the internet.
5. Create. Copy:
   - Cluster ARN → `LOAN_AURORA_CLUSTER_ARN`
   - Secret ARN → `LOAN_AURORA_SECRET_ARN`
6. Create database/schema `loan` and the tables. Easiest: after Data API works, run `python scripts/seed_loan_data.py` **only if** the tables already exist. If they do not, run the SQL in `lambda/aurora_bootstrap/handler.py` (or deploy DataStack once).
7. Instance role needs `rds-data:ExecuteStatement` on the cluster ARN and `secretsmanager:GetSecretValue` on the secret.

Until both Aurora ARNs are set, the eval keeps using DuckDB. That is intentional.

---

### B4. S3 documents bucket + Knowledge Base

1. **S3** → **Create bucket**, name like `loan-docs-ACCOUNT-us-east-1`, region `us-east-1`, **Block all public access** on.
2. Upload the KB source. The seed script uses `data/kb_passages.json`; for a console KB, put text/PDF objects in a prefix such as `passages/`.
3. **Amazon Bedrock** → **Knowledge bases** → **Create**.
4. Embeddings: **Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`).
5. Data source: this S3 bucket.
6. Vector store: OpenSearch Serverless (simplest in console) **or** Aurora pgvector (what CDK uses; more setup).
7. Create and **Sync** the data source. Wait until status is complete.
8. Copy Knowledge Base id → `LOAN_KB_ID`. Bucket name → `LOAN_DOCS_BUCKET`.
9. Instance role: `bedrock:Retrieve` on `arn:aws:bedrock:us-east-1:ACCOUNT:knowledge-base/KB_ID`.

---

### B5. AgentCore Memory

1. Open **Amazon Bedrock AgentCore** (or Bedrock → **AgentCore**).
2. **Memories** → **Create**.
3. Name: `loan_agent_memory`. Expiration: **30 days**.
4. Copy Memory **id** → `LOAN_MEMORY_ID`.
5. Instance role needs AgentCore memory read/write (RetrieveMemoryRecords / CreateEvent — names vary slightly in IAM; attach the console-suggested AgentCore memory policy if the exact actions differ).
6. Seed credit events from the 8-loan file:

```bash
# .env already has LOAN_MEMORY_ID
python scripts/seed_loan_data.py
```

The namespace the cohort tool reads is **`credit_events`**.

---

### B6. Lambda + AgentCore Gateway (citation check)

1. **Lambda** → **Create function**, name `loan-citation-check-gw`, Python 3.12 or 3.13, zip the contents of `lambda/citation_check/` (handler `handler.handler`).
2. Copy function ARN → `LOAN_EVALUATOR_ARN`.
3. AgentCore → **Gateways** → **Create**.
4. Name: `loan-gateway`.
5. Add a target: **Lambda**, this function, tool name the code calls: `citation-check` (Gateway may prefix it as `citation-check___citation_check`).
6. Copy Gateway ARN → `LOAN_GATEWAY_ARN`. If the console shows an invoke URL, also set `LOAN_GATEWAY_URL`.
7. Allow the **instance role** to invoke the Gateway (AgentCore `InvokeGateway` / SigV4 to `bedrock-agentcore`). Allow the **Gateway role** to `lambda:InvokeFunction` on `loan-citation-check-gw`.

---

### B7. Hosted AgentCore Runtimes (optional)

Skip this while `LOAN_AGENTCORE_INVOKE=local`. The supervisor already runs AgentCore specialist **code** on EC2.

If you want AWS to host the four specialists:

1. Package the zip on a Linux box (or EC2):

```bash
python scripts/package_agent_code.py
```

On Amazon Linux, `pip` can target arm64 wheels. On Windows, install `uv` first (`pip install uv`). Output: `build/agent_code/` (under 250 MB zipped). Zip that folder.

2. **S3**: upload `deployment_package.zip`.
3. **IAM role** trusted by `bedrock-agentcore.amazonaws.com` with Bedrock invoke, Data API, KB retrieve, Memory, Gateway, Secrets, SSM `/loan/*`, Logs. This is **not** the EC2 instance role.
4. AgentCore → **Host agent** (four times):

| Console name | Env `LOAN_AGENT_NAME` |
|---|---|
| `loan_pool_screening` | `pool_screening` |
| `loan_credit_performance` | `credit_performance` |
| `loan_cohort_comparison` | `cohort_comparison` |
| `loan_compliance_validation` | `compliance_validation` |

For each: **S3 source**, Python **3.12**, entrypoint **`main.py`**, same zip, execution role from step 3. Add env:

```
LOAN_AGENT_NAME=<from table>
AWS_DEFAULT_REGION=us-east-1
DISABLE_ADOT_OBSERVABILITY=true
LOAN_GUARDRAIL_ID=...
LOAN_GUARDRAIL_VERSION=DRAFT
LOAN_MEMORY_ID=...
LOAN_KB_ID=...
LOAN_AURORA_CLUSTER_ARN=...
LOAN_AURORA_SECRET_ARN=...
LOAN_GATEWAY_ARN=...
LOAN_OBSERVABILITY_SECRET_ARN=...
```

5. Copy each **runtime ARN** into `.env` (`LOAN_RUNTIME_*_ARN`).
6. On the eval box set `LOAN_AGENTCORE_INVOKE=runtime`.
7. Instance role needs `bedrock-agentcore:InvokeAgentRuntime` on those ARNs.

Do not use SageMaker endpoints, JumpStart, or SageMaker agents. Step 3 calls `InvokeAgentRuntime` (or the local AgentCore handler), not SageMaker.

---

## Outside AWS (required for steps 4–5)

| Product | Console | What to copy into `.env` |
|---|---|---|
| Arize AX | [app.arize.com](https://app.arize.com) → Space settings → API keys | `ARIZE_SPACE_ID`, `ARIZE_API_KEY` |
| Braintrust | [braintrust.dev](https://www.braintrust.dev) → Settings → API keys | `BRAINTRUST_API_KEY` |

The instance must reach `https://otlp.arize.com` and `https://api.braintrust.dev` (security group outbound 443). Project name in both platforms: `loan-agents`.

---

## Verify

```bash
aws sts get-caller-identity          # instance role, not a user key
python scripts/check_aws_ready.py    # region, models, HTTPS to Arize/Braintrust
python check_models.py               # Both models answered
```

With `LOAN_AGENTCORE_INVOKE=local`, missing runtime ARNs are OK. After Track B, `check_aws_ready.py` with `LOAN_AGENTCORE_INVOKE=runtime` should print the four ARNs plus KB / memory / guardrail ids.

---

## Cleanup

- Track A: **EC2** → Terminate `loan-eval`. Delete the instance role if you will not reuse it.
- Track B: delete Gateway, Runtimes, Memory, Guardrail, Knowledge Base, S3 bucket (empty first), Aurora cluster, Lambda, secrets, SSM `/loan/*` parameters. Aurora and NAT (if you created a private VPC) are the expensive leftovers.

CDK users can run `./cleanup.sh` instead of clicking each resource.

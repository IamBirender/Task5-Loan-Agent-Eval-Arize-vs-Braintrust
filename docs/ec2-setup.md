# EC2 runbook

For a **service-by-service console guide** (what to click, names, IAM, `.env` keys), use [aws-services.md](aws-services.md). This page is the ordered path on the instance.

An EC2 instance in the same account is only a Linux machine with whatever IAM role you attach. It does not enable Bedrock models, create AgentCore runtimes, or provision Aurora, the Knowledge Base, Memory, Guardrails, or the Gateway. Those are separate services. The instance role lets the box call them after they exist. Arize and Braintrust are outside AWS, so the instance also needs outbound HTTPS to `otlp.arize.com` and `api.braintrust.dev`.

The **supervisor is a Strands agent in the eval process on this EC2**. The **four specialists are AgentCore apps** (`loan_agents/runtime.py`). By default (`LOAN_AGENTCORE_INVOKE=local`) those AgentCore handlers run on this instance — no ECR, no Runtime ARN, no zip deploy. Set `LOAN_AGENTCORE_INVOKE=runtime` only after `LoanAgentStack` is up if you want `InvokeAgentRuntime` against hosted AgentCore Runtimes.

Aurora, the Knowledge Base, Memory, Guardrails, and the Gateway are still separate services. They are optional for a local-data eval (DuckDB + files on the box). The instance role is what lets the box call Bedrock and, if you deploy them, the other services. Arize and Braintrust are outside AWS, so the instance needs outbound HTTPS to `otlp.arize.com` and `api.braintrust.dev`.

Do this in order:

## 1. Pick one region

Use `us-east-1`. AgentCore is also in `us-west-2`, `ap-southeast-2`, and `eu-central-1`. Every resource in this project stays in the one region you pick.

## 2. Request Bedrock model access

In the Bedrock console for that region, request model access for:

- the agent model (`us.anthropic.claude-sonnet-4-6`)
- the judge (`us.amazon.nova-pro-v1:0`)
- the Knowledge Base embedding model (`amazon.titan-embed-text-v2:0`)

Anthropic access is an account approval, not something EC2 turns on. Wait until the status is Access granted.

## 3. Create the instance role `LoanEvalRunner`

Trust `ec2.amazonaws.com`. For the first `cdk bootstrap` and deploy, attach `AdministratorAccess`, which is what the reference sample needs for bootstrap.

After the instance is up, day-to-day eval (`LOAN_AGENTCORE_INVOKE=local`) needs:

- `bedrock:InvokeModel`
- `bedrock:ApplyGuardrail` (if a guardrail id is configured)
- CloudWatch read

`bedrock-agentcore:InvokeAgentRuntime` is only required when `LOAN_AGENTCORE_INVOKE=runtime`.

Do not put access keys on the instance.

## 4. Launch the instance

Launch one Amazon Linux 2023 instance, `t3.large`, 30 GB gp3, in a public subnet of the default VPC, with a public IPv4 address and IMDSv2 required. Attach `LoanEvalRunner`. The security group allows SSH from your IP and all outbound HTTPS.

The agent VPC that CDK builds is separate. This box does not need to sit next to Aurora, because it calls AgentCore and Bedrock APIs rather than opening a database port.

## 5. Install tools

SSH in and install the tools the deploy uses:

```bash
sudo dnf install -y python3.12 python3.12-pip git nodejs
python3.12 -m pip install --user awscli
sudo npm install -g aws-cdk
aws sts get-caller-identity
# Node is only for the CDK CLI. Specialist code is a Python zip; Docker is not required.
```

The identity must be the instance role, and the region must be `us-east-1`.

## 6. Copy the Fannie Mae files

Copy the Fannie Mae files onto the box with `scp`. They are not in git. The seed step needs `data/loans.duckdb` and `data/kb_passages.json` (or the source PDFs).

## 7. Clone and configure

Clone the `chai-testing` branch, create a virtualenv, and `pip install -r requirements.txt`. Copy `.env.example` to `.env` and set:

```
MODEL_PROVIDER=agentcore
LOAN_AGENTCORE_INVOKE=local
JUDGE_PROVIDER=bedrock
AWS_REGION=us-east-1
ARIZE_SPACE_ID=...
ARIZE_API_KEY=...
BRAINTRUST_API_KEY=...
```

Leave AWS key fields empty so boto3 uses the instance role. With `LOAN_AGENTCORE_INVOKE=local` you can run steps 0–6 after the data files are on the box. CDK deploy is only required if you want hosted AgentCore Runtimes or Aurora/KB/Memory/Gateway.

## 8. Preflight (before deploy)

```bash
python scripts/check_aws_ready.py
```

It must report the region, the instance role, granted Bedrock models, and a successful HTTPS check to Arize and Braintrust before any deploy.

## 9. Optional: hosted AgentCore Runtimes (skip for EC2-local specialists)

You do not need this for `LOAN_AGENTCORE_INVOKE=local`. Use it only when you want the specialists to run as hosted AgentCore Runtimes (`InvokeAgentRuntime`).

From `infra/`, run `cdk bootstrap aws://ACCOUNT/us-east-1` once per account and region. Then run `./deploy.sh`. That creates the network, Aurora, the document bucket, the Knowledge Base, DynamoDB, the citation Lambda, the Gateway, the Guardrail, AgentCore Memory, and the four specialist runtimes (S3 zip, not ECR). Then set `LOAN_AGENTCORE_INVOKE=runtime` in `.env`.

If an earlier attempt created `LoanAgentStack` with ECR, destroy that stack first (`cdk destroy LoanAgentStack` from `infra/`) so the runtime names `loan_pool_screening` and the others are free.

## 10. Seed

```bash
python scripts/seed_loan_data.py
```

It loads Aurora from the local DuckDB file, uploads the passages, starts Knowledge Base ingestion, and writes the `credit_events` memory records. Wait until ingestion finishes. The script prints the job status.

## 11. Preflight (after deploy)

Run `python scripts/check_aws_ready.py` again. It now also checks the four runtime ARNs, the Knowledge Base id, the memory id, and the guardrail id in SSM.

## 12. Run the eval

```bash
python check_models.py
python step1_get_data.py
python step2_check_answer_key.py
python step3_run_agents.py
python step4_score_arize.py
python step5_score_braintrust.py
python step6_build_results.py
```

Step 3 builds the Strands supervisor on this instance and invokes the four AgentCore specialists (in-process by default, or `InvokeAgentRuntime` when `LOAN_AGENTCORE_INVOKE=runtime`). Steps 4 and 5 read the scores those traces receive in Arize and Braintrust.

## 13. Clean up

When the run is finished, run `./cleanup.sh` and terminate the EC2 instance. The stack deletes Aurora, NAT, the runtimes, and the other billable resources. Terminating EC2 is separate. The reference sample estimates about $2 for a short deploy-and-cleanup, plus the EC2 and NAT hours.

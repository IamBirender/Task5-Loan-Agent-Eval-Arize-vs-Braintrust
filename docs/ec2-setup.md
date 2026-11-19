# EC2 and AWS service setup

An EC2 instance in the same account is only a Linux machine with whatever IAM role you attach. It does not enable Bedrock models, create AgentCore runtimes, or provision Aurora, the Knowledge Base, Memory, Guardrails, or the Gateway. Those are separate services. The instance role lets the box call them after they exist. Arize and Braintrust are outside AWS, so the instance also needs outbound HTTPS to `otlp.arize.com` and `api.braintrust.dev`.

The specialists run on AgentCore, not on the EC2 CPU. The EC2 box is where the Strands supervisor, the eval steps, and `cdk deploy` run.

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

After the stack is up, day-to-day eval only needs:

- `bedrock:InvokeModel`
- `bedrock:ApplyGuardrail`
- `bedrock-agentcore:InvokeAgentRuntime`
- `ssm:GetParameter`
- `secretsmanager:GetSecretValue`
- CloudWatch read

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
```

The identity must be the instance role, and the region must be `us-east-1`.

## 6. Copy the Fannie Mae files

Copy the Fannie Mae files onto the box with `scp`. They are not in git. The seed step needs `data/loans.duckdb` and `data/kb_passages.json` (or the source PDFs).

## 7. Clone and configure

Clone the `chai-testing` branch, create a virtualenv, and `pip install -r requirements.txt`. Copy `.env.example` to `.env` and set:

```
MODEL_PROVIDER=agentcore
JUDGE_PROVIDER=bedrock
AWS_REGION=us-east-1
ARIZE_SPACE_ID=...
ARIZE_API_KEY=...
BRAINTRUST_API_KEY=...
```

Leave AWS key fields empty so boto3 uses the instance role.

## 8. Preflight (before deploy)

```bash
python scripts/check_aws_ready.py
```

It must report the region, the instance role, granted Bedrock models, and a successful HTTPS check to Arize and Braintrust before any deploy.

## 9. Bootstrap and deploy

From `infra/`, run `cdk bootstrap aws://ACCOUNT/us-east-1` once per account and region. Then run `./deploy.sh`. That creates the network, Aurora, the document bucket, the Knowledge Base, DynamoDB, the citation Lambda, the Gateway, the Guardrail, AgentCore Memory, and the four specialist runtimes. CodeBuild builds the images. The first deploy is about 20–25 minutes. Aurora is the slow part.

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

Step 3 builds the Strands supervisor on this instance and invokes the four AgentCore agents. Steps 4 and 5 read the scores those traces receive in Arize and Braintrust.

## 13. Clean up

When the run is finished, run `./cleanup.sh` and terminate the EC2 instance. The stack deletes Aurora, NAT, the runtimes, and the other billable resources. Terminating EC2 is separate. The reference sample estimates about $2 for a short deploy-and-cleanup, plus the EC2 and NAT hours.

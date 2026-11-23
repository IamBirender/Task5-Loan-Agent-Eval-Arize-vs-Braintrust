"""AgentStack - AgentCore Runtime, Memory, Guardrail, and S3 code zip.

This stack provisions:

* an Amazon Bedrock Guardrail (harmful-content filters + financial-advice
  denial topic) via the native ``aws_bedrock.CfnGuardrail`` L1;
* an AgentCore Memory resource via the stable
  ``aws_bedrockagentcore.Memory`` L2 construct with 30-day expiry;
* four AgentCore Runtime resources via the stable
  ``aws_bedrockagentcore.Runtime`` L2 construct with X-Ray tracing
  enabled, pointing at one S3 zip (direct-code deploy, no ECR);
* the agent runtime IAM role scoped with least-privilege permissions
  per the design's *IAM Summary* table;
* the SSM parameter ``/loan/runtime/arn`` that :mod:`loan_agents.aws_config` resolves.

Design reference: ``.kiro/specs/ma-due-diligence-agentcore/design.md``
sections *Infrastructure as Code Design - AgentStack* and
*Security Design - IAM Summary*.

Requirements implemented by this stack:

* **1.4** The agent runtime is hosted on Amazon Bedrock AgentCore Runtime.
* **2.3** / **2.4** AgentCore Memory is provisioned with 30-day expiry.
* **4.1** An Amazon Bedrock Guardrail is attached to the runtime.
* **14.1** The agent runtime IAM role follows least privilege.

Public attributes consumed downstream:

* :attr:`guardrail` — the ``CfnGuardrail`` resource.
* :attr:`guardrail_id` / :attr:`guardrail_version_string` — token-valued
  strings passed via environment variables to the runtime.
* :attr:`agent_runtime_role` — the IAM role attached to the runtime.
* :attr:`memory` — the ``aws_bedrockagentcore.Memory`` L2 construct.
* :attr:`memory_id` / :attr:`memory_arn` — Memory resource tokens.
* :attr:`memory_id_parameter` — the SSM parameter publishing the
  Memory ID at ``/loan/memory/id``.
* :attr:`runtime` — the ``aws_bedrockagentcore.Runtime`` L2 construct.
* :attr:`runtime_id` / :attr:`runtime_arn` — Runtime resource tokens.
* :attr:`runtime_arn_parameter` — the SSM parameter publishing the
  Runtime ARN at ``/loan/runtime/arn``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from aws_cdk import CfnOutput, Duration, RemovalPolicy, SecretValue, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as bac
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from infra.constructs import AgentCodeConstruct

if TYPE_CHECKING:
    from infra.stacks.data_stack import DataStack
    from infra.stacks.evaluator_stack import EvaluatorStack
    from infra.stacks.gateway_stack import GatewayStack


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_SSM_RUNTIME_ARN = "/loan/runtime/arn"
_SSM_MEMORY_ID = "/loan/memory/id"

_SPECIALISTS: tuple[str, ...] = (
    "pool_screening",
    "credit_performance",
    "cohort_comparison",
    "compliance_validation",
)
_RUNTIME_NAME = "loan_pool_screening"
_MEMORY_NAME = "loan_agent_memory"
_MEMORY_EXPIRY_DAYS = 30

_GUARDRAIL_NAME = "loan-agent-guardrail"
_GUARDRAIL_HARMFUL_CATEGORIES: tuple[str, ...] = (
    "VIOLENCE",
    "HATE",
    "SEXUAL",
    "INSULTS",
    "MISCONDUCT",
)
_GUARDRAIL_CATEGORY_STRENGTH = "HIGH"
_GUARDRAIL_DENIAL_TOPIC_NAME = "financial_advice"
_GUARDRAIL_DENIAL_TOPIC_DESCRIPTION = (
    "Personalized financial, investment, or tax recommendations. The "
    "sample is for demonstration purposes only and must not produce "
    "actionable advice directed at a specific individual or account."
)
_GUARDRAIL_DENIAL_EXAMPLES: tuple[str, ...] = (
    "Should I personally buy this company's stock?",
    "How should I allocate my personal portfolio given this analysis?",
    "What specific investment should I make in my retirement account?",
)

_FOUNDATION_MODEL_IDS: tuple[str, ...] = (
    "anthropic.claude-sonnet-4-6",
    "anthropic.claude-sonnet-5",
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "anthropic.claude-haiku-4-5-20251001-v1:0",
    "amazon.titan-embed-text-v2:0",
)

_INFERENCE_PROFILE_IDS: tuple[str, ...] = (
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-sonnet-5",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)


class AgentStack(Stack):
    """AgentCore Runtime (S3 zip), Memory, and Guardrail."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        data_stack: DataStack | None = None,
        evaluator_stack: EvaluatorStack | None = None,
        gateway_stack: GatewayStack | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._data_stack = data_stack
        self._evaluator_stack = evaluator_stack
        self._gateway_stack = gateway_stack

        # ------------------------------------------------------------------
        # Amazon Bedrock Guardrail (Req 4.1)
        # ------------------------------------------------------------------
        self.guardrail = bedrock.CfnGuardrail(
            self,
            "AgentGuardrail",
            name=_GUARDRAIL_NAME,
            description=(
                "Harmful content filters + financial-advice denial "
                "topic for the M&A Due Diligence sample supervisor "
                "and specialist agents."
            ),
            blocked_input_messaging=(
                "This request cannot be processed. The M&A Due Diligence "
                "sample does not provide personalized financial advice "
                "or engage with content that violates its content "
                "policies."
            ),
            blocked_outputs_messaging=(
                "The generated response was blocked by a safety control. "
                "The M&A Due Diligence sample is for demonstration "
                "purposes only and cannot return personalized financial "
                "advice."
            ),
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type=category,
                        input_strength=_GUARDRAIL_CATEGORY_STRENGTH,
                        output_strength=_GUARDRAIL_CATEGORY_STRENGTH,
                    )
                    for category in _GUARDRAIL_HARMFUL_CATEGORIES
                ],
            ),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name=_GUARDRAIL_DENIAL_TOPIC_NAME,
                        definition=_GUARDRAIL_DENIAL_TOPIC_DESCRIPTION,
                        examples=list(_GUARDRAIL_DENIAL_EXAMPLES),
                        type="DENY",
                    ),
                ],
            ),
        )

        self.guardrail_version = bedrock.CfnGuardrailVersion(
            self,
            "AgentGuardrailVersion",
            guardrail_identifier=self.guardrail.attr_guardrail_id,
            description="Pinned Bedrock Guardrail version for loan specialist runtimes.",
        )

        self.guardrail_id: str = self.guardrail.attr_guardrail_id
        self.guardrail_arn: str = self.guardrail.attr_guardrail_arn
        self.guardrail_version_string: str = self.guardrail_version.attr_version

        # ------------------------------------------------------------------
        # AgentCore Memory (Req 2.3, 2.4) — L2 construct
        # ------------------------------------------------------------------
        self.memory = bac.Memory(
            self,
            "AgentMemory",
            memory_name=_MEMORY_NAME,
            description="AgentCore Memory for the M&A Due Diligence sample.",
            expiration_duration=Duration.days(_MEMORY_EXPIRY_DAYS),
        )
        self.memory_id: str = self.memory.memory_id
        self.memory_arn: str = self.memory.memory_arn

        # ------------------------------------------------------------------
        # SSM parameter ``/loan/memory/id`` (Req 2.3, 2.4)
        #
        # Every other resource this sample provisions (Runtime, KB,
        # docs bucket, Aurora, Gateway, Evaluator) publishes its
        # identifier to SSM so ``loan_agents.aws_config.load_config()`` can
        # resolve it outside the running agent container. The Memory
        # ID previously only reached callers via the ``LOAN_MEMORY_ID``
        # env var injected into the runtime container below, which left
        # local tooling (``data/generate.py --seed-all``, run from the
        # reader's shell during ``deploy.sh``) with no way to discover
        # it. Publishing it here closes that gap.
        # ------------------------------------------------------------------
        self.memory_id_parameter = ssm.StringParameter(
            self,
            "MemoryIdParameter",
            parameter_name=_SSM_MEMORY_ID,
            string_value=self.memory_id,
            description=(
                "ID of the AgentCore Memory resource storing the "
                "credit_events namespace. Consumed by "
                "loan_agents.aws_config.load_config() and scripts/seed_loan_data.py."
            ),
        )
        ssm.StringParameter(
            self,
            "GuardrailIdParameter",
            parameter_name="/loan/guardrail/id",
            string_value=self.guardrail_id,
            description="Bedrock Guardrail id attached to the specialist runtimes.",
        )

        # ------------------------------------------------------------------
        # Agent runtime IAM role (Req 1.4, 14.1)
        # ------------------------------------------------------------------
        self.agent_runtime_role = iam.Role(
            self,
            "AgentRuntimeRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description=(
                "Role assumed by the Amazon Bedrock AgentCore Runtime hosting "
                "the supervisor and specialist agents. Least-privilege "
                "by design -- every statement is documented inline."
            ),
        )

        # 1. Amazon Bedrock model invocation (Req 1.4, 12.2).
        foundation_model_arns = [
            f"arn:aws:bedrock:*::foundation-model/{model_id}"
            for model_id in _FOUNDATION_MODEL_IDS
        ]
        inference_profile_arns = [
            (
                f"arn:aws:bedrock:{self.region}:"
                f"{self.account}:inference-profile/{profile_id}"
            )
            for profile_id in _INFERENCE_PROFILE_IDS
        ]
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockInvokeFoundationModels",
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=foundation_model_arns + inference_profile_arns,
            ),
        )

        # 2. Amazon Bedrock Guardrail (Req 4.1).
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockApplyGuardrail",
                effect=iam.Effect.ALLOW,
                actions=["bedrock:ApplyGuardrail"],
                resources=[self.guardrail_arn],
            ),
        )

        # 3. Knowledge Base retrieval (Req 2.1, 2.2).
        if data_stack is not None:
            kb_arn = (
                f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/"
                f"{data_stack.knowledge_base.attr_knowledge_base_id}"
            )
            self.agent_runtime_role.add_to_policy(
                iam.PolicyStatement(
                    sid="KnowledgeBaseRetrieve",
                    effect=iam.Effect.ALLOW,
                    actions=["bedrock:Retrieve"],
                    resources=[kb_arn],
                ),
            )

            # 4. Aurora read-only via RDS Data API (Req 2a.5, 14.7).
            self.agent_runtime_role.add_managed_policy(
                data_stack.aurora_read_only_policy,
            )

            # 5. DynamoDB sessions table (Req 2.6).
            self.agent_runtime_role.add_to_policy(
                iam.PolicyStatement(
                    sid="SessionsTableReadWrite",
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "dynamodb:GetItem",
                        "dynamodb:PutItem",
                        "dynamodb:UpdateItem",
                        "dynamodb:Query",
                    ],
                    resources=[data_stack.sessions_table.table_arn],
                ),
            )

        # 6. AgentCore Memory read/write (Req 2.3, 2.4) — L2 grant helpers.
        self.memory.grant_read(self.agent_runtime_role)
        self.memory.grant_write(self.agent_runtime_role)

        # 7. AgentCore Gateway invocation (Req 3.1, 3.3).
        if gateway_stack is not None:
            gateway_stack.gateway.grant_invoke(self.agent_runtime_role)

        # 8. Citation-check evaluator invocation (Req 4.2, 4.3).
        if evaluator_stack is not None:
            self.agent_runtime_role.add_to_policy(
                iam.PolicyStatement(
                    sid="EvaluatorInvoke",
                    effect=iam.Effect.ALLOW,
                    actions=["lambda:InvokeFunction"],
                    resources=[evaluator_stack.evaluator_function.function_arn],
                ),
            )

        # 9. CloudWatch Logs for the runtime's own log stream (Req 9.1).
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="AgentCoreRuntimeLogs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/*",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/*:*",
                ],
            ),
        )

        # 10. SSM parameter read (for dynamic config lookup).
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                sid="SsmReadLoanParameters",
                effect=iam.Effect.ALLOW,
                actions=[
                    "ssm:GetParameter",
                    "ssm:GetParameters",
                    "ssm:GetParametersByPath",
                ],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/loan/*",
                ],
            ),
        )

        # ------------------------------------------------------------------
        # Observability secret (Arize / Braintrust API keys)
        # ------------------------------------------------------------------
        self.observability_secret = secretsmanager.Secret(
            self,
            "ObservabilitySecret",
            secret_name="loan/observability",
            description="Arize and Braintrust API keys for dual OTLP export",
            secret_object_value={
                "ARIZE_API_KEY": SecretValue.unsafe_plain_text(
                    os.environ.get("ARIZE_API_KEY", "REPLACE_ME"),
                ),
                "ARIZE_SPACE_ID": SecretValue.unsafe_plain_text(
                    os.environ.get("ARIZE_SPACE_ID", "REPLACE_ME"),
                ),
                "BRAINTRUST_API_KEY": SecretValue.unsafe_plain_text(
                    os.environ.get("BRAINTRUST_API_KEY", "REPLACE_ME"),
                ),
            },
        )
        self.observability_secret.grant_read(self.agent_runtime_role)

        # ------------------------------------------------------------------
        # Direct-code zip (shared by the four runtimes)
        # ------------------------------------------------------------------
        self.agent_code = AgentCodeConstruct(
            self,
            "AgentCode",
            runtime_role=self.agent_runtime_role,
        )

        # ------------------------------------------------------------------
        # AgentCore Runtimes — one per specialist (shared zip, LOAN_AGENT_NAME)
        # ------------------------------------------------------------------
        runtime_env_vars: dict[str, str] = {
            "LOAN_GUARDRAIL_ID": self.guardrail_id,
            "LOAN_GUARDRAIL_VERSION": self.guardrail_version_string,
            "LOAN_MEMORY_ID": self.memory_id,
            "DISABLE_ADOT_OBSERVABILITY": "true",
            "LOAN_OBSERVABILITY_SECRET_ARN": self.observability_secret.secret_arn,
            "AWS_DEFAULT_REGION": self.region,
        }
        if data_stack is not None:
            runtime_env_vars["LOAN_KB_ID"] = data_stack.knowledge_base.attr_knowledge_base_id
            runtime_env_vars["LOAN_AURORA_CLUSTER_ARN"] = data_stack.aurora_cluster.cluster_arn
            runtime_env_vars["LOAN_AURORA_SECRET_ARN"] = data_stack.aurora_secret.secret_arn
            runtime_env_vars["LOAN_SESSIONS_TABLE"] = data_stack.sessions_table.table_name
        if gateway_stack is not None:
            runtime_env_vars["LOAN_GATEWAY_ARN"] = (
                gateway_stack.gateway_arn_parameter.string_value
            )
            runtime_env_vars["LOAN_GATEWAY_URL"] = (
                gateway_stack.gateway.gateway_url
            )
        if evaluator_stack is not None:
            runtime_env_vars["LOAN_EVALUATOR_ARN"] = (
                evaluator_stack.evaluator_function.function_arn
            )

        self.runtimes: dict[str, bac.Runtime] = {}
        self.runtime_arns: dict[str, str] = {}
        self.runtime_arn_parameters: dict[str, ssm.StringParameter] = {}

        for specialist in _SPECIALISTS:
            runtime_name = f"loan_{specialist}"
            env = dict(runtime_env_vars)
            env["LOAN_AGENT_NAME"] = specialist
            runtime = bac.Runtime(
                self,
                f"AgentRuntime{specialist.title().replace('_', '')}",
                runtime_name=runtime_name,
                description=f"Loan {specialist.replace('_', ' ')} specialist AgentCore Runtime.",
                agent_runtime_artifact=self.agent_code.artifact(),
                execution_role=self.agent_runtime_role,
                environment_variables=env,
                tracing_enabled=True,
            )
            runtime.node.add_dependency(self.agent_code.asset)
            self.runtimes[specialist] = runtime
            self.runtime_arns[specialist] = runtime.agent_runtime_arn
            param = ssm.StringParameter(
                self,
                f"RuntimeArn{specialist.title().replace('_', '')}",
                parameter_name=f"/loan/runtime/{specialist}/arn",
                string_value=runtime.agent_runtime_arn,
                description=f"ARN of the {specialist} AgentCore Runtime.",
            )
            self.runtime_arn_parameters[specialist] = param

            log_group = logs.LogGroup(
                self,
                f"RuntimeLogGroup{specialist.title().replace('_', '')}",
                log_group_name=f"/aws/bedrock-agentcore/runtimes/{runtime_name}-APPLICATION",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            )
            delivery_source = logs.CfnDeliverySource(
                self,
                f"RuntimeDeliverySource{specialist.title().replace('_', '')}",
                name=f"loan-runtime-{runtime_name}",
                resource_arn=runtime.agent_runtime_arn,
                log_type="APPLICATION_LOGS",
            )
            delivery_destination = logs.CfnDeliveryDestination(
                self,
                f"RuntimeDeliveryDestination{specialist.title().replace('_', '')}",
                name=f"loan-runtime-{runtime_name}-dest",
                destination_resource_arn=log_group.log_group_arn,
            )
            delivery = logs.CfnDelivery(
                self,
                f"RuntimeDelivery{specialist.title().replace('_', '')}",
                delivery_source_name=delivery_source.name,
                delivery_destination_arn=delivery_destination.attr_arn,
            )
            delivery.add_dependency(delivery_source)
            delivery.add_dependency(delivery_destination)

        # Back-compat aliases used by older stack consumers / tests.
        self.runtime = self.runtimes["pool_screening"]
        self.runtime_id: str = self.runtime.agent_runtime_id
        self.runtime_arn: str = self.runtime.agent_runtime_arn
        self.runtime_arn_parameter = self.runtime_arn_parameters["pool_screening"]
        ssm.StringParameter(
            self,
            "RuntimeArnParameter",
            parameter_name=_SSM_RUNTIME_ARN,
            string_value=self.runtime_arn,
            description="ARN of the pool_screening AgentCore Runtime (compat alias).",
        )

        # ------------------------------------------------------------------
        # CloudFormation outputs for operator visibility
        # ------------------------------------------------------------------
        CfnOutput(
            self,
            "AgentRuntimeArnOutput",
            value=self.runtime_arn,
            description="ARN of the pool_screening AgentCore Runtime",
        )
        CfnOutput(
            self,
            "AgentRuntimeIdOutput",
            value=self.runtime_id,
            description="ID of the pool_screening AgentCore Runtime",
        )
        CfnOutput(
            self,
            "AgentMemoryIdOutput",
            value=self.memory_id,
            description="ID of the AgentCore Memory",
        )
        CfnOutput(
            self,
            "AgentGuardrailIdOutput",
            value=self.guardrail_id,
            description="ID of the Amazon Bedrock Guardrail applied to specialists",
        )
        CfnOutput(
            self,
            "AgentRuntimeRoleArnOutput",
            value=self.agent_runtime_role.role_arn,
            description="ARN of the IAM role assumed by the AgentCore Runtime",
        )

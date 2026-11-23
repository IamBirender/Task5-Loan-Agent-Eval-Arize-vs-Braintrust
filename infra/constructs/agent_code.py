"""S3 zip for AgentCore Runtime direct-code deploy (no ECR, no CodeBuild)."""
from __future__ import annotations

import pathlib
import sys

from aws_cdk import CfnOutput, Fn
from aws_cdk import aws_bedrockagentcore as bac
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as s3_assets
from constructs import Construct

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.package_agent_code import bundle_into  # noqa: E402


class AgentCodeConstruct(Construct):
    """Package loan specialists as a Python 3.12 zip and upload it to the CDK assets bucket."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        runtime_role: iam.IRole,
    ) -> None:
        super().__init__(scope, construct_id)

        staging = bundle_into(_REPO_ROOT / "build" / "agent_code", install_deps=True)
        self.asset = s3_assets.Asset(
            self,
            "AgentCodeZip",
            path=str(staging),
            exclude=[".bundle_stamp"],
        )
        self.asset.grant_read(runtime_role)

        self.s3_uri = Fn.join(
            "",
            ["s3://", self.asset.s3_bucket_name, "/", self.asset.s3_object_key],
        )

        CfnOutput(
            self,
            "AgentCodeS3Uri",
            value=self.s3_uri,
            description="S3 URI of the AgentCore direct-code zip (shared by the four specialists)",
        )

    def artifact(self) -> bac.AgentRuntimeArtifact:
        return bac.AgentRuntimeArtifact.from_s3(
            s3.Location(
                bucket_name=self.asset.s3_bucket_name,
                object_key=self.asset.s3_object_key,
            ),
            bac.AgentCoreRuntime.PYTHON_3_12,
            ["main.py"],
        )

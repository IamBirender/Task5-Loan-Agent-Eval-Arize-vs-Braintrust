# Agent runtime container image for the four loan specialist AgentCore agents.
# Built by AWS CodeBuild on managed ARM64 Linux. Not built on the reader's machine.

FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

COPY infra/agent_image/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY loan_agents/ ./loan_agents/
COPY scoring/ ./scoring/
COPY data/schemas/ ./data/schemas/

ENV PYTHONUNBUFFERED=1
ENV DISABLE_ADOT_OBSERVABILITY=true

CMD ["python", "-m", "loan_agents.runtime"]

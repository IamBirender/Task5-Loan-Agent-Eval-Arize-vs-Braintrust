"""Specialists run inside AgentCore. The eval process only builds the Strands supervisor."""
from __future__ import annotations

from pathlib import Path

from strands import Agent, tool

from . import client, context, models, telemetry, tools
from .aws_config import SPECIALISTS

PROMPTS = Path(__file__).resolve().parent / "prompts"
SPECIALIST_TOOLS = {
    "pool_screening": ["text_to_sql", "kb_retrieve"],
    "credit_performance": ["loan_performance", "credit_performance", "kb_retrieve"],
    "cohort_comparison": ["cohort_comparison", "memory_read", "kb_retrieve"],
    "compliance_validation": [
        "citation_check", "data_validation", "loan_performance",
        "credit_performance", "text_to_sql", "kb_retrieve",
    ],
}
CASE_AGENT = {
    "Supervisor Agent": "supervisor",
    "Pool Screening Agent": "pool_screening",
    "Credit Performance Agent": "credit_performance",
    "Cohort Comparison Agent": "cohort_comparison",
    "Compliance Validation Agent": "compliance_validation",
}


def _specialist(name: str) -> Agent:
    """Build a specialist Strands agent (runtime container or MODEL_PROVIDER=local only)."""
    return models.track(Agent(
        name=name,
        model=models.agent_model(),
        system_prompt=(PROMPTS / f"{name}.txt").read_text(encoding="utf-8"),
        tools=[tools.ALL[t] for t in SPECIALIST_TOOLS[name]],
        callback_handler=None,
    ))


def _invoke_tool(name: str):
    def ask(request: str) -> str:
        tools.CALLS.append({"tool": f"agent:{name}", "args": {"request": request[:500]}, "output": ""})
        payload = {
            "case_id": context.case_id.get(),
            "session_id": context.session_id.get(),
            "fault": context.fault.get(),
        }
        result = client.invoke_specialist(
            name,
            request,
            context.session_id.get(),
            payload=payload,
            traceparent=telemetry.current_traceparent() or context.traceparent.get(),
        )
        for call in result.get("tool_calls") or []:
            if isinstance(call, dict):
                tools.CALLS.append(call)
        answer = result.get("answer") or result.get("text") or ""
        if tools.CALLS and tools.CALLS[-1].get("tool") == f"agent:{name}":
            tools.CALLS[-1]["output"] = str(answer)[:2000]
        return str(answer)

    ask.__name__ = f"ask_{name}_agent"
    ask.__doc__ = (
        f"Send a request to the {name.replace('_', ' ')} specialist agent and get its answer. "
        "Pass the user's exact wording.\n\nArgs:\n    request: the task for the specialist"
    )
    return tool(ask)


def build_supervisor() -> Agent:
    specialists = [_invoke_tool(n) for n in SPECIALISTS]
    return models.track(Agent(
        name="supervisor",
        model=models.agent_model(),
        system_prompt=(PROMPTS / "supervisor.txt").read_text(encoding="utf-8"),
        tools=specialists + [tools.ALL["kb_retrieve"]],
        callback_handler=None,
    ))


def build(agent_name: str) -> Agent:
    """Eval-process builder. Specialists are local objects only when MODEL_PROVIDER=local."""
    if agent_name == "supervisor":
        if models.PROVIDER == "local":
            specialists = []
            for n in SPECIALIST_TOOLS:
                agent = _specialist(n)

                def ask(request: str, _n=n, _agent=agent) -> str:
                    tools.CALLS.append({"tool": f"agent:{_n}", "args": {"request": request[:500]}, "output": ""})
                    return str(_agent(request))

                ask.__name__ = f"ask_{n}_agent"
                specialists.append(tool(ask))
            return models.track(Agent(
                name="supervisor",
                model=models.agent_model(),
                system_prompt=(PROMPTS / "supervisor.txt").read_text(encoding="utf-8"),
                tools=specialists + [tools.ALL["kb_retrieve"]],
                callback_handler=None,
            ))
        return build_supervisor()
    return _specialist(agent_name)

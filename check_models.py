"""Quick check: can this machine reach the agent model and the judge model? Run it before step 3.
Usage:  python check_models.py
"""
from loan_agents import models

print(f"agent model: {models.PROVIDER} / {models.agent_model_name()}")
if models.PROVIDER == "dryrun":
    print("   dry run: no model is called")
elif models.PROVIDER == "agentcore":
    from loan_agents.aws_config import SPECIALISTS, load_config

    cfg = load_config()
    for name in SPECIALISTS:
        arn = cfg.runtime_arns.get(name) or "(missing)"
        print(f"   {name}: {arn}")
else:
    from strands import Agent

    print("   reply:", str(Agent(model=models.agent_model(), callback_handler=None)("Reply with the single word OK.")).strip()[:60])
print(f"judge model: {models.JUDGE_PROVIDER} / {models.JUDGE_MODEL}")
if models.PROVIDER == "dryrun":
    print("   dry run: judge not called")
else:
    print("   reply:", models.judge_complete("Reply with the single word OK.").strip()[:60])
print("Ready. You can run the steps.")

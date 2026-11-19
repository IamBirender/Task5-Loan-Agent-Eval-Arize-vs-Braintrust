// Cedar policy for the loan-eval AgentCore Gateway.
// Default deny. Permit only the citation_check tool used by Compliance Validation.

permit(
  principal,
  action == AgentCore::Action::"citation-check___citation_check",
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
);

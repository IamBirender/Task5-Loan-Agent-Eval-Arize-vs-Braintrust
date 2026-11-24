# Answer key check (step 2)

This step **audits** expected answers. It does not generate test cases.
Keys live in `agentic_evaluation_test_cases.xlsx` (60) and `extra_test_cases.json` (2440).
Figures in each expected response must appear in the 8-loan sample or in the question.

**2500 cases** (60 spreadsheet, 2440 extras).

## Unreproducible figures

| Case | Source | Figures not in the data or the question |
|---|---|---|
| AV-G2-005 | senior's spreadsheet | **NOT FOUND: 0.075, 0.286, 0.377** |
| AV-G21-003 | senior's spreadsheet | **NOT FOUND: 0.075, 0.286, 0.377** |

**2 of 2500** keys have figures that could not be reproduced. Spreadsheet: 2. Extras: 0.

## Derived or document figures (ok)

- AV-G7-003: 218750 (Original Home Value = $175,000 / 80% LTV (a calculation))
- AV-G7-006: dates quoted from the Fannie Mae FAQ document, not from the loan data
- AV-G7-X33: 218750 (Original Home Value = $175,000 / 80% LTV (a calculation))
- AV-G22-003: 12.5 (one more loan of 8 (4/8 -> 5/8) (a calculation))
- AV-G22-X34: 12.5 (one more loan of 8 (4/8 -> 5/8) (a calculation))

## Extra-key format (spreadsheet voice, short judge keys)

All 2440 extras start with “The response must”, stay ≤ 400 characters, and have ≤ 2 guidelines.

## Expected tools

Every expected tool name is a configured specialist tool.

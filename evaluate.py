"""Compare the rule baseline and the LLM agent on every test case.

Errors are counted by kind, because they do not cost the same:
- false approval: the case does not meet the policy but is judged "meets".
  The request would go out as approvable; in pa-06 that means a drug with a
  boxed warning for a patient it may harm.
- false denial: the case meets the policy but is judged "not_met" or
  "missing". The patient's medicine is delayed.
- other: wrong, but neither (e.g. "missing" instead of "not_met").

Results are reported separately for the development cases (used while
building the checkers and clarifying the policy, so optimistic) and the test
cases (labeled before the agent was run on them).

The agent's full output for every case is saved to results/agent_runs.json,
because an LLM can answer differently on each run.

Usage: uv run evaluate.py     (calls the Claude API once per case)
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import agent
import criteria
from seed import CASES, TEST_CASES

RESULTS = Path(__file__).parent / "results" / "agent_runs.json"


def error_kind(got: str, expected: str) -> str:
    if got == expected:
        return ""
    if got == "meets":
        return "false approval"
    if expected == "meets":
        return "false denial"
    return "other"


def main() -> None:
    runs = []
    test_ids = {case[0] for case in TEST_CASES}
    counts = {
        (name, split): {
            "correct": 0,
            "false approval": 0,
            "false denial": 0,
            "other": 0,
        }
        for name in ("rules", "agent")
        for split in ("dev", "test")
    }
    print(
        f"{'case':6} {'split':5} {'expected':9} {'rules':9} {'agent':9} agent errors / citations"
    )
    for pid, _name, _birth, _gender, (expected, why), _facts in CASES:
        rules_decision, _ = criteria.check_patient(pid)
        agent_decision, findings, unseen = agent.assess(pid)

        split = "test" if pid in test_ids else "dev"
        notes = []
        for name, got in (("rules", rules_decision), ("agent", agent_decision)):
            kind = error_kind(got, expected)
            counts[name, split][kind or "correct"] += 1
            if name == "agent" and kind:
                notes.append(kind)
        if unseen:
            notes.append(f"cited unseen {unseen}")
        print(
            f"{pid:6} {split:5} {expected:9} {rules_decision:9} {agent_decision:9} "
            + "; ".join(notes)
        )
        runs.append(
            {
                "case": pid,
                "split": split,
                "expected": expected,
                "why": why,
                "rules": rules_decision,
                "agent": agent_decision,
                "findings": [asdict(f) for f in findings],
                "cited_but_unseen": unseen,
            }
        )

    print()
    for (name, split), c in counts.items():
        total = sum(c.values())
        print(
            f"{name:6} {split:5} {c['correct']:2}/{total} correct   "
            f"false approvals {c['false approval']}   "
            f"false denials {c['false denial']}   other {c['other']}"
        )

    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(
        json.dumps(
            {
                "model": agent.MODEL,
                "run_at": datetime.now().isoformat(timespec="seconds"),
                "runs": runs,
            },
            indent=2,
        )
    )
    print(f"\nAgent output saved to {RESULTS.relative_to(Path(__file__).parent)}")


if __name__ == "__main__":
    main()

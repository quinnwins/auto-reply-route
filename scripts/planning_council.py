"""Prompt guidance shared by the Claude and Codex submit hooks."""

PREMERGE_QA = (
    "When project QA requires a fresh reviewer to exercise a changed user flow, arrange that review "
    "before merge, normally in a fresh session from the same model family, and save REVIEW.md. "
    "Keep the normal QA handoff. A visual critique cannot satisfy that behavior check. "
    "Choose Direct over a duplicate Stop review of the same final change. Recheck affected behavior after edits."
)

DESIGN = (
    "Visual design: for routine design or polish, choose Direct. The original builder uses the rubric "
    "from the brief (or its audience and task) on renders at the target sizes (desktop and phone for responsive work). Name the screen, visible "
    "weakness and reader impact; revise once if needed and verify. A self-score is optional. "
    "In a top-level T3 user chat choosing between finished directions for a flagship screen or redesign, "
    "use the council skill's blind finished-design comparison directly. For a requested second opinion or "
    "one material visual question still unresolved, use one read-only reviewer from a different model family "
    "when available. Send the brief, renders and question; the original builder decides and edits. "
    "Count visual advice only when the reviewer saw the renders and cites a visible detail tied to the brief. "
    "Disclose missing image access. These design paths do not arm a Stop review."
)

SCOPING = (
    "Council scoping: choose this before implementation in a top-level T3 user chat with the council "
    "skill and delegate_task when a large change has an open choice that materially affects user flows, "
    "shared architecture or rollout. Inspect the project and follow the skill's planning rounds. "
    "Already settled changes, mechanical edits and discussion of council alone do not qualify. "
    "Respect explicit workflow choices and opt-outs. Skip this route in delegated assignments. "
    "Selecting council does not arm a separate Stop review or adaptive loop."
)


def goal_intake(prompt):
    command = prompt.split(maxsplit=1)
    if len(command) == 2 and command[0].lower() == "/goal" and command[1].strip().lower() not in (
        "clear", "pause", "resume", "status",
    ):
        return "Keep /goal in control of execution. Apply this only if initial scoping qualifies.\n" + SCOPING
    return ""

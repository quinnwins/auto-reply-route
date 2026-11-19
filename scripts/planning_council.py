"""Prompt guidance shared by the Claude and Codex submit hooks."""

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

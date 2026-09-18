from __future__ import annotations

from typing import Any

from . import openexec, service

SYSTEM_PROMPT = (
    "You are a payroll assistant inside ai-multi-app. "
    "You can answer questions about employees, pay periods and payslips using the database summary provided. "
    "Do not invent employees or numbers. "
    "For exact paycheck calculations, direct the user to the 'Run Payroll' tab. "
    "Keep answers concise and respond in the same language as the user."
)


def _summarize_context(business_id: int) -> str:
    employees = service.list_employees(business_id)
    periods = service.list_pay_periods(business_id)

    lines: list[str] = []
    lines.append(f"Employees ({len(employees)}):")
    if employees:
        for emp in employees:
            lines.append(
                f"- {emp['name']} ({emp['pay_type']}, rate {emp['rate']}, "
                f"state {emp['state'] or 'n/a'}, filing {emp['filing_status']})"
            )
    else:
        lines.append("- No employees yet.")

    lines.append(f"Pay periods ({len(periods)}):")
    if periods:
        for period in periods:
            lines.append(
                f"- {period['start_date']} to {period['end_date']} ({period['status']})"
            )
    else:
        lines.append("- No pay periods yet.")

    return "\n".join(lines)


def _try_command(message: str, business_id: int) -> dict[str, Any] | None:
    """Handle a small set of deterministic local commands without calling OpenExecutive."""
    text = message.strip().lower()

    if any(phrase in text for phrase in ("list employees", "show employees", "employees list")):
        employees = service.list_employees(business_id)
        names = [f"{e['name']} ({e['pay_type']})" for e in employees]
        return {
            "response": "Employees: " + (", ".join(names) if names else "No employees yet."),
        }

    if any(phrase in text for phrase in ("list periods", "show periods", "pay periods")):
        periods = service.list_pay_periods(business_id)
        descs = [f"{p['start_date']} to {p['end_date']}" for p in periods]
        return {
            "response": "Pay periods: " + (", ".join(descs) if descs else "No pay periods yet."),
        }

    return None


def ask(
    message: str,
    business_id: int,
    session_id: str | None = None,
    committee_review: bool = False,
) -> dict[str, Any]:
    """Answer a payroll-related question.

    Local commands are handled directly; open-ended questions are sent to
    OpenExecutive with the current payroll summary as context.
    """
    command = _try_command(message, business_id)
    if command is not None:
        if session_id:
            command["session_id"] = session_id
        return command

    context = _summarize_context(business_id)
    prompt = f"{SYSTEM_PROMPT}\n\n{context}\n\nUser: {message}\nAssistant:"
    return openexec.chat(prompt, session_id=session_id, committee_review=committee_review)

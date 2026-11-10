"""Render a drafted labelling impact assessment as a Markdown document."""

from regintel.llm.assess import URGENCY
from regintel.llm.taxonomy import LABELLING_DOCUMENTS


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(update, analysis, assessment) -> str:
    c = assessment.content
    lines = [
        f"# Draft labelling impact assessment: {update.title}",
        "",
        (
            f"Source: [{update.source} {update.source_type}]({update.url}), published "
            f"{update.published_date or 'date unknown'}."
        ),
        (
            f"Drafted by {assessment.model} (assessment {assessment.prompt_version}, triage "
            f"{analysis.prompt_version}) on {assessment.created_at:%Y-%m-%d}. Status: "
            f"{assessment.status.replace('_', ' ')}."
        ),
        "",
        (
            "> Draft for review by a labelling professional. Routes are suggestions, and the "
            "assessment does not know the current content of company labels."
        ),
        "",
        "## Scope",
        "",
        c["scope"],
        "",
    ]
    if c["watchlist_effects"]:
        lines += ["Watchlist items affected:", ""]
        lines += [
            f"- **{w['watchlist_item']}**: {w['why']}" for w in c["watchlist_effects"]
        ]
        lines.append("")

    lines += [
        "## Urgency",
        "",
        (
            f"**{c['urgency'].replace('_', ' ').capitalize()}.** {c['urgency_rationale']} "
            f"({URGENCY[c['urgency']]})"
        ),
        "",
        "## Section changes",
        "",
        "| Document | Section | Change | What to do | Source wording | Quote verified |",
        "|---|---|---|---|---|---|",
    ]
    for ch in c["section_changes"]:
        lines.append(
            f"| {LABELLING_DOCUMENTS.get(ch['document'], ch['document'])} | {_cell(ch['section'])} "
            f"| {ch['change_type']} | {_cell(ch['description'])} | “{_cell(ch['source_quote'])}” "
            f"| {'Yes' if ch['supported'] else 'No, check'} |"
        )
    lines.append("")

    if c["routes"]:
        lines += ["## Suggested routes (to confirm)", ""]
        lines += [
            f"- **{r['region']}: {r['route']}.** {r['rationale']}" for r in c["routes"]
        ]
        lines.append("")
    if c["open_questions"]:
        lines += ["## Open questions for the labelling team", ""]
        lines += [f"- {q}" for q in c["open_questions"]]
        lines.append("")
    if assessment.reviewer_note:
        lines += ["## Reviewer note", "", assessment.reviewer_note, ""]
    return "\n".join(lines)

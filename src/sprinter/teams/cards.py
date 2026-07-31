from __future__ import annotations

from typing import Any


def _fact(title: str, value: Any) -> dict[str, str]:
    return {"title": title, "value": str(value if value not in (None, "") else "Not provided")}


def build_review_card(
    decision: dict[str, Any],
    *,
    run_details: dict[str, Any],
    evidence_links: list[dict[str, str]],
) -> dict[str, Any]:
    severity = str(decision.get("severity") or "informational").lower()
    accent = {
        "critical": "attention",
        "high": "attention",
        "medium": "warning",
        "low": "accent",
        "informational": "default",
    }.get(severity, "default")
    facts = [
        _fact("Run", run_details.get("run_id") or run_details.get("result_id") or "Latest"),
        _fact("Source", run_details.get("source")),
        _fact("Evidence", run_details.get("evidence_count", 0)),
        _fact("Model", run_details.get("model")),
    ]
    details_body: list[dict[str, Any]] = [
        {
            "type": "FactSet",
            "facts": facts,
            "spacing": "Small",
        }
    ]
    rationale = decision.get("rationale") or []
    if rationale:
        details_body.append(
            {
                "type": "TextBlock",
                "text": "\n".join(f"- {item}" for item in rationale),
                "wrap": True,
                "spacing": "Medium",
            }
        )
    actions = decision.get("recommended_actions") or []
    if actions:
        details_body.extend(
            [
                {
                    "type": "TextBlock",
                    "text": "Recommended actions",
                    "weight": "Bolder",
                    "spacing": "Medium",
                },
                {
                    "type": "TextBlock",
                    "text": "\n".join(f"- {item}" for item in actions),
                    "wrap": True,
                    "spacing": "Small",
                },
            ]
        )
    card_actions: list[dict[str, Any]] = [
        {
            "type": "Action.ShowCard",
            "title": "Run details",
            "card": {
                "type": "AdaptiveCard",
                "version": "1.5",
                "body": details_body,
            },
        }
    ]
    for link in evidence_links:
        if link.get("url"):
            card_actions.append(
                {
                    "type": "Action.OpenUrl",
                    "title": str(link.get("label") or "Open evidence")[:80],
                    "url": link["url"],
                }
            )
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "msteams": {"width": "Full"},
        "body": [
            {
                "type": "TextBlock",
                "text": "Sprinter review",
                "size": "Medium",
                "weight": "Bolder",
                "color": accent,
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": str(decision.get("summary") or "Review completed."),
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "facts": [
                    _fact(
                        "Verdict",
                        str(decision.get("verdict") or "needs investigation")
                        .replace("_", " ")
                        .title(),
                    ),
                    _fact("Severity", severity.title()),
                ],
                "spacing": "Medium",
            },
        ],
        "actions": card_actions,
    }

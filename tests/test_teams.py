from __future__ import annotations

import json
from pathlib import Path

import pytest
from microsoft_agents.activity import Activity

from sprinter.teams.cards import build_review_card
from sprinter.teams.gateway import TeamsAuthenticationError, TeamsGateway


def activity(activity_type: str, action: str | None = None, tenant: str = "tenant-1") -> Activity:
    payload = {
        "type": activity_type,
        "id": "activity-1",
        "timestamp": "2026-07-31T00:00:00Z",
        "serviceUrl": "https://smba.trafficmanager.net/au/",
        "channelId": "msteams",
        "from": {"id": "user-1"},
        "recipient": {"id": "bot-1"},
        "conversation": {"id": "conversation-1", "conversationType": "personal"},
        "channelData": {"tenant": {"id": tenant}},
    }
    if action:
        payload["action"] = action
    return Activity.model_validate(payload)


def gateway(settings, container) -> TeamsGateway:
    instance = TeamsGateway.__new__(TeamsGateway)
    instance.settings = settings.model_copy(update={"teams_allowed_tenant_ids": "tenant-1"})
    instance.database = container.db
    return instance


def test_message_activity_is_ignored_without_conversation_state(settings, container) -> None:
    result = gateway(settings, container).handle_lifecycle(activity("message"))
    assert result == {"accepted": True, "ignored": True}
    assert container.db.installations() == []


def test_installation_is_discovered_disabled_and_removed(settings, container) -> None:
    teams = gateway(settings, container)
    added = teams.handle_lifecycle(activity("installationUpdate", "add"))
    assert added["enabled"] is False
    installation = container.db.installations()[0]
    assert installation.active is True
    assert installation.enabled is False
    removed = teams.handle_lifecycle(activity("installationUpdate", "remove"))
    assert removed["deactivated"] is True
    assert container.db.installations()[0].active is False


def test_unallowed_tenant_is_rejected(settings, container) -> None:
    with pytest.raises(TeamsAuthenticationError, match="not allowed"):
        gateway(settings, container).handle_lifecycle(activity("conversationUpdate", tenant="other"))


def test_card_is_summary_first_details_collapsed_and_links_last() -> None:
    card = build_review_card(
        {
            "verdict": "true_positive",
            "severity": "high",
            "summary": "One actionable finding.",
            "rationale": ["Evidence matched."],
            "recommended_actions": ["Investigate."],
        },
        run_details={"run_id": "run-1", "source": "stix", "evidence_count": 1, "model": "provider/model"},
        evidence_links=[{"label": "Open evidence", "url": "https://example.invalid/evidence"}],
    )
    assert card["body"][1]["text"] == "One actionable finding."
    assert card["actions"][0]["type"] == "Action.ShowCard"
    assert card["actions"][-1]["type"] == "Action.OpenUrl"


def test_manifest_is_notification_only_and_command_free() -> None:
    manifest_path = Path(__file__).parents[1] / "teams/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    bot = manifest["bots"][0]
    assert bot["isNotificationOnly"] is True
    assert "commandLists" not in bot
    assert "messageTeamMembers" not in manifest["permissions"]

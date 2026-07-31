from __future__ import annotations

from typing import Any

from microsoft_agents.activity import Activity, Attachment, ConversationReference
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import TurnContext
from microsoft_agents.hosting.core.authorization import AgentAuthConfiguration, JwtTokenValidator

from sprinter.config import Settings
from sprinter.db import Database


class TeamsAuthenticationError(PermissionError):
    pass


class TeamsGateway:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        configuration = AgentAuthConfiguration(
            client_id=settings.teams_app_id,
            tenant_id=settings.teams_tenant_id,
            client_secret=settings.secret_value("teams"),
        )
        self.validator = JwtTokenValidator(configuration)
        connection_manager = MsalConnectionManager(
            CONNECTIONS={
                "SERVICE_CONNECTION": {
                    "SETTINGS": {
                        "CLIENTID": settings.teams_app_id,
                        "TENANTID": settings.teams_tenant_id,
                        "CLIENTSECRET": settings.secret_value("teams"),
                    }
                }
            }
        )
        self.adapter = CloudAdapter(connection_manager=connection_manager)

    def validate_activity(self, authorization: str, payload: dict[str, Any]) -> tuple[Any, Any]:
        if not authorization.startswith("Bearer "):
            raise TeamsAuthenticationError("missing Teams bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = self.validator.validate_token(token)
            activity = Activity.model_validate(payload)
        except (ValueError, TypeError) as exc:
            raise TeamsAuthenticationError("invalid Teams activity") from exc
        if not claims.is_authenticated:
            raise TeamsAuthenticationError("unauthenticated Teams activity")
        return claims, activity

    def handle_lifecycle(self, activity: Activity) -> dict[str, Any]:
        tenant_id = str(((activity.channel_data or {}).get("tenant") or {}).get("id") or "")
        if tenant_id not in self.settings.allowed_teams_tenants:
            raise TeamsAuthenticationError("Teams tenant is not allowed")
        activity_type = str(activity.type or "")
        action = str(getattr(activity, "action", "") or "")
        if activity_type == "message":
            self.database.audit(
                "teams.message_ignored",
                "teams",
                {"tenant_id": tenant_id, "conversation_id": activity.conversation.id},
            )
            return {"accepted": True, "ignored": True}
        if activity_type == "installationUpdate":
            if action == "remove":
                changed = self.database.deactivate_installation(tenant_id, activity.conversation.id)
                return {"accepted": True, "deactivated": changed}
            installation = self.database.upsert_installation(activity, tenant_id)
            return {"accepted": True, "installation_id": installation.id, "enabled": installation.enabled}
        if activity_type == "conversationUpdate":
            installation = self.database.upsert_installation(activity, tenant_id)
            return {"accepted": True, "installation_id": installation.id, "enabled": installation.enabled}
        self.database.audit(
            "teams.activity_ignored",
            "teams",
            {
                "tenant_id": tenant_id,
                "conversation_id": activity.conversation.id if activity.conversation else "",
                "activity_type": activity_type,
            },
        )
        return {"accepted": True, "ignored": True}

    async def send_card(self, reference_json: str, card: dict[str, Any]) -> None:
        reference = ConversationReference.model_validate_json(reference_json)
        continuation = Activity(type="event").apply_conversation_reference(reference)

        async def callback(context: TurnContext) -> None:
            await context.send_activity(
                Activity(
                    type="message",
                    attachments=[
                        Attachment(
                            content_type="application/vnd.microsoft.card.adaptive",
                            content=card,
                        )
                    ],
                )
            )

        await self.adapter.continue_conversation(self.settings.teams_app_id, continuation, callback)

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from sprinter.config import Settings
from sprinter.schemas import ModelDecision


class PiError(RuntimeError):
    pass


class PiUnavailable(PiError):
    pass


class PiProtocolError(PiError):
    pass


@dataclass(frozen=True)
class PiResult:
    decision: ModelDecision
    provider: str
    model: str
    pi_version: str


class PiGateway:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def argv(self) -> list[str]:
        return [
            self.settings.pi_command,
            "--mode",
            "rpc",
            "--provider",
            self.settings.pi_provider,
            "--model",
            self.settings.pi_model,
            "--thinking",
            self.settings.pi_thinking,
            "--no-session",
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
        ]

    @property
    def environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "PI_TELEMETRY": "0",
            "PI_SKIP_VERSION_CHECK": "1",
            "NO_COLOR": "1",
        }

    async def version(self) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.settings.pi_command,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.environment,
            )
        except OSError as exc:
            raise PiUnavailable(f"Pi is not executable: {exc}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise PiUnavailable("Pi version check timed out") from exc
        if process.returncode:
            raise PiUnavailable(stderr.decode("utf-8", "replace")[:1000] or "Pi version check failed")
        match = re.search(r"\b(\d+\.\d+\.\d+)\b", stdout.decode("utf-8", "replace"))
        if not match:
            raise PiProtocolError("Pi returned an unrecognised version")
        return match.group(1)

    async def probe(self) -> dict[str, str]:
        version = await self.version()
        if version != self.settings.pi_expected_version:
            raise PiUnavailable(
                f"Pi version {version} is installed; expected {self.settings.pi_expected_version}"
            )
        result = await self._rpc_prompt(
            'Return exactly this JSON object and nothing else: {"status":"ok"}',
            deadline_seconds=min(45, self.settings.pi_timeout_seconds),
        )
        try:
            payload = self._extract_json(result)
        except (ValueError, json.JSONDecodeError) as exc:
            raise PiUnavailable("Pi model/authentication probe returned invalid output") from exc
        if payload != {"status": "ok"}:
            raise PiUnavailable("Pi model/authentication probe did not return the expected response")
        return {"version": version, "provider": self.settings.pi_provider, "model": self.settings.pi_model}

    async def review(self, prompt: str) -> PiResult:
        version = await self.version()
        if version != self.settings.pi_expected_version:
            raise PiUnavailable(
                f"Pi version {version} is installed; expected {self.settings.pi_expected_version}"
            )
        raw = await self._rpc_prompt(prompt)
        try:
            decision = ModelDecision.model_validate(self._extract_json(raw))
        except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
            correction = (
                "Your prior response did not match the required JSON schema. "
                "Return only one corrected JSON object. Do not use markdown.\n\n"
                f"Validation error: {first_error}\n\nPrior response:\n{raw[:8000]}"
            )
            corrected = await self._rpc_prompt(correction)
            try:
                decision = ModelDecision.model_validate(self._extract_json(corrected))
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                raise PiProtocolError(f"Pi returned invalid review output after correction: {exc}") from exc
        return PiResult(
            decision=decision,
            provider=self.settings.pi_provider,
            model=self.settings.pi_model,
            pi_version=version,
        )

    async def _rpc_prompt(self, prompt: str, deadline_seconds: int | None = None) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *self.argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.environment,
                limit=self.settings.pi_max_output_bytes + 1,
            )
        except OSError as exc:
            raise PiUnavailable(f"Pi is not executable: {exc}") from exc
        assert process.stdin and process.stdout and process.stderr
        request = json.dumps({"id": "sprinter-review", "type": "prompt", "message": prompt}) + "\n"
        process.stdin.write(request.encode("utf-8"))
        await process.stdin.drain()
        output = ""
        output_bytes = 0
        accepted = False
        try:
            async with asyncio.timeout(deadline_seconds or self.settings.pi_timeout_seconds):
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    output_bytes += len(line)
                    if output_bytes > self.settings.pi_max_output_bytes:
                        raise PiProtocolError("Pi output exceeded the configured limit")
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise PiProtocolError("Pi emitted invalid JSONL") from exc
                    if event.get("type") == "response" and event.get("command") == "prompt":
                        if not event.get("success"):
                            raise PiUnavailable(str(event.get("error") or "Pi rejected the prompt"))
                        accepted = True
                    if event.get("type") == "message_update":
                        delta = event.get("assistantMessageEvent") or {}
                        if delta.get("type") == "text_delta":
                            output += str(delta.get("delta") or "")
                    if event.get("type") == "agent_settled":
                        break
                if not accepted:
                    stderr = (await process.stderr.read()).decode("utf-8", "replace")[:2000]
                    raise PiUnavailable(stderr or "Pi exited before accepting the prompt")
        except TimeoutError as exc:
            raise PiUnavailable("Pi request timed out") from exc
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        if not output.strip():
            raise PiProtocolError("Pi returned no assistant text")
        return output

    @staticmethod
    def _extract_json(value: str) -> dict[str, Any]:
        value = value.strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*", "", value)
            value = re.sub(r"\s*```$", "", value)
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object")
        return parsed

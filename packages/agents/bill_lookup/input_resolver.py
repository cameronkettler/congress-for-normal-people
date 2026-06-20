import json
import re
from typing import Any

import httpx
from pydantic import BaseModel

from packages.shared.config import Settings, get_settings


class BillInputResolution(BaseModel):
    original_input: str
    bill_id: str
    confidence: str = "medium"
    explanation: str = "Input already looked like a bill identifier."


class BillInputResolutionError(ValueError):
    pass


class BillInputResolver:
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def resolve(self, value: str) -> BillInputResolution:
        normalized = self._normalize_bill_id(value)
        if normalized:
            return BillInputResolution(original_input=value, bill_id=normalized)

        if not (self.settings.openai_api_live and self.settings.openai_api_key):
            raise BillInputResolutionError(
                "Enter a bill number like H.R. 22, or enable OpenAI lookup resolution for natural-language searches."
            )

        resolved = await self._resolve_with_openai(value)
        if resolved and resolved.confidence != "low":
            return resolved

        raise BillInputResolutionError(
            "Could not confidently resolve that search to a single Congress.gov bill number. Try an exact bill number like H.R. 22."
        )

    def _normalize_bill_id(self, value: str) -> str | None:
        cleaned = value.strip().lower().replace(".", "").replace(" ", "-")
        match = re.fullmatch(r"(hr|hres|hjres|hconres|s|sres|sjres|sconres)-?(\d+)(?:-?(\d+))?", cleaned)
        if not match:
            return None
        bill_type, number, congress = match.groups()
        return f"{bill_type}-{number}-{congress or '119'}"

    async def _resolve_with_openai(self, value: str) -> BillInputResolution | None:
        try:
            async with httpx.AsyncClient(timeout=self.settings.openai_api_timeout_seconds) as client:
                response = await client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._payload(value),
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        data = self._extract_json(response.json())
        if not data or not data.get("bill_id"):
            return None

        bill_id = self._normalize_bill_id(data["bill_id"])
        if not bill_id:
            return None

        return BillInputResolution(
            original_input=value,
            bill_id=bill_id,
            confidence=data.get("confidence", "low"),
            explanation=data.get("explanation", "Resolved by OpenAI from natural language input."),
        )

    def _payload(self, value: str) -> dict[str, Any]:
        return {
            "model": self.settings.openai_model,
            "reasoning": {"effort": "low"},
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Resolve user input about a U.S. federal bill to a Congress.gov bill id. "
                        "Use the format hr-22-119 or s-123-119. If the input is ambiguous, return "
                        "bill_id as null and confidence low. Do not guess when multiple bills share "
                        "the same short title."
                    ),
                },
                {"role": "user", "content": value},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "bill_input_resolution",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["bill_id", "confidence", "explanation"],
                        "properties": {
                            "bill_id": {"type": ["string", "null"]},
                            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                            "explanation": {"type": "string"},
                        },
                    },
                }
            },
        }

    def _extract_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if output_text := payload.get("output_text"):
            return self._loads_object(output_text)
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    parsed = self._loads_object(content.get("text", ""))
                    if parsed is not None:
                        return parsed
        return None

    def _loads_object(self, value: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

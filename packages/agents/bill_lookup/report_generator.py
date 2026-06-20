import json
from typing import Any

import httpx

from packages.shared.config import Settings, get_settings


class OpenAIReportGenerator:
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.openai_api_live and self.settings.openai_api_key)

    async def generate(
        self,
        *,
        state: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.enabled:
            return fallback

        payload = self._build_payload(state)
        try:
            async with httpx.AsyncClient(timeout=self.settings.openai_api_timeout_seconds) as client:
                response = await client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return fallback

        report = self._extract_json(response.json())
        if not report:
            return fallback

        return {
            "generated_summary": report.get("generated_summary") or fallback["generated_summary"],
            "generated_analysis": report.get("generated_analysis") or fallback["generated_analysis"],
            "caveats": report.get("caveats") or fallback["caveats"],
            "confidence": report.get("confidence") or fallback["confidence"],
        }

    def _build_payload(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.settings.openai_model,
            "reasoning": {"effort": self.settings.openai_reasoning_effort},
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are Civic Pulse's policy analysis assistant. Synthesize only the "
                        "provided structured source data. Do not invent facts, dates, sponsors, "
                        "positions, or stakeholder intent. Use cautious language for inferred "
                        "support or opposition."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Generate a concise bill lookup report.",
                            "bill": state["bill"].model_dump(mode="json"),
                            "sponsor": state.get("sponsor", {}),
                            "finance": state.get("finance", {}),
                            "lobbying": state.get("lobbying", {}),
                            "stakeholders": self._dump_value(state.get("stakeholders", {})),
                            "existing_caveats": state.get("caveats", []),
                            "confidence": state.get("confidence", "low"),
                        },
                        default=str,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "civic_pulse_bill_lookup_report",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "generated_summary",
                            "generated_analysis",
                            "caveats",
                            "confidence",
                        ],
                        "properties": {
                            "generated_summary": {
                                "type": "string",
                                "description": "One or two sentences summarizing the bill.",
                            },
                            "generated_analysis": {
                                "type": "string",
                                "description": (
                                    "A grounded paragraph connecting bill status, sponsor, finance "
                                    "context, and lobbying disclosures."
                                ),
                            },
                            "caveats": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": 5,
                            },
                            "confidence": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
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

    def _dump_value(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {key: self._dump_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._dump_value(item) for item in value]
        return value

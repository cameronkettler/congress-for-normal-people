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
            "analysis_sections": report.get("analysis_sections") or fallback.get("analysis_sections", {}),
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
                        "You are Civic Pulse's political commentary analyst. Explain what a federal "
                        "bill would do and why people may support or criticize it. Synthesize only "
                        "the provided structured source data. Do not invent facts, dates, sponsors, "
                        "positions, vote counts, or stakeholder intent. Use cautious language for "
                        "inferred arguments."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Generate a concise, source-grounded political commentary report.",
                            "requirements": [
                                "Explain what the bill would do in plain language.",
                                "Explain the strongest likely supporter argument and critic concern based on the bill summary.",
                                "Explain practical day-to-day impact.",
                                "Treat lobbying disclosure matches as context, not support or opposition, unless a filing directly states a position.",
                                "Keep each analysis section to 2-4 sentences.",
                            ],
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
                            "analysis_sections",
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
                                    "A short synthesis of the bill's political stakes."
                                ),
                            },
                            "analysis_sections": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "What The Bill Does",
                                    "Why Supporters Want It",
                                    "Why Critics Are Concerned",
                                    "How It Could Affect Daily Life",
                                    "Political And Influence Read",
                                ],
                                "properties": {
                                    "What The Bill Does": {"type": "string"},
                                    "Why Supporters Want It": {"type": "string"},
                                    "Why Critics Are Concerned": {"type": "string"},
                                    "How It Could Affect Daily Life": {"type": "string"},
                                    "Political And Influence Read": {"type": "string"},
                                },
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

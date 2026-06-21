import asyncio
from datetime import date

import httpx

from packages.agents.bill_lookup.report_generator import OpenAIReportGenerator
from packages.shared.config import Settings
from packages.shared.schemas import BillRecord


class _FakeAsyncClient:
    last_request: dict | None = None

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.__class__.last_request = {"url": url, **kwargs}
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"generated_summary":"LLM summary",'
                                    '"generated_analysis":"LLM analysis",'
                                    '"analysis_sections":{'
                                    '"What The Bill Does":"Explains the bill.",'
                                    '"Why Supporters Want It":"Supporter case.",'
                                    '"Why Critics Are Concerned":"Critic concern.",'
                                    '"How It Could Affect Daily Life":"Daily life impact.",'
                                    '"Political And Influence Read":"Influence context."'
                                    '},'
                                    '"caveats":["Verify source filings."],'
                                    '"confidence":"medium"}'
                                ),
                            }
                        ]
                    }
                ]
            },
        )


class _FakeRepresentativePositionAsyncClient:
    last_request: dict | None = None

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.__class__.last_request = {"url": url, **kwargs}
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"position":"criticizes",'
                                    '"reason":"Public reporting says the representative opposed the bill because of concerns that documentary proof requirements could burden eligible voters.",'
                                    '"sources":[{"title":"Member statement","url":"https://example.com/statement"}],'
                                    '"confidence":"medium"}'
                                ),
                            }
                        ]
                    }
                ]
            },
        )


class _FakeUnclearRepresentativePositionAsyncClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"position":"unclear",'
                                    '"reason":"The public sources identify the bill and representative but do not establish whether the senator supports or opposes it.",'
                                    '"sources":[{"title":"Bill tracker","url":"https://example.com/bill"}],'
                                    '"confidence":"low"}'
                                ),
                            }
                        ]
                    }
                ]
            },
        )


class _FakeRepresentativeWebSearchAsyncClient:
    last_request: dict | None = None

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.__class__.last_request = {"url": url, **kwargs}
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"position":"supports",'
                                    '"reason":"Public sources found by web search say the senator backed the bill because it creates a federal stablecoin framework.",'
                                    '"sources":[{"title":"Senator statement","url":"https://www.senate.gov/member-statement"}],'
                                    '"confidence":"medium"}'
                                ),
                            }
                        ]
                    }
                ]
            },
        )


def test_openai_report_generator_posts_grounded_state_and_returns_structured_report(monkeypatch):
    _FakeAsyncClient.last_request = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    settings = Settings(
        openai_api_key="test-key",
        openai_api_live=True,
        openai_model="gpt-5.4-mini",
        openai_reasoning_effort="low",
    )
    state = {
        "bill": BillRecord(
            congress_bill_id="hr-1234-119",
            title="Responsible Artificial Intelligence in Public Services Act",
            summary="Creates federal AI procurement standards.",
            sponsor="Rep. Jordan Lee",
            introduced_date=date(2026, 2, 12),
            latest_action="Referred to committee.",
            status="introduced",
            topic="Artificial Intelligence",
        ),
        "sponsor": {"name": "Rep. Jordan Lee"},
        "finance": {"confidence": "low"},
        "lobbying": {"confidence": "medium", "registrations": []},
        "stakeholders": {"possible_supporters": ["Agency modernization advocates"]},
        "caveats": ["Provider data can lag official filings."],
        "confidence": "medium",
    }
    fallback = {
        "generated_summary": "Fallback summary",
        "generated_analysis": "Fallback analysis",
        "analysis_sections": {
            "What The Bill Does": "Fallback substance",
            "Why Supporters Want It": "Fallback supporter case",
            "Why Critics Are Concerned": "Fallback critic concern",
            "How It Could Affect Daily Life": "Fallback impact",
            "Political And Influence Read": "Fallback influence context",
        },
        "caveats": state["caveats"],
        "confidence": state["confidence"],
    }

    report = asyncio.run(OpenAIReportGenerator(settings).generate(state=state, fallback=fallback))

    assert report == {
        "generated_summary": "LLM summary",
        "generated_analysis": "LLM analysis",
        "analysis_sections": {
            "What The Bill Does": "Explains the bill.",
            "Why Supporters Want It": "Supporter case.",
            "Why Critics Are Concerned": "Critic concern.",
            "How It Could Affect Daily Life": "Daily life impact.",
            "Political And Influence Read": "Influence context.",
        },
        "caveats": ["Verify source filings."],
        "confidence": "medium",
    }
    assert _FakeAsyncClient.last_request is not None
    assert _FakeAsyncClient.last_request["url"] == "https://api.openai.com/v1/responses"
    assert _FakeAsyncClient.last_request["headers"]["Authorization"] == "Bearer test-key"
    assert _FakeAsyncClient.last_request["json"]["model"] == "gpt-5.4-mini"
    assert _FakeAsyncClient.last_request["json"]["text"]["format"]["type"] == "json_schema"


def test_openai_report_generator_summarizes_representative_position_evidence(monkeypatch):
    _FakeRepresentativePositionAsyncClient.last_request = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeRepresentativePositionAsyncClient)
    settings = Settings(openai_api_key="test-key", openai_api_live=True)

    reason = asyncio.run(
        OpenAIReportGenerator(settings).generate_representative_position_reason(
            bill={"congress_bill_id": "hr-22-119", "title": "SAVE Act"},
            representative={"name": "Crockett, Jasmine", "state": "TX", "district": "30"},
            signal="Voted against",
            search_results=[
                {
                    "title": "Member statement",
                    "url": "https://example.com/statement",
                    "snippet": "The representative opposed documentary proof requirements.",
                    "source": "example.com",
                }
            ],
        )
    )

    assert reason is not None
    assert reason["position"] == "criticizes"
    assert "documentary proof" in reason["reason"]
    assert _FakeRepresentativePositionAsyncClient.last_request is not None
    request = _FakeRepresentativePositionAsyncClient.last_request["json"]
    assert request["text"]["format"]["name"] == "civic_pulse_representative_position_reason"


def test_openai_report_generator_keeps_unclear_public_context(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeUnclearRepresentativePositionAsyncClient)
    settings = Settings(openai_api_key="test-key", openai_api_live=True)

    reason = asyncio.run(
        OpenAIReportGenerator(settings).generate_representative_position_reason(
            bill={"congress_bill_id": "s-1582-119", "title": "GENIUS Act"},
            representative={"name": "Cruz, Ted", "state": "TX"},
            signal="No direct signal found",
            search_results=[
                {
                    "title": "Bill tracker",
                    "url": "https://example.com/bill",
                    "snippet": "Bill tracking page for S. 1582.",
                    "source": "example.com",
                }
            ],
        )
    )

    assert reason is not None
    assert reason["position"] == "unclear"
    assert "do not establish" in reason["reason"]


def test_openai_report_generator_can_use_web_search_for_representative_context(monkeypatch):
    _FakeRepresentativeWebSearchAsyncClient.last_request = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeRepresentativeWebSearchAsyncClient)
    settings = Settings(
        openai_api_key="test-key",
        openai_api_live=True,
        openai_web_search_enabled=True,
        openai_web_search_context_size="low",
    )

    reason = asyncio.run(
        OpenAIReportGenerator(settings).generate_representative_web_context(
            bill={"congress_bill_id": "s-1582-119", "title": "GENIUS Act"},
            representative={"name": "Cruz, Ted", "state": "TX"},
            signal="No direct signal found",
            search_results=[],
        )
    )

    assert reason is not None
    assert reason["position"] == "supports"
    assert _FakeRepresentativeWebSearchAsyncClient.last_request is not None
    request = _FakeRepresentativeWebSearchAsyncClient.last_request["json"]
    assert request["tools"] == [{"type": "web_search", "search_context_size": "low"}]
    assert request["text"]["format"]["name"] == "civic_pulse_representative_web_context"

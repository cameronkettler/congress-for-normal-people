import asyncio

import httpx

from packages.ingestion.congress.client import CongressClient
from packages.shared.config import Settings
from packages.shared.schemas import RepresentativeRecord


class _TimeoutAsyncClient:
    last_timeout: httpx.Timeout | None = None

    def __init__(self, **kwargs: object) -> None:
        self.__class__.last_timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, *_: object, **__: object) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")


class _SuccessfulBillAsyncClient:
    last_timeout: httpx.Timeout | None = None

    def __init__(self, **kwargs: object) -> None:
        self.__class__.last_timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **__: object) -> httpx.Response:
        if url.endswith("/summaries"):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={
                    "summaries": [
                        {
                            "updateDate": "2025-01-04",
                            "text": (
                                "<p>This bill requires documentary proof of U.S. citizenship "
                                "to register to vote in federal elections.</p>"
                            ),
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "bill": {
                    "title": "SAVE Act",
                    "latestAction": {"text": "Received in the Senate."},
                    "sponsors": [{"fullName": "Rep. Roy, Chip [R-TX-21]"}],
                    "introducedDate": "2025-01-03",
                    "status": "introduced",
                }
            },
        )


class _HouseVoteAsyncClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **__: object) -> httpx.Response:
        if url.endswith("/house-vote/119/1/102/members"):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={
                    "houseRollCallVoteMemberVotes": {
                        "voteQuestion": "On Passage",
                        "result": "Passed",
                        "rollCallNumber": "102",
                            "results": {
                                "item": [
                                    {
                                        "bioguideId": "C001130",
                                        "voteCast": "Nay",
                                        "firstName": "Jasmine",
                                        "lastName": "Crockett",
                                        "voteParty": "D",
                                        "voteState": "TX",
                                    }
                                ]
                            },
                    }
                },
            )

        votes = []
        if url.endswith("/house-vote/119/1"):
            votes = {
                "item": [
                    {
                        "congress": "119",
                        "sessioNumber": "1",
                        "identifier": "11912025102",
                        "legislationType": "HR",
                        "legislationNumber": 22,
                        "voteQuestion": "On Passage",
                        "result": "Passed",
                        "startDate": "2025-04-10T12:00:00-04:00",
                    },
                    {
                        "congress": "119",
                        "sessionNumber": "1",
                        "rollCallNumber": "103",
                        "legislationType": "HR",
                        "legislationNumber": "33",
                        "voteQuestion": "On Passage",
                        "result": "Passed",
                        "startDate": "2025-04-10T13:00:00-04:00",
                    },
                ]
            }

        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"houseRollCallVotes": votes},
        )


class _CosponsorAsyncClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        offset = kwargs.get("params", {}).get("offset", 0)
        items = []
        if offset == 0:
            items = [{"cosponsor": {"bioguideID": f"X{index:06d}", "fullName": f"Member {index}"}} for index in range(250)]
        elif offset == 250:
            items = [
                {
                    "cosponsor": {
                        "bioguideID": "W000814",
                        "fullName": "Rep. Weber, Randy K. Sr. [R-TX-14]",
                    }
                }
            ]

        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"cosponsors": {"item": items}},
        )


def test_list_recent_bills_returns_empty_list_when_congress_times_out(monkeypatch):
    _TimeoutAsyncClient.last_timeout = None
    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutAsyncClient)

    result = asyncio.run(CongressClient(Settings(congress_api_key="test-key")).list_recent_bills())

    assert result == []
    assert isinstance(_TimeoutAsyncClient.last_timeout, httpx.Timeout)


def test_get_bill_uses_configured_five_minute_timeout(monkeypatch):
    _SuccessfulBillAsyncClient.last_timeout = None
    monkeypatch.setattr(httpx, "AsyncClient", _SuccessfulBillAsyncClient)

    bill = asyncio.run(
        CongressClient(
            Settings(congress_api_key="test-key", congress_api_timeout_seconds=300)
        ).get_bill("hr-22")
    )

    assert bill.title == "SAVE Act"
    assert "documentary proof of U.S. citizenship" in bill.summary
    assert isinstance(_SuccessfulBillAsyncClient.last_timeout, httpx.Timeout)
    assert _SuccessfulBillAsyncClient.last_timeout.connect == 300


def test_list_house_votes_for_bill_filters_to_matching_legislation(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _HouseVoteAsyncClient)

    votes = asyncio.run(
        CongressClient(Settings(congress_api_key="test-key")).list_house_votes_for_bill("hr-22-119")
    )

    assert len(votes) == 1
    assert votes[0]["rollCallNumber"] == "102"


def test_get_house_member_vote_returns_vote_cast(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _HouseVoteAsyncClient)
    vote = {
        "congress": "119",
        "sessionNumber": "1",
        "rollCallNumber": "102",
    }
    representative = RepresentativeRecord(
        name="Crockett, Jasmine",
        chamber="House",
        party="Democratic",
        state="TX",
        district="30",
        bioguide_id="C001130",
    )

    member_vote = asyncio.run(
        CongressClient(Settings(congress_api_key="test-key")).get_house_member_vote(vote, representative)
    )

    assert member_vote is not None
    assert member_vote["vote_cast"] == "Nay"


def test_list_bill_cosponsors_paginates_and_unwraps_items(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _CosponsorAsyncClient)

    cosponsors = asyncio.run(
        CongressClient(Settings(congress_api_key="test-key")).list_bill_cosponsors("hr-22-119")
    )

    assert len(cosponsors) == 251
    assert cosponsors[-1]["bioguideID"] == "W000814"

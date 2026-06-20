from packages.shared.config import Settings


def test_provider_timeout_defaults_are_hosting_friendly():
    settings = Settings(_env_file=None)

    assert settings.congress_api_timeout_seconds == 300
    assert settings.congress_recent_api_timeout_seconds == 30
    assert settings.fec_api_timeout_seconds == 60
    assert settings.lobbying_api_timeout_seconds == 60
    assert settings.openai_api_timeout_seconds == 120
    assert settings.serpapi_timeout_seconds == 20
    assert settings.rep_position_search_results == 5

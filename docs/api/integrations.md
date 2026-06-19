# API Integration Documentation

## Congress.gov

`packages.ingestion.congress.CongressClient` owns legislative retrieval.

- `get_bill(bill_id)`: Retrieves a bill record and maps it into `BillRecord`.
- `get_sponsor(sponsor_name)`: Returns sponsor metadata. This is ready for richer member expansion.
- `list_recent_bills(limit)`: Retrieves recent bills for monitoring.

Configure with `CONGRESS_API_KEY`.

## OpenFEC

`packages.ingestion.fec.FECClient` owns campaign finance enrichment.

- `get_candidate_finance_patterns(sponsor_name)`: Searches candidate records and returns finance context.

Configure with `FEC_API_KEY`.

## Lobbying Disclosure

`packages.ingestion.lobbying.LobbyingDisclosureClient` owns lobbying activity search.

- `search_activity(query)`: Searches registrations and filings related to bill title or policy terms.

Configure with `LOBBYING_DISCLOSURE_API_KEY`, `LOBBYING_DISCLOSURE_BASE_URL`, and
`LOBBYING_API_LIVE=true`. Authenticated requests send `Authorization: Token <key>` and use the
LDA filings `filing_specific_lobbying_issues` filter.

## Demo Mode

When API keys are absent, clients return deterministic demo responses. This keeps the repository easy to clone, run, and present during interviews while preserving production boundaries.

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-16

The first release: signal-based MEDDPICC qualification for West Coast B2B startups,
runnable end to end with zero keys.

### Added

- **Contracts:** Pydantic v2 models for profiles, evidence-cited tech-stack signals,
  Claude wedges, MEDDPICC scorecards and outbound briefs, and an import-layer test that
  keeps the architecture honest.
- **Offline mode:** twelve fictional fixture accounts and deterministic synthetic
  signals on the reserved `.example` domain, plus a 26-account `targets.csv`.
- **Qualification pipeline:** three Claude wedges (prompt caching, extended thinking,
  cloud marketplace), a pre-discovery MEDDPICC baseline that treats unknown as grey rather
  than red, and a four-touch outbound brief exported as Markdown or JSON.
- **Claude client:** structured outputs validated against the models, a cached static
  system prompt, server-side refusal fallbacks and per-call cost estimates. A zero-cost
  mock runs the same pipeline without a key.
- **Live scrapers:** Greenhouse, Lever and Ashby boards, company pages (robots.txt
  honoured) and DNS with a DNS-over-HTTPS fallback, behind one polite, cached HTTP client.
- **CLI:** `run`, `qualify` (`--export-brief`), `territory-batch` (concurrent, resumable,
  budget-capped) and `doctor`, with Rich views that adapt from 60 to 120 columns and fall
  back to ASCII.
- **Documentation:** a README whose examples the test suite executes, a sample brief, and
  a LinkedIn carousel deck with WCAG-checked colours.

[0.1.0]: https://github.com/the-gtm-guy/EE-JOP/releases/tag/v0.1.0

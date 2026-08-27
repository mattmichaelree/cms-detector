# LobbyBook — Texas Political Knowledge Layer: Source & Data-Architecture Audit

**Date:** August 2026 · **Status:** Complete audit, pre-implementation

This audit answers one question for every major documentary source of Texas politics and
government: *what unique political knowledge does it contain, what would a sophisticated
Texas lobbyist use it for, and what is the best technical representation for LobbyBook?*

It covers 20 source families — from Texas Legislature Online and the House Research
Organization to campaign finance disclosures, party platforms, and the capitol press corps —
and converts them into a concrete plan for structured institutional memory: what becomes
canonical structured data, what becomes searchable cited text, what becomes training or
evaluation material, and what becomes proprietary derived intelligence.

## Method

Findings were produced by parallel research agents that **live-inspected each source**
(index pages, sample documents, sitemaps, bulk/FTP trees, APIs, RSS feeds, archive
services) rather than describing sources from memory. Every availability or format claim
cites a URL. Claims that could not be confirmed from this environment are marked
**UNVERIFIED** — treat those as leads to re-check during implementation, not facts.
Government sites change; re-verify load-bearing endpoints before building against them.

## How to read this audit

| File | Contents |
|---|---|
| [01-executive-findings.md](01-executive-findings.md) | The most important discoveries, in priority order |
| [02-source-matrix.md](02-source-matrix.md) | One row per source family: coverage, format, authority, use case, ingestion, priority tier (0–3), and 13-dimension scores |
| [03-deep-dives/](03-deep-dives/) | Full audit of each source family (coverage → formats → lobbyist use → ontology → edges → temporal semantics → authority → ingestion → training value → derived intelligence → scores) |
| [04-knowledge-graph.md](04-knowledge-graph.md) | Canonical entity types, stable-ID strategy, shared schema, and the edge registry with provenance classes |
| [05-retrieval-architecture.md](05-retrieval-architecture.md) | Chunking per document family, retrieval routing matrix, and where SQL / graph / BM25 / vectors each apply |
| [06-training-architecture.md](06-training-architecture.md) | What to train vs. what to retrieve; every naturally labeled dataset found |
| [07-benchmark.md](07-benchmark.md) | The Texas-politics benchmark: categories, example questions, gold sources, adversarial traps |
| [08-derived-intelligence.md](08-derived-intelligence.md) | Proprietary signals LobbyBook can compute that no source exposes |
| [09-ingestion-roadmap.md](09-ingestion-roadmap.md) | Ordered implementation plan with dependencies and refresh cadences |
| [10-data-gaps.md](10-data-gaps.md) | What a lobbyist needs that these sources still don't provide, and where to get it |

## Source families audited

Texas Legislature Online (TLO) · House Research Organization (HRO) · Senate Research
Center · House journals · Senate journals · committee minutes & witness lists · hearing
video/testimony · Texas Register · Texas Administrative Code / agency rules · Attorney
General opinions · Governor executive orders & proclamations · Legislative Budget Board ·
Sunset Advisory Commission · interim committee reports & charges · Texas courts · Texas
Ethics Commission (campaign finance, lobbying, PFS) · Texas Comptroller · agency strategic
plans · party platforms · legislator press releases & official statements · campaign
content (sites, ads, endorsements) · Texas political news — plus the cross-cutting
historical/bulk ecosystem (Legislative Reference Library, OpenStates, LegiScan,
data.texas.gov, Internet Archive, UNT Portal to Texas History).

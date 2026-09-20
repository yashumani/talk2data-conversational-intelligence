## Outcome and product slice

Describe the complete, testable behavior delivered by this pull request.

## Scope contract

- Registry or roadmap IDs:
- User-visible capability:
- Explicitly out of scope:
- Compatibility or migration impact:

## Security and data boundaries

- [ ] No credentials, private source names, proprietary schemas, or production data are included.
- [ ] Authorization remains deterministic and outside model prompts.
- [ ] New model output is validated before use.
- [ ] Data access remains read-only unless separately approved.
- [ ] Public Pages assets contain no API client, runtime URL, credential, or browser storage.
- [ ] CSV and private BigQuery/Parquet services remain separately configured.
- [ ] Only synthetic or explicitly redistributable fixtures are included.

## Validation evidence

- [ ] Ruff lint and format checks
- [ ] Mypy
- [ ] Pytest
- [ ] Relevant manual smoke test
- [ ] Community, workflow, visualization, Pages, and public-security validators
- [ ] Frontend tests, all builds, and production/full dependency audits
- [ ] Hosted PostgreSQL/Docker evidence attached when applicable

Exact candidate SHA and evidence links:

## Documentation and community impact

- [ ] User/contributor documentation reflects the behavior and limitations.
- [ ] Changelog and version metadata are updated when release-visible.
- [ ] New public contracts have an issue form, runbook, or matrix entry.
- [ ] Commit includes an author-matching DCO sign-off (`git commit -s`).

## Known limitations and next step

Document intentionally deferred work and the next highest-priority unblocked slice.

## Release decision

- [ ] This PR is not described as releasable until every mandatory item in
      `docs/PUBLIC_ALPHA_RELEASE_CHECKLIST.md` is satisfied for the exact SHA.

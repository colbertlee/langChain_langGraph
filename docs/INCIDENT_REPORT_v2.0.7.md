# Incident Report · v2.0.7 release

> **Date observed**: 2026-09-03
> **Author**: colbertlee
> **Severity**: Medium (no data loss; no service outage; user-facing only)
> **Status**: Resolved (mitigations shipped in PRs #2 and #3)
> **Related docs**: [POST_CLEANUP_VERIFICATION.md](POST_CLEANUP_VERIFICATION.md), [VERSION_MANAGEMENT.md](VERSION_MANAGEMENT.md)

---

## 1. Summary

During the v2.0.7 release a number of long-standing process gaps surfaced that
should have been documented as an SOP but never were. None of the issues caused
data loss or downtime, but they made the release feel ad-hoc and required
manual recovery steps that would not scale to a second maintainer.

This report consolidates **6 distinct incidents** into a single retro, ranks
them by severity, and documents the concrete mitigations that landed in
PRs #2 and #3 (release_cli.py + branch protection + orphan cleanup).

---

## 2. Incidents

### I-1 · Orphan `main` branch could not be deleted

**Severity**: Low
**Surface**: 2026-09-03 during orphan-branch cleanup

**What happened**: After merging the v2.0.7 cleanup PR (#1), GitHub still had
a `main` branch pointing at an empty commit (auto-created when the repo was
initialized in 2026-07). `git push origin --delete main` returned:

```
remote: error: Cannot delete the default branch
```

**Root cause**: `main` was still configured as `default_branch` at the repo
level. GitHub refuses to delete the default branch for safety.

**Why it wasn't caught earlier**: There was no SOP covering orphan-branch
cleanup. The cleanup PR (#1) merged without verifying the resulting branch
inventory.

**Mitigation (shipped in PR #3 + §7.6.2 of VERSION_MANAGEMENT.md)**:
1. PATCH `default_branch=master` first
2. Then DELETE `refs/heads/main` (returns HTTP 204)
3. Documented as mandatory step in §7.6

**Preventive control**:
- `release_cli.py cleanup --switch-default-to-master --delete-main` wraps
  both steps atomically and refuses to run them in the wrong order.

---

### I-2 · Branch protection payload rejected (HTTP 422)

**Severity**: Low
**Surface**: 2026-09-03 during initial §7.5.2 enable

**What happened**: First PUT against
`/repos/.../branches/master/protection` returned HTTP 422:

```json
{
  "message": "Invalid request.\n\n\"required_status_checks\", \"restrictions\" weren't supplied."
}
```

**Root cause**: Recent GitHub REST API versions **require** both
`required_status_checks` and `restrictions` fields to be **explicitly
present** (even as `null`). Omitting them is no longer accepted; the
documentation is unclear on this point.

**Why it wasn't caught earlier**: §7.5.4 examples in older SOPs (from v2.0.4
era) omitted these fields because they were optional at that time.

**Mitigation (shipped in PR #2)**:
- `apply_branch_protection.{sh,ps1}` and `release_cli.py protect` now always
  include both fields.
- VERSION_MANAGEMENT.md §7.5.2 has a warning callout + the corrected payload.

---

### I-3 · Single-owner repo deadlock on first PR merge

**Severity**: Medium
**Surface**: 2026-09-04 during PR #2 merge

**What happened**: After enabling `enforce_admins=true` +
`required_approving_review_count=1` + `require_last_push_approval=true`,
the **owner could not merge their own PR**. GitHub returned:

```json
{"message": "At least 1 approving review is required by reviewers with write access."}
```

`enforce_admins=true` made the admin-bypass route unavailable, and there is
no second approver in the repo.

**Root cause**: These three settings together form a *PR + approve* loop that
**requires two humans** to close. Single-owner repos cannot complete the loop.

**Why it wasn't caught earlier**: §7.5.2 was written assuming a multi-maintainer
team. The single-owner case was never validated.

**Mitigation (shipped in PR #3)**:
- §7.5.2 now exposes two payload variants:
  - **Multi-maintainer** (recommended): keep `reviews=1`, `last_push_approval=true`
  - **Single-owner** (this repo): `reviews=0`, `last_push_approval=false`
- The single-owner payload still preserves **all other strict protections**:
  linear history, no force push, no branch deletion, enforce_admins,
  conversation resolution.
- §7.5.2 includes a "upgrade trigger": when a second maintainer joins,
  immediately switch back to the multi-maintainer payload.

**Preventive control**: `release_cli.py status` should be run before pushing
to verify the protection payload matches the team's ownership model.

---

### I-4 · release_cli.py / publish_to_releases.py were deleted by cleanup

**Severity**: Medium (tooling gap, not a runtime outage)
**Surface**: 2026-09-03 (immediately after cleanup merge)

**What happened**: The v2.0.7 cleanup commit (`916992a chore(cleanup):
remove build artifacts + legacy tests + preview/screenshot files (-5.3GB)`)
removed `ai_agent/publish_to_releases.py`, `ai_agent/upload_to_github_release.py`,
`ai_agent/release_cli.py`, and the entire `scripts/` tree. After the cleanup
there was **no working CLI** to publish new releases.

**Root cause**: The cleanup policy treated any unreferenced Python file as
"legacy". But `release_cli.py` was the documented entry point in
`VERSION_MANAGEMENT.md` (which itself wasn't checked in).

**Why it wasn't caught earlier**: There was no dependency check in the
cleanup commit — it just deleted files matching patterns.

**Mitigation (shipped in PR #2)**:
- New `scripts/release/release_cli.py` replaces the old one, but with a
  **slimmer dependency surface**:
  - Uses stdlib `urllib.request` only (no `requests` / `gh` required)
  - gh CLI is a nice-to-have, with curl-style REST fallback
- Documented as the canonical entry point in README.md "release owner" row.

**Preventive control**: future cleanup PRs should run
`git grep -l 'release_cli\|publish_to_releases' docs/` before deleting
Python files. A `--dry-run` mode for cleanup would also help.

---

### I-5 · Tag target drift between local and remote

**Severity**: Low
**Surface**: 2026-09-03 during the initial fetch after cleanup

**What happened**: `git fetch --tags origin` returned:

```
! [rejected]   v2.0.7-cleanup-verified -> v2.0.7-cleanup-verified  (would clobber existing tag)
```

because the local tag pointed at `25fecda` while the remote tag pointed at
`66d6312` (one cleanup-verification commit later).

**Root cause**: The local tag was created during the v2.0.7 milestone build
(before the post-cleanup verification report was added). The remote tag was
pushed by the v2.0.7 release PR **after** the verification report, which
GitHub considers a valid tag update (tags are mutable until first fetch).

**Why it wasn't caught earlier**: No SOP defined which side wins on tag
conflict.

**Mitigation (shipped in PR #2)**:
- §7.2 in VERSION_MANAGEMENT.md codifies: **remote wins, never force-push**
- The recovery procedure:
  ```bash
  git tag -d vX.Y.Z                      # delete local
  git fetch origin refs/tags/vX.Y.Z:refs/tags/vX.Y.Z  # re-fetch from remote
  ```

**Preventive control**: tag creation in `release_cli.py github` checks
`_tag_exists` before creating a local tag, so this drift pattern can no longer
appear in greenfield releases.

---

### I-6 · Cleanup backup branch `chore/project-cleanup-backup` lingered

**Severity**: Low (cosmetic, but risk of confusion)

**What happened**: The cleanup PR created a backup branch at the
pre-cleanup snapshot (`66162cf`) and never deleted it. It was visible in
`git branch -a` for several weeks and could have confused a new contributor
into thinking the cleanup hadn't happened.

**Root cause**: No SOP for backup-branch retention.

**Mitigation (handled in cleanup session)**:
- §7.1 / §7.6.4 now codify backup-branch deletion as a release-step
- The branch was force-deleted via `git branch -D chore/project-cleanup-backup`
  after confirming its commits are all reachable from `master` (cleanup series)

---

## 3. Severity Matrix

| ID | Severity | Surface | User-visible? | Lost data? | Status |
|---|---|---|---|---|---|
| I-1 | Low | Post-release cleanup | No | No | Resolved (PR #3) |
| I-2 | Low | Initial §7.5.2 enable | No | No | Resolved (PR #2) |
| I-3 | Medium | First PR merge attempt | No | No | Resolved (PR #3) |
| I-4 | Medium | Post-cleanup | Yes (no CLI to release) | No | Resolved (PR #2) |
| I-5 | Low | Post-release fetch | No | No | Resolved (PR #2) |
| I-6 | Low | Branch hygiene | No | No | Resolved (this session) |

---

## 4. What Went Well

- **PR #1 (cleanup) itself**: merged cleanly, 1.06 GB → 527 MB size reduction,
  zero regression in the automated test suite (per
  [POST_CLEANUP_VERIFICATION.md](POST_CLEANUP_VERIFICATION.md)).
- **Verification report was committed BEFORE release tagging** (good
  sequencing; this is what made the release PR easy to write).
- **Owner noticed all 6 issues within 24 hours** and acted on them.

## 5. What Didn't Go Well

- No incident-report template existed, so the retro was done ad-hoc.
- No CI to catch `publish_to_releases.py` deletion in PR #1 (no workflows
  folder at all).
- §7.5.2 was written from theory, not from single-owner-repo reality.
- The "orphan branch cleanup" SOP was invented on the spot during this
  session, not pre-documented.

## 6. Action Items

| # | Action | Owner | Status | Target |
|---|---|---|---|---|
| A-1 | Ship release_cli.py + branch protection + PR template | colbertlee | ✅ Done | PR #2 |
| A-2 | Document single-owner protection payload | colbertlee | ✅ Done | PR #3 |
| A-3 | Add tag-driven release workflow | colbertlee | ✅ Done | this PR |
| A-4 | Add PR-merge-label workflow | colbertlee | ✅ Done | this PR |
| A-5 | Pre-flight cleanup-check script (`scripts/release/preflight_cleanup.py`) | colbertlee | ⏳ TODO | v2.0.8 |
| A-6 | Add CODEOWNERS file requiring release owner approval on `VERSION_MANAGEMENT.md` | colbertlee | ⏳ TODO | v2.0.8 |
| A-7 | Add CI status checks to master branch protection | colbertlee | ⏳ TODO | when CI exists |

---

## 7. Lessons Learned (TL;DR)

1. **GitHub's REST API has stricter requirements than the docs imply**.
   Always send `required_status_checks: null` and `restrictions: null`
   explicitly in branch-protection payloads.

2. **Single-owner repos are a real edge case** that default SOP templates
   ignore. Always validate protection payloads with an end-to-end PR
   **before** locking them in.

3. **A `gh CLI` installation cannot be assumed**. release_cli.py must work
   on a stock Windows / Linux box with only Python stdlib.

4. **Cleanup PRs are risky**. They are the only kind of PR that can silently
   remove the tooling that other PRs depend on. Add a `--dry-run` mode and
   a "what depends on this file?" check.

5. **Documentation before tooling**. VERSION_MANAGEMENT.md was committed in
   §7.5.4 reference but the file didn't exist for weeks. Always commit the
   doc + the tool in the same PR.

6. **Tags are mutable until first fetch**. Decide explicitly which side
   wins on conflict (we chose: remote wins, never force-push).

---

## 8. Related Commits

| Commit | Description |
|---|---|
| `916992a` | chore(cleanup): remove build artifacts + legacy tests (-5.3GB) — **root** |
| `25fecda` | docs: add post-cleanup verification report |
| `66d6312` | docs: add post-cleanup verification report (re-applied) |
| `dbb36b8` | Merge pull request #1 from colbertlee/release/v2.0.7-cleanup-verified |
| `ff4c57e` | docs(version): add VERSION_MANAGEMENT.md + branch-protection tooling |
| `439c412` | fix(release): branch-protection payload requires explicit null fields |
| `42e97ce` | feat(release): release_cli.py + release PR template + README cross-links — PR #2 |
| `129cb6e` | docs(version): single-owner branch-protection recipe — PR #3 |
| `TBD`    | feat(release): gitee release + webhook sub + CI workflows + incident report — this PR |

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
manual intervention at every step.

The v2.0.8 release ships a complete SOP and a cross-platform release CLI to
prevent these issues from recurring.

---

## 2. Incidents

### I-1. Orphan `main` branch cannot be deleted
- **Symptom**: GitHub repository has both `master` and `main`. Trying to delete
  `main` via `DELETE /git/refs/heads/main` returns `422 Cannot delete the
  default branch`.
- **Root cause**: GitHub initializes the repository with a default branch
  (`main` since 2020-10); local pushes of `master` end up alongside it. `main`
  is the default, so it can't be deleted until the default is patched to
  something else.
- **Fix**: §7.6.2 in VERSION_MANAGEMENT.md — PATCH default_branch first, then
  DELETE the orphan ref.

### I-2. Branch protection PUT returns 422
- **Symptom**: `PUT /branches/master/protection` returns `422 Invalid request`
  even though the payload looks correct.
- **Root cause**: GitHub REST API requires `required_status_checks` and
  `restrictions` to be **explicitly present** in the PUT body, even when
  `null`. Omitting them silently fails validation.
- **Fix**: §7.5.4 in VERSION_MANAGEMENT.md — payload template includes both
  fields. `release_cli.py protect` enforces this.

### I-3. Single-owner PR deadlock
- **Symptom**: With `enforce_admins=true` and `required_approving_review_count=1`,
  the only owner cannot merge their own PR — and no one else can approve.
- **Root cause**: Strict protection rules assume multi-owner collaboration.
- **Fix**: §7.5.2 in VERSION_MANAGEMENT.md — split the recipe into
  "multi-owner (recommended)" vs "single-owner (this repo)". Single-owner
  recipe uses `required_approving_review_count=0` and
  `require_last_push_approval=false`.

### I-4. `release_cli.py` was deleted by cleanup
- **Symptom**: An earlier `release_cli.py` (bash + curl) was cleaned up along
  with the orphan branches and stopped being recoverable.
- **Root cause**: Cleanup ran before the script was checked into git.
- **Fix**: New `scripts/release/release_cli.py` (Python, 100% stdlib) is
  committed and part of `master`. Tested on PowerShell 5.1 / Bash 4+.

### I-5. Local / remote tag drift
- **Symptom**: After publishing v2.0.7, a local tag was moved to a different
  commit than the GitHub Release `target_commitish`.
- **Root cause**: Manual re-tagging without realizing the tag was already
  bound to a release.
- **Fix**: §7.2 in VERSION_MANAGEMENT.md — "remote wins, never force-push".

### I-6. Cleanup left backup branches
- **Symptom**: `chore/project-cleanup-backup*` branches survived the
  cleanup, taking up branch-list real estate.
- **Root cause**: No retention policy documented.
- **Fix**: §7.6.3 in VERSION_MANAGEMENT.md — keep 2 weeks for audit, then
  delete.

### I-7. PAT lacks `workflow` scope
- **Symptom**: `.github/workflows/*.yml` files were written but couldn't be
  pushed because the PAT didn't have the `workflow` scope.
- **Root cause**: The PAT used for `git push` was issued with `repo` scope
  but not `workflow`.
- **Fix (workaround)**: The release CLI is fully usable without the workflows.
  `release.yml` and `pr-merge-label.yml` are optional accelerators; they
  remain useful once a workflow-scoped PAT is provisioned.
- **Fix (permanent)**: Re-issue the PAT with `workflow` scope. v2.0.9 has
  the workflow files committed to master so they're ready to run as soon as
  the new PAT is in place.

---

## 3. Lessons learned

- **"Document or it didn't happen"**: every release-time ritual should have
  a written SOP entry. Otherwise the next person (or future-self) re-discovers
  the gotchas the hard way.
- **Test the SOP on a toy release first**: §7.5.2 was written from theory,
  not from single-owner-repo reality.
- **The "orphan branch cleanup" SOP was invented on the spot during this
  session, not pre-documented.

---

## 4. Action Items

| # | Action | Owner | Status | Target |
|---|---|---|---|---|
| A-1 | Ship release_cli.py + branch protection + PR template | colbertlee | ✅ Done | PR #2 |
| A-2 | Document single-owner protection payload | colbertlee | ✅ Done | PR #3 |
| A-3 | Add tag-driven release workflow | colbertlee | ✅ Done | v2.0.9 (committed in master; auto-runs after PAT `workflow` scope is granted) |
| A-4 | Add PR-merge-label workflow | colbertlee | ✅ Done | v2.0.9 (same caveat as A-3) |
| A-5 | Pre-flight cleanup-check script (`scripts/release/preflight_cleanup.py`) | colbertlee | ⏳ TODO | v2.0.10 |
| A-6 | Add CODEOWNERS file requiring release owner approval on `VERSION_MANAGEMENT.md` | colbertlee | ⏳ TODO | v2.0.10 |
| A-7 | Add CI status checks to master branch protection | colbertlee | ⏳ TODO | when A-3/A-4 CI is enabled (PAT `workflow` scope) |
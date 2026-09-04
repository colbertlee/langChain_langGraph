#!/usr/bin/env python3
# scripts/release/release_cli.py
# Unified release CLI for colbertlee/langChain_langGraph (v2.0.7+).
#
# Subcommands:
#   github    Push tag + create GitHub Release (via gh CLI or REST API)
#   gitee     Push tag + create Gitee Release (mirror)
#   protect   Apply branch protection (wraps apply_branch_protection.{sh,ps1})
#   cleanup   Orphan-branch cleanup per docs/VERSION_MANAGEMENT.md section 7.6
#   status    Show latest release + tag/protection state
#
# Usage:
#   python scripts/release/release_cli.py github v2.0.7 --body release_notes.md
#   python scripts/release/release_cli.py gitee  v2.0.7
#   python scripts/release/release_cli.py protect master --enforce-admins
#   python scripts/release/release_cli.py cleanup --delete-main
#   python scripts/release/release_cli.py status
#
# Ref: docs/VERSION_MANAGEMENT.md
# Exit codes: 0 = success, 1 = sub-step failure, 2 = argument error

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTECT_PS1 = REPO_ROOT / "scripts" / "release" / "apply_branch_protection.ps1"
PROTECT_SH = REPO_ROOT / "scripts" / "release" / "apply_branch_protection.sh"

GITHUB_REPO = os.environ.get("GH_REPO", "colbertlee/langChain_langGraph")
GITEE_REPO = os.environ.get("GITEE_REPO", "colbertlee/langChain_langGraph")
GITEE_BINARIES_REPO = os.environ.get("GITEE_BINARIES_REPO", "colbertlee/ai-agent-releases")

_LOG_LEVEL = os.environ.get("RELEASE_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] release_cli: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("release_cli")


# ============================================================
# Subcommand: github
# ============================================================
def cmd_github(args) -> int:
    """Push tag + create GitHub Release."""
    log.info("=" * 70)
    log.info("  PUBLISH TO GITHUB")
    log.info("=" * 70)
    version = _normalize_version(args.version)
    log.info("  Version:  %s", version)
    log.info("  Repo:     %s", GITHUB_REPO)

    # Step 1: push tag (annotated)
    if not args.skip_push:
        tag = f"v{version}"
        if not _tag_exists(tag):
            log.info("  [1/3] Creating annotated tag %s ...", tag)
            _run(["git", "tag", "-a", tag, "-m", f"release: v{version}"], check=True)
        else:
            log.info("  [1/3] Tag %s already exists locally", tag)
        log.info("  [2/3] Pushing tag %s to origin ...", tag)
        _run(["git", "push", "origin", tag], check=True)
    else:
        log.info("  [skip] Tag push skipped (--skip-push)")

    # Step 2: create Release (gh CLI first, curl fallback)
    log.info("  [3/3] Creating GitHub Release ...")
    if shutil.which("gh"):
        _create_release_via_gh(args, version)
    else:
        log.info("  gh CLI not found; falling back to REST API (curl)")
        _create_release_via_curl(args, version)

    return 0


def _create_release_via_gh(args, version: str) -> None:
    cmd = [
        "gh", "release", "create", f"v{version}",
        "--repo", GITHUB_REPO,
    ]
    if args.target:
        cmd.extend(["--target", args.target])
    if args.body:
        cmd.extend(["--notes-file", args.body])
    elif args.body_text:
        cmd.extend(["--notes", args.body_text])
    if args.draft:
        cmd.append("--draft")
    if args.prerelease:
        cmd.append("--prerelease")
    if args.title:
        cmd.extend(["--title", args.title])
    cmd.extend(args.assets or [])
    log.info("  Running: %s", " ".join(cmd))
    _run(cmd, check=True)


def _create_release_via_curl(args, version: str) -> None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        log.error("GH_TOKEN (or GITHUB_TOKEN) not set; cannot call REST API")
        sys.exit(1)

    # Resolve target SHA
    target_sha = args.target or _get_default_branch_sha(GITHUB_REPO, token)
    log.info("  Target commit: %s", target_sha)

    # Build payload
    notes = ""
    if args.body and Path(args.body).is_file():
        notes = Path(args.body).read_text(encoding="utf-8")
    elif args.body_text:
        notes = args.body_text

    payload = {
        "tag_name": f"v{version}",
        "target_commitish": target_sha,
        "name": args.title or f"AI Agent v{version}",
        "body": notes,
        "draft": bool(args.draft),
        "prerelease": bool(args.prerelease),
    }

    # POST /releases
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            release = json.loads(r.read())
            log.info("  [OK] Release created: %s", release.get("html_url"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error("  [FAIL] HTTP %d: %s", e.code, body)
        sys.exit(1)

    # Upload assets
    if args.assets:
        upload_url = release["upload_url"].split("{")[0]
        for asset_path in args.assets:
            _upload_asset(upload_url, token, version, asset_path)


def _upload_asset(upload_url: str, token: str, version: str, asset_path: str) -> None:
    p = Path(asset_path)
    if not p.is_file():
        log.warning("  Asset not found, skipping: %s", asset_path)
        return
    log.info("  Uploading asset: %s (%s MB)", p.name, f"{p.stat().st_size / 1e6:.1f}")
    # URL-encode filename for Unicode safety
    from urllib.parse import quote
    safe_name = quote(p.name)
    with open(p, "rb") as f:
        req = urllib.request.Request(
            f"{upload_url}?name={safe_name}",
            data=f.read(),
            method="POST",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/octet-stream",
                "User-Agent": "release_cli.py",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                asset = json.loads(r.read())
                log.info("  [OK] Asset uploaded: %s", asset.get("browser_download_url"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            log.error("  [FAIL] Asset %s (HTTP %d): %s", p.name, e.code, body)
            sys.exit(1)


def _get_default_branch_sha(repo: str, token: str) -> str:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "release_cli.py",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    branch = data["default_branch"]
    req2 = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/branches/{branch}",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "release_cli.py",
        },
    )
    with urllib.request.urlopen(req2, timeout=15) as r:
        data2 = json.loads(r.read())
    return data2["commit"]["sha"]


def _tag_exists(tag: str) -> bool:
    rc = subprocess.run(["git", "tag", "-l", tag], capture_output=True, text=True).stdout.strip()
    return bool(rc)


# ============================================================
# Subcommand: gitee
# ============================================================
def cmd_gitee(args) -> int:
    """Mirror master + tags to Gitee, optionally create a Gitee Release."""
    log.info("=" * 70)
    log.info("  MIRROR TO GITEE")
    log.info("=" * 70)
    version = _normalize_version(args.version)
    log.info("  Version:  %s", version)
    log.info("  Repo:     %s", GITEE_REPO)
    log.info("  Create Release: %s", bool(args.create_release and os.environ.get("GITEE_TOKEN")))

    # Step 1: push master + tags
    if not args.skip_push:
        log.info("  [1/3] Pushing master to gitee ...")
        _run(["git", "push", "gitee", "master"], check=True)
        for t in [f"v{version}", f"v{version}-cleanup-verified"]:
            if _tag_exists(t):
                log.info("  [2/3] Pushing tag %s to gitee ...", t)
                _run(["git", "push", "gitee", t], check=True)
            else:
                log.info("  [2/3] Skip: tag %s does not exist locally", t)
    else:
        log.info("  [skip] Tag push skipped (--skip-push)")

    # Step 2: optionally create Gitee Release (only if both --create-release and GITEE_TOKEN set)
    if args.create_release:
        token = os.environ.get("GITEE_TOKEN")
        if not token:
            log.error("  --create-release requires GITEE_TOKEN env var; skipping")
            return 1
        log.info("  [3/3] Creating Gitee Release ...")
        _create_gitee_release(version, token, args)
    else:
        log.info("  [3/3] Skip Release creation (pass --create-release to enable)")
        log.info("  Note: per VERSION_MANAGEMENT.md section 6, GitHub is the source of truth;")
        log.info("        Gitee Releases are optional and only for users stuck behind GFW.")

    log.info("  [OK] Gitee mirror synced")
    return 0


def _create_gitee_release(version: str, token: str, args) -> None:
    """Create a Gitee Release via Gitee OpenAPI v5.

    Gitee API: POST https://gitee.com/api/v5/repos/{owner}/{repo}/releases
    Required scope: project (token must be personal access token with project scope).
    """
    tag_name = f"v{version}"
    target = args.target or "master"
    notes = ""
    if args.body and Path(args.body).is_file():
        notes = Path(args.body).read_text(encoding="utf-8")
    elif getattr(args, "body_text", None):
        notes = args.body_text

    payload = {
        "tag_name": tag_name,
        "target_commitish": target,
        "name": getattr(args, "title", None) or f"AI Agent v{version}",
        "body": notes,
        "prerelease": bool(getattr(args, "prerelease", False)),
        "draft": False,
    }

    req = urllib.request.Request(
        f"https://gitee.com/api/v5/repos/{GITEE_REPO}/releases",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            release = json.loads(r.read())
            log.info("  [OK] Gitee Release created: %s", release.get("html_url"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error("  [FAIL] Gitee Release HTTP %d: %s", e.code, body)
        sys.exit(1)

    # Upload assets if requested
    for asset_path in getattr(args, "assets", []) or []:
        _upload_gitee_asset(release.get("id"), token, asset_path)


def _upload_gitee_asset(release_id: str, token: str, asset_path: str) -> None:
    """Upload asset to a Gitee Release via multipart upload_url."""
    p = Path(asset_path)
    if not p.is_file():
        log.warning("  Asset not found, skipping: %s", asset_path)
        return
    log.info("  Uploading Gitee asset: %s (%s MB)", p.name, f"{p.stat().st_size / 1e6:.1f}")

    # Gitee accepts multipart/form-data; build minimal manual multipart body
    boundary = "----release_cli_boundary_" + os.urandom(8).hex()
    filename = p.name
    with open(p, "rb") as f:
        file_bytes = f.read()
    parts = []
    parts.append(f"--{boundary}\r\n")
    parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n')
    parts.append("Content-Type: application/octet-stream\r\n\r\n")
    body = "".join(parts).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"https://gitee.com/api/v5/repos/{GITEE_REPO}/releases/{release_id}/attach_files",
        data=body,
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            log.info("  [OK] Gitee asset uploaded: %s", p.name)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error("  [FAIL] Gitee asset %s (HTTP %d): %s", p.name, e.code, body)
        sys.exit(1)


# ============================================================
# Subcommand: webhook (apply side-effects on PR merge events)
# ============================================================
def cmd_webhook(args) -> int:
    """Apply side-effects when a PR is merged.

    Currently supports:
      - Add a 'merged' label to a release PR
      - (future) auto-close linked issues
      - (future) notify a webhook URL

    Designed to be called from a CI workflow on pull_request.closed action
    where action == 'closed' and merged == true.

    Required env vars:
      GH_TOKEN, PR_NUMBER (the PR id)
      REPO (defaults to colbertlee/langChain_langGraph)
    """
    log.info("=" * 70)
    log.info("  PR WEBHOOK HANDLER")
    log.info("=" * 70)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        log.error("GH_TOKEN env var is required")
        return 1

    pr_number = args.pr_number or os.environ.get("PR_NUMBER")
    if not pr_number:
        log.error("--pr-number (or PR_NUMBER env) is required")
        return 1

    repo = args.repo or os.environ.get("REPO") or GITHUB_REPO
    log.info("  Repo:      %s", repo)
    log.info("  PR number: %s", pr_number)
    log.info("  Action:    %s", args.action)

    # Fetch PR to detect merged state
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            pr = json.loads(r.read())
    except urllib.error.HTTPError as e:
        log.error("Failed to fetch PR: HTTP %d", e.code)
        return 1

    merged = bool(pr.get("merged"))
    state = pr.get("state")
    log.info("  PR state:  %s", state)
    log.info("  Merged:    %s", merged)

    if args.action == "merged" and not merged:
        log.warning("  PR is not merged but --action=merged was specified; skipping label")
        return 0

    # Step 1: ensure label exists
    if args.label:
        log.info("  [1/3] Ensuring label '%s' exists ...", args.label)
        _ensure_label(repo, token, args.label, color="0E8A16", description="PR has been merged")

    # Step 2: apply label
    if args.label:
        log.info("  [2/3] Applying label to PR ...")
        _apply_label(repo, token, pr_number, args.label)

    # Step 3: optional close-comment
    if args.comment and merged:
        log.info("  [3/3] Posting merge comment ...")
        _post_pr_comment(repo, token, pr_number, args.comment)

    log.info("  [OK] Webhook handler complete")
    return 0


def _ensure_label(repo: str, token: str, name: str, color: str, description: str) -> None:
    """Idempotently create a label (ignore 422 'already exists')."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/labels",
        data=json.dumps({"name": name, "color": color, "description": description}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            log.info("    label '%s' created", name)
    except urllib.error.HTTPError as e:
        if e.code == 422:
            log.info("    label '%s' already exists (skip)", name)
        else:
            log.warning("    label create failed HTTP %d: %s", e.code, e.read().decode("utf-8", errors="replace"))


def _apply_label(repo: str, token: str, pr_number: str, name: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels",
        data=json.dumps({"labels": [name]}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            log.info("    [OK] label '%s' applied to PR #%s", name, pr_number)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error("    [FAIL] HTTP %d: %s", e.code, body)
        sys.exit(1)


def _post_pr_comment(repo: str, token: str, pr_number: str, body: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
        data=json.dumps({"body": body}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            log.info("    [OK] comment posted")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error("    [FAIL] HTTP %d: %s", e.code, body)
        sys.exit(1)


# ============================================================
# Subcommand: protect
# ============================================================
def cmd_protect(args) -> int:
    """Apply branch protection by delegating to apply_branch_protection.{sh,ps1}."""
    log.info("=" * 70)
    log.info("  APPLY BRANCH PROTECTION")
    log.info("=" * 70)
    log.info("  Branch: %s", args.branch)
    log.info("  Enforce admins: %s", args.enforce_admins)

    if not os.environ.get("GH_TOKEN"):
        log.error("GH_TOKEN env var is required")
        return 1

    if sys.platform == "win32" and PROTECT_PS1.exists():
        cmd = [
            "powershell", "-ExecutionPolicy", "Bypass",
            "-File", str(PROTECT_PS1), args.branch,
        ]
    elif PROTECT_SH.exists():
        cmd = ["bash", str(PROTECT_SH), args.branch]
    else:
        log.error("Neither apply_branch_protection.ps1 nor .sh found")
        return 1

    log.info("  Running: %s", " ".join(cmd))
    _run(cmd, check=False)

    # Apply enforce_admins override if requested
    if args.enforce_admins is not None:
        _patch_enforce_admins(args.branch, args.enforce_admins)

    return 0


def _patch_enforce_admins(branch: str, enforce: bool) -> None:
    token = os.environ.get("GH_TOKEN")
    log.info("  Patching enforce_admins=%s on %s ...", enforce, branch)
    payload = {
        "required_status_checks": None,
        "enforce_admins": enforce,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "required_approving_review_count": 1,
        } if branch == "master" else None,
        "restrictions": None,
        "required_linear_history": True if branch == "master" else False,
        "allow_force_pushes": False,
        "allow_deletions": False,
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/branches/{branch}/protection",
        data=json.dumps(payload).encode("utf-8"),
        method="PUT",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            log.info("  [OK] enforce_admins=%s applied", data["enforce_admins"]["enabled"])
    except urllib.error.HTTPError as e:
        log.error("  [FAIL] HTTP %d", e.code)


# ============================================================
# Subcommand: cleanup (orphan branch cleanup per section 7.6)
# ============================================================
def cmd_cleanup(args) -> int:
    """Orphan branch cleanup per docs/VERSION_MANAGEMENT.md section 7.6."""
    log.info("=" * 70)
    log.info("  ORPHAN BRANCH CLEANUP")
    log.info("=" * 70)

    token = os.environ.get("GH_TOKEN")
    if not token and (args.delete_main or args.list_remote):
        log.error("GH_TOKEN env var is required for remote operations")
        return 1

    # Step 1: list remote branches
    if args.list_remote:
        _list_remote_branches(token)
        return 0

    # Step 2: switch default_branch to master (must come before delete main)
    if args.switch_default_to_master:
        log.info("  [1/4] Switching default branch to master ...")
        _patch_default_branch(token, "master")

    # Step 3: delete orphan main
    if args.delete_main:
        log.info("  [2/4] Deleting orphan main branch ...")
        _delete_remote_ref(token, "main")

    # Step 4: prune stale local refs
    log.info("  [3/4] Pruning local refs ...")
    _run(["git", "remote", "set-head", "origin", "-d"], check=False)
    _run(["git", "fetch", "--prune", "origin"], check=False)

    # Step 5: print remaining
    log.info("  [4/4] Remaining remote branches:")
    _list_remote_branches(token)
    log.info("")
    log.info("  Next: see docs/VERSION_MANAGEMENT.md section 7.6 for retention policy")
    return 0


def _patch_default_branch(token: str, branch: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}",
        data=json.dumps({"default_branch": branch}).encode("utf-8"),
        method="PATCH",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "release_cli.py",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
        log.info("    default_branch: %s", data["default_branch"])


def _delete_remote_ref(token: str, ref: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/git/refs/heads/{ref}",
        method="DELETE",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "release_cli.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            log.info("    [OK] ref deleted (HTTP %d)", r.status)
    except urllib.error.HTTPError as e:
        log.error("    [FAIL] HTTP %d: %s", e.code, e.read().decode("utf-8", errors="replace"))


def _list_remote_branches(token: str | None) -> None:
    cmd = ["git", "ls-remote", "origin"]
    if token is None:
        log.info("    (using unauthenticated ls-remote)")
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    seen = set()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref.startswith("refs/heads/"):
            short = ref[len("refs/heads/"):]
            if short not in seen:
                seen.add(short)
                log.info("      - %s  (%s)", short, sha[:8])


# ============================================================
# Subcommand: status
# ============================================================
def cmd_status(args) -> int:
    """Show latest release + tag/protection state."""
    log.info("=" * 70)
    log.info("  RELEASE STATUS")
    log.info("=" * 70)

    # Local
    log.info("  Local master:  %s", _git_rev("master"))
    log.info("")
    log.info("  Local tags:")
    tag_proc = _run(["git", "tag", "-l", "--sort=-version:refname"], capture=True)
    for line in (tag_proc.stdout or "").splitlines()[:10]:
        log.info("    - %s", line)
    log.info("")

    # GitHub
    token = os.environ.get("GH_TOKEN")
    if token:
        log.info("  GitHub releases:")
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=5",
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "release_cli.py",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                for rel in json.loads(r.read()):
                    log.info("    - %s  target=%s  prerelease=%s",
                             rel["tag_name"],
                             rel["target_commitish"][:8],
                             rel["prerelease"])
        except urllib.error.HTTPError as e:
            log.warning("    [FAIL] HTTP %d", e.code)
    else:
        log.info("  GitHub releases: (set GH_TOKEN to query)")

    log.info("")
    log.info("  For full SOP, see docs/VERSION_MANAGEMENT.md")
    return 0


# ============================================================
# Helpers
# ============================================================
def _normalize_version(v: str) -> str:
    return v.lstrip("v")


def _git_rev(ref: str) -> str:
    out = subprocess.run(["git", "rev-parse", ref], capture_output=True, text=True)
    return out.stdout.strip()[:12]


def _run(cmd: list, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=check,
        capture_output=capture,
        text=True,
    )


def print_summary(args, start_time, success):
    duration = datetime.now() - start_time
    log.info("")
    log.info("=" * 70)
    log.info("  [release_cli SUMMARY]")
    log.info("=" * 70)
    log.info("  Command:   %s", args.command)
    log.info("  Version:   %s", getattr(args, "version", None) or "(n/a)")
    log.info("  Status:    %s", "OK SUCCESS" if success else "FAIL FAILED")
    log.info("  Duration:  %.1fs", duration.total_seconds())
    log.info("=" * 70)


# ============================================================
# argparse
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release_cli",
        description="Unified release CLI for colbertlee/langChain_langGraph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Subcommands:
  github    Push tag + create GitHub Release
  gitee     Push tag + mirror to Gitee (--create-release for Gitee Release)
  protect   Apply branch protection (wraps apply_branch_protection.*)
  cleanup   Orphan-branch cleanup per VERSION_MANAGEMENT.md section 7.6
  webhook   Apply side-effects on PR events (label/comment)
  status    Show latest release + tag/protection state

Examples:
  python scripts/release/release_cli.py github v2.0.7 --body release_notes.md
  python scripts/release/release_cli.py gitee v2.0.7 --create-release --body notes.md
  python scripts/release/release_cli.py protect master --enforce-admins
  python scripts/release/release_cli.py cleanup --switch-default-to-master --delete-main
  python scripts/release/release_cli.py webhook --pr-number 2 --label release
  python scripts/release/release_cli.py status
""",
    )
    sub = parser.add_subparsers(dest="command", required=True, help="subcommand")

    # github
    p_gh = sub.add_parser("github", help="publish to GitHub")
    p_gh.add_argument("version", help="version like 2.0.7 (with or without 'v')")
    p_gh.add_argument("--body", help="path to release notes file (UTF-8)")
    p_gh.add_argument("--notes", dest="body_text", help="inline release notes")
    p_gh.add_argument("--title", help="release title (default: 'AI Agent vX.Y.Z')")
    p_gh.add_argument("--target", help="commit SHA or branch (default: default_branch HEAD)")
    p_gh.add_argument("--asset", dest="assets", action="append", default=[],
                      help="path to binary asset to upload (repeatable)")
    p_gh.add_argument("--draft", action="store_true")
    p_gh.add_argument("--prerelease", action="store_true")
    p_gh.add_argument("--skip-push", action="store_true",
                      help="skip git tag creation/push (Release-only)")

    # gitee
    p_gt = sub.add_parser("gitee", help="mirror to Gitee (optional Release creation)")
    p_gt.add_argument("version")
    p_gt.add_argument("--skip-push", action="store_true",
                      help="skip git push (Release creation only)")
    p_gt.add_argument("--create-release", action="store_true",
                      help="create a Gitee Release (requires GITEE_TOKEN env var)")
    p_gt.add_argument("--body", help="path to release notes file (UTF-8)")
    p_gt.add_argument("--notes", dest="body_text", help="inline release notes")
    p_gt.add_argument("--title", help="release title")
    p_gt.add_argument("--target", help="commit SHA or branch (default: master)")
    p_gt.add_argument("--asset", dest="assets", action="append", default=[],
                      help="path to binary asset to upload (repeatable)")
    p_gt.add_argument("--prerelease", action="store_true")

    # webhook
    p_wh = sub.add_parser("webhook",
                          help="apply side-effects on PR events (label/comment) "
                               "- typically called from CI on pull_request.closed")
    p_wh.add_argument("--pr-number", help="PR id (or set PR_NUMBER env)")
    p_wh.add_argument("--repo", help="repo (default: $REPO or $GH_REPO)")
    p_wh.add_argument("--action", default="merged",
                      choices=["merged", "closed", "opened"],
                      help="event action (default: merged)")
    p_wh.add_argument("--label", default="merged",
                      help="label to apply (default: 'merged')")
    p_wh.add_argument("--comment",
                      help="optional comment body to post after merge")

    # protect
    p_pr = sub.add_parser("protect", help="apply branch protection")
    p_pr.add_argument("branch", help="branch name (master or release/vX.Y.Z-...)")
    p_pr.add_argument("--enforce-admins", type=lambda s: s.lower() in ("true", "1", "yes"),
                      default=None,
                      help="override enforce_admins (true/false) after applying base rules")

    # cleanup
    p_cl = sub.add_parser("cleanup", help="orphan branch cleanup per section 7.6")
    p_cl.add_argument("--list-remote", action="store_true",
                      help="only list remote branches")
    p_cl.add_argument("--switch-default-to-master", action="store_true",
                      help="PATCH default_branch=master (required before deleting main)")
    p_cl.add_argument("--delete-main", action="store_true",
                      help="DELETE refs/heads/main (must run after switch-default)")

    # status
    sub.add_parser("status", help="show release status")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    start_time = datetime.now()
    try:
        rc = {"github": cmd_github, "gitee": cmd_gitee, "protect": cmd_protect,
              "cleanup": cmd_cleanup, "status": cmd_status,
              "webhook": cmd_webhook}[args.command](args)
        success = (rc == 0)
        print_summary(args, start_time, success)
        return rc
    except KeyboardInterrupt:
        log.error("Interrupted by user")
        return 1
    except Exception as e:
        log.exception("Unhandled exception: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

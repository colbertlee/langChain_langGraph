#!/usr/bin/env python3
"""One-shot script: push tag v2.0.8 to origin via GitHub REST API.

Bypasses git+https (intermittently blocked by GFW) by creating the tag object
and ref directly through the GitHub REST API.

Usage: GH_TOKEN=xxx python scripts/release/_push_tag_via_api.py 2.0.8
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

TAG_VERSION = sys.argv[1] if len(sys.argv) > 1 else "2.0.8"
TAG_NAME = f"v{TAG_VERSION}"
TAG_MESSAGE = f"release: v{TAG_VERSION} - tooling/process release (SOP + release_cli + incident report)"
COMMIT_SHA = "944cb80353b8e891f27faca476c279e17ef92fbc"  # squash-merged PR #6
REPO = os.environ.get("GH_REPO", "colbertlee/langChain_langGraph")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

if not TOKEN:
    print("ERROR: GH_TOKEN env var required", file=sys.stderr)
    sys.exit(1)


def _req(url, method, payload=None):
    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "_push_tag_via_api.py",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


code, body = _req(f"https://api.github.com/repos/{REPO}/git/refs/tags/{TAG_NAME}", "GET")
if code == 200:
    print(f"[SKIP] tag {TAG_NAME} already exists at {body['object']['sha'][:8]}")
    sys.exit(0)
elif code != 404:
    print(f"[FAIL] GET tag: HTTP {code} {body}", file=sys.stderr)
    sys.exit(1)
print(f"[1/3] tag {TAG_NAME} does not exist yet")

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
tag_payload = {
    "tag": TAG_NAME,
    "message": TAG_MESSAGE,
    "object": COMMIT_SHA,
    "type": "commit",
    "tagger": {
        "name": "colbertlee",
        "email": "colbertlee@users.noreply.github.com",
        "date": now,
    },
}
code, body = _req(f"https://api.github.com/repos/{REPO}/git/tags", "POST", tag_payload)
if code != 201:
    print(f"[FAIL] create tag object: HTTP {code} {body}", file=sys.stderr)
    sys.exit(1)
tag_sha = body["sha"]
print(f"[2/3] tag object created: {tag_sha[:8]}")

ref_payload = {"ref": f"refs/tags/{TAG_NAME}", "sha": tag_sha}
code, body = _req(f"https://api.github.com/repos/{REPO}/git/refs", "POST", ref_payload)
if code != 201:
    print(f"[FAIL] create tag ref: HTTP {code} {body}", file=sys.stderr)
    sys.exit(1)
print(f"[3/3] tag ref created: refs/tags/{TAG_NAME} -> {tag_sha[:8]}")
print(f"[OK] pushed tag {TAG_NAME} via REST API")
#!/usr/bin/env node
/**
 * 用 GitHub API 启用 main 分支保护。
 *
 * 用法：
 *   GITHUB_TOKEN=ghp_xxx node scripts/setup-branch-protection.mjs OWNER/REPO
 *
 * 需要：classic PAT with `repo` scope。
 */

const [, , repoArg] = process.argv;
if (!repoArg) {
  console.error('Usage: GITHUB_TOKEN=<token> node scripts/setup-branch-protection.mjs OWNER/REPO');
  process.exit(1);
}
const [owner, repo] = repoArg.split('/');
if (!owner || !repo) {
  console.error('Invalid repo format. Use OWNER/REPO');
  process.exit(1);
}

const token = process.env.GITHUB_TOKEN;
if (!token) {
  console.error('Missing GITHUB_TOKEN env var.');
  process.exit(1);
}

const body = {
  required_status_checks: {
    strict: true,
    contexts: [
      'e2e',
      'build',
      'type-check',
      'workflow-lint',
      'security',
    ],
  },
  enforce_admins: true,
  required_pull_request_reviews: {
    dismissal_restrictions: {},
    dismiss_stale_reviews: true,
    require_code_owner_reviews: false,
    required_approving_review_count: 1,
    require_last_push_approval: false,
  },
  restrictions: null,
  required_linear_history: true,
  allow_force_pushes: false,
  allow_deletions: false,
  block_creations: false,
  required_conversation_resolution: true,
  lock_branch: false,
  allow_fork_syncing: false,
};

const url = `https://api.github.com/repos/${owner}/${repo}/branches/main/protection`;

const res = await fetch(url, {
  method: 'PUT',
  headers: {
    Accept: 'application/vnd.github+json',
    Authorization: `Bearer ${token}`,
    'X-GitHub-Api-Version': '2022-11-28',
  },
  body: JSON.stringify(body),
});

if (!res.ok) {
  const text = await res.text();
  console.error('Failed:', res.status, text);
  process.exit(1);
}

const data = await res.json();
console.log('✅ Branch protection enabled for', repoArg);
console.log('   - Required status checks:', data.required_status_checks?.contexts?.length ?? 0);
console.log('   - Required reviews:', data.required_pull_request_reviews?.required_approving_review_count ?? 0);
console.log('   - Enforce admins:', data.enforce_admins);
console.log('   - Linear history:', data.required_linear_history);

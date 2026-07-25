#!/usr/bin/env node
/**
 * 检查依赖的最新版本，特别是 @assistant-ui/react 是否有 1.x / React 19 first-class 版本。
 *
 * 用法：
 *   node scripts/check-upgrades.mjs           # 检查所有
 *   node scripts/check-upgrades.mjs --json    # 输出 JSON（供 CI 使用）
 *   node scripts/check-upgrades.mjs --exit-1  # 任何升级可用时退出 1
 *
 * 在 CI 中可作为 weekly scheduled job：
 *   on:
 *     schedule:
 *       - cron: '0 9 * * MON'
 */

import { execSync } from 'node:child_process';

const WATCHED = [
  { name: '@assistant-ui/react', currentRange: '^0.14.27', tags: ['latest', 'next'] },
  { name: '@assistant-ui/react-markdown', currentRange: '^0.14.6' },
  { name: 'react', currentRange: '^19' },
  { name: 'react-dom', currentRange: '^19' },
];

function getInfo(pkg, tag = 'latest') {
  try {
    const v = execSync(`npm view ${pkg}@${tag} version peerDependencies --json`, {
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return JSON.parse(v);
  } catch (e) {
    return { error: e.message?.split('\n')[0] ?? 'unknown' };
  }
}

function isMajorAhead(current, latest) {
  const c = current.replace(/^[~^>=<]+\s*/, '').split('.')[0];
  const l = latest.split('.')[0];
  return parseInt(l) > parseInt(c);
}

function check() {
  const report = { timestamp: new Date().toISOString(), packages: [], upgradesAvailable: false };
  for (const w of WATCHED) {
    const latest = getInfo(w.name, 'latest');
    const next = getInfo(w.name, 'next');
    const entry = {
      name: w.name,
      currentRange: w.currentRange,
      latestVersion: latest?.version ?? null,
      latestPeers: latest?.peerDependencies ?? null,
      nextVersion: next?.version ?? null,
      upgradeAvailable: false,
      majorJump: false,
    };
    if (latest?.version) {
      // 简单 semver 比较
      const cur = w.currentRange.replace(/^[~^>=<]+\s*/, '');
      const curMaj = parseInt(cur.split('.')[0]);
      const latMaj = parseInt(latest.version.split('.')[0]);
      entry.upgradeAvailable = latest.version !== cur;
      entry.majorJump = latMaj > curMaj;
      if (entry.upgradeAvailable) report.upgradesAvailable = true;
    }
    if (next?.version && next.version !== latest?.version) {
      entry.nextVersion = next.version;
    }
    report.packages.push(entry);
  }
  return report;
}

function print(report) {
  console.log(`\n🔍 Dependency upgrade check @ ${report.timestamp}\n`);
  console.log('Package                                 Current       Latest        Next          Major↑');
  console.log('─'.repeat(96));
  for (const p of report.packages) {
    const cur = p.currentRange.padEnd(14);
    const lat = (p.latestVersion ?? '?').padEnd(13);
    const nxt = (p.nextVersion ?? '—').padEnd(13);
    const flag = p.majorJump ? '🟢 YES' : p.upgradeAvailable ? '🟡 patch' : '⚪ current';
    console.log(`${p.name.padEnd(40)} ${cur}${lat}${nxt}${flag}`);
  }
  if (report.upgradesAvailable) {
    console.log('\n✨ Major upgrades available! Run `npm outdated` to see details.');
  } else {
    console.log('\n✅ All watched packages up-to-date.');
  }
}

const argv = process.argv.slice(2);
const report = check();
if (argv.includes('--json')) {
  console.log(JSON.stringify(report, null, 2));
} else {
  print(report);
}
if (argv.includes('--exit-1') && report.upgradesAvailable) {
  process.exit(1);
}

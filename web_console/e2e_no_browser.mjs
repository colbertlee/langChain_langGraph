/**
 * e2e_no_browser.mjs — 前端 + 后端集成 E2E（无浏览器）
 *
 * 由于 TRAE 沙盒拦截 playwright-core 写入
 * C:\Users\Colbert\AppData\Local\ms-playwright\b\browser@*（Playwright 内部
 * 用于 browser registry cache），无法在沙盒内启动 headless chromium。
 *
 * 这里退一步：用 Vite SSR-fetch + 后端 HTTP 调用，直接验证：
 *   1. Vite dev server 起的 SPA 返回的 HTML 包含 React root + main.tsx 引用
 *   2. Vite 编译的 main.tsx 不报 TS/JS 错误
 *   3. 后端 /api/health、/api/agents、/api/tools 全部正确
 *   4. /api/agents 不含玩具 agent（analyst-01 / github-bot）
 */
import http from 'http';

const FRONTEND = 'http://127.0.0.1:5173';
const BACKEND = 'http://localhost:8000';

const PASS = [];
const FAIL = [];

function ok(name, cond, detail) {
  if (cond) {
    PASS.push(name);
    console.log(`  [PASS] ${name}` + (detail ? `  (${detail})` : ''));
  } else {
    FAIL.push({ name, detail });
    console.log(`  [FAIL] ${name}` + (detail ? `  (${detail})` : ''));
  }
}

function fetch(url, opts = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, opts, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
    });
    req.on('error', reject);
    req.setTimeout(10_000, () => req.destroy(new Error('timeout')));
  });
}

async function main() {
  // ---- T1: Vite dev server 返回 index.html 含 React 入口 ----
  try {
    const r = await fetch(FRONTEND + '/');
    const hasRoot = /<div id="root">/.test(r.body);
    const hasMain = /\/src\/main\.tsx/.test(r.body);
    const hasTitle = /<title>[^<]+<\/title>/.test(r.body);
    ok(
      'frontend-index',
      r.status === 200 && hasRoot && hasMain,
      `status=${r.status} root=${hasRoot} main=${hasMain} title=${hasTitle}`,
    );
  } catch (e) {
    ok('frontend-index', false, e.message);
  }

  // ---- T2: Vite 编译 main.tsx 无 TS 错误 ----
  try {
    const r = await fetch(FRONTEND + '/src/main.tsx');
    // Vite 编译失败时会返回错误 HTML/JS 段；编译成功则返回转换后的 JS
    const isJs = /^import\s+/.test(r.body) || /^export\s+/.test(r.body) || /createRoot/.test(r.body);
    const hasError = /Transform failed|SyntaxError|TS\d{4}/.test(r.body);
    ok(
      'main-tsx-compiled',
      r.status === 200 && isJs && !hasError,
      `status=${r.status} js=${isJs} error=${hasError}`,
    );
  } catch (e) {
    ok('main-tsx-compiled', false, e.message);
  }

  // ---- T3: Vite 编译 App.tsx 无 TS 错误 ----
  try {
    const r = await fetch(FRONTEND + '/src/App.tsx');
    const isJs = /createElement|jsx/.test(r.body);
    const hasError = /Transform failed|SyntaxError/.test(r.body);
    ok('app-tsx-compiled', r.status === 200 && isJs && !hasError, `status=${r.status}`);
  } catch (e) {
    ok('app-tsx-compiled', false, e.message);
  }

  // ---- T4: 后端 /api/health ----
  try {
    const r = await fetch(BACKEND + '/api/health');
    const body = JSON.parse(r.body);
    ok('backend-health', r.status === 200 && body.status === 'ok', JSON.stringify(body));
  } catch (e) {
    ok('backend-health', false, e.message);
  }

  // ---- T5: 后端 /api/agents — 4 个 agent，不含玩具 ----
  try {
    const r = await fetch(BACKEND + '/api/agents');
    const body = JSON.parse(r.body);
    const agents = body.agents ?? [];
    const ids = agents.map((a) => a.worker_id).sort();
    const expected = ['coder-02', 'researcher-01', 'reviewer-01', 'supervisor-01'];
    const toyIds = ['analyst-01', 'github-bot'];
    const missing = expected.filter((e) => !ids.includes(e));
    const toy = ids.filter((i) => toyIds.includes(i));
    ok(
      'backend-agents',
      r.status === 200 && missing.length === 0 && toy.length === 0 && agents.length === 4,
      `ids=${ids.join(',')} missing=${missing.join(',')} toy=${toy.join(',')}`,
    );
  } catch (e) {
    ok('backend-agents', false, e.message);
  }

  // ---- T6: 后端 /api/tools — 不含玩具工具 ----
  try {
    const r = await fetch(BACKEND + '/api/tools');
    const body = JSON.parse(r.body);
    const tools = body.tools ?? [];
    const names = tools.map((t) => t.name || t).filter(Boolean);
    const toyNames = [
      'get_current_time', 'calculate', 'search_web', 'get_weather',
      'github_search', 'generate_chart',
      'get_etf_info', 'get_etf_price', 'get_etf_history',
      'get_etf_knowledge', 'compare_etfs', 'etf_analysis',
    ];
    const intersect = names.filter((n) => toyNames.includes(n));
    ok(
      'backend-tools',
      r.status === 200 && intersect.length === 0,
      `count=${names.length} toy_intersect=${intersect.join(',') || '∅'}`,
    );
  } catch (e) {
    ok('backend-tools', false, e.message);
  }

  // ---- T7: 后端 /api/capabilities — 不含 etf/chart/github_* ----
  try {
    const r = await fetch(BACKEND + '/api/capabilities');
    const body = JSON.parse(r.body);
    const caps = Array.isArray(body) ? body : (body.capabilities ?? []);
    const names = caps.map((c) => c.name || c).filter(Boolean);
    const toyCaps = ['etf', 'chart', 'github_search', 'github_issue', 'github_pr'];
    const intersect = names.filter((n) => toyCaps.includes(n));
    ok(
      'backend-capabilities',
      r.status === 200 && intersect.length === 0,
      `count=${names.length} toy_intersect=${intersect.join(',') || '∅'}`,
    );
  } catch (e) {
    ok('backend-capabilities', false, e.message);
  }

  // ---- T8: 后端 /api/version ----
  try {
    const r = await fetch(BACKEND + '/api/version');
    const body = JSON.parse(r.body);
    ok('backend-version', r.status === 200 && !!body.version, JSON.stringify(body));
  } catch (e) {
    ok('backend-version', false, e.message);
  }

  console.log('');
  console.log('='.repeat(60));
  console.log(`RESULT: ${PASS.length} passed, ${FAIL.length} failed (total ${PASS.length + FAIL.length})`);
  console.log('='.repeat(60));
  if (FAIL.length) process.exit(1);
}

main().catch((e) => {
  console.error('FATAL:', e);
  process.exit(2);
});

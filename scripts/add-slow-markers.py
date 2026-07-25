"""Add pytest.mark.slow to long-running legacy test files."""
import os
import re

KNOWN_SLOW = [
    'ai_agent/tests/legacy/test_full_system_integration.py',
    'ai_agent/tests/legacy/test_full.py',
    'ai_agent/tests/legacy/test_p3_all.py',
    'ai_agent/tests/legacy/test_p2_extra.py',
    'ai_agent/tests/legacy/test_negotiation_integration.py',
    'ai_agent/tests/legacy/test_multi_agent.py',
    'ai_agent/tests/legacy/test_github_push.py',
    'ai_agent/tests/legacy/test_zhipu_embedding.py',
]

REASONS = {
    'ai_agent/tests/legacy/test_full_system_integration.py': 'end-to-end integration with real components',
    'ai_agent/tests/legacy/test_full.py': 'full feature test suite',
    'ai_agent/tests/legacy/test_p3_all.py': 'P3 stage tests with multiple components',
    'ai_agent/tests/legacy/test_p2_extra.py': 'P2 stage extended tests',
    'ai_agent/tests/legacy/test_negotiation_integration.py': 'multi-agent negotiation integration (multi-round)',
    'ai_agent/tests/legacy/test_multi_agent.py': 'multi-agent full workflow (multi-round + bus)',
    'ai_agent/tests/legacy/test_github_push.py': 'real GitHub API calls',
    'ai_agent/tests/legacy/test_zhipu_embedding.py': 'real Zhipu Embedding API calls',
}


def add_slow_marker(filepath):
    content = open(filepath, encoding='utf-8').read()

    if 'pytestmark' in content or '@pytest.mark.slow' in content:
        return False

    reason = REASONS.get(filepath, 'long-running')

    # 在文件顶部加 pytestmark slow（保留原 docstring 如果有）
    slow_block = f'''"""Long-running test (>2s). Skipped by default in CI.
Run explicitly with: pytest -m slow

Reason: {reason}
"""
import pytest

pytestmark = pytest.mark.slow

'''

    # 跳过文件开头的 docstring（如果有）
    lines = content.split('\n')
    insert_idx = 0

    # 检测开头的 docstring
    if lines and lines[0].strip().startswith('"""'):
        # 找到 docstring 结尾
        for i in range(1, len(lines)):
            if lines[i].strip().endswith('"""'):
                insert_idx = i + 1
                break
        else:
            # docstring 未关闭
            insert_idx = 0
    elif lines and lines[0].strip().startswith("'''"):
        for i in range(1, len(lines)):
            if lines[i].strip().endswith("'''"):
                insert_idx = i + 1
                break

    # 在 docstring 后插入
    if insert_idx > 0:
        # 文件以 docstring 开始
        new_content = '\n'.join(lines[:insert_idx]) + '\n\n' + slow_block + '\n'.join(lines[insert_idx:])
    else:
        # 文件以 import 开始 → 直接插入
        new_content = slow_block + content

    with open(filepath, 'w', encoding='utf-8') as fp:
        fp.write(new_content)
    return True


def main():
    print('Adding slow markers...')
    for f in KNOWN_SLOW:
        if not os.path.exists(f):
            print(f'  SKIP (not found): {f}')
            continue
        if add_slow_marker(f):
            print(f'  +marked: {f}')
        else:
            print(f'  -skipped (already has marker): {f}')


if __name__ == '__main__':
    main()

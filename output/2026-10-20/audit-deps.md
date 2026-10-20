# audit-deps
---
generated_at: see mtime
scope: ai_agent/ (Python) + web_console/ (Node)

## Python 依赖

- 声明（requirements*.txt + pyproject.toml 去重）: 125
- 实际 import（递归 ai_agent/**/*.py）: 1380

**声明但未使用（Top）**

- `_`
- `addopts`
- `ai`
- `ai_agent_format`
- `ai_agent_lint`
- `ai_agent_server`
- `ai_agent_test`
- `allow_dirty`
- `allowed_types`
- `asyncio_mode`
- `authors`
- `branch`
- `build_backend`
- `changelog`
- `changelog_file`
- `changelog_omit_zero_versions`
- `classifiers`
- `commit_author`
- `commit_message`
- `commit_version_number`
- `current_version`
- `description`
- `dev`
- `disallow_untyped_defs`
- `discussions`
- `docker`
- `docstring_code_format`
- `docstring_code_line_length`
- `documentation`
- `exclude_also`
- `exclude_lines`
- `filename`
- `filterwarnings`
- `funding`
- `homepage`
- `hvcs`
- `ignore`
- `ignore_missing_imports`
- `indent_style`
- `issues`
- `keywords`
- `license`
- `line_ending`
- `line_length`
- `markers`
- `name`
- `omit`
- `openai_whisper`
- `opentelemetry_api`
- `parse`
- `pillow`
- `precision`
- `push_mode`
- `py_modules`
- `pytest_asyncio`
- `pytest_cov`
- `pytest_mock`
- `pytest_timeout`
- `python_classes`
- `python_dotenv`
- `python_files`
- `python_functions`
- `python_version`
- `pyyaml`
- `quote_style`
- `readme`
- `releases`
- `replace`
- `repository`
- `requires`
- `requires_python`
- `ruff`
- `search`
- `serialize`
- `show_missing`
- `skip_covered`
- `skip_empty`
- `skip_magic_trailing_comma`
- `sort`
- `tag_commit`
- `tag_message`
- `tag_name`
- `target_version`
- `template`
- `testpaths`
- `upload_to_pypi`
- `upload_to_release`
- `version`
- `version_variable`
- `warn_unused_ignores`

**使用但未声明（已粗筛 stdlib，Top 50）**

- `0`
- `1`
- `__builtin__`
- `__future__`
- `__main__`
- `__pypy__`
- `__version__`
- `_abcoll`
- `_aix_support`
- `_argcomplete`
- `_cffi_backend`
- `_collections_abc`
- `_csv`
- `_ctypes`
- `_distutils_hack`
- `_dummy_thread`
- `_frozen_importlib`
- `_frozen_importlib_external`
- `_imp`
- `_interpqueues`
- `_interpreters`
- `_manylinux`
- `_operator`
- `_osx_support`
- `_pytest`
- `_socket`
- `_ssl`
- `_testbuffer`
- `_thread`
- `_typeshed`
- `_win32sysloader`
- `_win32verstamp_pywin32ctypes`
- `_winreg`
- `_winxptheme`
- `a`
- `a2wsgi`
- `ab_testing`
- `above`
- `adaptive_threshold`
- `adodbapi`
- `adodbapitestconfig`
- `ads`
- `adsi`
- `aerospike_vector_search`
- `affinity_helper`
- `agent`
- `agent_config`
- `agent_tool_router`
- `agent_workers`
- `agents`
- … 共 1308 项，仅列前 50

## Node 依赖

- declared(deps+devDeps): 32
- used in src/: 20

**未使用的 Node 依赖（声明 → 未 import）**

- `@assistant-ui/core`
- `@playwright/test`
- `@testing-library/dom`
- `@testing-library/jest-dom`
- `@testing-library/user-event`
- `@types/node`
- `@types/react`
- `@types/react-dom`
- `@types/react-syntax-highlighter`
- `@vitejs/plugin-react`
- `@vitest/coverage-v8`
- `actionlint`
- `autoprefixer`
- `framer-motion`
- `jsdom`
- `postcss`
- `tailwindcss`
- `typescript`
- `vite`

**使用但未声明的 Node 依赖**

- `@/components`
- `@/hooks`
- `@/lib`
- `@/pages`
- `@/stores`
- `@/types`
- `node:util`

_摸排口径：Python import 用 `^(?:from|import)` 首段；Node import 用 `from '...'` 字面量；scope 包按 `@scope/pkg` 整体匹配；package-lock 不计入声明集。_
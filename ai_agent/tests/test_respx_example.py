"""respx 用法示例：mock HTTP 调用。

respx 是 HTTPX 兼容的 mock 库，可以拦截 HTTP 请求并返回预设响应。
适用于：
- 测试 akshare（HTTP API 调用）
- 测试 serpapi（Google 搜索）
- 测试 GitHub API
- 测试 OpenAI/Anthropic API

基本用法：
```python
import respx
import httpx

@respx.mock
def test_api():
    respx.get("https://api.example.com/data").mock(
        return_value=httpx.Response(200, json={"x": 1})
    )

    # 这里 httpx 调用会被 mock
    response = httpx.get("https://api.example.com/data")
    assert response.json() == {"x": 1}
```

更多用法见 README：https://lundberg.github.io/respx/
"""
import json

import httpx
import pytest

try:
    import respx
    HAS_RESPX = True
except ImportError:
    HAS_RESPX = False


pytestmark = pytest.mark.skipif(not HAS_RESPX, reason="respx not installed")


class TestRespxExample:
    """展示 respx 的几种用法"""

    @respx.mock
    def test_mock_get_request(self):
        """Mock 一个 GET 请求"""
        respx.get("https://api.example.com/users").mock(
            return_value=httpx.Response(200, json={"users": ["alice", "bob"]})
        )

        response = httpx.get("https://api.example.com/users")
        assert response.status_code == 200
        assert response.json() == {"users": ["alice", "bob"]}

    @respx.mock
    def test_mock_post_with_payload(self):
        """Mock POST + 验证 payload"""
        route = respx.post("https://api.example.com/users").mock(
            return_value=httpx.Response(201, json={"id": 123, "name": "new user"})
        )

        response = httpx.post(
            "https://api.example.com/users",
            json={"name": "new user"},
        )

        assert response.status_code == 201
        assert response.json()["id"] == 123
        # 验证请求 payload
        assert route.called
        assert json.loads(route.calls.last.request.content) == {"name": "new user"}

    @respx.mock
    def test_mock_error_response(self):
        """Mock 一个错误响应"""
        respx.get("https://api.example.com/error").mock(
            return_value=httpx.Response(500, json={"error": "Internal Server Error"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            httpx.get("https://api.example.com/error").raise_for_status()

    @respx.mock
    def test_mock_timeout(self):
        """Mock 网络超时"""
        respx.get("https://slow.example.com").mock(side_effect=httpx.ConnectTimeout("timeout"))

        with pytest.raises(httpx.ConnectTimeout):
            httpx.get("https://slow.example.com")

    @respx.mock
    def test_mock_regex_pattern(self):
        """Mock 正则匹配路径"""
        respx.get(url__regex=r"https://api\.example\.com/users/\d+").mock(
            return_value=httpx.Response(200, json={"id": 1, "name": "alice"})
        )

        response = httpx.get("https://api.example.com/users/1")
        assert response.json()["name"] == "alice"

    @respx.mock
    def test_mock_multiple_responses(self):
        """Mock 多次返回（依次返回不同响应）"""
        route = respx.get("https://api.example.com/counter").mock(
            side_effect=[
                httpx.Response(200, json={"count": 1}),
                httpx.Response(200, json={"count": 2}),
                httpx.Response(200, json={"count": 3}),
            ]
        )

        r1 = httpx.get("https://api.example.com/counter")
        r2 = httpx.get("https://api.example.com/counter")
        r3 = httpx.get("https://api.example.com/counter")

        assert r1.json()["count"] == 1
        assert r2.json()["count"] == 2
        assert r3.json()["count"] == 3

    @respx.mock
    @pytest.mark.parametrize("status_code,expected", [
        (200, "OK"),
        (404, "Not Found"),
        (500, "Internal Server Error"),
    ])
    def test_parametrized_status(self, status_code, expected):
        """参数化测试不同状态码"""
        url = f"https://api.example.com/status/{status_code}"
        respx.get(url).mock(
            return_value=httpx.Response(status_code, text=expected)
        )

        response = httpx.get(url)
        assert response.status_code == status_code
        assert response.text == expected


# ─────────────────── 真实场景示例 ───────────────────


class TestAkshareMockExample:
    """演示如何 mock akshare 的 HTTP 调用（参考用，akshare 实际更复杂）"""

    @respx.mock
    def test_mock_fund_etf_spot_em(self):
        """Mock akshare 的 fund_etf_spot_em（实际是 HTTP 调用东方财富 API）"""
        # akshare 内部会调用东方财富的 HTTP API
        route = respx.get(url__regex=r"https://.*eastmoney.*\.com/.*").mock(
            return_value=httpx.Response(
                200,
                text="数据,代码,名称\n,510300,沪深300ETF\n,510500,中证500ETF",
            )
        )

        # 现在调用 akshare 会被 mock
        # df = ak.fund_etf_spot_em()
        # 实际调用仍会失败（akshare 内部流程复杂），但本示例展示 mock 思路

        # 验证 mock 路由被注册
        assert route.call_count == 0  # mock 设置好了但没调用


class TestSerpapiMockExample:
    """演示如何 mock serpapi"""

    @respx.mock
    def test_mock_serpapi_search(self):
        """Mock serpapi 搜索结果"""
        mock_results = {
            "organic_results": [
                {"title": "Result 1", "snippet": "Snippet 1", "link": "https://example.com/1"},
                {"title": "Result 2", "snippet": "Snippet 2", "link": "https://example.com/2"},
            ]
        }

        respx.get("https://serpapi.com/search.json").mock(
            return_value=httpx.Response(200, json=mock_results)
        )

        # 直接模拟 serpapi 的 HTTP 调用
        import os
        os.environ.setdefault("SERPAPI_API_KEY", "fake-key")
        response = httpx.get(
            "https://serpapi.com/search.json",
            params={"q": "test", "api_key": "fake-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["organic_results"]) == 2
        assert data["organic_results"][0]["title"] == "Result 1"


class TestGithubApiMockExample:
    """演示如何 mock GitHub API"""

    @respx.mock
    def test_mock_github_search(self):
        """Mock GitHub search API"""
        mock_response = {
            "total_count": 2,
            "items": [
                {
                    "full_name": "owner/repo1",
                    "description": "first repo",
                    "stargazers_count": 100,
                    "html_url": "https://github.com/owner/repo1",
                },
                {
                    "full_name": "owner/repo2",
                    "description": "second repo",
                    "stargazers_count": 50,
                    "html_url": "https://github.com/owner/repo2",
                },
            ],
        }
        respx.get("https://api.github.com/search/repositories").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        response = httpx.get(
            "https://api.github.com/search/repositories",
            params={"q": "agent"},
            headers={"Authorization": "token fake"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 2
        assert data["items"][0]["full_name"] == "owner/repo1"

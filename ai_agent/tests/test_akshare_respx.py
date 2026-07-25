"""用 respx 拦截 akshare 内部 HTTP 调用。

akshare 内部使用 requests 调用东方财富 / 新浪财经等公开 API。
用 respx 拦截这些 HTTP 调用，让 akshare 不访问真实网络。

注意：akshare 内部使用 requests（不是 httpx），所以需要 respx
用 transport=httpx.MockTransport 或者直接 patch requests。

由于 respx 主要支持 httpx（而非 requests），我们用 respx
但通过 httpx.Client 替代 requests 调用的方式不太适合 akshare。
所以本测试展示如何：
1. 用 respx + httpx（更现代）
2. 用 unittest.mock.patch 替换 requests（更通用）
"""
import json

import pytest

try:
    import respx
    import httpx
    HAS_RESPX = True
except ImportError:
    HAS_RESPX = False


pytestmark = pytest.mark.skipif(not HAS_RESPX, reason="respx not installed")


# ==================== 示例 1: 用 respx 拦截 akshare-like HTTP ====================


class TestAkshareHttpMock:
    """演示如何 mock akshare 的 HTTP 调用。"""

    @respx.mock
    @pytest.mark.asyncio
    async def test_mock_eastmoney_api(self):
        """模拟东方财富的 ETF 数据 API。"""
        # 东方财富基金 API 实际 URL 格式（简化）
        url_pattern = url__regex = r"https://fundgz\.1234567\.com\.cn/js/\d+\.js"

        # respx 注册 mock 响应
        route = respx.get(url__regex=url_pattern).mock(
            return_value=httpx.Response(
                200,
                text='jsonpgz({"fundcode":"510300","name":"沪深300ETF","jzrq":"2024-01-15","dwjz":"1.234"});',
            )
        )

        # 现在 httpx 调用会被 mock
        async with httpx.AsyncClient() as client:
            response = await client.get("https://fundgz.1234567.com.cn/js/510300.js")

        assert response.status_code == 200
        assert "沪深300ETF" in response.text
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_mock_sina_stock_api(self):
        """模拟新浪财经的股票数据 API。"""
        url__regex = r"https://hq\.sinajs\.cn/list=sh\d+"

        respx.get(url__regex=url__regex).mock(
            return_value=httpx.Response(
                200,
                text='var hq_str_sh510300="沪深300ETF,1.234,1.240,1.230,...";',
            )
        )

        async with httpx.AsyncClient() as client:
            response = await client.get("https://hq.sinajs.cn/list=sh510300")

        assert response.status_code == 200
        assert "沪深300ETF" in response.text

    @respx.mock
    @pytest.mark.asyncio
    async def test_mock_timeout(self):
        """模拟网络超时。"""
        url__regex = r"https://.*eastmoney.*"

        respx.get(url__regex=url__regex).mock(
            side_effect=httpx.ConnectTimeout("Connection timed out")
        )

        async with httpx.AsyncClient(timeout=1.0) as client:
            with pytest.raises(httpx.ConnectTimeout):
                await client.get("https://fund.eastmoney.com/510300.html")


# ==================== 示例 2: 用 monkeypatch 替换 akshare 的底层 HTTP ====================


class TestAkshareIntegration:
    """用 monkeypatch 替换 akshare 内部的 requests 调用。"""

    def test_akshare_with_mocked_requests(self, monkeypatch):
        """Mock requests 让 akshare 不访问真实网络。"""
        from unittest.mock import MagicMock

        # 模拟 requests.get 返回 DataFrame-like JSON
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "code": "510300",
                "name": "沪深300ETF",
                "price": 1.234,
            }
        ]
        mock_resp.text = json.dumps(mock_resp.json.return_value)

        # 替换全局 requests.get
        import requests
        monkeypatch.setattr(requests, "get", lambda *args, **kwargs: mock_resp)

        # 现在用 requests.get 会被 mock
        response = requests.get("https://example.com/api")
        assert response.status_code == 200
        data = response.json()
        assert data[0]["name"] == "沪深300ETF"


# ==================== 示例 3: 直接 mock akshare 函数 ====================


class TestAkshareDirectMock:
    """用 patch 直接替换 akshare 的特定函数（最简单）。"""

    def test_akshare_fund_etf_spot(self):
        """直接 mock ak.fund_etf_spot_em()。"""
        import pandas as pd
        from unittest.mock import patch

        mock_data = pd.DataFrame([
            {"代码": "510300", "名称": "沪深300ETF", "最新价": 1.234},
            {"代码": "510500", "名称": "中证500ETF", "最新价": 2.345},
        ])

        with patch("akshare.fund_etf_spot_em", return_value=mock_data):
            import akshare as ak
            df = ak.fund_etf_spot_em()
            assert len(df) == 2
            assert "沪深300ETF" in df["名称"].values

    def test_akshare_fund_etf_info(self):
        """直接 mock ak.fund_etf_fund_info_em()。"""
        import pandas as pd
        from unittest.mock import patch

        mock_data = pd.DataFrame([{
            "基金名称": "华泰柏瑞沪深300ETF",
            "基金全称": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
            "基金管理人": "华泰柏瑞基金管理有限公司",
            "成立日期": "2012-05-04",
            "最新规模": "1000.0亿元",
            "最新净值": "1.234",
            "净值日期": "2024-01-15",
            "风险等级": "中高风险",
        }])

        with patch("akshare.fund_etf_fund_info_em", return_value=mock_data):
            import akshare as ak
            df = ak.fund_etf_fund_info_em("510300")
            assert len(df) == 1
            assert "华泰柏瑞" in df["基金管理人"].values[0]

    def test_akshare_history(self):
        """mock ak.fund_etf_hist_em()。"""
        import pandas as pd
        from unittest.mock import patch

        # 模拟 30 天历史数据
        dates = pd.date_range("2024-01-01", periods=30)
        mock_data = pd.DataFrame({
            "日期": dates,
            "开盘": [1.0 + i * 0.01 for i in range(30)],
            "收盘": [1.005 + i * 0.01 for i in range(30)],
            "最高": [1.01 + i * 0.01 for i in range(30)],
            "最低": [0.995 + i * 0.01 for i in range(30)],
            "成交量": [1000000] * 30,
        })

        with patch("akshare.fund_etf_hist_em", return_value=mock_data):
            import akshare as ak
            df = ak.fund_etf_hist_em("510300")
            assert len(df) == 30
            assert "日期" in df.columns
            assert "收盘" in df.columns


# ==================== 示例 4: 集成到 tools.py 的 ETF 函数 ====================


class TestToolsEETFWithMock:
    """演示如何用 mock 跑 tools.py 的 ETF 函数。"""

    def test_get_etf_info_mocked(self):
        """用 mock 跑 get_etf_info 验证逻辑。"""
        from unittest.mock import patch
        import pandas as pd

        # Mock 内部 akshare 调用
        mock_data = pd.DataFrame([{
            "基金名称": "沪深300ETF",
            "基金全称": "华泰柏瑞沪深300ETF",
            "基金管理人": "华泰柏瑞",
            "成立日期": "2012-05-04",
            "最新规模": "1000亿元",
            "最新净值": "1.234",
            "净值日期": "2024-01-15",
            "风险等级": "中高风险",
        }])

        with patch("akshare.fund_etf_fund_info_em", return_value=mock_data):
            from tools import get_etf_info
            # get_etf_info 是 @tool 装饰的 StructuredTool
            result = get_etf_info.invoke({"etf_code": "510300"})
            # 应包含基金名称
            assert "沪深300ETF" in result or "510300" in result

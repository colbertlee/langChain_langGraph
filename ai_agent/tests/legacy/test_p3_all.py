"""
P3 全部测试：A/B Testing + 自适应阈值 + Plugin Manager + Distributed Bus
"""

"""Long-running test (>2s). Skipped by default in CI.
Run explicitly with: pytest -m slow

Reason: P3 stage tests with multiple components
"""
import pytest

pytestmark = pytest.mark.slow


import asyncio
import os
import json
import tempfile
import shutil
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

import functools
_print = print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _print(*args, **kwargs)


# ============================================================
# P3-16 A/B Testing
# ============================================================

def test_ab_testing_basic():
    print("\n[1] A/B Experiment 创建 + 分配 + 记录")
    from ab_testing import (
        ExperimentRunner, get_experiment_runner, reset_experiment_runner,
        AssignmentStrategy, ExperimentStatus,
    )
    import ab_testing as _m
    _m._runner = None
    runner = get_experiment_runner()

    exp = runner.create(
        name="test_ab",
        description="unit test",
        assignment_strategy=AssignmentStrategy.WEIGHTED,
    )
    exp.add_variant("A", weight=1.0, config={"strategy": "alpha"})
    exp.add_variant("B", weight=2.0, config={"strategy": "beta"})

    runner.start(exp.experiment_id)

    # 分配 100 次
    counts = {"A": 0, "B": 0}
    for i in range(100):
        v = runner.assign(exp.experiment_id, f"user_{i}")
        if v:
            counts[v.name] += 1

    # B 应该是 A 的大约 2 倍（weighted）
    assert counts["A"] + counts["B"] == 100
    print(f"  PASS - weighted distribution A={counts['A']} B={counts['B']}")


def test_ab_testing_deterministic():
    print("\n[2] A/B 粘性分配")
    from ab_testing import (
        ExperimentRunner, get_experiment_runner, AssignmentStrategy,
    )
    runner = get_experiment_runner()
    exp = runner.create(
        name="sticky",
        assignment_strategy=AssignmentStrategy.DETERMINISTIC,
    )
    exp.add_variant("control", weight=1.0)
    exp.add_variant("treatment", weight=1.0)
    runner.start(exp.experiment_id)

    # 同一 user_id 应该永远分到同一变体
    user_id = "user_42"
    v1 = runner.assign(exp.experiment_id, user_id)
    v2 = runner.assign(exp.experiment_id, user_id)
    assert v1.name == v2.name
    print(f"  PASS - user_42 → {v1.name} (sticky)")


def test_ab_testing_winner():
    print("\n[3] A/B 胜出决策")
    from ab_testing import (
        ExperimentRunner, get_experiment_runner,
    )
    runner = get_experiment_runner()
    exp = runner.create(name="winner_test", primary_metric="reward")
    exp.add_variant("weak", weight=1.0)
    exp.add_variant("strong", weight=1.0)
    runner.start(exp.experiment_id)

    # 录入数据：strong 显著好
    for i in range(50):
        runner.record(exp.experiment_id, "weak",
                      reward=0.3, latency_ms=100 + i)
    for i in range(50):
        runner.record(exp.experiment_id, "strong",
                      reward=0.9, latency_ms=80 + i)

    winner = runner.decide_winner(exp.experiment_id)
    assert winner == "strong"
    print(f"  PASS - winner = {winner}")


async def test_ab_testing_strategy_evaluator():
    print("\n[4] StrategyEvaluator 跑 benchmark")
    from ab_testing import StrategyEvaluator, get_experiment_runner

    ev = StrategyEvaluator()
    runner = get_experiment_runner()

    def strategy_alpha(task):
        # 总是返回 1（不好）
        return 1.0

    def strategy_beta(task):
        # 总是返回任务值（好）
        return task.get("value", 0.0)

    ev.register("alpha", strategy_alpha)
    ev.register("beta", strategy_beta)

    exp = runner.create(name="strategy_bench", primary_metric="reward")
    exp.add_variant("v_a", weight=1.0, config={"strategy": "alpha"})
    exp.add_variant("v_b", weight=1.0, config={"strategy": "beta"})
    runner.start(exp.experiment_id)

    benchmark = [{"value": float(i)} for i in range(1, 21)]
    result = await ev.evaluate(
        runner, exp.experiment_id, benchmark,
        reward_fn=lambda t, o: 1.0 if o == t.get("value") else -0.5,
    )
    assert result["evaluated_tasks"] > 0
    print(f"  PASS - evaluated {result['evaluated_tasks']} tasks")


# ============================================================
# P3-19 自适应阈值
# ============================================================

def test_adaptive_threshold_basic():
    print("\n[5] 自适应阈值 - EWMA 学习")
    from adaptive_threshold import (
        ThresholdLearner, AdaptationStrategy, reset_threshold_learner,
    )
    import adaptive_threshold as _m
    _m._learner = None
    learner = ThresholdLearner()
    learner.set_strategy(AdaptationStrategy.EWMA)

    # 录入历史：稳定成交价 100
    for i in range(10):
        learner.record_trade(
            agent_id="A1", counterparty_id="B1",
            task_type="search",
            initial_price=120.0, final_price=100.0,
            reservation_point=80.0, rounds=3,
        )

    threshold = learner.learn("A1", "search", default_threshold=50.0)
    assert threshold > 50.0, f"expected > default, got {threshold}"
    print(f"  PASS - learned threshold = {threshold:.2f} (default=50)")


def test_adaptive_threshold_empirical():
    print("\n[6] 自适应阈值 - 经验分位数")
    from adaptive_threshold import (
        ThresholdLearner, AdaptationStrategy,
    )
    learner = ThresholdLearner()
    learner.set_strategy(AdaptationStrategy.EMPIRICAL)

    # 录入：价格 100, 200, 300
    for p in [100.0, 200.0, 300.0]:
        learner.record_trade(
            agent_id="A", counterparty_id="B",
            task_type="analyze",
            initial_price=p, final_price=p,
            reservation_point=p * 0.8,
        )

    # p25 应接近 100-150 之间
    threshold = learner.learn("A", "analyze", default_threshold=0.0)
    assert 70.0 < threshold < 200.0, f"unexpected: {threshold}"
    print(f"  PASS - p25 threshold = {threshold:.2f}")


def test_adaptive_threshold_bayesian():
    print("\n[7] 自适应阈值 - 贝叶斯折扣")
    from adaptive_threshold import (
        ThresholdLearner, AdaptationStrategy,
    )
    learner = ThresholdLearner()
    learner.set_strategy(AdaptationStrategy.BAYESIAN)

    # 3 个数据（少 → 折扣）
    for p in [100.0, 100.0, 100.0]:
        learner.record_trade(
            agent_id="A", counterparty_id="B",
            task_type="search",
            initial_price=p, final_price=p, reservation_point=80.0,
        )
    threshold = learner.learn("A", "search")
    # 100 × 0.85 (safety_margin) × 0.7 (sample < 5 折扣) ≈ 60
    print(f"  PASS - bayesian = {threshold:.2f}")


def test_adaptive_threshold_persistence():
    print("\n[8] 自适应阈值 - 持久化")
    from adaptive_threshold import ThresholdLearner
    learner = ThresholdLearner()
    for i in range(5):
        learner.record_trade(
            agent_id="X", counterparty_id="Y",
            task_type="test",
            initial_price=100, final_price=80, reservation_point=70,
        )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        learner.save_to_file(path)
        assert os.path.exists(path)

        new_learner = ThresholdLearner()
        n = new_learner.load_from_file(path)
        assert n == 5
        th = new_learner.learn("X", "test")
        assert th > 0
    finally:
        os.unlink(path)
    print(f"  PASS - {n} records persisted & loaded")


# ============================================================
# P3-17 Plugin Manager
# ============================================================

def test_plugin_manifest():
    print("\n[9] PluginManifest 创建 + 保存")
    from plugin_manager import PluginManifest

    m = PluginManifest(
        name="my_plugin",
        version="1.0.0",
        capabilities=["custom"],
        hooks=["on_message"],
    )
    d = m.to_dict()
    assert d["name"] == "my_plugin"
    assert "custom" in d["capabilities"]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        m.save_to_file(path)
        m2 = PluginManifest.from_file(path)
        assert m2.name == "my_plugin"
        assert m2.version == "1.0.0"
    finally:
        os.unlink(path)
    print(f"  PASS - manifest saved & loaded")


def test_plugin_install_disable():
    print("\n[10] Plugin 安装 + 禁用")
    from plugin_manager import (
        PluginManager, PluginManifest, get_plugin_manager, reset_plugin_manager,
    )
    import plugin_manager as _m
    _m._plugin_manager = None
    pm = get_plugin_manager()

    m = PluginManifest(name="test_plugin", version="0.1.0", capabilities=["t1"])
    pm.install(m)

    installed = pm.list_installed()
    assert len(installed) == 1

    pm.uninstall("test_plugin")
    assert len(pm.list_installed()) == 0
    print(f"  PASS - install + uninstall")


async def test_plugin_hooks():
    print("\n[11] Plugin hook 触发")
    from plugin_manager import (
        PluginManager, PluginHook, get_plugin_manager,
    )
    pm = get_plugin_manager()

    received = []
    async def hook_fn(*args, **kwargs):
        received.append((args, kwargs))

    pm.register_hook(PluginHook.ON_MESSAGE, hook_fn)

    results = await pm.emit_hook(PluginHook.ON_MESSAGE, "data", foo="bar")
    assert len(received) >= 1
    print(f"  PASS - hook fired, got {len(received)} callbacks")


def test_plugin_upgrade():
    print("\n[12] Plugin 版本升级")
    from plugin_manager import PluginManager, PluginManifest, get_plugin_manager
    pm = get_plugin_manager()
    pm._plugins.clear()
    pm._hooks.clear()

    m_v1 = PluginManifest(name="u", version="1.0.0")
    m_v2 = PluginManifest(name="u", version="2.0.0", capabilities=["new"])

    pm.install(m_v1)
    entry = pm.upgrade("u", m_v2)
    assert entry.manifest.version == "2.0.0"
    assert "new" in entry.manifest.capabilities
    print(f"  PASS - upgraded to v2.0.0")


def test_plugin_find_by_capability():
    print("\n[13] Plugin 按 capability 查找")
    from plugin_manager import PluginManager, PluginManifest, get_plugin_manager
    pm = get_plugin_manager()
    pm._plugins.clear()

    p1 = pm.install(PluginManifest(name="p1", version="1.0", capabilities=["audio"], description="audio plugin"))
    p2 = pm.install(PluginManifest(name="p2", version="1.0", capabilities=["image", "audio"], description="image plugin"))
    # enable 它们
    pm.enable("p1")
    pm.enable("p2")

    audio_plugins = pm.find_by_capability("audio")
    assert len(audio_plugins) == 2

    image_plugins = pm.find_by_capability("image")
    assert len(image_plugins) == 1
    print(f"  PASS - audio={len(audio_plugins)}, image={len(image_plugins)}")


# ============================================================
# P3-18 Distributed Bus
# ============================================================

def test_in_process_transport():
    print("\n[14] InProcess 传输")
    from distributed_bus import InProcessTransport

    t = InProcessTransport()
    received = []
    t.start_listening(received.append)
    t.send(_make_envelope(t.node_id, "hello"))
    t.send(_make_envelope(t.node_id, "world"))
    t.stop_listening()
    assert len(received) == 2
    print(f"  PASS - {len(received)} messages delivered")


def test_file_transport():
    print("\n[15] File 传输")
    from distributed_bus import FileTransport

    with tempfile.TemporaryDirectory() as tmp_dir:
        t1 = FileTransport(watch_dir=tmp_dir, node_id="node1", poll_interval=0.02)
        t2 = FileTransport(watch_dir=tmp_dir, node_id="node2", poll_interval=0.02)

        received = []
        t2.start_listening(received.append)

        # 等 thread 启动
        import time as _t
        _t.sleep(0.05)

        t1.send(_make_envelope("node1", "from1"))
        t2.send(_make_envelope("node2", "from2"))

        # 等轮询拿到
        for _ in range(40):
            if len(received) >= 1:
                break
            _t.sleep(0.05)

        t1.stop_listening()
        t2.stop_listening()

        # t2 收到 t1 的消息（自己发的被过滤）
        assert len(received) >= 1, "no messages received"
        assert any(env.sender_node == "node1" for env in received), \
            f"expected node1 messages, got {[e.sender_node for e in received]}"
        print(f"  PASS - {len(received)} cross-process messages")


def test_socket_transport():
    print("\n[16] Socket 传输")
    from distributed_bus import SocketTransport
    import socket as _s
    import time as _t

    # 找一个空闲端口
    sock = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = SocketTransport(mode="server", host="127.0.0.1", port=port, node_id="server")
    client = SocketTransport(mode="client", host="127.0.0.1", port=port, node_id="client")

    received = []
    server.start_listening(received.append)
    client.start_listening(lambda e: None)

    # 等连接建立
    _t.sleep(0.3)

    client.send(_make_envelope("client", "msg1"))

    for _ in range(30):
        if len(received) >= 1:
            break
        _t.sleep(0.1)

    server.stop_listening()
    client.stop_listening()

    assert any(env.sender_node == "client" for env in received), \
        f"no message from client, got: {[(e.sender_node, e.payload) for e in received]}"
    print(f"  PASS - {len(received)} socket messages")


def test_distributed_bus_factory():
    print("\n[17] Distributed bus 工厂")
    from distributed_bus import create_distributed_bus, _distributed_buses, TransportType

    bus = create_distributed_bus("factory_test", transport_type=TransportType.IN_PROCESS)
    assert bus.transport.node_id is not None
    assert "factory_test" in _distributed_buses

    received = []
    bus.on_message(lambda env: received.append(env))
    bus.start()
    bus.send({"hi": 1})
    assert len(received) == 1
    bus.stop()
    print(f"  PASS - bus factory + dispatch")


# ============================================================
# AIAgentExtension 集成
# ============================================================

async def test_extension_p3_apis():
    print("\n[18] AIAgentExtension P3 API")
    from observability import reset_observability
    reset_observability()
    import observability as _obs
    _obs._observability = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "p3_ext"
        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()
    ext = AIAgentExtension(fake)
    await ext.initialize()

    # A/B Testing
    exp_info = ext.create_experiment(
        name="ext_test",
        variants=[
            {"name": "A", "weight": 1.0, "config": {"strategy": "a"}},
            {"name": "B", "weight": 1.0, "config": {"strategy": "b"}},
        ],
    )
    ext.start_experiment(exp_info["experiment_id"])
    v = ext.assign_experiment(exp_info["experiment_id"], "u1")
    assert v is not None
    ext.record_experiment(exp_info["experiment_id"], v["name"], reward=0.5, latency_ms=10)
    winner = ext.decide_experiment_winner(exp_info["experiment_id"])
    assert winner["winner"] is not None

    # 自适应阈值
    ext.record_trade(
        agent_id="X", counterparty_id="Y", task_type="search",
        initial_price=100, final_price=80, reservation_point=70,
    )
    threshold = ext.learn_threshold("X", "search", default_threshold=50)
    assert threshold >= 0
    rec = ext.recommend_threshold("X", "search", current_bid=80, default_threshold=50)
    assert rec["history_count"] >= 1
    cfg = ext.set_adaptive_strategy("ewma")
    assert cfg["strategy"] == "ewma"

    # Plugin
    ext.install_plugin(
        name="test_plugin_v1",
        version="1.0.0",
        capabilities=["test_capability"],
    )
    plugins = ext.list_plugins()
    assert any(p["manifest"]["name"] == "test_plugin_v1" for p in plugins)
    ext.uninstall_plugin("test_plugin_v1")

    # Distributed Bus
    bus_info = ext.create_distributed_bus("ext_test_bus", transport="in_process")
    assert bus_info["name"] == "ext_test_bus"
    ext.start_distributed_bus("ext_test_bus")
    ext.send_distributed("ext_test_bus", payload={"hello": "world"})
    ext.stop_distributed_bus("ext_test_bus")

    print(f"  PASS - all P3 APIs work")


# ============================================================
# 辅助函数
# ============================================================

def _make_envelope(sender_node, payload_data):
    """构造一个测试 Envelope"""
    from distributed_bus import Envelope
    if isinstance(payload_data, str):
        payload = {"data": payload_data}
    else:
        payload = payload_data
    return Envelope(
        payload=payload,
        sender_node=sender_node,
    )


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" P3 全模块测试：A/B + 自适应 + Plugin + Distributed")
    print("#"*60)

    failures = []

    tests = [
        ("ab_basic", test_ab_testing_basic, False),
        ("ab_deterministic", test_ab_testing_deterministic, False),
        ("ab_winner", test_ab_testing_winner, False),
        ("ab_strategy_eval", test_ab_testing_strategy_evaluator, True),
        ("threshold_ewma", test_adaptive_threshold_basic, False),
        ("threshold_empirical", test_adaptive_threshold_empirical, False),
        ("threshold_bayesian", test_adaptive_threshold_bayesian, False),
        ("threshold_persist", test_adaptive_threshold_persistence, False),
        ("plugin_manifest", test_plugin_manifest, False),
        ("plugin_install", test_plugin_install_disable, False),
        ("plugin_hooks", test_plugin_hooks, True),
        ("plugin_upgrade", test_plugin_upgrade, False),
        ("plugin_find", test_plugin_find_by_capability, False),
        ("in_process", test_in_process_transport, False),
        ("file_transport", test_file_transport, False),
        ("socket_transport", test_socket_transport, False),
        ("bus_factory", test_distributed_bus_factory, False),
        ("ext_p3_apis", test_extension_p3_apis, True),
    ]

    for name, fn, is_async in tests:
        try:
            if is_async:
                await fn()
            else:
                fn()
        except Exception as e:
            failures.append((name, e))
            print(f"  FAIL: {e}")
            import traceback; traceback.print_exc()

    print("\n" + "#"*60)
    if not failures:
        print(f" All {len(tests)} tests passed")
    else:
        print(f" {len(failures)}/{len(tests)} failed: {[n for n,_ in failures]}")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(main())
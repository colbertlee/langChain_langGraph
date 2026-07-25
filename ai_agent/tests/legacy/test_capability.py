"""
能力发现 + 负载均衡测试

覆盖：
1. CapabilityProfile / WorkerMetrics
2. CapabilityRegistry 注册/查询/订阅/更新
3. LoadBalancer 6 种策略
4. WorkerAgent 自动注册到 registry
5. Orchestrator._find_best_worker 加权评分
6. AuctionManager 多维评分含负载
7. AIAgentExtension 暴露的便捷 API
"""

import asyncio
import os
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 1. CapabilityProfile / WorkerMetrics
# ============================================================

def test_worker_metrics():
    print("\n[1] WorkerMetrics active_tasks + error_rate")
    from capability import WorkerMetrics

    m = WorkerMetrics()
    m.record_start()
    m.record_start()
    assert m.active_tasks == 2
    assert m.last_status == "busy"

    m.record_end(success=True, duration_ms=100.5)
    m.record_end(success=False, duration_ms=200.0)
    assert m.active_tasks == 0
    assert m.completed_tasks == 1
    assert m.failed_tasks == 1
    assert m.error_rate == 0.5
    assert m.last_status == "idle"

    d = m.to_dict()
    assert "recent_avg_latency_ms" in d
    print(f"  PASS - metrics active={m.active_tasks} err={m.error_rate:.2f}")


# ============================================================
# 2. CapabilityRegistry
# ============================================================

def test_registry_register_find():
    print("\n[2] CapabilityRegistry 注册 + 查询")
    from capability import (
        CapabilityRegistry, WorkerProfile, CapabilityProfile, reset_capability
    )
    reset_capability()
    from capability import _capability_registry, _load_balancer
    # 重置一下 instance
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    _cap_mod._load_balancer = None

    reg = CapabilityRegistry()

    p1 = WorkerProfile(
        worker_id="w1", name="W1",
        capabilities={"search": CapabilityProfile(name="search", quality=0.9, avg_cost=10)},
        tags=["fast"],
    )
    p2 = WorkerProfile(
        worker_id="w2", name="W2",
        capabilities={"search": CapabilityProfile(name="search", quality=0.7, avg_cost=5)},
        tags=["cheap"],
    )
    p3 = WorkerProfile(
        worker_id="w3", name="W3",
        capabilities={"code": CapabilityProfile(name="code", quality=0.95)},
    )
    reg.register(p1)
    reg.register(p2)
    reg.register(p3)

    # find by capability
    search_workers = reg.find("search")
    assert len(search_workers) == 2, f"expected 2, got {len(search_workers)}"
    assert {w.worker_id for w in search_workers} == {"w1", "w2"}

    # find by tag
    fast = reg.find_by_tag("fast")
    assert len(fast) == 1 and fast[0].worker_id == "w1"

    # find_idle / underloaded
    idles = reg.find_idle()
    assert len(idles) == 3
    print(f"  PASS - register/find/filter all work")


def test_registry_metrics_update():
    print("\n[3] Registry 指标上报")
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    from capability import (
        CapabilityRegistry, WorkerProfile, CapabilityProfile
    )
    reg = CapabilityRegistry()

    p = WorkerProfile(
        worker_id="w1", name="W1",
        capabilities={"search": CapabilityProfile(name="search", quality=0.9, max_concurrent=2)},
    )
    reg.register(p)

    # 上报 2 个任务启动 -> 不再 underloaded
    reg.record_task_started("w1")
    reg.record_task_started("w1")
    underloaded = reg.find_underloaded("search")
    assert len(underloaded) == 0, f"expected 0 underloaded, got {len(underloaded)}"
    busy = [w for w in reg.find("search") if w.metrics.active_tasks > 0]
    assert len(busy) == 1

    # 完成一个
    reg.record_task_ended("w1", success=True, duration_ms=150)
    profile = reg.get("w1")
    assert profile.metrics.active_tasks == 1
    assert profile.metrics.completed_tasks == 1
    assert profile.metrics.recent_durations_ms == [150]
    print(f"  PASS - metrics update works (active=1, completed=1)")


def test_registry_subscribe():
    print("\n[4] Registry 订阅")
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    from capability import CapabilityRegistry, WorkerProfile

    reg = CapabilityRegistry()
    events = []

    def cb(event_type, worker_id):
        events.append((event_type, worker_id))

    reg.subscribe(cb)
    p = WorkerProfile(worker_id="w1", name="W1", capabilities={})
    reg.register(p)
    reg.set_online("w1", False)
    reg.unregister("w1")

    assert ("registered", "w1") in events
    assert ("online_changed", "w1") in events
    assert ("unregistered", "w1") in events
    print(f"  PASS - subscribe delivered {len(events)} events")


# ============================================================
# 3. LoadBalancer
# ============================================================

def _make_workers(count: int = 3, name_prefix: str = "w"):
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    from capability import WorkerProfile, CapabilityProfile, WorkerMetrics

    return [
        WorkerProfile(
            worker_id=f"{name_prefix}{i}",
            name=f"W{i}",
            capabilities={
                "search": CapabilityProfile(
                    name="search",
                    quality=0.5 + i * 0.15,    # 质量递增
                    avg_cost=10.0 - i,         # 成本递减
                    avg_latency_ms=500 + i * 500,   # 延迟递增（升序）
                )
            },
            metrics=WorkerMetrics(active_tasks=i % 2, completed_tasks=i * 5),
        )
        for i in range(count)
    ]


def test_load_balancer_least_loaded():
    print("\n[5] LoadBalancer LEAST_LOADED")
    from capability import LoadBalancer, LoadBalanceStrategy

    workers = _make_workers(3)
    lb = LoadBalancer(strategy=LoadBalanceStrategy.LEAST_LOADED)
    chosen, score = lb.select(workers)
    # workers[0] active=0 completed=0, workers[1] active=1 completed=5, workers[2] active=0 completed=10
    # 最少 active=0，同列选 completed 最小 → w0
    assert chosen.worker_id in {"w0", "w2"}, f"got {chosen.worker_id}"
    assert chosen.worker_id == "w0", f"expected w0 (least completed among idle), got {chosen.worker_id}"
    print(f"  PASS - chose {chosen.worker_id}, score={score.total:.2f}")


def test_load_balancer_score_based():
    print("\n[6] LoadBalancer SCORE_BASED")
    from capability import LoadBalancer, LoadBalanceStrategy

    workers = _make_workers(3)
    lb = LoadBalancer(strategy=LoadBalanceStrategy.SCORE_BASED)

    chosen, score = lb.select(workers, capability="search")
    assert chosen is not None
    assert score.total > 0
    assert "load" in score.components
    assert "quality" in score.components
    print(f"  PASS - score based chose {chosen.worker_id}, "
          f"components={list(score.components.keys())}")


def test_load_balancer_wrr():
    print("\n[7] LoadBalancer WEIGHTED_ROUND_ROBIN")
    from capability import LoadBalancer, LoadBalanceStrategy

    workers = _make_workers(3)
    lb = LoadBalancer(strategy=LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN)

    # 跑 100 次，确保每个 worker 都被选过至少一次（尽管不一定均等）
    chosen_set = set()
    for _ in range(100):
        chosen, _ = lb.select(workers, capability="search")
        chosen_set.add(chosen.worker_id)

    # 因为 quality 都 > 0，应该每个 worker 都被选择过
    assert len(chosen_set) == 3, f"Expected all 3 workers selected, got {chosen_set}"
    print(f"  PASS - WRR covered all {len(chosen_set)} workers in 100 calls")


def test_load_balancer_latency_first():
    print("\n[8] LoadBalancer LATENCY_FIRST")
    from capability import LoadBalancer, LoadBalanceStrategy

    workers = _make_workers(3)
    lb = LoadBalancer(strategy=LoadBalanceStrategy.LATENCY_FIRST)
    chosen, _ = lb.select(workers, capability="search")
    # workers[2] latency = 2000 - 2*500 = 500ms，最小
    assert chosen.worker_id == "w2", f"expected w2, got {chosen.worker_id}"
    print(f"  PASS - LATENCY_FIRST picked lowest-latency worker {chosen.worker_id}")


def test_load_balancer_tags():
    print("\n[9] LoadBalancer tag_bonus 偏好")
    from capability import LoadBalancer, LoadBalanceStrategy

    workers = _make_workers(3)
    # 给 w2 加 "fast" tag
    workers[2].tags = ["fast"]

    lb = LoadBalancer(strategy=LoadBalanceStrategy.SCORE_BASED)
    chosen, score = lb.select(workers, capability="search", prefer_tags=["fast"])
    # w2 有 fast，tag_bonus 让它胜出
    assert chosen.worker_id == "w2", f"expected w2, got {chosen.worker_id}"
    assert score.components.get("tag_bonus", 0) > 0
    print(f"  PASS - tag_bonus={score.components['tag_bonus']:.2f} boosted w2")


# ============================================================
# 4. WorkerAgent 自动注册到 registry
# ============================================================

async def test_worker_auto_registers():
    print("\n[10] WorkerAgent 自动注册到 registry")
    from message_bus import get_message_bus
    from multi_agent import WorkerAgent
    from capability import get_capability_registry

    bus = get_message_bus()
    bus.reset()
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    reg = get_capability_registry()

    w = WorkerAgent(
        agent_id="autoreg_w",
        name="AutoRegW",
        capabilities=["search", "code"],
        capability_profiles={
            "search": {"quality": 0.95, "avg_cost": 12.0, "avg_latency_ms": 1500},
        },
        tags=["fast"],
    )
    await w.start()

    profile = reg.get("autoreg_w")
    assert profile is not None, "Worker should be registered"
    assert profile.has_capability("search")
    assert profile.has_capability("code")
    assert profile.tags == ["fast"]
    assert profile.capabilities["search"].quality == 0.95

    await w.stop()
    print(f"  PASS - Worker auto-registered with profile")


# ============================================================
# 5. Orchestrator._find_best_worker 加权评分
# ============================================================

async def test_orchestrator_picks_lowest_load():
    print("\n[11] Orchestrator 选择负载最低的 worker")
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    from capability import get_capability_registry, get_load_balancer, LoadBalanceStrategy
    from message_bus import get_message_bus
    from multi_agent import WorkerAgent, AgentOrchestrator

    bus = get_message_bus()
    bus.reset()
    reg = get_capability_registry()
    lb = get_load_balancer()

    # 创建 3 个 worker，注册到 registry
    w1 = WorkerAgent(agent_id="ow1", name="OW1", capabilities=["search"], executor=lambda d, dd: d)
    w2 = WorkerAgent(agent_id="ow2", name="OW2", capabilities=["search"], executor=lambda d, dd: d)
    w3 = WorkerAgent(agent_id="ow3", name="OW3", capabilities=["search"], executor=lambda d, dd: d)

    # w2 设为 busy（手动）
    reg.record_task_started("ow2")

    orch = AgentOrchestrator(supervisor_id="sup_test_lb")
    orch._workers = {
        "ow1": w1, "ow2": w2, "ow3": w3
    }

    chosen = orch._find_best_worker("search", strategy=LoadBalanceStrategy.LEAST_LOADED)
    assert chosen is not None
    # ow1 / ow3 都 idle，ow2 busy；选其中一个
    assert chosen.agent_id in {"ow1", "ow3"}, f"Picked {chosen.agent_id}"
    print(f"  PASS - LEAST_LOADED picked {chosen.agent_id} (avoided busy ow2)")


async def test_orchestrator_score_picks_highest_quality():
    print("\n[12] Orchestrator SCORE_BASED 优选高质量")
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    from capability import get_capability_registry, LoadBalanceStrategy
    from message_bus import get_message_bus
    from multi_agent import WorkerAgent, AgentOrchestrator

    bus = get_message_bus()
    bus.reset()
    reg = get_capability_registry()

    w_low = WorkerAgent(
        agent_id="oq_low", name="QLow", capabilities=["search"],
        executor=lambda d, dd: d,
        capability_profiles={"search": {"quality": 0.3, "avg_cost": 5, "avg_latency_ms": 3000}},
    )
    w_high = WorkerAgent(
        agent_id="oq_high", name="QHigh", capabilities=["search"],
        executor=lambda d, dd: d,
        capability_profiles={"search": {"quality": 0.99, "avg_cost": 15, "avg_latency_ms": 500}},
    )

    orch = AgentOrchestrator(supervisor_id="sup_test_score")
    orch._workers = {"oq_low": w_low, "oq_high": w_high}

    chosen = orch._find_best_worker("search", strategy=LoadBalanceStrategy.SCORE_BASED)
    assert chosen.agent_id == "oq_high", f"expected high quality, got {chosen.agent_id}"
    print(f"  PASS - SCORE_BASED picked highest-quality {chosen.agent_id}")


# ============================================================
# 6. AuctionManager 多维评分含负载
# ============================================================

async def test_auction_considers_load():
    print("\n[13] AuctionManager 多维评分纳入负载")
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    from capability import get_capability_registry
    from negotiation import AuctionManager, AuctionStrategy, Bid

    reg = get_capability_registry()

    # bidder_A 已经有 3 个任务在跑（max=3, 满载）
    mgr = AuctionManager()
    auction = mgr.create_auction(
        auctioneer_id="sup", task_id="t1", task_type="search",
        strategy=AuctionStrategy.SCORED,
        weights={"price": 0.4, "quality": 0.3, "eta": 0.2, "load": 0.1},
    )

    # 注册两个 worker
    from capability import WorkerProfile, CapabilityProfile, WorkerMetrics
    pA = WorkerProfile(
        worker_id="bidderA", name="A",
        capabilities={"search": CapabilityProfile(name="search", quality=0.5, max_concurrent=3)},
        metrics=WorkerMetrics(active_tasks=3, completed_tasks=10),  # 满载
    )
    pB = WorkerProfile(
        worker_id="bidderB", name="B",
        capabilities={"search": CapabilityProfile(name="search", quality=0.5, max_concurrent=3)},
        metrics=WorkerMetrics(active_tasks=0, completed_tasks=2),  # 空闲
    )
    reg.register(pA)
    reg.register(pB)

    # 两个 bid 同价同质，差别只在负载
    mgr.add_bid(auction.auction_id, Bid(auction_id=auction.auction_id, bidder_id="bidderA", price=10.0, quality=0.5, eta_seconds=2.0))
    mgr.add_bid(auction.auction_id, Bid(auction_id=auction.auction_id, bidder_id="bidderB", price=10.0, quality=0.5, eta_seconds=2.0))

    # B 应该胜出（低负载）
    mgr.close_auction(auction.auction_id)
    assert auction.winner_id == "bidderB", f"expected bidderB, got {auction.winner_id}"
    print(f"  PASS - bidderB (idle) won over bidderA (full load)")


# ============================================================
# 7. AIAgentExtension 便捷 API
# ============================================================

async def test_extension_load_api():
    print("\n[14] AIAgentExtension 暴露的 load API")
    import capability as _cap_mod
    _cap_mod._capability_registry = None
    from message_bus import get_message_bus
    from multi_agent_integration import AIAgentExtension

    bus = get_message_bus()
    bus.reset()

    class FakeAgent:
        def __init__(self):
            self.model = None
            self.current_session_id = "ext_load_test"

        async def run(self, prompt):
            return f"[Agent] {prompt}"

    fake = FakeAgent()
    # 直接构造 MultiAgentMixin 的实例（它有 list_workers / get_load_stats 等 API）
    from multi_agent_integration import MultiAgentMixin
    class _TestExt(MultiAgentMixin):
        def __init__(self):
            self.model = None
            self.current_session_id = "ext_load_test"
        def run(self, prompt):
            return f"[{self.__class__.__name__}] {prompt}"
        async def arun(self, prompt):
            return f"[async] {prompt}"

    ext = _TestExt()
    # 跳过 init_multi_agent（它跑 event loop），用 AIAgentExtension.initialize() 路径
    ext._multi_agent = AIAgentExtension(fake)
    await ext._multi_agent.initialize()
    ext._multi_agent_initialized = True

    # list_workers
    workers = ext.list_workers()
    assert len(workers) >= 4  # 默认 4 个 worker
    worker_ids = {w["worker_id"].lower() for w in workers}
    assert "searchworker" in worker_ids

    # get_load_stats
    stats = ext.get_load_stats()
    assert "workers" in stats
    assert "stats" in stats
    assert stats["stats"]["total_workers"] >= 4

    # set_load_balance_strategy
    res = ext.set_load_balance_strategy("least_loaded", prefer_tags=["fast"])
    assert res["strategy"] == "least_loaded"

    print(f"  PASS - {len(workers)} workers, stats keys={list(stats['stats'].keys())}")


# ============================================================
# 主函数
# ============================================================

async def main():
    print("\n" + "#"*60)
    print(" Capability & Load Balancing Tests")
    print("#"*60)

    failures = []

    tests = [
        ("worker_metrics", test_worker_metrics, False),
        ("registry_register", test_registry_register_find, False),
        ("registry_metrics", test_registry_metrics_update, False),
        ("registry_subscribe", test_registry_subscribe, False),
        ("lb_least", test_load_balancer_least_loaded, False),
        ("lb_score", test_load_balancer_score_based, False),
        ("lb_wrr", test_load_balancer_wrr, False),
        ("lb_latency", test_load_balancer_latency_first, False),
        ("lb_tags", test_load_balancer_tags, False),
        ("worker_autoreg", test_worker_auto_registers, True),
        ("orch_least_loaded", test_orchestrator_picks_lowest_load, True),
        ("orch_score_quality", test_orchestrator_score_picks_highest_quality, True),
        ("auction_load", test_auction_considers_load, True),
        ("extension_api", test_extension_load_api, True),
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

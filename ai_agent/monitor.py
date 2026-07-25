"""
结构化上下文持久化 - 性能监控模块
Phase 5: 性能优化与监控
"""
import time
import logging
from typing import Dict, Any, Optional, Callable
from functools import wraps
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.metrics = defaultdict(list)
        self.start_times = {}
        self.operation_counts = defaultdict(int)
        self.error_counts = defaultdict(int)
        
        # 性能阈值（毫秒）
        self.thresholds = {
            'db_query': 100,      # 数据库查询
            'context_build': 200,  # 上下文构建
            'entity_extract': 50,  # 实体提取
            'summary_generate': 500,  # 摘要生成
        }
    
    def start_timer(self, operation: str):
        """开始计时"""
        self.start_times[operation] = time.time()
    
    def end_timer(self, operation: str) -> float:
        """结束计时并返回耗时（毫秒）"""
        if operation not in self.start_times:
            return 0
        
        elapsed = (time.time() - self.start_times[operation]) * 1000
        del self.start_times[operation]
        
        # 记录指标
        self.metrics[operation].append({
            'elapsed_ms': elapsed,
            'timestamp': datetime.now().isoformat()
        })
        
        # 检查阈值
        if operation in self.thresholds and elapsed > self.thresholds[operation]:
            logger.warning(f"Slow operation [{operation}]: {elapsed:.2f}ms > {self.thresholds[operation]}ms")
        
        self.operation_counts[operation] += 1
        
        return elapsed
    
    def record_error(self, operation: str):
        """记录错误"""
        self.error_counts[operation] += 1
    
    def get_stats(self, operation: str = None) -> Dict[str, Any]:
        """获取统计信息"""
        if operation:
            metrics = self.metrics.get(operation, [])
            if not metrics:
                return {
                    'operation': operation,
                    'count': self.operation_counts.get(operation, 0),
                    'errors': self.error_counts.get(operation, 0)
                }
            
            elapsed_times = [m['elapsed_ms'] for m in metrics]
            return {
                'operation': operation,
                'count': len(metrics),
                'errors': self.error_counts.get(operation, 0),
                'avg_ms': sum(elapsed_times) / len(elapsed_times),
                'min_ms': min(elapsed_times),
                'max_ms': max(elapsed_times),
                'last_ms': elapsed_times[-1] if elapsed_times else 0
            }
        
        # 返回所有操作的统计
        return {
            op: self.get_stats(op) 
            for op in self.metrics.keys()
        }
    
    def reset(self):
        """重置所有指标"""
        self.metrics.clear()
        self.start_times.clear()
        self.operation_counts.clear()
        self.error_counts.clear()
    
    def cleanup_old_metrics(self, max_age_seconds: int = 3600):
        """清理旧的指标数据"""
        now = datetime.now()
        for operation in list(self.metrics.keys()):
            self.metrics[operation] = [
                m for m in self.metrics[operation]
                if (now - datetime.fromisoformat(m['timestamp'])).total_seconds() < max_age_seconds
            ]


def monitor(operation: str = None):
    """性能监控装饰器
    
    使用方式:
    @monitor('my_operation')
    def my_function():
        pass
    """
    def decorator(func: Callable) -> Callable:
        nonlocal operation
        if operation is None:
            operation = func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.time() - start) * 1000
                
                # 记录到全局监控器
                monitor_global.record_operation(operation, elapsed)
                
                return result
            except Exception as e:
                monitor_global.record_error(operation)
                raise
        
        return wrapper
    return decorator


# 全局性能监控器
monitor_global = PerformanceMonitor()


class CacheManager:
    """缓存管理器（简单内存缓存）"""
    
    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        self.cache: Dict[str, tuple[Any, datetime]] = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key not in self.cache:
            return None
        
        value, timestamp = self.cache[key]
        
        # 检查过期
        if (datetime.now() - timestamp).total_seconds() > self.ttl_seconds:
            del self.cache[key]
            return None
        
        return value
    
    def set(self, key: str, value: Any):
        """设置缓存"""
        # 如果缓存满了，删除最老的
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
        
        self.cache[key] = (value, datetime.now())
    
    def delete(self, key: str):
        """删除缓存"""
        if key in self.cache:
            del self.cache[key]
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'ttl_seconds': self.ttl_seconds
        }


# 全局缓存实例
context_cache = CacheManager(max_size=50, ttl_seconds=60)  # 上下文缓存
entity_cache = CacheManager(max_size=200, ttl_seconds=300)  # 实体缓存


def get_monitor() -> PerformanceMonitor:
    """获取全局性能监控器"""
    return monitor_global


def get_context_cache() -> CacheManager:
    """获取上下文缓存"""
    return context_cache


def get_entity_cache() -> CacheManager:
    """获取实体缓存"""
    return entity_cache

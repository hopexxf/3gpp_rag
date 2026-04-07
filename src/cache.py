#!/usr/bin/env python3
"""
模糊缓存模块 - 缓存相似查询结果
- 使用查询文本的哈希作为key
- LRU淘汰策略
- 支持配置启用/禁用
"""

import hashlib
import json
import time
from typing import Dict, Any, Optional
from collections import OrderedDict


class FuzzyCache:
    """模糊缓存 - 基于查询文本哈希"""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.hit_count = 0
        self.miss_count = 0
    
    def _get_key(self, query: str, release: str, mode: str, **kwargs) -> str:
        """生成缓存key"""
        # 规范化查询文本
        normalized = query.lower().strip()
        key_str = f"{normalized}:{release}:{mode}:{json.dumps(kwargs, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, query: str, release: str, mode: str, **kwargs) -> Optional[Any]:
        """获取缓存结果"""
        key = self._get_key(query, release, mode, **kwargs)
        
        if key in self.cache:
            # 移动到末尾（最近使用）
            self.cache.move_to_end(key)
            self.hit_count += 1
            return self.cache[key]["result"]
        
        self.miss_count += 1
        return None
    
    def set(self, query: str, release: str, mode: str, result: Any, **kwargs):
        """设置缓存结果"""
        key = self._get_key(query, release, mode, **kwargs)
        
        # 如果已存在，先删除
        if key in self.cache:
            del self.cache[key]
        
        # 如果超过最大大小，删除最旧的
        while len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        
        # 添加新缓存
        self.cache[key] = {
            "result": result,
            "timestamp": time.time(),
            "query": query[:50]  # 保存部分查询用于调试
        }
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.hit_count = 0
        self.miss_count = 0
    
    def stats(self) -> Dict[str, int]:
        """获取缓存统计"""
        total = self.hit_count + self.miss_count
        hit_rate = self.hit_count / total if total > 0 else 0
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hit_count,
            "misses": self.miss_count,
            "hit_rate": round(hit_rate, 3)
        }


# 全局缓存实例（单例）
_cache_instance: Optional[FuzzyCache] = None


def get_cache(max_size: int = 100) -> FuzzyCache:
    """获取全局缓存实例"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = FuzzyCache(max_size=max_size)
    return _cache_instance


def cached_search(search_func):
    """装饰器 - 为搜索函数添加缓存"""
    def wrapper(query: str, release: str = "Rel-19", mode: str = "hybrid", 
                use_cache: bool = True, **kwargs):
        # 检查配置是否启用缓存
        if use_cache:
            try:
                from src.config_loader import load_config
                cfg = load_config()
                cache_enabled = cfg.get("cache", {}).get("enabled", True)
                cache_size = cfg.get("cache", {}).get("max_size", 100)
                
                if cache_enabled:
                    cache = get_cache(cache_size)
                    cached_result = cache.get(query, release, mode, **kwargs)
                    if cached_result is not None:
                        return cached_result
                    
                    # 执行搜索
                    result = search_func(query, release, mode, **kwargs)
                    
                    # 缓存结果
                    cache.set(query, release, mode, result, **kwargs)
                    return result
            except Exception:
                # 缓存出错不影响主流程
                pass
        
        # 缓存禁用或出错，直接执行
        return search_func(query, release, mode, **kwargs)
    
    return wrapper


if __name__ == "__main__":
    # 测试
    cache = FuzzyCache(max_size=3)
    
    # 测试缓存
    cache.set("PRACH", "Rel-19", "hybrid", ["result1", "result2"])
    result = cache.get("PRACH", "Rel-19", "hybrid")
    print(f"缓存命中: {result}")
    
    # 测试不同查询
    result2 = cache.get("PUSCH", "Rel-19", "hybrid")
    print(f"缓存未命中: {result2}")
    
    # 测试LRU淘汰
    cache.set("A", "Rel-19", "hybrid", "A")
    cache.set("B", "Rel-19", "hybrid", "B")
    cache.set("C", "Rel-19", "hybrid", "C")
    cache.set("D", "Rel-19", "hybrid", "D")  # 应该淘汰A
    
    print(f"缓存统计: {cache.stats()}")

#!/usr/bin/env python3
"""
重排序模块 - 使用Cross-Encoder对检索结果二次排序
- 优先使用本地模型
- 次之下载HuggingFace模型
"""

import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))


class Reranker:
    """重排序器 - 基于Cross-Encoder"""
    
    def __init__(self, model_path: str):
        """
        初始化重排序器
        
        Args:
            model_path: 模型路径（本地或HuggingFace名称）
        """
        self.model_path = model_path
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """加载Cross-Encoder模型"""
        try:
            from sentence_transformers import CrossEncoder
            
            print(f"加载重排序模型: {self.model_path}")
            self.model = CrossEncoder(self.model_path)
            print("重排序模型加载完成")
            
        except Exception as e:
            print(f"警告: 加载重排序模型失败: {e}")
            self.model = None
    
    def is_available(self) -> bool:
        """检查模型是否可用"""
        return self.model is not None
    
    def rerank(self, query: str, results: List[Dict[str, Any]], 
               top_k: int = 5) -> List[Dict[str, Any]]:
        """
        对检索结果重排序
        
        Args:
            query: 查询文本
            results: 检索结果列表（来自混合检索）
            top_k: 返回前K个结果
            
        Returns:
            重排序后的结果列表
        """
        if not self.is_available() or not results:
            return results[:top_k]
        
        # 准备输入对 (query, document)
        pairs = []
        for r in results:
            # 构建文档文本
            doc_text = f"{r.get('title', '')}\n{r.get('content', '')[:500]}"
            pairs.append((query, doc_text))
        
        # 计算相关性分数
        scores = self.model.predict(pairs)
        
        # 组合结果和分数
        scored_results = list(zip(results, scores))
        
        # 按分数降序排序
        scored_results.sort(key=lambda x: x[1], reverse=True)
        
        # 返回前K个结果（保留原始格式，添加rerank_score）
        reranked = []
        for result, score in scored_results[:top_k]:
            result_copy = result.copy()
            result_copy['rerank_score'] = float(score)
            reranked.append(result_copy)
        
        return reranked


def get_reranker_from_config() -> Reranker:
    """从配置创建重排序器"""
    try:
        from src.config_loader import load_config, get_embedding_model
        
        cfg = load_config()
        reranker_cfg = cfg.get("reranker", {})
        
        if not reranker_cfg.get("enabled", False):
            print("重排序已禁用")
            return None
        
        # 优先使用本地路径
        local_path = reranker_cfg.get("model_local_path", "").strip()
        if local_path:
            # 解析路径
            from src.config_loader import resolve_path
            config_file = cfg.get("_config_file", Path.cwd())
            resolved_path = resolve_path(local_path, config_file.parent)
            if resolved_path.exists():
                return Reranker(str(resolved_path))
            else:
                print(f"警告: 本地重排序模型不存在: {resolved_path}")
        
        # 使用模型名称
        model_name = reranker_cfg.get("model_name", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        return Reranker(model_name)
        
    except Exception as e:
        print(f"警告: 初始化重排序器失败: {e}")
        return None


if __name__ == "__main__":
    # 测试
    print("测试重排序模块")
    
    reranker = get_reranker_from_config()
    
    if reranker and reranker.is_available():
        # 模拟检索结果
        test_results = [
            {"title": "PRACH配置", "content": "随机接入信道配置参数", "score": 0.8},
            {"title": "PUSCH调度", "content": "上行共享信道调度", "score": 0.7},
            {"title": "PRACH preamble", "content": "随机接入前导码格式", "score": 0.9},
        ]
        
        query = "随机接入格式"
        reranked = reranker.rerank(query, test_results, top_k=3)
        
        print(f"\n查询: {query}")
        print("重排序结果:")
        for i, r in enumerate(reranked, 1):
            print(f"{i}. {r['title']} (score: {r.get('rerank_score', 0):.3f})")
    else:
        print("重排序器不可用")

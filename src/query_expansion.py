#!/usr/bin/env python3
"""
查询扩展模块 - 同义词扩展
- 内置词典（data/synonyms_builtin.json）
- 自动补充（data/synonyms_auto.json）
- 用户自定义（config.json，优先级最高）
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional
from datetime import datetime


class QueryExpansion:
    """查询扩展器"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.enabled = config.get("query_expansion", {}).get("enabled", True)
        
        # 加载各级词典
        self.builtin_dict = self._load_builtin_dict()
        self.auto_dict = self._load_auto_dict()
        self.custom_dict = config.get("query_expansion", {}).get("custom_terms", {})
        
        # 合并词典（优先级：custom > auto > builtin）
        self.merged_dict = self._merge_dicts()
    
    def _get_data_dir(self) -> Path:
        """获取数据目录"""
        # 尝试从配置获取work_dir，然后找data子目录
        try:
            from src.config_loader import get_path
            work_dir = get_path(self.config, "work_dir")
            data_dir = work_dir / "data"
            if data_dir.exists():
                return data_dir
        except:
            pass
        
        # 回退：从脚本位置推断
        script_dir = Path(__file__).parent.parent
        data_dir = script_dir / "data"
        if data_dir.exists():
            return data_dir
        
        # 最后回退：当前目录
        return Path("data")
    
    def _load_builtin_dict(self) -> Dict[str, List[str]]:
        """加载内置词典"""
        data_dir = self._get_data_dir()
        builtin_file = data_dir / "synonyms_builtin.json"
        
        if not builtin_file.exists():
            return {}
        
        try:
            with open(builtin_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 扁平化嵌套结构
                result = {}
                for category, terms in data.items():
                    if category.startswith("_"):
                        continue
                    if isinstance(terms, dict):
                        result.update(terms)
                return result
        except Exception as e:
            print(f"警告: 加载内置词典失败: {e}")
            return {}
    
    def _load_auto_dict(self) -> Dict[str, List[str]]:
        """加载自动补充词典"""
        data_dir = self._get_data_dir()
        auto_file = data_dir / "synonyms_auto.json"
        
        if not auto_file.exists():
            return {}
        
        try:
            with open(auto_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("auto_terms", {})
        except Exception as e:
            print(f"警告: 加载自动词典失败: {e}")
            return {}
    
    def _merge_dicts(self) -> Dict[str, List[str]]:
        """合并词典（优先级：custom > auto > builtin）"""
        merged = {}
        
        # 先加载builtin
        for term, synonyms in self.builtin_dict.items():
            merged[term.upper()] = set(s.lower() for s in synonyms)
        
        # 再加载auto（覆盖builtin）
        for term, synonyms in self.auto_dict.items():
            merged[term.upper()] = set(s.lower() for s in synonyms)
        
        # 最后加载custom（最高优先级）
        for term, synonyms in self.custom_dict.items():
            if not term.startswith("_"):  # 跳过注释键
                merged[term.upper()] = set(s.lower() for s in synonyms)
        
        # 转换回列表
        return {k: list(v) for k, v in merged.items()}
    
    def expand(self, query: str) -> str:
        """
        扩展查询
        例如: "BWP配置" -> "BWP OR Bandwidth Part OR 带宽部分 配置"
        """
        if not self.enabled:
            return query
        
        # 分词（简单按空格分割，保留引号内的短语）
        tokens = self._tokenize(query)
        expanded_tokens = []
        
        for token in tokens:
            token_upper = token.upper()
            expanded_tokens.append(token)  # 保留原词
            
            # 查找同义词
            if token_upper in self.merged_dict:
                synonyms = self.merged_dict[token_upper]
                # 添加同义词（排除原词本身）
                for syn in synonyms:
                    if syn.lower() != token.lower():
                        expanded_tokens.append(syn)
        
        # 去重并组合
        seen = set()
        unique_tokens = []
        for t in expanded_tokens:
            t_lower = t.lower()
            if t_lower not in seen:
                seen.add(t_lower)
                unique_tokens.append(t)
        
        return " ".join(unique_tokens)
    
    def _tokenize(self, query: str) -> List[str]:
        """简单分词"""
        # 保留引号内的短语
        pattern = r'"[^"]*"|\S+'
        tokens = re.findall(pattern, query)
        return [t.strip('"') for t in tokens]
    
    def add_auto_term(self, term: str, synonyms: List[str]):
        """
        添加自动补充的同义词
        在查询过程中自动学习
        """
        term_upper = term.upper()
        
        # 更新内存中的词典
        if term_upper not in self.merged_dict:
            self.merged_dict[term_upper] = []
        
        for syn in synonyms:
            if syn.lower() not in [s.lower() for s in self.merged_dict[term_upper]]:
                self.merged_dict[term_upper].append(syn)
        
        # 持久化到文件
        self._save_auto_dict()
    
    def _save_auto_dict(self):
        """保存自动补充词典到文件"""
        data_dir = self._get_data_dir()
        auto_file = data_dir / "synonyms_auto.json"
        
        try:
            # 只保存非builtin的项
            auto_terms = {}
            for term, synonyms in self.merged_dict.items():
                if term not in self.builtin_dict:
                    auto_terms[term] = synonyms
            
            data = {
                "_comment": "自动补充同义词 - 由程序在查询过程中自动学习补充，用户请勿手动修改",
                "_version": "1.0",
                "_last_updated": datetime.now().isoformat(),
                "auto_terms": auto_terms
            }
            
            with open(auto_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"警告: 保存自动词典失败: {e}")
    
    def get_stats(self) -> Dict:
        """获取扩展统计"""
        return {
            "enabled": self.enabled,
            "builtin_terms": len(self.builtin_dict),
            "auto_terms": len(self.auto_dict),
            "custom_terms": len(self.custom_dict),
            "total_terms": len(self.merged_dict)
        }


def expand_query(query: str, config: Optional[Dict] = None) -> str:
    """便捷函数：扩展查询"""
    if config is None:
        try:
            from src.config_loader import load_config
            config = load_config()
        except:
            return query
    
    expander = QueryExpansion(config)
    return expander.expand(query)


if __name__ == "__main__":
    # 测试
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.config_loader import load_config
    
    cfg = load_config()
    expander = QueryExpansion(cfg)
    
    print(f"扩展统计: {expander.get_stats()}")
    
    # 测试扩展
    test_queries = [
        "BWP配置",
        "PRACH preamble格式",
        "RedCap能力"
    ]
    
    for q in test_queries:
        expanded = expander.expand(q)
        print(f"\n原查询: {q}")
        print(f"扩展后: {expanded}")

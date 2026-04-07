#!/usr/bin/env python3
"""
3GPP RAG Configuration Loader
支持配置文件 + 环境变量覆盖，无代码内嵌路径
"""

import os
import json
from pathlib import Path
from typing import Dict, Optional

# 配置文件名
CONFIG_FILENAME = "config.json"

# 环境变量前缀
ENV_PREFIX = "GPP_RAG_"

# 环境变量到配置键的映射
ENV_MAPPING = {
    "GPP_RAG_WORK_DIR": ("paths", "work_dir"),
    "GPP_RAG_PROTOCOL_BASE": ("paths", "protocol_base"),
    "GPP_RAG_LOG_DIR": ("paths", "log_dir"),
}


class ConfigError(Exception):
    """配置错误异常"""
    pass


def find_config_file() -> Optional[Path]:
    """
    查找配置文件，搜索顺序：
    1. 环境变量 GPP_RAG_CONFIG 指定的路径
    2. config/config.json（新目录结构）
    3. 当前工作目录
    4. 脚本所在目录的config子目录
    5. 父目录（向上递归3层）
    """
    # 1. 环境变量指定
    env_config = os.environ.get("GPP_RAG_CONFIG")
    if env_config:
        path = Path(env_config)
        if path.exists():
            return path
        raise ConfigError(f"环境变量 GPP_RAG_CONFIG 指定的配置文件不存在: {env_config}")
    
    # 2. 新目录结构：config/config.json
    new_structure = Path.cwd() / "config" / CONFIG_FILENAME
    if new_structure.exists():
        return new_structure
    
    # 3. 当前工作目录
    cwd_config = Path.cwd() / CONFIG_FILENAME
    if cwd_config.exists():
        return cwd_config
    
    # 4. 脚本所在目录的config子目录（新结构）
    script_dir = Path(__file__).parent.resolve()
    script_config_new = script_dir / "config" / CONFIG_FILENAME
    if script_config_new.exists():
        return script_config_new
    
    # 5. 脚本所在目录（旧结构兼容）
    script_config = script_dir / CONFIG_FILENAME
    if script_config.exists():
        return script_config
    
    # 6. 向上递归查找
    for parent in script_dir.parents[:3]:
        parent_config_new = parent / "config" / CONFIG_FILENAME
        if parent_config_new.exists():
            return parent_config_new
        parent_config_old = parent / CONFIG_FILENAME
        if parent_config_old.exists():
            return parent_config_old
    
    return None


def load_config_file(config_path: Path) -> Dict:
    """加载配置文件"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"配置文件 JSON 格式错误: {e}")
    except Exception as e:
        raise ConfigError(f"读取配置文件失败: {e}")


def apply_env_overrides(config: Dict) -> Dict:
    """应用环境变量覆盖"""
    for env_var, (section, key) in ENV_MAPPING.items():
        value = os.environ.get(env_var)
        if value:
            if section not in config:
                config[section] = {}
            config[section][key] = value
    return config


def resolve_path(path_str: str, base_dir: Optional[Path] = None) -> Path:
    """
    解析路径：
    - 绝对路径直接使用
    - 相对路径相对于 base_dir（若未指定则相对于当前工作目录）
    - 自动转换正斜杠为系统路径分隔符
    """
    if not path_str:
        raise ConfigError("路径不能为空")
    
    path = Path(path_str.replace("/", os.sep))
    
    if path.is_absolute():
        return path.resolve()
    
    if base_dir:
        return (base_dir / path).resolve()
    
    return path.resolve()


def validate_config(config: Dict, config_file: Path) -> None:
    """验证配置完整性"""
    required_paths = ["work_dir", "protocol_base"]
    
    paths = config.get("paths", {})
    for key in required_paths:
        if not paths.get(key):
            raise ConfigError(f"配置缺少必需路径: paths.{key}")
    
    # 验证路径可解析
    base_dir = config_file.parent
    for key in required_paths:
        try:
            path = resolve_path(paths[key], base_dir)
            if not path.exists():
                print(f"警告: 路径不存在，将自动创建: {path}")
        except Exception as e:
            raise ConfigError(f"路径解析失败 paths.{key}: {e}")


def load_config() -> Dict:
    """
    加载完整配置（配置文件 + 环境变量覆盖）
    
    Returns:
        配置字典，包含解析后的 Path 对象
    """
    # 查找配置文件
    config_file = find_config_file()
    if not config_file:
        raise ConfigError(
            f"未找到配置文件 {CONFIG_FILENAME}。"
            f"请确保配置文件存在于工作目录或脚本所在目录，"
            f"或通过环境变量 GPP_RAG_CONFIG 指定路径。"
        )
    
    # 加载配置
    config = load_config_file(config_file)
    
    # 应用环境变量覆盖
    config = apply_env_overrides(config)
    
    # 验证
    validate_config(config, config_file)
    
    # 解析路径为 Path 对象
    base_dir = config_file.parent
    paths = config.get("paths", {})
    
    resolved_paths = {}
    for key, value in paths.items():
        if key.startswith("_"):
            continue  # 跳过注释键
        if value:
            resolved_paths[key] = resolve_path(value, base_dir)
        else:
            # log_dir 为空时使用默认值
            if key == "log_dir":
                resolved_paths[key] = resolved_paths.get("work_dir", base_dir) / "logs"
    
    config["_resolved_paths"] = resolved_paths
    config["_config_file"] = config_file
    
    return config


def get_path(config: Dict, name: str) -> Path:
    """获取解析后的路径"""
    resolved = config.get("_resolved_paths", {})
    if name not in resolved:
        raise ConfigError(f"未知路径名称: {name}")
    return resolved[name]


def get_db_path(config: Dict, release: str) -> Path:
    """获取指定 Release 的数据库路径"""
    work_dir = get_path(config, "work_dir")
    # 新目录结构：data/chroma_db/rel19
    release_lower = release.lower().replace("-", "")
    return work_dir / "data" / "chroma_db" / release_lower


def get_embedding_model(config: Dict) -> str:
    """
    获取嵌入模型配置。
    优先使用本地路径，本地路径为空时使用模型名称（联网下载）。
    
    Returns:
        模型路径或名称（可直接传给 SentenceTransformer）
    """
    db_config = config.get("database", {})
    
    # 优先检查本地路径
    local_path = db_config.get("embedding_model_local_path", "").strip()
    if local_path:
        # 解析为绝对路径
        config_file = config.get("_config_file", Path.cwd())
        resolved_path = resolve_path(local_path, config_file.parent)
        if resolved_path.exists():
            return str(resolved_path)
        else:
            print(f"警告: 本地模型路径不存在: {resolved_path}，将使用在线模型")
    
    # 使用模型名称（在线下载）
    return db_config.get("embedding_model", "all-MiniLM-L6-v2")


# 向后兼容的便捷函数
def get_work_dir() -> Path:
    """获取工作目录（便捷函数）"""
    return get_path(load_config(), "work_dir")


def get_protocol_base() -> Path:
    """获取协议根目录（便捷函数）"""
    return get_path(load_config(), "protocol_base")


def get_log_dir() -> Path:
    """获取日志目录（便捷函数）"""
    return get_path(load_config(), "log_dir")


if __name__ == "__main__":
    # 测试配置加载
    try:
        cfg = load_config()
        print(f"配置文件: {cfg['_config_file']}")
        print(f"工作目录: {get_path(cfg, 'work_dir')}")
        print(f"协议目录: {get_path(cfg, 'protocol_base')}")
        print(f"日志目录: {get_path(cfg, 'log_dir')}")
        print(f"Rel-19 DB: {get_db_path(cfg, 'Rel-19')}")
    except ConfigError as e:
        print(f"配置错误: {e}")
        exit(1)

#!/usr/bin/env python3
"""
日志管理模块 - 支持大小轮转
- 单个文件最大10MB
- 最多保留5个文件
- 超过时删除最旧的
"""

import os
import glob
from pathlib import Path
from datetime import datetime
from typing import Optional

LOG_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
LOG_MAX_FILES = 5


class LogManager:
    """日志管理器"""
    
    def __init__(self, log_dir: Path, name: str):
        self.log_dir = log_dir
        self.name = name
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def get_log_file(self) -> Path:
        """获取当前日志文件路径"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        base_name = f"{self.name}_{date_str}"
        log_file = self.log_dir / f"{base_name}.log"
        
        # 检查当前日志大小
        if log_file.exists() and log_file.stat().st_size > LOG_MAX_SIZE_BYTES:
            # 需要轮转
            self._rotate_logs(base_name)
        
        # 清理旧日志
        self._cleanup_old_logs()
        
        return log_file
    
    def _rotate_logs(self, base_name: str):
        """轮转日志文件"""
        # 从后往前重命名
        for i in range(LOG_MAX_FILES - 1, 0, -1):
            old_file = self.log_dir / f"{base_name}.{i}.log"
            new_file = self.log_dir / f"{base_name}.{i+1}.log"
            if old_file.exists():
                if i == LOG_MAX_FILES - 1:
                    # 删除最旧的
                    old_file.unlink()
                else:
                    old_file.rename(new_file)
        
        # 重命名当前日志
        current = self.log_dir / f"{base_name}.log"
        if current.exists():
            current.rename(self.log_dir / f"{base_name}.1.log")
    
    def _cleanup_old_logs(self):
        """清理超出数量的日志文件"""
        pattern = str(self.log_dir / f"{self.name}_*.log")
        files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        
        # 保留最新的 LOG_MAX_FILES 个
        for old_file in files[LOG_MAX_FILES:]:
            try:
                os.unlink(old_file)
            except:
                pass
    
    def write(self, msg: str, level: str = "INFO"):
        """写入日志"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}\n"
        
        log_file = self.get_log_file()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)


def get_log_manager(name: str) -> LogManager:
    """获取日志管理器实例"""
    from src.config_loader import load_config, get_path
    
    try:
        cfg = load_config()
        log_dir = get_path(cfg, "log_dir")
    except:
        # 回退到默认路径
        log_dir = Path(__file__).parent.parent / "logs"
    
    return LogManager(log_dir, name)


if __name__ == "__main__":
    # 测试
    log_mgr = get_log_manager("test")
    log_mgr.write("测试日志消息")
    print(f"日志文件: {log_mgr.get_log_file()}")

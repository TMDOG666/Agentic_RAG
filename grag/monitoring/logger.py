# Logging Module
 
from __future__ import annotations
 
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional
 
from grag.config import get_config_manager
 
 
_CONFIGURED: bool = False
 
 
def _configure_root_logger() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
 
    settings = get_config_manager().get_settings()
    logging_cfg = getattr(settings.system, "logging", {}) or {}
    level_name = str(logging_cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
 
    root = logging.getLogger()
    root.setLevel(level)
 
    # 避免重复添加 handler
    if root.handlers:
        _CONFIGURED = True
        return
 
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
 
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)
 
    file_path = logging_cfg.get("file_path")
    if file_path:
        try:
            file_path = os.path.abspath(str(file_path))
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
 
            max_file_size_raw = str(logging_cfg.get("max_file_size", "100MB"))
            max_bytes = 100 * 1024 * 1024
            if max_file_size_raw.lower().endswith("mb"):
                max_bytes = int(float(max_file_size_raw[:-2]) * 1024 * 1024)
            elif max_file_size_raw.lower().endswith("kb"):
                max_bytes = int(float(max_file_size_raw[:-2]) * 1024)
            elif max_file_size_raw.lower().endswith("b"):
                max_bytes = int(float(max_file_size_raw[:-1]))
 
            backup_count = int(logging_cfg.get("backup_count", 5))
 
            file_handler = RotatingFileHandler(
                file_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except Exception:
            # 文件日志配置失败时不要阻断业务
            pass
 
    _CONFIGURED = True
 
 
def get_logger(name: Optional[str] = None) -> logging.Logger:
    _configure_root_logger()
    return logging.getLogger(name if name else "grag")
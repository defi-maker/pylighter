"""
日志配置工具库
Logger Configuration Utility

提供统一的日志配置和管理功能
Provides unified logging configuration and management functionality
"""

import os
import logging
from typing import Optional


class LoggerConfig:
    """日志配置管理器"""

    def __init__(self,
                 log_dir: str = "log",
                 log_level: int = logging.INFO,
                 console_output: bool = True,
                 file_encoding: str = 'utf-8'):
        """
        初始化日志配置

        Args:
            log_dir: 日志目录
            log_level: 日志级别
            console_output: 是否输出到控制台
            file_encoding: 文件编码
        """
        self.log_dir = log_dir
        self.log_level = log_level
        self.console_output = console_output
        self.file_encoding = file_encoding
        self.log_format = "%(asctime)s - %(levelname)s - %(message)s"
        logging.getLogger().setLevel(log_level)

        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)

    def setup_logger(self,
                     name: Optional[str] = None,
                     log_file: Optional[str] = None,
                     file_mode: str = 'a') -> logging.Logger:
        """
        设置日志器

        Args:
            name: 日志器名称，默认使用调用脚本名称
            log_file: 日志文件名，默认使用脚本名称
            file_mode: 文件模式 ('a' 追加, 'w' 覆盖)

        Returns:
            配置好的日志器
        """
        # 获取调用者信息
        if name is None:
            import inspect
            frame = inspect.currentframe().f_back
            caller_filename = frame.f_code.co_filename
            name = os.path.splitext(os.path.basename(caller_filename))[0]

        if log_file is None:
            log_file = f"{name}.log"

        # 创建日志格式器
        formatter = logging.Formatter(self.log_format)

        # 获取日志器
        logger = logging.getLogger(name)
        logger.setLevel(self.log_level)

        # 防止日志传播到根日志器（避免重复输出）
        logger.propagate = False

        # 清除现有处理器（避免重复）
        logger.handlers.clear()

        # 创建文件处理器
        log_file_path = os.path.join(self.log_dir, log_file)
        file_handler = logging.FileHandler(
            log_file_path,
            mode=file_mode,
            encoding=self.file_encoding
        )
        file_handler.setLevel(self.log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # 创建控制台处理器（可选）
        if self.console_output:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.log_level)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        # 记录初始化信息
        logger.info(f"📝 日志系统初始化完成 - 文件: {log_file_path}")
        logger.info(f"🤖 {name} 启动中...")

        return logger

    def get_strategy_logger(self, strategy_name: str) -> logging.Logger:
        """
        获取策略专用日志器

        Args:
            strategy_name: 策略名称

        Returns:
            策略日志器
        """
        return self.setup_logger(
            name=f"strategy_{strategy_name}",
            log_file=f"{strategy_name}_strategy.log"
        )

    def get_backtest_logger(self, backtest_name: str) -> logging.Logger:
        """
        获取回测专用日志器

        Args:
            backtest_name: 回测名称

        Returns:
            回测日志器
        """
        return self.setup_logger(
            name=f"backtest_{backtest_name}",
            log_file=f"{backtest_name}_backtest.log"
        )


# 默认日志配置实例
default_logger_config = LoggerConfig()


def get_logger(name: Optional[str] = None,
               log_file: Optional[str] = None) -> logging.Logger:
    """
    快速获取日志器的便捷函数

    Args:
        name: 日志器名称
        log_file: 日志文件名

    Returns:
        配置好的日志器
    """
    return default_logger_config.setup_logger(name, log_file)


def get_strategy_logger(strategy_name: str) -> logging.Logger:
    """
    快速获取策略日志器的便捷函数

    Args:
        strategy_name: 策略名称

    Returns:
        策略日志器
    """
    return default_logger_config.get_strategy_logger(strategy_name)

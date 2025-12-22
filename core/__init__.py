"""
core 包：提供项目的“核心大脑”统一入口。

Card 1：
- 通过 SecondBrain 封装上下文构建 / 模式切换 / 隐私闸门 / 工具调用的统一入口
"""

from .brain import SecondBrain

__all__ = ["SecondBrain"]



"""关键路径安全包装：捕获异常 → log → 通知 UI → 重新抛出或返回 None。"""

import functools
import inspect
from typing import Any, Callable, Optional, TypeVar

from app.observability.logger import get_logger
from app.observability.log_signals import emit_log_message, LogLevel


_log = get_logger("app.system")
T = TypeVar("T")


def safe_call(
    func: Optional[Callable] = None,
    *,
    context: str = "",
    reraise: bool = False,
    on_error: Optional[Callable[[Exception], Any]] = None,
) -> Callable:
    """装饰器/上下文：在关键路径 catch 异常。

    用法：
        @safe_call(context="_open_detail")
        def _open_detail(self, cid): ...

        或：
        safe_call(self._do, context="...")(*args)
    """
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                ctx = context or f.__qualname__
                _log.error(
                    "exception in %s: %r\n  args=%r kwargs=%r",
                    ctx, e, _safe_repr(args), _safe_repr(kwargs),
                    exc_info=True,
                )
                emit_log_message(
                    LogLevel.ERROR,
                    f"{ctx}: {e}",
                )
                if on_error is not None:
                    try:
                        return on_error(e)
                    except Exception:
                        _log.critical("on_error handler itself failed",
                                      exc_info=True)
                if reraise:
                    raise
                return None
        return wrapper
    if func is not None and callable(func):
        return decorator(func)
    return decorator


def _safe_repr(obj: Any) -> str:
    """repr 但防递归。"""
    try:
        s = repr(obj)
        if len(s) > 200:
            s = s[:200] + "..."
        return s
    except Exception:
        return "<unreprable>"

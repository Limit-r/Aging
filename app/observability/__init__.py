"""可观测性模块：logger 配置 + 异常兜底 + 关键路径包装 + 日志信号。

3 个 logger 命名空间：
- app.data     数据源相关（MockDataSource / HistoryBuffer）
- app.ui       UI 事件（点击、双击、详情页开关）
- app.system   全局异常、启动、关闭

3 个输出：
- 文件      logs/app_YYYY-MM-DD.log  按天轮转
- 控制台    带 ANSI 颜色
- Qt signal  推送到 MainWindow / DetailWindow 状态栏

异常兜底（install_exception_hooks）：
- sys.excepthook                Python 顶层
- threading.excepthook          后台线程
- QApplication.notify wrapper   Qt 事件循环
"""

from app.observability.logger import get_logger, configure_logging
from app.observability.exception_hook import (
    install_exception_hooks, set_exception_handler,
)
from app.observability.safe_call import safe_call
from app.observability.log_signals import (
    log_message_emitted, LogLevel, emit_log_message,
)

__all__ = [
    "get_logger", "configure_logging",
    "install_exception_hooks", "set_exception_handler",
    "safe_call",
    "log_message_emitted", "LogLevel", "emit_log_message",
]

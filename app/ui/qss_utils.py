"""QSS / 样式相关工具函数。"""


def refresh_qss(widget) -> None:
    """强制重新应用 QSS（修改 dynamic property 后必须调用）。

    之前在 4 个模块（main_window / countdown_widget / control_button / data_cell）
    各有一份相同的 `_restyle` 工具函数，现集中到此处作为唯一公开 API。

    使用场景：调用 `setProperty("xxx", value)` 后 QSS 不会自动重新评估，
    必须走 unpolish/polish 流程才会触发 `[xxx="value"]` 选择器匹配。

    Args:
        widget: 任意 QWidget
    """
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()

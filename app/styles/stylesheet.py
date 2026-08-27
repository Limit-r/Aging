"""QSS 合并：把分块模板拼接为一份完整 stylesheet。

调用入口：`StylesheetBuilder.render(tokens)`。
"""

from app.core.tokens import DesignTokens
from app.styles import templates as T


class StylesheetBuilder:
    @staticmethod
    def render(tokens: DesignTokens) -> str:
        return "".join((
            T.main_window(tokens),
            T.title_bar(tokens),
            T.data_cell(tokens),
            T.header_bar(tokens),
            T.data_grid(tokens),
            T.data_point(tokens),
            T.button(tokens),
            T.vline(tokens),
            T.status_bar(tokens),
            T.right_panel(tokens),
            T.batch_section(tokens),
            T.countdown(tokens),
            T.current_page(tokens),
            T.video_page(tokens),
            T.nav_bar(tokens),
            T.floater(tokens),
            T.reset_view_button(tokens),
            T.led_dot(tokens),
            T.data_center(tokens),
            T.settings_page(tokens),
            T.detail_aging(tokens),
        ))


def build_stylesheet(tokens: DesignTokens) -> str:
    """便捷函数：默认用法。"""
    return StylesheetBuilder.render(tokens)

# -*- coding: utf-8 -*-
"""类别注册表（Phase A · 数据中心）。

统一管理 LED 检测任务的类别定义，替换散落在各脚本中的硬编码类别集合，
下游（标注器 / YOLO 数据准备 / 二分类数据准备）统一从这里取数，避免改类别时多点遗漏。

数据源：``datasets/categories.json``（见 CategoryRegistry 解析说明）。

对外统一入口：``load_categories()`` 返回一个 ``CategoryRegistry`` 实例，
其上提供各类派生 API（见类注释）。

设计要点：
- 纯标准库（json / pathlib），不依赖 torch / opencv，供懒加载与训练脚本共用。
- 数据源路径自动定位到 ``datasets/categories.json``，无需关心 cwd。
"""

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[0]
_DEFAULT_PATH = _PROJECT_ROOT / "datasets" / "categories.json"


class CategoryRegistry:
    """类别注册表：封装 categories.json 的解析与派生查询。

    categories.json 结构::

        {
          "series": ["FP"],
          "categories": [
            {"name": "FP_SIG_area", "kind": "area", "hl": false},
            {"name": "FP_VPL",      "kind": "led",  "hl": true}
          ]
        }

    - ``kind``: ``area``（区域大框）| ``led``（LED 点）
    - ``hl``:  该类别是否带亮/灭（H/L）属性。``hl=true`` 时：
      - VOC 原始标注会展开为 ``<name>_H`` / ``<name>_L`` 两类；
      - YOLO 5 类映射自动去掉 H/L 后缀；
      - TinyConv 二分类直接取 ``_H`` / ``_L`` 作为亮/灭标签。
    """

    def __init__(self, data: dict):
        self._series = list(data.get("series", []))
        self._categories = list(data.get("categories", []))
        self._by_name = {c["name"]: c for c in self._categories}

    # -- 基础信息 ----------------------------------------------------------
    @property
    def series(self) -> list:
        return list(self._series)

    @property
    def categories(self) -> list:
        """返回全部基础类别 dict 列表。"""
        return [dict(c) for c in self._categories]

    def category_names(self) -> list:
        """返回全部基础类别名（不带 H/L 后缀），标注器用。"""
        return [c["name"] for c in self._categories]

    def categories_for_series(self, series: str) -> list:
        """返回指定系列下的基础类别 dict 列表。

        系列匹配规则：类别名前缀与系列名一致（大小写不敏感），
        例如系列 ``FP`` 会命中 ``FP_VPL`` / ``FP_SIG_area`` 等。
        """
        prefix = (series or "").upper()
        if not prefix:
            return []
        return [dict(c) for c in self._categories
                if c["name"].upper().startswith(prefix + "_")]

    def category_names_for_series(self, series: str) -> list:
        """返回指定系列下的基础类别名（不带 H/L 后缀）列表。"""
        return [c["name"] for c in self.categories_for_series(series)]

    def annotation_names_for_series(self, series: str) -> list:
        """返回指定系列下的完整标注类别名列表（H/L 展开）。

        区分规则：
        - ``area`` 类别名不变；
        - ``led + hl=true`` 展开为 ``<name>_H`` 与 ``<name>_L`` 两个名称。
        标注界面用此列表即可在标注时直接区分 LED 亮/灭属性。
        """
        names = []
        for c in self.categories_for_series(series):
            if c["kind"] == "led" and c.get("hl", False):
                names.extend((c["name"] + "_H", c["name"] + "_L"))
            else:
                names.append(c["name"])
        return names

    # -- 派生：VOC 原始标注名（7 类化）-------------------------------------
    def annotation_names(self) -> list:
        """返回标注/读取 XML 时用到的完整类别名集合顺序列表。

        - ``area`` 类别名不变；
        - ``led + hl=true`` 展开为 ``<name>_H`` 与 ``<name>_L`` 两个名称。
        """
        names = []
        for c in self._categories:
            if c["kind"] == "led" and c.get("hl", False):
                names.extend((c["name"] + "_H", c["name"] + "_L"))
            else:
                names.append(c["name"])
        return names

    def annotation_name_set(self) -> set:
        return set(self.annotation_names())

    # -- 派生：YOLO 5 类（去 H/L）------------------------------------------
    def yolo_class_names(self) -> list:
        """返回 YOLO 训练用的类别名列表（等于基础类别名）。"""
        return self.category_names()

    def to_yolo_map(self) -> dict:
        """返回 7 类 → YOLO 类的映射 dict（仅 led+hl 类别参与映射）。"""
        mapping = {}
        for c in self._categories:
            if c["kind"] == "led" and c.get("hl", False):
                name = c["name"]
                mapping[name + "_H"] = name
                mapping[name + "_L"] = name
        return mapping

    # -- 派生：TinyConv H/L 二分类 ----------------------------------------
    def h_classes(self) -> set:
        return {c["name"] + "_H" for c in self._categories
                if c["kind"] == "led" and c.get("hl", False)}

    def l_classes(self) -> set:
        return {c["name"] + "_L" for c in self._categories
                if c["kind"] == "led" and c.get("hl", False)}


def load_categories(path=None) -> CategoryRegistry:
    """加载类别注册表。

    参数：
        path : 可选，categories.json 路径；缺省使用模块定位的默认路径。
    返回：
        CategoryRegistry 实例。
    抛出：
        FileNotFoundError / json.JSONDecodeError：数据源缺失或格式错误。
    """
    target = Path(path) if path else _DEFAULT_PATH
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    return CategoryRegistry(data)


# 模块内缓存：同一进程多次调用不重复读盘
_CACHE = {}


def get_registry(path=None) -> CategoryRegistry:
    """带缓存地加载类别注册表（推荐入口）。"""
    key = str(path) if path else str(_DEFAULT_PATH)
    if key not in _CACHE:
        _CACHE[key] = load_categories(path)
    return _CACHE[key]


def save_categories(registry: CategoryRegistry, path=None) -> None:
    """把注册表内容写回数据源文件，并刷新缓存。

    参数：
        registry : 待保存的 CategoryRegistry 实例。
        path     : 可选，categories.json 路径；缺省使用默认路径。
    返回：
        None。
    """
    target = Path(path) if path else _DEFAULT_PATH
    data = {
        "series": registry.series,
        "categories": registry.categories,
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 写回后刷新缓存，保证后续 get_registry 读到最新
    key = str(target)
    _CACHE.pop(key, None)


def _validate_name(name: str) -> str:
    """校验类别名合法性，返回去除首尾空白后的名字；非法抛 ValueError。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("类别名不能为空")
    if name.endswith("_H") or name.endswith("_L"):
        raise ValueError("类别名不能带 _H/_L 后缀：%r" % name)
    return name


def infer_series(name: str) -> str:
    """从类别名前缀推断所属系列（取第一个下划线前的部分）。"""
    return name.split("_", 1)[0]


def add_category(name: str, kind: str, hl: bool = False, path=None) -> bool:
    """新增一个类别并写回数据源。

    参数：
        name : 基础类别名（不带 _H/_L 后缀，如 ``FP_VPL``）。
        kind : ``area``（区域大框）| ``led``（LED 点）。
        hl   : 是否带亮/灭（H/L）属性；仅在 kind=='led' 时有意义。
        path : 可选，数据源路径；缺省使用默认路径。
    返回：
        True=新增成功；False=类别已存在（未做任何修改）。
    抛出：
        ValueError：名字非法或 kind 非法。
    """
    _validate_name(name)
    if kind not in ("area", "led"):
        raise ValueError("kind 必须是 'area' 或 'led'：%r" % kind)
    reg = get_registry(path)
    existing = {c["name"] for c in reg.categories}
    if name in existing:
        return False
    # 注意：categories 是只读 property（返回副本），须直接改内部 _categories
    reg._categories.append({"name": name, "kind": kind, "hl": bool(hl)})
    # 自动记录系列（若由此新类别引入新的前缀）
    series = infer_series(name)
    if series not in reg.series:
        reg.series.append(series)
    save_categories(reg, path)
    return True


def remove_category(name: str, path=None) -> bool:
    """删除一个类别并写回数据源。

    参数：
        name : 要删除的基础类别名。
        path : 可选，数据源路径；缺省使用默认路径。
    返回：
        True=删除成功；False=类别不存在（未做任何修改）。
    """
    reg = get_registry(path)
    before = len(reg.categories)
    reg._categories = [c for c in reg.categories if c["name"] != name]
    if len(reg.categories) == before:
        return False
    save_categories(reg, path)
    return True


if __name__ == "__main__":  # pragma: no cover - 命令行自检
    reg = get_registry()
    print("series     :", reg.series)
    print("categories :", reg.category_names())
    print("annotation :", reg.annotation_names())
    print("yolo       :", reg.yolo_class_names())
    print("to_yolo    :", reg.to_yolo_map())
    print("H classes  :", sorted(reg.h_classes()))
    print("L classes  :", sorted(reg.l_classes()))
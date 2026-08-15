# -*- coding: utf-8 -*-
"""数据标注 - 图片文件夹导入与 XML 映射。

数据中心「数据标注」页的第一步：导入一个图片文件夹，
并把每张图片与同名（不含扩展名）的 VOC XML 标注映射起来。

设计要点：
- 纯标准库实现（os / glob / xml.etree），不依赖 torch / opencv / openvino，
  保证懒加载时启动轻量。
- 系列目录约定（见 ANNOTATION_SCHEME.md）：
      <series>/JPEGImages/    图片（jpg / png / bmp）
      <series>/Annotations/   同名 XML 标注（优先）
      <series>/Annotations_5class/  5 类副本（回退）
  XML 目录缺省自动推断，也允许显式指定。
- 只读取、不修改任何已有数据，满足「不动已有旧数据」约束。

对外主入口：
    scan_image_folder(image_dir, xml_dir=None) -> list[ImageEntry]
"""

import os
import xml.etree.ElementTree as ET

# 支持的图片扩展名（小写比较）
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")

# 默认的 XML 兄弟目录名（按优先级）
_DEFAULT_XML_DIRS = ("Annotations", "Annotations_5class")


class ImageEntry:
    """单张图片及其同名 XML 标注的映射结果。

    属性：
        image_path : 图片绝对路径
        xml_path   : 同名 XML 绝对路径；无标注时为 None
        image_name : 图片文件名（含扩展名）
        stem       : 图片文件名（不含扩展名），即映射键
        series     : 所属系列目录名（如 "FP" / "A"），缺省推断失败时为 ""
    """

    __slots__ = ("image_path", "xml_path", "xml_dir", "_stem", "_series")

    def __init__(self, image_path: str, xml_path: str | None = None,
                 xml_dir: str | None = None):
        self.image_path = image_path
        self.xml_path = xml_path
        self.xml_dir = xml_dir
        base = os.path.basename(image_path)
        self._stem = os.path.splitext(base)[0]
        self._series = self._infer_series(image_path)

    @staticmethod
    def _infer_series(image_path: str) -> str:
        # 目录结构 <series>/JPEGImages/img.jpg -> 取 JPEGImages 的父目录名
        parent = os.path.dirname(image_path)
        if os.path.basename(parent).lower() in ("jpegimages", "images", "img"):
            return os.path.basename(os.path.dirname(parent))
        return ""

    @property
    def image_name(self) -> str:
        return os.path.basename(self.image_path)

    @property
    def stem(self) -> str:
        return self._stem

    @property
    def series(self) -> str:
        return self._series

    @property
    def has_xml(self) -> bool:
        return bool(self.xml_path) and os.path.isfile(self.xml_path)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return "<ImageEntry %s xml=%s>" % (self.image_name, "Y" if self.has_xml else "-")


def _resolve_xml_dir(image_dir: str, explicit: str | None = None) -> str | None:
    """确定 XML 目录。

    优先使用显式指定的 xml_dir；否则在 image_dir 的父目录下按默认名查找；
    若显式目录不存在返回其原值（让调用方决定是否报错），
    自动推断时找不到则返回 image_dir 自身（允许图片目录内就放同名 xml）。
    """
    if explicit:
        return explicit
    parent = os.path.dirname(image_dir)
    for name in _DEFAULT_XML_DIRS:
        cand = os.path.join(parent, name)
        if os.path.isdir(cand):
            return cand
    return image_dir


def scan_image_folder(image_dir: str, xml_dir: str | None = None) -> list[ImageEntry]:
    """扫描图片文件夹，返回与同名 XML 映射后的条目列表。

    参数：
        image_dir : 图片所在文件夹（如 <series>/JPEGImages/）
        xml_dir   : 可选，XML 标注目录；缺省自动推断兄弟 Annotations。

    返回：
        按文件名排序的 list[ImageEntry]。
        若 image_dir 不存在或不是目录，抛出 FileNotFoundError。
    """
    if not image_dir or not os.path.isdir(image_dir):
        raise FileNotFoundError("图片文件夹不存在: %s" % image_dir)

    xml_dir = _resolve_xml_dir(image_dir, xml_dir)

    entries: list[ImageEntry] = []
    for name in sorted(os.listdir(image_dir)):
        lower = name.lower()
        if not lower.endswith(_IMAGE_EXTS):
            continue
        stem = os.path.splitext(name)[0]
        xml_path = os.path.join(xml_dir, stem + ".xml")
        if not os.path.isfile(xml_path):
            xml_path = None
        entries.append(ImageEntry(
            os.path.join(image_dir, name), xml_path, xml_dir=xml_dir))
    return entries


def count_mapped(entries: list[ImageEntry]) -> int:
    """统计已有同名 XML 标注的图片数量。"""
    return sum(1 for e in entries if e.has_xml)


def parse_annotation(xml_path: str) -> dict:
    """解析一个 VOC XML 标注文件，返回结构化摘要。

    返回：
        {
            "filename": <filename 节点文本>,
            "width": int, "height": int,
            "objects": [{"name": str, "xmin": int, "ymin": int,
                         "xmax": int, "ymax": int, "difficult": int}, ...]
        }
    解析失败时抛 ET.ParseError（由调用方决定如何处理）。
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    def _text(tag: str) -> str:
        node = root.find(tag)
        return node.text if node is not None and node.text else ""

    size = root.find("size")
    width = int(size.find("width").text) if size is not None and size.find("width") is not None else 0
    height = int(size.find("height").text) if size is not None and size.find("height") is not None else 0

    objects = []
    for obj in root.iter("object"):
        name_node = obj.find("name")
        if name_node is None or not name_node.text:
            continue
        bb = obj.find("bndbox")
        if bb is None:
            continue
        try:
            x1 = int(float(bb.find("xmin").text))
            y1 = int(float(bb.find("ymin").text))
            x2 = int(float(bb.find("xmax").text))
            y2 = int(float(bb.find("ymax").text))
        except (TypeError, ValueError, AttributeError):
            continue
        diff = obj.find("difficult")
        difficult = int(diff.text) if diff is not None and diff.text else 0
        objects.append({
            "name": name_node.text,
            "xmin": x1, "ymin": y1, "xmax": x2, "ymax": y2,
            "difficult": difficult,
        })

    return {
        "filename": _text("filename"),
        "width": width,
        "height": height,
        "objects": objects,
    }


def write_annotation(xml_path: str, filename: str, width: int, height: int,
                     objects: list[dict]) -> None:
    """把结构化对象写入一个 VOC XML 文件。

    参数：
        xml_path : 目标 XML 绝对路径
        filename : <filename> 节点文本（通常是图片文件名）
        width/height : 图片尺寸
        objects : list[dict]，字段 name/xmin/ymin/xmax/ymax/difficult

    返回：
        None。写入失败抛 OSError（由调用方决定如何处理）。
    """
    root = ET.Element("annotation")
    ET.SubElement(root, "folder").text = ""
    ET.SubElement(root, "filename").text = filename
    ET.SubElement(root, "path").text = ""
    src = ET.SubElement(root, "source")
    ET.SubElement(src, "database").text = "Unknown"
    size = ET.SubElement(root, "size")
    ET.SubElement(size, "width").text = str(int(width))
    ET.SubElement(size, "height").text = str(int(height))
    ET.SubElement(size, "depth").text = "3"
    ET.SubElement(root, "segmented").text = "0"

    for o in objects:
        obj = ET.SubElement(root, "object")
        ET.SubElement(obj, "name").text = o["name"]
        ET.SubElement(obj, "pose").text = "Unspecified"
        ET.SubElement(obj, "truncated").text = "0"
        ET.SubElement(obj, "difficult").text = str(int(o.get("difficult", 0)))
        bb = ET.SubElement(obj, "bndbox")
        ET.SubElement(bb, "xmin").text = str(int(o["xmin"]))
        ET.SubElement(bb, "ymin").text = str(int(o["ymin"]))
        ET.SubElement(bb, "xmax").text = str(int(o["xmax"]))
        ET.SubElement(bb, "ymax").text = str(int(o["ymax"]))

    # 简单缩进：用 ElementTree 自带的递归方式
    _pretty(root, 0)
    tree = ET.ElementTree(root)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _pretty(elem, level: int) -> None:
    """给 XML 元素添加缩进（ElementTree 标准套路）。"""
    pad = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        for child in elem:
            _pretty(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = pad
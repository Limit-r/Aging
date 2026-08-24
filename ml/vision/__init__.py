"""视频视觉检测模块（v3.0 视频检测页）。

统一检测引擎 + 独立 worker 脚本，供 QProcess 以独立进程方式复用
`ml/deploy/` 中的 YOLO(9类) + TinyConv(亮灭) 模型。

设计约束：GUI 进程不 import 本模块（保持 Main.py 启动轻量）；
torch / cv2 / PIL 仅在 worker 子进程内加载。
"""
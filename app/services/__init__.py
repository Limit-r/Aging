"""app/services 包：跨 widget 的业务服务。

当前包含：
- CountdownService：每 cell 的倒计时（wall-clock），与详情页解耦
- AutoAgingDetector：按 CH 检测电流"空载→稳定有载"，自动判定老化开始
- AgingSettings：会话级老化倒计时全局时长（默认 2h，可改，不落盘）
- DeviceBinding：会话级设备绑定（摄像头 + 电流单元 3×2 分组，不落盘）
"""

# dataOCR
一个基于工业视觉检测OCR的系统

## 系统架构
<img width="1142" height="1130" alt="image" src="https://github.com/user-attachments/assets/2fcf9059-79ca-4f45-8d72-fce5bb508a1d" />

核心流水线：海康相机硬件触发采图 → 模板匹配滤空白 → ROI裁剪 → YOLOv8文本检测 → PPOCRv4文本识别 → 内容/倾斜/波浪验证 → GPIO脉冲剔除 → 带标注存图（NG）

前端页面通过pyqt制作,包括参数设置和运行展示。
核心包括4个线程，如上图所示，多线程并行运行以减少等待时间，满足实时检测需求。

## 技术栈
语言:Python3
GUI:PyQt5
AI加速:TPU
OCR引擎：PP-OCRv4 +YOLOv8
图像处理:OpenCV
相机:海康威视
部署平台:ARM+aarch64

代码需在Linux嵌入式设备上运行，故提供演示视频。

import threading
import queue
import time
import numpy as np
from Infer.ppocr_system_opencv import TextSystem
from image_capture.image_capture_thread import ImagePacket
from Infer.image_cropper import crop_image_v2
import logging
import cv2
from common.message import *
import os


# logger = logging.getLogger("OCRThread")
from logger import logger

class OCRThread(threading.Thread):
    """
    工业级 OCR 线程：
    - 从 image_queue 获取 ImagePacket
    - 根据配置裁剪 ROI（支持多 ROI）
    - 调用 TextSystem OCR
    - 将结果存入 ocr_result_queue（阻塞模式，确保不漏帧）
    - 状态回调上报每帧处理情况和异常
    """

    def __init__(self, config_manager, image_queue: queue.Queue,
                 ocr_result_queue: queue.Queue,
                 stop_event: threading.Event = None,
                 status_callback=None,
                 max_retry: int = 3):
        super().__init__(daemon=True)
        self.config_manager = config_manager
        self.image_queue = image_queue
        self.ocr_result_queue = ocr_result_queue
        self.stop_event = stop_event or threading.Event()
        self.infer_obj = TextSystem(self.config_manager.get_ocr_config())
        self.max_retry = max_retry

        # 统计信息
        self.total_frames = 0
        self.success_frames = 0
        self.fail_frames = 0

        # 状态回调
        self.status_callback = status_callback

    # TODO: move get_roi() to ROIProcessor after multi-ROI support
    def get_roi(self, src_img):
        """
        根据配置获取 ROI 裁剪结果

        Returns:
            cropped_img (np.ndarray): 裁剪后的图像
            roi_box (tuple): (x_min, y_min, x_max, y_max)
        """
        # -------- 从配置中解析 ROI --------
        roi_cfg = self.config_manager.get_config().get("roi", None)
        use_roi = (
                roi_cfg
                and roi_cfg.get("enable", False)
                and (
                        all(k in roi_cfg for k in ("x", "y", "width", "height"))  # 格式1: x,y,width,height
                        or all(k in roi_cfg for k in ("x1", "y1", "x2", "y2"))  # 格式2: x1,y1,x2,y2
                )
        )

        if use_roi:
            try:
                if "x" in roi_cfg and "y" in roi_cfg and "width" in roi_cfg and "height" in roi_cfg:
                    # 格式1: x,y,width,height → 计算 x_max, y_max
                    x_min = int(roi_cfg["x"])
                    y_min = int(roi_cfg["y"])
                    x_max = x_min + int(roi_cfg["width"])
                    y_max = y_min + int(roi_cfg["height"])
                elif "x1" in roi_cfg and "y1" in roi_cfg and "x2" in roi_cfg and "y2" in roi_cfg:
                    # 格式2: x1,y1,x2,y2 → 直接使用
                    x_min = int(roi_cfg["x1"])
                    y_min = int(roi_cfg["y1"])
                    x_max = int(roi_cfg["x2"])
                    y_max = int(roi_cfg["y2"])
                else:
                    raise ValueError("Invalid ROI format: must be either (x,y,width,height) or (x1,y1,x2,y2)")
            except Exception as e:
                logger.warning(f"[get_roi] invalid roi config: {roi_cfg}, err={e}")
                x_min = y_min = x_max = y_max = None
        else:
            x_min = y_min = x_max = y_max = None

        # -------- 边界收敛 --------
        h_img, w_img = src_img.shape[:2]

        if x_min is not None:
            x_min = max(0, min(x_min, w_img - 1))
            y_min = max(0, min(y_min, h_img - 1))
            x_max = max(x_min + 1, min(x_max, w_img))
            y_max = max(y_min + 1, min(y_max, h_img))

        # -------- 裁剪 --------
        try:
            if x_min is None:
                cropped_img, roi_box = crop_image_v2(src_img)
            else:
                cropped_img, roi_box = crop_image_v2(
                    src_img,
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max
                )
        except Exception as e:
            logger.warning(f"[get_roi] crop failed, fallback to full image: {e}")
            cropped_img = src_img
            roi_box = (0, 0, w_img - 1, h_img - 1)

        #     save_dir = "debug/defeat_cropped"
        #     os.makedirs(save_dir, exist_ok=True)
        #
        #     save_path = os.path.join(save_dir, f"defeat_cropped_{time.time()}.png")
        #
        #     cv2.imwrite(save_path, cropped_img)
        #
        #     print("裁剪失败，保存原图")
        #
        # save_dir = "debug/success_cropped"
        # os.makedirs(save_dir, exist_ok=True)
        #
        # save_path = os.path.join(save_dir, f"success_cropped_{time.time()}.png")
        #
        # cv2.imwrite(save_path, cropped_img)
        # print("裁剪成功，保存裁剪图")

        return cropped_img, roi_box

    def run(self):
        logger.info("[OCRThread] started")
        while not self.stop_event.is_set():
            try:
                packet: ImagePacket = self.image_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            self.total_frames += 1
            # self._report_status(packet.frame_id, status="ocr_start")
            try:
                image = packet.image
                src_img = image.copy()
                cropped_img, roi_box = self.get_roi(src_img)

                # -------- OCR 推理（单图）--------
                for attempt in range(1, self.max_retry + 1):
                    try:
                        results_list = self.infer_obj([cropped_img])
                        result = results_list[0]
                        break
                    except Exception as e:
                        logger.warning(f"OCR attempt {attempt} failed: {e}")
                        if attempt == self.max_retry:
                            raise
                        time.sleep(0.1)

                # -------- 结果回填--------
                packet.ocr_result = result
                self.success_frames += 1

                #---------------- 阻塞写入 OCR 结果队列 ----------------#
                while not self.stop_event.is_set():
                    try:
                        self.ocr_result_queue.put(packet, timeout=0.5)
                        break
                    except queue.Full:
                        logger.warning("[OCRThread] ocr_result_queue full, waiting...")

                # # 上报 OCR 成功
                # self._report_status(packet.frame_id, status="ocr_success", result=result)

            except Exception as e:

                self.fail_frames += 1
                packet.ocr_result = None
                report_status(self.status_callback, status_type="error", data={"msg": str(e)})
                logger.error(f"[OCRThread] OCR processing failed: {e}")

            finally:
                self.image_queue.task_done()
        logger.info(f"[OCRThread] stopped. Total={self.total_frames}, Success={self.success_frames}, Fail={self.fail_frames}")


# ----------------- 测试 main -----------------
def main():
    from config.config_manager import ConfigManager
    cfg = ConfigManager("config/config.json")
    # 读取配置
    ocr_config = cfg.get_ocr_config()

    image_queue = queue.Queue(maxsize=5)
    ocr_result_queue = queue.Queue(maxsize=5)
    stop_event = threading.Event()

    config_manager = cfg.get_config()

    # 创建 OCR 线程
    ocr_thread = OCRThread(
        ocr_config=ocr_config,
        config_manager=config_manager,
        image_queue=image_queue,
        ocr_result_queue=ocr_result_queue,
        stop_event=stop_event,
        status_callback=lambda msg: print("[STATUS]", msg),
        max_retry=2
    )

    ocr_thread.start()
    # ---------- 读取测试图片 ----------
    img = cv2.imread("test.jpg")
    if img is None:
        raise RuntimeError("failed to load test.jpg")

    # ---------- 构造 ImagePacket ----------
    packet = ImagePacket(
        image=img,
        frame_id=1,
        timestamp=int(time.time() * 1000)
    )

    print("[MAIN] put image packet")
    image_queue.put(packet)

    # ---------- 等待 OCR 结果 ----------
    try:
        result_packet = ocr_result_queue.get(timeout=10)
        print("\n========== OCR RESULT ==========")
        print(result_packet.ocr_result)
        print("================================\n")
    except queue.Empty:
        print("[MAIN] OCR timeout")

    # ---------- 退出 ----------
    stop_event.set()
    ocr_thread.join(timeout=2)
    print("[MAIN] OCRThread stopped")

if __name__ == "__main__":
    main()


'''
测试输出：
linaro@bm1684:/data/V2$ python3 Infer/ocr_thread.py
INFO:root:using model ./models/det/compilation.bmodel
[BMRT][bmcpu_setup:349] INFO:cpu_lib 'libcpuop.so' is loaded.
bmcpu init: skip cpu_user_defined
open usercpu.so, init user_cpu_init
[BMRT][load_bmodel:1079] INFO:Loading bmodel from [./models/det/compilation.bmodel]. Thanks for your patience...
[BMRT][load_bmodel:1023] INFO:pre net num: 0, load net num: 1
INFO:root:load bmodel success!
INFO:root:using model ./models/rec/compilation.bmodel
[BMRT][bmcpu_setup:349] INFO:cpu_lib 'libcpuop.so' is loaded.
bmcpu init: skip cpu_user_defined
open usercpu.so, init user_cpu_init
[BMRT][load_bmodel:1079] INFO:Loading bmodel from [./models/rec/compilation.bmodel]. Thanks for your patience...
[BMRT][load_bmodel:1023] INFO:pre net num: 0, load net num: 1
INFO:root:load bmodel success!
INFO:OCRThread:[OCRThread] started
Open /dev/jpu successfully, device index = 0, jpu fd = 31, vpp fd = 32
[MAIN] put image packet

========== OCR RESULT ==========
{'dt_boxes': [array([[143.,  64.],
       [632.,  76.],
       [631., 129.],
       [141., 117.]], dtype=float32), array([[ 658.,   94.],
       [1088.,  111.],
       [1085.,  183.],
       [ 655.,  166.]], dtype=float32), array([[270., 125.],
       [517., 133.],
       [515., 188.],
       [268., 180.]], dtype=float32)], 'text': ['Y2026/01/28H', '广东美宜佳渠道', '016550'], 'score': [0.99340177, 0.98140854, 0.99777794]}
================================

INFO:OCRThread:[OCRThread] stopped. Total=1, Success=1, Fail=0
[MAIN] OCRThread stopped

'''
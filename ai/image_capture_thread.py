# image_capture_thread.py

import threading
import queue
import time
import numpy as np
import cv2
from image_capture.camera import HikCamera, CaptureMode
from common.message import *
from logger import logger
from image_capture.template import TemplateMatcher

class ImagePacket:
    """
    每帧图像数据包
    """
    def __init__(self, image: np.ndarray, frame_id: int, timestamp: int):
        self.image = image                # RGB 图像
        self.frame_id = frame_id          # 帧 ID
        self.timestamp = timestamp        # 毫秒时间戳(取图时间)
        self.ocr_result = None
        self.verify_code = None
        self.verify_msg = False
        self.verify_timestamp = False
        self.is_work = False

class ImageCaptureThread(threading.Thread):
    """
    工业级取图线程
      - 队列阻塞保证无帧丢失
      - 异常自动重连
      - 状态通过回调上报
      - 帧率统计
    """
    def __init__(self, config_manager,camera,pause_event,
                 image_queue: queue.Queue,
                 status_callback=None,
                 reconnect_interval=1.0,
                 max_reconnect_attempts=5):
        super().__init__(daemon=True)
        self.config_manager = config_manager
        self.camera = camera
        self.image_queue = image_queue
        self.status_callback = status_callback
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.pause_event = pause_event

        self._exit_event = threading.Event()
        self.frame_id = 0
        self._last_fps_time = time.time()
        self._frame_counter = 0

        # 用来过滤空图像（喷码机没有工作的情况
        self._filter = None
        self._last_filter_cfg = None
        self._last_filter_check = 0
        self._filter_check_interval = 1.0

    def _get_cfg(self):
        try:
            return self.config_manager.get_config() or {}
        except Exception:
            return {}

    def _update_filter_if_needed(self):
        now = time.time()
        if now - self._last_filter_check < self._filter_check_interval:
            return

        self._last_filter_check = now

        cfg = self._get_cfg()
        filter_cfg = cfg.get("filter_image", {}) or {}

        if filter_cfg == self._last_filter_cfg:
            return

        self._last_filter_cfg = filter_cfg

        try:
            self._filter = TemplateMatcher(
                template_dir=filter_cfg.get("template_dir"),
                img_size=(720, 540),
                method=filter_cfg.get("method"),
                threshold=filter_cfg.get("threshold")
            )
            logger.info("[ImageCaptureThread] filter updated")
        except Exception as e:
            logger.warning(f"filter init failed: {e}")
            self._filter = None

    def run(self):
        # self._report_status(msg="ImageCaptureThread started", level="info")
        logger.info("[ImageCaptureThread] started")
        while not self._exit_event.is_set() :
            self.pause_event.wait()  #  暂停！
            try:
                self._update_filter_if_needed()
                # 1.获取帧（阻塞模式）
                cfg = self._get_cfg()
                timeout_ms = cfg.get("camera", {}).get("timeout_ms", 1000)
                frame = self.camera.get_frame(timeout_ms=timeout_ms)
                # 2.图像处理
                src_img = cv2.rotate(frame, cv2.ROTATE_180)

                # 3.过滤（热更新）
                if self._filter:
                    if self._filter.predict(src_img, 1) != "unknown":
                        print("检测到空白图像，跳过")
                        continue

                # 4.打包
                timestamp = int(time.time() * 1000)
                packet = ImagePacket(
                    image=src_img,  # numpy.ndarray
                    frame_id=self.frame_id,
                    timestamp=timestamp
                )
                # print("时间戳为：",timestamp)
                self.frame_id += 1

                # 5.入队
                # 队列阻塞入队，保证无帧丢失
                while not self._exit_event.is_set():
                    try:
                        self.image_queue.put(packet, timeout=0.5)
                        break
                    except queue.Full:
                        # self._report_status(error="image_queue full, waiting...", level="error")
                        continue

                # 6. FPS统计
                self._frame_counter += 1
                now = time.time()
                if now - self._last_fps_time >= 1.0:
                    fps = self._frame_counter / (now - self._last_fps_time)
                    # self._report_status(msg=f"FPS: {fps:.1f}", level="info")
                    self._frame_counter = 0
                    self._last_fps_time = now

            except Exception as e:
                # 异常处理 + 自动重连
                if "0x80000007" in str(e):
                    # 硬件触发下的正常超时，直接 continue
                    # print("等待触发")
                    continue
                report_status(self.status_callback, msg_type="error", source="ImageCaptureThread",
                                    data={"msg": str(e)}
                                    )

                reconnect_attempts = 0
                while reconnect_attempts < self.max_reconnect_attempts and not self._exit_event.is_set():
                    try:
                        self.camera.reconnect()
                        # self._report_status(msg="Camera reconnected", level="reconnect")
                        break
                    except Exception as re:
                        reconnect_attempts += 1
                        report_status(self.status_callback,msg_type="error", source="ImageCaptureThread",
                                            data={"msg": f"Camera reconnect failed", "camera_id": 0}
                                            )
                        time.sleep(self.reconnect_interval)
                else:
                    time.sleep(self.reconnect_interval)

        logger.info("[ImageCaptureThread] stopped")

    def stop(self):
        """安全停止线程"""
        self._exit_event.set()


def main():

    cam = HikCamera(device_index=0)
    if not cam.open():
        print("相机打开失败")
        return

    cam.set_acquisition_mode(CaptureMode.CONTINUOUS)
    cam.start_grabbing()
    print("相机开始抓图...")

    # ---------------- 2.创建图像队列 ----------------
    image_queue = queue.Queue(maxsize=10)

    # ---------------- 3.状态回调 ----------------
    def status_callback(status):
        level = status.get("level") or status.get("msg_type", "info")

        message = status.get("message") or status.get("data", {}).get("msg", "")
        error = status.get("error", False)

        print(f"[Status] {level} | {message} | error={error}")

    # ---------------- 4.启动取图线程 ----------------
    capture_thread = ImageCaptureThread(
        camera=cam,
        image_queue=image_queue,
        timeout_ms=1000,
        status_callback=status_callback,
        reconnect_interval=1.0,
        max_reconnect_attempts=5
    )
    capture_thread.start()

    # ---------------- 5.主循环：消费队列帧并显示 ----------------
    try:
        frame_count = 0
        while True:
            if not image_queue.empty():
                packet = image_queue.get()
                # 显示 RGB 图像

                if frame_count < 20:
                    cv2.imwrite(f"thread_hard_test_frame_{frame_count}.png", packet.image)
                    frame_count += 1

                if frame_count == 20:
                    print("取图完毕")
                    break



    finally:
        # ---------------- 6.安全退出 ----------------
        capture_thread.stop()
        capture_thread.join()
        cam.close()

        print("取图线程测试结束")


if __name__ == "__main__":
    main()

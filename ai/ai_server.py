# ai_server.py

import threading
import queue
import traceback
import time

from config.config_manager import ConfigManager
from image_capture.image_capture_thread import ImageCaptureThread
from image_capture.folder_image_thread import FolderImageCaptureThread
from Infer.ocr_thread import OCRThread
from post_process.post_process_thread import PostProcessThread
from post_process.save_image_thread import SaveImageThread
from post_process.ocr_validator import OCRValidator
from post_process.GPIOHandler import GPIOHandler
from image_capture.camera import CaptureMode
from common.message import report_status
from state import SystemStats
from GPIO.plc_gpio import InkjetRejectController
from GPIO.alarm_gpio import AlarmLightGPIOHandler


class AIServer:
    """
    AI Server 主控制器
    统一管理：
      - 相机（硬件触发）
      - 取图线程
      - OCR 线程
      - 后处理线程
      - 存图线程

    配置热更新策略：
      - AIServer 不缓存线程所需的配置快照
      - 直接把 config_manager 引用传给各线程
      - 各线程内部按需读取最新配置
    """

    def __init__(self, camera, config_manager: ConfigManager, status_callback=None):
        self.camera = camera
        self.config_manager = config_manager
        self.status_callback = status_callback

        self.running = False
        self.stop_event = threading.Event()

        # 暂停控制，不终止线程，避免慢启动
        self.pause_event = threading.Event()
        self.pause_event.set()  # 默认是运行状态

        # ---------------- 队列 ----------------
        self.image_queue = queue.Queue(maxsize=20)
        self.postprocess_queue = queue.Queue(maxsize=20)
        self.save_queue = queue.Queue(maxsize=50)

        # ---------------- 系统状态 ----------------
        self.system_stats = SystemStats()

        # ---------------- Validator ----------------
        self.validator = OCRValidator(self.config_manager)

        # ---------------- 线程实例 ----------------
        # 注意：这里传入的是 config_manager，而不是 config 快照
        input_cfg = self.config_manager.get_config().get("input_source", {}) or {}
        source_type = input_cfg.get("type", "camera")

        if source_type == "folder":
            self.grab_thread = FolderImageCaptureThread(
                config_manager=self.config_manager,
                pause_event=self.pause_event,
                image_queue=self.image_queue,
                status_callback=self.status_callback
            )
        else:
            self.grab_thread = ImageCaptureThread(
                config_manager=self.config_manager,
                camera=self.camera,
                pause_event=self.pause_event,
                image_queue=self.image_queue,
                status_callback=self.status_callback
            )

        self.source_type = source_type

        self.ocr_thread = OCRThread(
            config_manager=self.config_manager,
            image_queue=self.image_queue,
            ocr_result_queue=self.postprocess_queue,
            stop_event=self.stop_event,
            status_callback=self.status_callback,
            max_retry=3
        )

        self.post_thread = PostProcessThread(
            system_stats=self.system_stats,
            config_manager=self.config_manager,
            postprocess_queue=self.postprocess_queue,
            save_queue=self.save_queue,
            validator=self.validator,
            status_callback=self.status_callback,
            stop_event=self.stop_event
        )

        self.save_thread = SaveImageThread(
            system_stats=self.system_stats,
            config_manager=self.config_manager,
            save_queue=self.save_queue,
            stop_event=self.stop_event,
            status_callback=self.status_callback
        )

        self.threads = [
            ("GrabThread", self.grab_thread),
            ("OCRThread", self.ocr_thread),
            ("PostProcessThread", self.post_thread),
            ("SaveThread", self.save_thread),
        ]

    # ==========================================================
    # 启动
    # ==========================================================

    def start(self):
        if self.running:
            return True, None

        self.running = True
        self.stop_event.clear()

        try:
            current_cfg = self.config_manager.get_config() or {}
            camera_cfg = current_cfg.get("camera", {}) or {}

            if self.source_type == "camera":
                # -------- 相机初始化（从当前配置读取）--------
                if not self.camera.open():
                    raise RuntimeError("Camera open failed")

                # 触发模式
                trigger_mode = str(camera_cfg.get("trigger_mode", "hardware")).lower()
                trigger_source = camera_cfg.get("trigger_source", "line0")

                if trigger_mode == "hardware":
                    self.camera.set_acquisition_mode(
                        CaptureMode.HARDWARE,
                        trigger_source=trigger_source
                    )
                elif trigger_mode == "software":
                    self.camera.set_acquisition_mode(CaptureMode.SOFTWARE)
                else:
                    self.camera.set_acquisition_mode(CaptureMode.CONTINUOUS)

                # 相机参数
                self.camera.set_camera_params(
                    exposure=camera_cfg.get("exposure_us"),
                    gain=camera_cfg.get("gain"),
                    frame_rate=camera_cfg.get("frame_rate_limit")
                )

                self.camera.start_grabbing()

                report_status(
                    self.status_callback,
                    "system_recover",
                    "AIServer",
                    {"message": f"Camera started in {trigger_mode.upper()} trigger mode"}
                )

            # -------- 启动线程 --------
            for name, thread in self.threads:
                self._safe_start_thread(name, thread)

            report_status(
                self.status_callback,
                "system_recover",
                "AIServer",
                {"message": "AI Server started"}
            )

            return True, None

        except Exception as e:
            report_status(
                self.status_callback,
                "system_error",
                "AIServer",
                {"message": str(e)}
            )
            self.stop()
            return False, str(e)

    def _safe_start_thread(self, name, thread):
        orig_run = thread.run

        def run_wrapper():
            try:
                orig_run()
            except Exception as e:
                report_status(
                    self.status_callback,
                    "system_error",
                    name,
                    {"message": f"{e}\n{traceback.format_exc()}"}
                )

        thread.run = run_wrapper
        thread.start()

    # ==========================================================
    # 停止
    # ==========================================================
    def stop(self):
        if not self.running:
            return True, None

        self.running = False
        self.stop_event.set()

        # 1️⃣ 停止取图线程
        try:
            self.grab_thread.stop()
        except Exception:
            pass

        # 2️⃣ 等线程退出
        for _, thread in self.threads:
            try:
                thread.join(timeout=2)
            except Exception:
                pass

        # 3️⃣ 停止并关闭相机
        if self.source_type == "camera":
            try:
                self.camera.close()
            except Exception:
                pass

        report_status(
            self.status_callback,
            "system_recover",
            "AIServer",
            {"message": "AI Server stopped"}
        )
        return True, None

    # ==========================================================
    # 暂停/恢复
    # ==========================================================
    def pause(self):
        if not self.running:
            return False, "not running"

        self.pause_event.clear()
        # 等待队列处理完
        while not self.image_queue.empty() or not self.postprocess_queue.empty():
            time.sleep(0.05)
        return True, None

    def resume(self):
        if not self.running:
            return False, "not running"

        self.pause_event.set()
        return True, None
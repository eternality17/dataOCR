import threading
import queue
import time
import logging
from state import SystemStats
from common.message import *

# logger = logging.getLogger("PostProcessThread")
from logger import logger

class PostProcessThread(threading.Thread):
    """
    工业级后处理线程（最终版）：
    - 从 postprocess_queue 获取 ImagePacket
    - 调用 OCRValidator 校验
    - GPIO 控制
    - 错误状态回调（仅在NG或异常时触发）
    - 放入 save_queue，由存图线程决定保存策略
    """

    def __init__(
        self,
        system_stats: SystemStats,
        config_manager,
        postprocess_queue: queue.Queue,
        save_queue: queue.Queue,
        validator,
        status_callback=None,
        stop_event=None
    ):
        super().__init__(daemon=True)
        self.config_manager = config_manager
        self.queue = postprocess_queue
        self.save_queue = save_queue
        self.validator = validator
        self.status_callback = status_callback
        self.stop_event = stop_event or threading.Event()

        self._gpio_plc = None
        self._gpio_alarm = None

        self._last_gpio_cfg = None
        self._last_gpio_check = 0
        self._gpio_check_interval = 1.0  # 秒

        # 统计信息
        self.total_frames = 0
        self.success_frames = 0
        self.fail_frames = 0

        self.system_stats = system_stats

    def _get_cfg(self):
        try:
            return self.config_manager.get_config() or {}
        except Exception:
            return {}

    # GPIO 热更新函数
    def _update_gpio_if_needed(self):
        now = time.time()
        if now - self._last_gpio_check < self._gpio_check_interval:
            return

        self._last_gpio_check = now

        cfg = self._get_cfg()
        gpio_cfg = cfg.get("gpio", {}) or {}

        # 如果配置没变化，不重建
        if gpio_cfg == self._last_gpio_cfg:
            return

        logger.info("[PostProcessThread] GPIO config changed, rebuilding...")

        self._last_gpio_cfg = gpio_cfg

        # 延迟 import，避免循环依赖
        from GPIO.plc_gpio import InkjetRejectController
        from GPIO.alarm_gpio import AlarmLightGPIOHandler

        # -------- PLC --------
        plc_cfg = gpio_cfg.get("gpio_plc", {}) or {}
        if plc_cfg.get("enable"):
            try:
                self._gpio_plc = InkjetRejectController.from_config(gpio_cfg)
            except Exception as e:
                logger.warning(f"PLC init failed: {e}")
                self._gpio_plc = None
        else:
            self._gpio_plc = None

        # -------- Alarm --------
        alarm_cfg = gpio_cfg.get("gpio_alarm", {}) or {}
        if alarm_cfg.get("enable"):
            try:
                self._gpio_alarm = AlarmLightGPIOHandler(alarm_cfg.get("gpio_path"))
            except Exception as e:
                logger.warning(f"Alarm init failed: {e}")
                self._gpio_alarm = None
        else:
            self._gpio_alarm = None

    def run(self):
        logger.info("[PostProcessThread] started")
        while not self.stop_event.is_set():
            try:
                image_packet = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            self.total_frames += 1
            try:
                self._process(image_packet)
                # print("post_process:    ",self._get_cfg().get("gpio"))
                self.success_frames += 1
            except Exception as e:
                self.fail_frames += 1
                logger.exception("[PostProcessThread] processing exception")
                # 异常回调
                report_status(self.status_callback, msg_type="error", source="postprocess Thread",
                              data={"msg": str(e)}
                              )
            finally:
                self.queue.task_done()

        logger.info(
            f"[PostProcessThread] stopped. "
            f"Total={self.total_frames}, "
            f"Success={self.success_frames}, "
            f"Fail={self.fail_frames}"
        )

    def _process(self, image_packet):
        """
        处理单帧图像：
        1. 校验
        2. GPIO控制
        3. 错误回调
        4. 放入存图队列（阻塞）
        """
        # 调用校验器
        code, msg = self.validator.validate(image_packet)
        self.system_stats.update_by_code(code)

        # 写入校验结果
        image_packet.verify_code = code
        image_packet.verify_msg = msg
        image_packet.verify_timestamp = int(time.time() * 1000)

        # GPIO控制
        self._handle_gpio(code)

        # 放入存图队列，由存图线程决定保存策略
        while not self.stop_event.is_set():
            try:
                self.save_queue.put(image_packet, timeout=0.5)
                break
            except queue.Full:
                logger.warning("[PostProcessThread] save_queue full, waiting...")

    # ---------------- GPIO控制 ----------------
    def _handle_gpio(self, code: int):
        # 每次处理前检查配置（低频）
        self._update_gpio_if_needed()

        if not self._gpio_plc and not self._gpio_alarm:
            return

        # 报警灯
        if self._gpio_alarm:
            try:
                self._gpio_alarm.handle_result(code)
            except Exception as e:
                logger.warning(f"[PostProcessThread] alarm gpio error: {e}")

        try:
            if code != 0:  # NG
                if self._gpio_plc:
                    self._gpio_plc.reject_once()
        except Exception as e:
            logger.warning(f"[PostProcessThread] PLC gpio error: {e}")


# ----------------- 测试 main -----------------

class ImagePacket:
    def __init__(self, frame_id, ocr_result):
        self.frame_id = frame_id
        self.ocr_result = ocr_result

        # 后处理线程写入
        self.verify_code = None
        self.verify_msg = None
        self.verify_timestamp = None

class FakeGPIOHandler:
    def turn_off_alarm(self):
        print("[GPIO] Alarm OFF")

    def trigger_alarm(self, duration=2.0):
        print(f"[GPIO] Alarm ON for {duration}s")



def main():
    # ---------------- 队列 ----------------
    postprocess_queue = queue.Queue(maxsize=5)
    save_queue = queue.Queue(maxsize=5)

    from config.config_manager import ConfigManager
    from post_process.ocr_validator import OCRValidator
    cfg = ConfigManager("config/config.json")

    from state import SystemStats
    # ---------------- Mock 对象 ----------------
    stats = SystemStats()
    config_manager = cfg.get_config()
    validator = OCRValidator(config_manager)
    gpio_handler = FakeGPIOHandler()

    def status_callback(**kwargs):
        print("[STATUS CALLBACK]", kwargs)

    # ---------------- 启动线程 ----------------
    thread = PostProcessThread(
        system_stats=stats,
        config_manager=config_manager,
        postprocess_queue=postprocess_queue,
        save_queue=save_queue,
        validator=validator,
        status_callback=status_callback,
        gpio_handler=gpio_handler
    )
    thread.start()

    # ---------------- 构造测试数据 ----------------
    packets = [
        ImagePacket(
            frame_id=1,
            ocr_result={"text": ["ABC123"], "dt_boxes": []}
        ),
        ImagePacket(
            frame_id=2,
            ocr_result={"text": ["NG_CODE"], "dt_boxes": []}
        ),
        ImagePacket(
            frame_id=3,
            ocr_result={"text": ["ABC123"], "dt_boxes": []}
        ),
    ]

    for p in packets:
        print(f"[MAIN] put frame {p.frame_id}")
        postprocess_queue.put(p)

    # 等待处理完成
    time.sleep(1)

    # ---------------- 停止线程 ----------------
    thread.stop_event.set()
    thread.join(timeout=2)

    # ---------------- 查看 save_queue ----------------
    print("\n====== SAVE QUEUE RESULT ======")
    while not save_queue.empty():
        pkt = save_queue.get()
        print(
            f"Frame={pkt.frame_id}, "
            f"Code={pkt.verify_code}, "
            f"Msg={pkt.verify_msg}, "
            f"Time={pkt.verify_timestamp}"
        )

    print("\n====== SYSTEM STATS ======")
    print(stats.snapshot())


if __name__ == "__main__":
    main()

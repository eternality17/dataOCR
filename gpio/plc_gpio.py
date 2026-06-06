import threading
import os
import time

class InkjetRejectController:
    """
    喷码硬触发检测专用剔除控制器

    工作模型：
        每次图像触发 = 一个袋子
        AI检测NG → 输出0脉冲 → 松夹

    逻辑：
        1 = 正常
        0 = NG触发
    """

    def __init__(
        self,
        gpio_path: str,
        pulse_width: float = 0.08,
        min_trigger_interval: float = 0.15,
        active_level: int = 0
    ):
        self.gpio_path = gpio_path
        self.pulse_width = pulse_width
        self.min_trigger_interval = min_trigger_interval
        self.active_level = active_level
        self.inactive_level = 1 if active_level == 0 else 0

        self._lock = threading.Lock()
        self._pulse_timer = None
        self._last_trigger_time = 0

        self._ensure_gpio_accessible()
        self._open_gpio()
        self._write_gpio(self.inactive_level)

    # ---------------- 内部方法 ----------------
    def _ensure_gpio_accessible(self):
        if not os.path.exists(self.gpio_path):
            raise FileNotFoundError(f"GPIO路径不存在: {self.gpio_path}")

    def _open_gpio(self):
        self._gpio_fd = open(self.gpio_path, "w")

    def _write_gpio(self, value: int):
        self._gpio_fd.seek(0)
        self._gpio_fd.write(str(value))
        self._gpio_fd.flush()
        print(f"[Inkjet Reject] GPIO={value}")

    def reject_once(self):
        """触发NG脉冲"""
        with self._lock:
            now = time.time()
            if now - self._last_trigger_time < self.min_trigger_interval:
                return
            if self._pulse_timer is not None:
                return
            self._last_trigger_time = now
            self._write_gpio(self.active_level)
            self._pulse_timer = threading.Timer(self.pulse_width, self._end_pulse)
            self._pulse_timer.start()

    def _end_pulse(self):
        with self._lock:
            self._write_gpio(self.inactive_level)
            self._pulse_timer = None

    def close(self):
        with self._lock:
            if self._pulse_timer:
                self._pulse_timer.cancel()
            self._write_gpio(self.inactive_level)
            self._gpio_fd.close()

    # ---------------- 类方法 ----------------
    @classmethod
    def from_config(cls, gpio_cfg):
        """
        从配置字典或ConfigManager实例创建实例

        支持配置结构：
        {
           "gpio": {
    "enable": true,
    "gpio_alarm": {
      "enable": true,
      "gpio_path": "/sys/class/leds/gpio6/brightness",
      "active_level": 1,
      "auto_off_time": 3
    },
    "gpio_plc": {
      "enable": true,
      "gpio_path": "/sys/class/leds/gpio5/brightness",
      "active_level": 0,
      "mode": "pulse",
      "pulse_width_ms": 20,
      "min_interval_ms": 50
    }
        }
        """

        if not gpio_cfg.get("enable", False):
            raise ValueError("GPIO功能未启用")

        plc_cfg = gpio_cfg.get("gpio_plc", {})
        gpio_path = plc_cfg.get("gpio_path")
        if gpio_path is None:
            raise ValueError("PLC未配置 gpio_path")

        active_level = plc_cfg.get("active_level", 0)
        pulse_width = plc_cfg.get("pulse_width_ms", 20) / 1000.0  # ms → 秒
        min_trigger_interval = plc_cfg.get("min_interval_ms", 50) / 1000.0  # ms → 秒

        return cls(
            gpio_path=gpio_path,
            pulse_width=pulse_width,
            min_trigger_interval=min_trigger_interval,
            active_level=active_level
        )


if __name__ == "__main__":
    import sys
    import time
    import json

    # ⚠ 修改为你的真实 GPIO 路径
    GPIO_PATH = "/sys/class/leds/gpio5/brightness"

    # 模拟配置
    test_config = {
        "gpio": {
            "enable": True,
            "gpio_path": GPIO_PATH,
            "active_level": 0,          # NG 输出0
            "pulse_width_ms": 80,       # 80ms 脉冲
            "min_interval_ms": 150      # 150ms 最小间隔
        }
    }

    try:
        controller = InkjetRejectController.from_config(test_config)
    except Exception as e:
        print(f"初始化失败: {e}")
        sys.exit(1)

    print("=== PLC 剔除控制测试程序 ===")
    print("命令说明：")
    print("  ng      → 单次剔除脉冲")
    print("  fast    → 快速连续触发测试")
    print("  auto    → 自动生产线模拟")
    print("  interval→ 测试最小触发间隔保护")
    print("  exit    → 退出")
    print("----------------------------------")

    try:
        while True:
            cmd = input("请输入指令: ").strip().lower()

            if cmd == "ng":
                print("手动触发一次剔除")
                controller.reject_once()

            elif cmd == "fast":
                print("快速连续触发 10 次")
                for i in range(10):
                    controller.reject_once()
                    time.sleep(0.02)  # 20ms 间隔
                print("测试完成")

            elif cmd == "interval":
                print("测试最小间隔保护")
                controller.reject_once()
                time.sleep(0.05)  # 小于150ms
                controller.reject_once()
                print("第二次触发应被忽略")

            elif cmd == "auto":
                print("模拟生产线（每0.3秒一袋，共20袋）")
                for i in range(20):
                    print(f"袋子 {i+1}")
                    controller.reject_once()
                    time.sleep(0.3)
                print("模拟完成")

            elif cmd == "exit":
                print("退出程序")
                break

            else:
                print("未知指令")

    except KeyboardInterrupt:
        print("\n收到 Ctrl+C")

    finally:
        controller.close()
        print("GPIO 已安全关闭")


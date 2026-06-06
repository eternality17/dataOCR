import json
import copy
import threading
import os

from types import SimpleNamespace
from logger import logger

class ConfigError(Exception):
    pass

class ConfigManager:
    """
    工业级单例配置管理器
    - 单例模式
    - 强校验
    - 原子替换
    - 支持局部更新
    """

    _instance = None
    _lock_instance = threading.Lock()  # 确保多线程下只创建一个实例

    def __new__(cls, config_path="./config.json"):
        with cls._lock_instance:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path="./config.json"):
        # 避免多次初始化
        if getattr(self, "_initialized", False):
            return

        self.config_path = config_path
        self._lock = threading.RLock()  # 线程安全锁
        self._config = None

        self._load_from_file()
        self._initialized = True

        self._last_mtime = None

    # ===============================
    # 对外接口
    # ===============================

    def _get_file_mtime(self):
        try:
            return os.path.getmtime(self.config_path)
        except OSError:
            return None

    def get_config(self):
        with self._lock:
            current_mtime = self._get_file_mtime()
            if current_mtime != self._last_mtime:
                # 文件被修改，重新加载
                self._load_from_file()
                self._last_mtime = current_mtime
            return copy.deepcopy(self._config)   # 深拷贝防止外部修改

    def get_ocr_config(self):
        """
        获取 OCR 模块配置，返回支持属性访问的对象（只读语义）
        返回配置中的所有 OCR 字段
        """
        with self._lock:
            ocr = self._config.get("ocr")
            if ocr is None:
                raise ConfigError("ocr config not found")

            # 返回所有 OCR 配置字段
            return SimpleNamespace(**copy.deepcopy(ocr))


    def update(self, new_data: dict):
        """
        更新配置（局部或完整配置），原子替换
        :param new_data: dict
        :return: (True, None) or (False, error_message)
        """
        try:
            merged = self._merge_config(self._config, new_data)
            self._validate(merged)

            with self._lock:
                self._config = merged
                self._save_to_file(self._config)

            logger.debug("config saved to config.json")

            return True, None
        except ConfigError as e:
            return False, str(e)
        except Exception as e:
            return False, f"unexpected error: {e}"


    # ===============================
    # 内部方法
    # ===============================

    def _load_from_file(self):
        if not os.path.exists(self.config_path):
            raise ConfigError(f"config file not found: {self.config_path}")

        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            raise RuntimeError(f"Config load failed: {e}")

        self._validate(config)
        self._config = config

    def _save_to_file(self, config: dict):
        tmp_path = self.config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.config_path)

    def _merge_config(self, old: dict, new: dict):
        """深度合并 new 覆盖 old"""
        merged = copy.deepcopy(old)

        def _merge(dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    _merge(dst[k], v)
                else:
                    dst[k] = v

        _merge(merged, new)
        return merged

    # ===============================
    # 校验逻辑（保持和之前一致）
    # ===============================

    def _validate(self, cfg: dict):
        self._require(cfg, "config_version", str)
        self._validate_ocr(cfg.get("ocr"))
        self._validate_roi(cfg.get("roi"))
        self._validate_code_rule(cfg.get("validator"))
        self._validate_save_image(cfg.get("image_save"), "image_save")
        self._validate_gpio(cfg.get("gpio"))
        self._validate_camera(cfg.get("camera"))
        self._validate_runtime(cfg.get("runtime"))
        self._validate_logging(cfg.get("logging"))

    def _require(self, obj, key, typ):
        if obj is None or key not in obj:
            raise ConfigError(f"missing required field: {key}")
        if not isinstance(obj[key], typ):
            raise ConfigError(f"{key} must be {typ}")

    def _range(self, val, min_v, max_v, name):
        if not (min_v <= val <= max_v):
            raise ConfigError(f"{name} out of range [{min_v}, {max_v}]")

    # ---------- 各模块校验 ----------


    def _validate_ocr(self, ocr):
        self._require(ocr, "enable", bool)
        self._require(ocr, "bmodel_det", str)
        self._require(ocr, "bmodel_rec", str)
        self._require(ocr, "rec_thresh", (int, float))
        self._range(ocr["rec_thresh"], 0.0, 1.0, "ocr.rec_thresh")

    def _validate_roi(self, roi):
        """
        校验 ROI 配置，支持两种格式：
        1. x,y,width,height
        2. x1,y1,x2,y2
        """
        self._require(roi, "enable", bool)
        if not roi["enable"]:
            return

        # 检查格式1: x,y,width,height
        if all(k in roi for k in ("x", "y", "width", "height")):
            for k in ["x", "y", "width", "height"]:
                self._require(roi, k, int)
                if roi[k] <= 0:
                    raise ConfigError(f"roi.{k} must be > 0")

        # 检查格式2: x1,y1,x2,y2
        elif all(k in roi for k in ("x1", "y1", "x2", "y2")):
            for k in ["x1", "y1", "x2", "y2"]:
                self._require(roi, k, int)
                if roi[k] < 0:
                    raise ConfigError(f"roi.{k} must be >= 0")

            if roi["x2"] <= roi["x1"]:
                raise ConfigError("roi.x2 must be > roi.x1")
            if roi["y2"] <= roi["y1"]:
                raise ConfigError("roi.y2 must be > roi.y1")

        else:
            raise ConfigError(
                "roi config must contain either (x,y,width,height) or (x1,y1,x2,y2)"
            )

    def _validate_code_rule(self, rule):
        self._require(rule, "enable", bool)
        self._require(rule, "match_mode", str)
        if rule["match_mode"] not in ("exact", "contains", "regex", "date"):
            raise ConfigError("code_rule.match_mode invalid")

    def _validate_save_image(self, cfg: dict, node_name: str):
        """
        校验 save_ok_image 节点
        :param cfg: cfg.get("save_ok_image")
        :param node_name: 用于报错信息，如 "save_ok_image"
        """
        if cfg is None:
            raise ConfigError(f"{node_name} 节点缺失")

        # 检查必须字段
        required_fields = {
            "enable": bool,
            "base_dir": str,
            "max_disk_mb": int,
            "save_ok": bool,
            "ok_max_days": int,
            "ng_max_days": int,
            "image_format": str
        }

        for key, typ in required_fields.items():
            if key not in cfg:
                raise ConfigError(f"{node_name} 缺少必需字段: {key}")
            if not isinstance(cfg[key], typ):
                raise ConfigError(f"{node_name}.{key} 类型错误，应为 {typ.__name__}, 实际: {type(cfg[key]).__name__}")

        # 额外检查
        if cfg["max_disk_mb"] <= 0:
            raise ConfigError(f"{node_name}.max_disk_mb 必须大于 0")
        if cfg["ok_max_days"] < 0 or cfg["ng_max_days"] < 0:
            raise ConfigError(f"{node_name}.ok_max_days/ng_max_days 必须 >= 0")
        if cfg["image_format"].lower() not in ("jpg", "jpeg", "png", "bmp"):
            raise ConfigError(f"{node_name}.image_format 必须是 jpg/png/bmp")

        # 确保 base_dir 存在
        import os
        if not os.path.exists(cfg["base_dir"]):
            try:
                os.makedirs(cfg["base_dir"], exist_ok=True)
            except Exception as e:
                raise ConfigError(f"{node_name}.base_dir 无法创建: {cfg['base_dir']}  错误: {e}")

    def _validate_gpio(self, gpio):
        self._require(gpio, "enable", bool)
        # for out in ("out1", "out2"):
        #     if out in gpio:
        #         self._require(gpio[out], "enable", bool)
        #         self._require(gpio[out], "trigger_on", str)

    def _validate_camera(self, cam):
        self._require(cam, "vendor", str)
        self._require(cam, "trigger_mode", str)
        if cam["trigger_mode"] not in ("hardware", "software","continuous"):
            raise ConfigError("camera.trigger_mode invalid")

    def _validate_runtime(self, rt):
        self._require(rt, "auto_start", bool)
        self._require(rt, "status_report_interval_ms", int)

    def _validate_logging(self, log):
        self._require(log, "level", str)
        if log["level"] not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ConfigError("logging.level invalid")


    def get_params(self, module_name: str, keys=None):
        """
        获取指定模块的指定字段
        :param module_name: 配置模块名，例如 "roi", "ocr", "gpio"
        :param keys: 字段列表，例如 ["x","y","width"]
        :return: dict, 例如 {"x": 320, "y": 180, "width": 420}
        :raises ConfigError: 模块或字段不存在
        """
        with self._lock:
            module_cfg = self._config.get(module_name)
            if module_cfg is None:
                raise ConfigError(f"module '{module_name}' not found in config")

            if keys is None:
                return module_cfg

            result = {}
            for k in keys:
                if k not in module_cfg:
                    raise ConfigError(f"key '{k}' not found in module '{module_name}'")
                # 深拷贝保证外部修改不会影响内部状态
                result[k] = module_cfg[k]

            return result


if __name__ == '__main__':

    cfg = ConfigManager("config/config.json")
    # 读取配置
    config = cfg.get_config()

    # 更新配置
    success, err = cfg.update({"roi": {"x": 300, "y": 200}})

    # 获取 ROI 的 x,y,width,height
    roi_values = cfg.get_params("roi", ["x","y","width","height"])
    print(roi_values)
    # 输出可能是：
    # {'x': 320, 'y': 180, 'width': 420, 'height': 120}

    # 获取 OCR 的 batch_size 和 rec_thresh
    ocr_values = cfg.get_params("ocr", ["batch_size", "rec_thresh"])
    print(ocr_values)
    # 输出可能是：
    # {'batch_size': 1, 'rec_thresh': 0.5}





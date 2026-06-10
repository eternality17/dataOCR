import threading
import queue
import time
import os
import shutil
from pathlib import Path
import cv2
import logging
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from state import SystemStats
from common.message import report_status
# from config.save_config import SaveConfig

# logger = logging.getLogger("SaveImageThread")
from logger import logger

class SaveImageThread(threading.Thread):
    """
    工业级存图线程（最终版）：
    - 阻塞获取 save_queue
    - 保存原图和结果图
    - 绘制 OCR + 验证结果
    - 支持热更新配置（从传入的 dict）
    - 磁盘空间管理
    - 异常捕获 + 状态回调（传图像路径给UI）
    """

    def __init__(
        self,
        system_stats: SystemStats,
        config_manager,
        save_queue: queue.Queue,
        stop_event=None,
        status_callback=None,
    ):
        super().__init__(daemon=True)
        self.system_stats = system_stats
        self.queue = save_queue

        # config is a dict containing image_save, roi, etc.
        self.config_manager = config_manager
        self.stop_event = stop_event or threading.Event()
        self.status_callback = status_callback

        # 统计信息
        self.total_frames = 0
        self.success_frames = 0
        self.fail_frames = 0

        # 检查磁盘空间参数
        self._last_disk_check = 0
        self._disk_check_interval = 500  # 秒

        # 命名逻辑，保存时间
        self._last_sec = None
        self._sec_counter = 0

    def _get_cfg(self):
        """
        每次动态获取最新配置（线程安全由 config_manager 保证）
        """
        try:
            return self.config_manager.get_config() or {}
        except Exception:
            return {}

    # 文件名生成函数,返回绘制结果NG图文件名和NG原图文件名
    def _gen_time_filename(self, ext="jpg"):
        """
        生成文件名: YYYYMMDD_HHMMSS_counter.jpg
        同一秒自动递增
        """
        now = time.time()
        current_time = time.localtime(now)

        # 获取日期和时间
        date_str = time.strftime("%Y%m%d", current_time)  # 年月日
        sec = time.strftime("%H%M%S", current_time)  # 时分秒

        if sec != self._last_sec:
            self._last_sec = sec
            self._sec_counter = 1
        else:
            self._sec_counter += 1

        return f"{date_str}_{sec}_{self._sec_counter:03d}.{ext}",f"{date_str}_{sec}_{self._sec_counter:03d}_NG_raw.{ext}"



    # ---------------- helper: image_save config getter ----------------
    def _image_save_cfg(self):
        """
        返回 image_save 配置字典（如果不存在，返回默认字典）
        """
        default = {
            "enable": True,
            "base_dir": "data_images",
            "max_disk_mb": 10240,
            "save_ok": True,
            "ok_max_days": 10,
            "ng_max_days": 30,
            "ok_max_count": 1000,
            "ng_max_count": 2000,
            "raw_max_count": 500,
            "image_format": "jpg",
            "font_path": "fonts/ukai.ttc",
            "font_size": 40
        }
        img_save = self._get_cfg().get("image_save") if isinstance(self._get_cfg(), dict) else None

        if not img_save:
            return default
        # shallow merge
        out = default.copy()
        out.update({k: img_save.get(k, v) for k, v in default.items()})
        # also copy unknown keys
        out.update({k: v for k, v in img_save.items() if k not in out})
        return out

    # ---------------- helper: roi box normalizer ----------------
    def _get_roi_box(self):
        """
        支持两种 roi 配置形式：
        1) {"x":..., "y":..., "width":..., "height":...}
        2) {"x1":..., "y1":..., "x2":..., "y2":...}
        返回 (x1,y1,x2,y2)（int）
        如果 roi 不启用或没配置，返回 None
        """
        roi_cfg = self._get_cfg().get("roi") if isinstance(self._get_cfg(), dict) else None
        if not roi_cfg:
            return None
        if not roi_cfg.get("enable", True):
            return None

        # form 2: x1,y1,x2,y2
        if all(k in roi_cfg for k in ("x1", "y1", "x2", "y2")):
            x1 = int(roi_cfg["x1"])
            y1 = int(roi_cfg["y1"])
            x2 = int(roi_cfg["x2"])
            y2 = int(roi_cfg["y2"])
        # form 1: x,y,width,height
        elif all(k in roi_cfg for k in ("x", "y", "width", "height")):
            x = int(roi_cfg["x"])
            y = int(roi_cfg["y"])
            w = int(roi_cfg["width"])
            h = int(roi_cfg["height"])
            x1, y1, x2, y2 = x, y, x + w, y + h
        else:
            # unsupported format
            return None

        # ensure order
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        return (x1, y1, x2, y2)

    # ---------------- thread main ----------------
    def run(self):
        logger.info("[SaveImageThread] started")
        while not self.stop_event.is_set():
            try:
                packet = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            self.total_frames += 1
            try:
                # 避免每帧都检查磁盘
                now = time.time()
                if now - self._last_disk_check > self._disk_check_interval:
                    self.ensure_disk_space()
                    self._last_disk_check = now

                raw_path, result_path ,vis_bytes = self._save_packet(packet)
                self.success_frames += 1

                # 上报
                stats = self.system_stats.snapshot() if hasattr(self.system_stats, "snapshot") else {}
                data = {"vis_image_bytes": vis_bytes, **stats}

                print("savethread",stats)

                # 使用你的 report_status 签名
                report_status(self.status_callback, msg_type="info", source="SaveImageThread", data=data)

                # ---------------- 计算整帧耗时 ----------------
                now_ms = int(time.time() * 1000)
                cost_ms = now_ms - getattr(packet, "timestamp", now_ms)
                # print("获取的时间戳为：",getattr(packet, "timestamp", now_ms))

                logger.info(f"[SaveImageThread] frame cost: {cost_ms} ms")

            except Exception as e:
                self.fail_frames += 1
                logger.exception(f"[SaveImageThread] exception: {e}")
                report_status(
                    self.status_callback, msg_type="error", source="SaveImageThread", data={"msg": str(e)}
                )
            finally:
                self.queue.task_done()

        logger.info(
            f"[SaveImageThread] stopped. Total={self.total_frames}, Success={self.success_frames}, Fail={self.fail_frames}"
        )

    # ---------------- 核心保存逻辑 ----------------
    def _save_packet(self, packet):
        """
        保存原图和结果图
        返回值: (raw_path_str_or_None, result_path_str_or_None)
        """
        img_cfg = self._image_save_cfg()

        code = getattr(packet, "verify_code", None)
        is_ok = (code == 0)


        base_dir = Path(img_cfg.get("base_dir", "./images"))
        base_dir.mkdir(parents=True, exist_ok=True)

        raw_path = None
        result_path = None

        # ---------------- 保存原图 ----------------
        if img_cfg.get("save_raw", True):
            raw_dir = base_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_name,_ = self._gen_time_filename(img_cfg.get("image_format", "jpg"))
            raw_path = raw_dir / raw_name
            try:
                cv2.imwrite(str(raw_path), packet.image)
            except Exception:
                logger.exception("[SaveImageThread] write raw image failed")

            # ---------------- 控制原图数量 ----------------
            raw_max = img_cfg.get("raw_max_count", 5000)
            self._trim_daily_limit(raw_dir, max_count=raw_max)



        # 构建每日目录 YYYYMMDD（单层）
        ts = getattr(packet, "timestamp", int(time.time() * 1000))
        date_str = time.strftime("%Y%m%d", time.localtime(ts / 1000))
        subdir = "OK" if is_ok else "NG"

        # 分别存储NG原图和NG识别结果图
        result_dir = base_dir / "result" / subdir / date_str
        result_dir.mkdir(parents=True, exist_ok=True)


        # ---------------- 文本 & ROI 处理 ----------------
        texts = []
        if getattr(packet, "ocr_result", None):
            t = packet.ocr_result.get("text", [])
            if not isinstance(t, (list, tuple)):
                texts = [str(t)]
            else:
                texts = t

        # 验证结果使用 verify_msg（用于绘制）
        result_text = str(getattr(packet, "verify_msg", ""))
        if result_text:
            lines = list(texts) + [result_text]
        else:
            lines = list(texts)

        # ROI：优先使用 packet 内的 roi_box（若有），否则使用全局配置 roi
        roi_box = getattr(packet, "roi_box", None)
        if roi_box is None:
            roi_cfg_box = self._get_roi_box()
            if roi_cfg_box:
                roi_box = roi_cfg_box
            else:
                # 整图
                h, w = packet.image.shape[:2]
                roi_box = (0, 0, w - 1, h - 1)

        # ---------------- 调用绘制并保存函数 ----------------
        out_name,out_name_NG_raw = self._gen_time_filename(img_cfg.get("image_format", "jpg"))
        out_path = str(result_dir / out_name)


        out_path_NG_raw=str(result_dir / out_name_NG_raw)  # 和结果图保存在一个文件夹下


        vis_bytes = None

        # 画框并保存，如果需要则返回 vis bytes
        try:
            # vis_bytes = self._draw_and_get_vis_bytes(packet.image, roi_box, lines, code)
            # print("roi_box",roi_box)
            # print("lines",lines)

            # 多框
            ocr = getattr(packet, "ocr_result", {})
            boxes = ocr.get("dt_boxes", [])
            # print("【save_image_thread】  boxes",boxes)

            # 这里的 box_space:
            # - 如果 dt_boxes 是基于整图坐标，填 "image"
            # - 如果 dt_boxes 是基于 ROI crop 坐标，填 "roi"
            box_space = ocr.get("box_space", "roi" if roi_box is not None else "image")

            # 如果 OCR 输入图做过缩放，可在 ocr_result 里传 box_scale，例如 (2.0, 2.0)
            box_scale = ocr.get("box_scale", (1.0, 1.0))
            vis_bytes = self._draw_multi_vis_bytes(
                packet.image,
                boxes,
                texts,
                code,
                result_text,
                roi_box=roi_box,
                box_space=box_space,
                box_scale=box_scale,
            )

        except Exception as e:
            logger.error(f"draw_and_get_vis_bytes exception: {e}")


        # 如果 image_save 被禁用
        if not img_cfg.get("enable", True):
            return None, None, vis_bytes

        # ---------------- 保存结果图 ----------------

        if code is None:
            # 如果没有验证结果，按策略：不保存结果图（只保存 raw）
            return (str(raw_path) if raw_path else None, None,vis_bytes)


        # 根据配置决定是否保存 OK/NG
        if (is_ok and not img_cfg.get("save_ok", True)) or (not is_ok and not img_cfg.get("save_ng", True)):
            return (str(raw_path) if raw_path else None, None,vis_bytes)

        # 保存绘制图，传入vis_bytes=vis_bytes
        # 保存原图，传入vis_bytes=None
        saved = self.draw_and_save_result(
            packet.image,
            code,
            out_path,
            save_ok=img_cfg.get("save_ok", True),
            vis_bytes=vis_bytes
        )
        if saved:
            result_path = out_path

        saved2 = self.draw_and_save_result(
            packet.image,
            code,
            out_path_NG_raw,
            save_ok=img_cfg.get("save_ok", True),
            vis_bytes=None
        )



        # ---------------- 控制每日数量 ----------------
        ok_max = img_cfg.get("ok_max_count", img_cfg.get("ok_max_count", 100))
        ng_max = img_cfg.get("ng_max_count", img_cfg.get("ng_max_count", 1000))
        self._trim_daily_limit(result_dir,  max_count=ok_max if is_ok else ng_max)
        # self.system_stats.update_by_code(packet.verify_code)  在后处理线程更新过，无需重复更新，如单独测试image_save线程，则反注释

        return (str(raw_path) if raw_path else None, str(result_path) if result_path else None,vis_bytes)

    # ---------------- 绘图 / 编码辅助 ----------------
    def _load_font(self, font_path, font_size):
        """
        加载字体，支持 .ttc （index=0）和 .ttf
        返回 ImageFont 对象（若失败返回 ImageFont.load_default()）
        """
        if not font_path:
            return ImageFont.load_default()
        # 绝对路径
        font_path_use = os.path.abspath(font_path)
        # remove trailing spaces
        font_path_use = font_path_use.strip()
        try:
            if font_path_use.lower().endswith(".ttc"):
                # TrueType Collection 需指定 index
                font = ImageFont.truetype(font_path_use, font_size, index=0)
            else:
                font = ImageFont.truetype(font_path_use, font_size)
            # logger.info(f"[FONT] loaded: {font_path_use}, size={font_size}")
            return font
        except Exception as e:
            logger.warning(f"Load font failed ({font_path_use}), using default. err={e}")
            return ImageFont.load_default()

    def _normalize_ocr_box(self, box):
        """
        统一把 OCR box 转成 4 个点：
        [(x1,y1), (x2,y1), (x2,y2), (x1,y2)]
        兼容：
          - np.ndarray(shape=(4,2))
          - [[x,y], [x,y], [x,y], [x,y]]
          - [x1, y1, x2, y2]
        """
        if box is None:
            return None

        if isinstance(box, np.ndarray):
            box = box.tolist()

        if not isinstance(box, (list, tuple)) or len(box) == 0:
            return None

        # 四点框
        if isinstance(box[0], (list, tuple, np.ndarray)):
            pts = []
            for p in box:
                if len(p) < 2:
                    return None
                x = int(round(float(p[0])))
                y = int(round(float(p[1])))
                pts.append((x, y))
            if len(pts) >= 4:
                return pts[:4]
            return None

        # xyxy
        if len(box) >= 4:
            x1 = int(round(float(box[0])))
            y1 = int(round(float(box[1])))
            x2 = int(round(float(box[2])))
            y2 = int(round(float(box[3])))
            return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

        return None

    def _shift_scale_box(self, pts, dx=0, dy=0, sx=1.0, sy=1.0):
        """
        对四点框做平移/缩放。
        """
        if not pts:
            return None
        out = []
        for x, y in pts:
            xx = int(round(x * sx + dx))
            yy = int(round(y * sy + dy))
            out.append((xx, yy))
        return out

    def _draw_multi_vis_bytes(
            self,
            src_img,
            boxes,
            texts,
            code,
            reason=None,
            roi_box=None,
            box_space="roi",
            box_scale=(1.0, 1.0),
    ):
        """
        多检测框绘制版本

        参数：
            src_img: BGR 图像 (numpy)
            boxes: 检测框列表
                   支持：
                   - np.ndarray(shape=(4,2))
                   - [[x,y], [x,y], [x,y], [x,y]]
                   - [x1, y1, x2, y2]
            texts: 识别文字列表
            code: 结果码
            roi_box: (x1, y1, x2, y2)，当 box_space='roi' 时作为偏移量
            box_space:
                - "image": boxes 已经是原图坐标
                - "roi": boxes 是 ROI 裁剪图坐标，需要加 roi_box 左上角偏移
            box_scale:
                - (sx, sy) / 1.0
                - 用于 OCR 输入图缩放后再映射回原图
        返回：
            jpg bytes / None
        """
        try:
            vis_img = cv2.cvtColor(src_img.copy(), cv2.COLOR_BGR2RGB)
        except Exception:
            logger.exception("[_draw_multi_vis_bytes] cvtColor failed")
            vis_img = src_img.copy()

        pil_img = Image.fromarray(vis_img)
        draw = ImageDraw.Draw(pil_img)

        img_cfg = self._image_save_cfg()
        font_path_cfg = img_cfg.get("font_path")
        font_size_cfg = img_cfg.get("font_size", 40)
        try:
            font = ImageFont.truetype(font_path_cfg, font_size_cfg)
        except Exception:
            font = ImageFont.load_default()

        # ROI 偏移
        dx = 0
        dy = 0
        if box_space == "roi" and roi_box is not None:
            dx = int(roi_box[0])
            dy = int(roi_box[1])

        if isinstance(box_scale, (list, tuple)) and len(box_scale) >= 2:
            sx, sy = float(box_scale[0]), float(box_scale[1])
        else:
            sx = sy = float(box_scale) if box_scale is not None else 1.0

        img_w, img_h = pil_img.size

        for i, box in enumerate(boxes):
            text = texts[i] if i < len(texts) else ""

            pts = self._normalize_ocr_box(box)
            if not pts:
                continue

            # 平移 / 缩放到原图坐标
            pts = self._shift_scale_box(pts, dx=dx, dy=dy, sx=sx, sy=sy)
            if not pts:
                continue

            # 画框
            draw.line(pts + [pts[0]], fill=(0, 255, 0), width=2)

            # 左上角作为文字锚点
            x1 = min(p[0] for p in pts)
            y1 = min(p[1] for p in pts)

            # 文本尺寸
            try:
                bbox = font.getbbox(text)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
            except Exception:
                try:
                    bbox2 = draw.textbbox((0, 0), text, font=font)
                    w = bbox2[2] - bbox2[0]
                    h = bbox2[3] - bbox2[1]
                except Exception:
                    w, h = draw.textsize(text, font=font)

            # 文本位置：优先框上方，放不下则贴框内/下方
            text_x = max(0, min(x1, img_w - w - 1))
            text_y = max(0, y1 - h - 4)
            if text_y + h >= img_h:
                text_y = max(0, img_h - h - 1)

            # 背景
            draw.rectangle([text_x, text_y, text_x + w, text_y + h], fill=(0, 0, 0))
            draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255))

        # ===== 整体状态 =====
        status_map = {0: "OK", 1: "NG", 2: "倾斜", 3: "波浪"}
        status_text = status_map.get(code, f"未知({code})")

        # 拼接原因
        if reason:
            status_text = f"{status_text} | {reason}"

        # 计算文字尺寸（建议加背景）
        try:
            bbox = font.getbbox(status_text)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        except Exception:
            w, h = draw.textsize(status_text, font=font)

        # 背景（更清晰）
        draw.rectangle([10, 10, 10 + w, 10 + h], fill=(0, 0, 0))

        # 画状态
        draw.text((10, 10), status_text, font=font, fill=(255, 255, 255))

        vis_np = np.array(pil_img)
        vis_bgr = cv2.cvtColor(vis_np, cv2.COLOR_RGB2BGR)

        try:
            ok, jpg = cv2.imencode(".jpg", vis_bgr)
            if ok:
                return jpg.tobytes()
        except Exception as e:
            logger.error(f"[_draw_multi_vis_bytes] imencode error: {e}", exc_info=True)

        return None

    def _draw_and_get_vis_bytes(self, src_img, roi_box, texts, code):
        """
        返回 overlay 后的 JPEG bytes（RGB->BGR 编码为 jpg bytes）
        src_img: BGR numpy array (OpenCV)
        roi_box: (x1,y1,x2,y2)
        texts: list or str
        code: int (0: OK, 1: 内容错误, 2: 倾斜, 3: 波浪)
        """
        x1, y1, x2, y2 = roi_box
        try:
            vis_img = cv2.cvtColor(src_img.copy(), cv2.COLOR_BGR2RGB)
        except Exception:
            logger.exception("[_draw_and_get_vis_bytes] cvtColor failed, using original image")
            vis_img = src_img.copy()

        pil_img = Image.fromarray(vis_img)
        draw = ImageDraw.Draw(pil_img)

        # ROI 框
        draw.rectangle([x1, y1, x2, y2], outline=(0, 255, 0), width=2)

        if not isinstance(texts, (list, tuple)):
            texts = [str(texts)]

        lines = texts
        # lines = texts + [{0: "合格", 1: "内容错误", 2: "倾斜", 3: "波浪"}.get(code, f"未知({code})")]

        # 字体：优先使用配置，回退到默认
        img_cfg = self._image_save_cfg()
        font_path_cfg = img_cfg.get("font_path")
        font_size_cfg = img_cfg.get("font_size", 40)
        try:
            font = ImageFont.truetype(font_path_cfg, font_size_cfg)
        except Exception:
            font = ImageFont.load_default()


        # 兼容不同 Pillow 版本：使用 font.getbbox 计算宽高
        line_heights = []
        max_w = 0
        for line in lines:
            try:
                bbox = font.getbbox(line)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
            except Exception:
                # fallback: try textbbox or getsize
                try:
                    bbox2 = draw.textbbox((0, 0), line, font=font)
                    w = bbox2[2] - bbox2[0]
                    h = bbox2[3] - bbox2[1]
                except Exception:
                    w, h = draw.textsize(line, font=font)
            max_w = max(max_w, w)
            line_heights.append(h)

        total_h = sum(line_heights) + 5 * (len(lines) - 1)
        text_x = x1
        text_y = max(y1 - total_h - 5, 0)
        draw.rectangle([text_x, text_y, text_x + max_w, text_y + total_h], fill=(0, 0, 0))

        curr_y = text_y
        for i, line in enumerate(lines):
            draw.text((text_x, curr_y), line, font=font, fill=(255, 255, 255))
            curr_y += line_heights[i] + 5

        vis_np = np.array(pil_img)  # RGB
        vis_bgr = cv2.cvtColor(vis_np, cv2.COLOR_RGB2BGR)
        try:
            ok, jpg = cv2.imencode(".jpg", vis_bgr)
            if ok:
                return jpg.tobytes()
        except Exception as e:
            logger.error(f"imencode exception: {e}", exc_info=True)
        return None

    def draw_and_save_result(
            self,
            src_img,
            code,
            out_path,
            save_ok=True,
            vis_bytes=None,
    ):
        """
        仅负责保存结果图：
        - 优先使用 vis_bytes（推荐）
        - fallback 使用原图 src_img
        - 不再做任何绘制

        返回：
            True: 成功写入文件
            False: 未保存或失败
        """

        is_ok = (code == 0)
        if is_ok and not save_ok:
            logger.debug("OK 图片未保存（save_ok=False）。")
            return False

        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            # ---------------- 优先写 vis_bytes ----------------
            if vis_bytes is not None:
                try:
                    with open(out_path, "wb") as f:
                        f.write(vis_bytes)
                    return True
                except Exception as e:
                    logger.warning(f"[draw_and_save_result] 写入 vis_bytes 失败，fallback raw: {e}")

            # ---------------- fallback: 写原图 ----------------
            if src_img is not None:
                try:
                    ok = cv2.imwrite(out_path, src_img)
                    if ok:
                        print("未传入绘制图，保存原图成功")
                        return True
                except Exception as e:
                    logger.error(f"[draw_and_save_result] fallback 写原图失败: {e}", exc_info=True)

            return False

        except Exception as e:
            logger.error(f"[draw_and_save_result] 保存失败: {out_path}, err={e}", exc_info=True)
            return False


    # ---------------- 控制每日保存数量 ----------------
    def _trim_daily_limit(self, dir_path: Path, max_count: int = 100):
        files = sorted(dir_path.glob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[max_count:]:
            try:
                f.unlink()
            except Exception as e:
                logger.warning(f"[SaveImageThread] remove old file failed: {f}, {e}")

    # ---------------- 磁盘管理 ----------------
    def ensure_disk_space(self):
        try:
            self._clean_by_days()
            self._force_clean_by_disk()
        except Exception as e:
            logger.warning(f"[SaveImageThread] ensure_disk_space exception: {e}")

    def _list_date_dirs(self):
        base = Path(self._image_save_cfg().get("base_dir")) / "result"
        if not base.exists():
            return []
        dirs = [d for d in base.glob("*/*") if d.is_dir()]
        dirs.sort(key=lambda d: d.name)
        return dirs

    def _date_dir_to_ts(self, dir_name):
        try:
            return time.mktime(time.strptime(dir_name, "%Y%m%d"))
        except Exception:
            return 0

    def _clean_by_days(self):
        now = time.time()
        img_cfg = self._image_save_cfg()
        ok_max_days = img_cfg.get("ok_max_days", 30)
        ng_max_days = img_cfg.get("ng_max_days", 30)
        for d in self._list_date_dirs():
            date_ts = self._date_dir_to_ts(d.name)
            days = (now - date_ts) / 86400
            if ("OK" in str(d) and days > ok_max_days) or ("NG" in str(d) and days > ng_max_days):
                try:
                    shutil.rmtree(d)
                    logger.info(f"[SaveImageThread] removed old dir: {d}")
                except Exception as e:
                    logger.warning(f"[SaveImageThread] remove dir failed: {d}, {e}")

    def _get_dir_size_mb(self, path):
        path = str(path)
        total = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)

        return total / 1024 / 1024

    def _force_clean_by_disk(self):

        base = Path(self._image_save_cfg().get("base_dir"))

        # 1 当前图片目录大小
        used = self._get_dir_size_mb(base)
        print("当前使用：", used, "mb")
        max_mb = self._image_save_cfg().get("max_disk_mb", 10240)

        # 2 当前磁盘剩余空间
        total, used_sys, free_sys = shutil.disk_usage("/data")
        free_mb = free_sys / 1024 / 1024
        # print("当前剩余空间为：",free_mb,"mb")

        min_free_mb = self._image_save_cfg().get("min_free_mb", 500)

        # 条件1：图片目录太大
        need_clean = used > max_mb

        # 条件2：系统磁盘太小
        if free_mb < min_free_mb:
            logger.warning(f"[SaveImageThread] disk free low: {free_mb:.1f}MB")

            need_clean = True

        if not need_clean:
            return

        logger.warning("[SaveImageThread] start disk cleanup")

        for d in sorted(base.glob("*"), key=lambda p: p.stat().st_mtime):
            try:
                shutil.rmtree(d)
            except Exception:
                pass

            total, used_sys, free_sys = shutil.disk_usage("/data")
            free_mb = free_sys / 1024 / 1024

            if free_mb > min_free_mb:
                break


# ----------------- 测试 main（保持向后兼容） -----------------
if __name__ == "__main__":
    import time
    import numpy as np
    import queue
    import logging

    logging.basicConfig(level=logging.INFO)

    from config.config_manager import ConfigManager
    cfg = ConfigManager("config/config.json")
    config_manager = cfg.get_config()
    class ImagePacket:
        def __init__(self, frame_id: int):
            self.frame_id = frame_id
            self.timestamp = int(time.time() * 1000)
            # 假图像
            self.image = cv2.imread("post_process/test2.jpg")
            # 假 OCR 结果
            self.ocr_result = {"text": [f"Y{time.strftime('%Y%m%d')}", "深圳"]}
            # 以下字段由 PostProcessThread 填充
            self.verify_code = 0 if frame_id % 2 == 0 else 1
            self.verify_msg = "OK" if self.verify_code == 0 else "NG"
            # optional: packet can override roi_box
            # self.roi_box = (170, 260, 1380, 460)

    class FakeValidator:
        def validate(self, image_packet):
            if image_packet.frame_id % 2 == 0:
                return 0, "OK"
            else:
                return 1, "NG: code mismatch"

    def status_callback(data=None, **kwargs):
        print("[STATUS CALLBACK]", data or kwargs)

    postprocess_queue = queue.Queue(maxsize=10)
    save_queue = queue.Queue(maxsize=10)

    stop_event = threading.Event()

    system_stats = SystemStats()
    save_thread = SaveImageThread(system_stats=system_stats, save_queue=save_queue, config=config_manager, stop_event=stop_event, status_callback=status_callback)

    # start threads
    save_thread.start()

    # feed some packets
    for i in range(6):
        pkt = ImagePacket(frame_id=i)
        save_queue.put(pkt)
        time.sleep(0.1)

    time.sleep(1)
    stop_event.set()
    save_thread.join()
    print("Done. Stats:", system_stats.snapshot() if hasattr(system_stats, "snapshot") else {})

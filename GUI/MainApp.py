# MainApp.py
import sys
import subprocess

sys.path.append("/data/dataOCR")

import os
import json
from PyQt5 import QtCore
from PyQt5.QtCore import Qt, QRect, pyqtSignal,QFileSystemWatcher
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
                             QPushButton, QFileDialog, QMessageBox, QCheckBox, QHBoxLayout, QLineEdit)

from GUI.PyUICMainUI import Ui_MainWindow

from logger import logger
import time

# AdjustableImageLabel with helper to load from bytes
from PyQt5.QtWidgets import QLabel
from PyQt5.QtGui import QPainter, QPen, QBrush, QPixmap
from common.message import MessageType, Message
from config.config_manager import ConfigManager
from image_capture.camera import HikCamera
from ai_server import AIServer


HANDLE_NONE = 0
HANDLE_TOP_LEFT = 1
HANDLE_TOP_RIGHT = 2
HANDLE_BOTTOM_LEFT = 3
HANDLE_BOTTOM_RIGHT = 4
HANDLE_MOVE = 5


class AdjustableImageLabel(QLabel):
    def __init__(self, img_path=None):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.original_pixmap = None
        self.last_image_path = None
        if img_path and os.path.exists(img_path):
            self.original_pixmap = QPixmap(img_path)
            self.last_image_path = img_path
            self.update_scaled_pixmap()
        self.rect_box = QRect()
        self.current_drawing_rect = None
        self.has_rect = False
        self.drawing_mode = False
        self.adjusting_mode = False
        self.drag_start = None
        self.active_handle = HANDLE_NONE
        self.handle_size = 6
        self.setMouseTracking(True)

    def set_image(self, path):
        if path and os.path.exists(path):
            self.original_pixmap = QPixmap(path)
            self.last_image_path = path
            self.update_scaled_pixmap()

    def set_pixmap_from_bytes(self, b, save_to_path=None):
        if not b:
            return
        if save_to_path:
            try:
                with open(save_to_path, "wb") as f:
                    f.write(b)
                self.last_image_path = save_to_path
            except Exception as e:
                logger.error(f"Failed to save image bytes to {save_to_path}: {e}")
        pm = QPixmap()
        ok = pm.loadFromData(b)
        if ok:
            self.original_pixmap = pm
            self.update_scaled_pixmap()

    def update_scaled_pixmap(self):
        if self.original_pixmap:
            scaled = self.original_pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.setPixmap(scaled)

    def resizeEvent(self, event):
        self.update_scaled_pixmap()

    def map_rect_to_image_coords(self, rect: QRect):
        if self.original_pixmap is None or rect.isNull():
            return None

        label_w = self.width()
        label_h = self.height()

        pix_w = self.original_pixmap.width()
        pix_h = self.original_pixmap.height()

        scale = min(label_w / pix_w, label_h / pix_h)
        disp_w = pix_w * scale
        disp_h = pix_h * scale

        offset_x = (label_w - disp_w) / 2
        offset_y = (label_h - disp_h) / 2

        x1 = (rect.left() - offset_x) / scale
        y1 = (rect.top() - offset_y) / scale
        x2 = (rect.right() - offset_x) / scale
        y2 = (rect.bottom() - offset_y) / scale

        x1 = max(0, min(pix_w - 1, x1))
        y1 = max(0, min(pix_h - 1, y1))
        x2 = max(0, min(pix_w - 1, x2))
        y2 = max(0, min(pix_h - 1, y2))

        return int(x1), int(y1), int(x2), int(y2)

    def map_image_coords_to_label_rect(self, x1, y1, x2, y2):
        if self.original_pixmap is None:
            return QRect()
        label_w = self.width()
        label_h = self.height()
        pix_w = self.original_pixmap.width()
        pix_h = self.original_pixmap.height()

        scale = min(label_w / pix_w, label_h / pix_h)
        disp_w = pix_w * scale
        disp_h = pix_h * scale
        offset_x = (label_w - disp_w) / 2
        offset_y = (label_h - disp_h) / 2

        lx1 = int(x1 * scale + offset_x)
        ly1 = int(y1 * scale + offset_y)
        lx2 = int(x2 * scale + offset_x)
        ly2 = int(y2 * scale + offset_y)
        return QRect(lx1, ly1, lx2 - lx1, ly2 - ly1)

    # mouse handlers & paintEvent — same behavior as earlier
    def get_handle_rect(self, point):
        return QRect(point.x() - self.handle_size, point.y() - self.handle_size,
                     self.handle_size * 2, self.handle_size * 2)

    def get_handles(self):
        if self.rect_box.isNull():
            return []
        return [self.rect_box.topLeft(), self.rect_box.topRight(), self.rect_box.bottomLeft(),
                self.rect_box.bottomRight()]

    def get_handle_at_pos(self, pos):
        if self.rect_box.isNull():
            return HANDLE_NONE
        handles = self.get_handles()
        if self.get_handle_rect(handles[0]).contains(pos):
            return HANDLE_TOP_LEFT
        if self.get_handle_rect(handles[1]).contains(pos):
            return HANDLE_TOP_RIGHT
        if self.get_handle_rect(handles[2]).contains(pos):
            return HANDLE_BOTTOM_LEFT
        if self.get_handle_rect(handles[3]).contains(pos):
            return HANDLE_BOTTOM_RIGHT
        if self.rect_box.contains(pos):
            return HANDLE_MOVE
        return HANDLE_NONE

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.drawing_mode:
            self.drag_start = e.pos()
            self.current_drawing_rect = QRect(e.pos(), e.pos())
            self.update()
        elif self.adjusting_mode and not self.rect_box.isNull():
            self.drag_start = e.pos()
            self.active_handle = self.get_handle_at_pos(e.pos())

    def mouseMoveEvent(self, e):
        if self.adjusting_mode and not self.rect_box.isNull():
            handle_type = self.get_handle_at_pos(e.pos())
            if handle_type == HANDLE_TOP_LEFT or handle_type == HANDLE_BOTTOM_RIGHT:
                self.setCursor(Qt.SizeFDiagCursor)
            elif handle_type == HANDLE_TOP_RIGHT or handle_type == HANDLE_BOTTOM_LEFT:
                self.setCursor(Qt.SizeBDiagCursor)
            elif handle_type == HANDLE_MOVE:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

        if self.drawing_mode and self.drag_start is not None:
            self.current_drawing_rect = QRect(self.drag_start, e.pos()).normalized()
            self.update()
        elif self.adjusting_mode and self.drag_start is not None and not self.rect_box.isNull():
            delta = e.pos() - self.drag_start
            rect = self.rect_box
            if self.active_handle == HANDLE_MOVE:
                rect.translate(delta)
            elif self.active_handle == HANDLE_TOP_LEFT:
                rect.setTopLeft(rect.topLeft() + delta)
            elif self.active_handle == HANDLE_TOP_RIGHT:
                rect.setTopRight(rect.topRight() + delta)
            elif self.active_handle == HANDLE_BOTTOM_LEFT:
                rect.setBottomLeft(rect.bottomLeft() + delta)
            elif self.active_handle == HANDLE_BOTTOM_RIGHT:
                rect.setBottomRight(rect.bottomRight() + delta)
            self.rect_box = rect.normalized()
            self.drag_start = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.drawing_mode and self.current_drawing_rect is not None:
            self.rect_box = self.current_drawing_rect.normalized()
            self.current_drawing_rect = None
            self.drawing_mode = False
            self.adjusting_mode = True
            self.has_rect = True
            self.update()
        self.drag_start = None
        self.active_handle = HANDLE_NONE

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        if self.drawing_mode and self.current_drawing_rect is not None:
            painter.setPen(QPen(Qt.blue, 2, Qt.DashLine))
            painter.drawRect(self.current_drawing_rect)
        elif self.adjusting_mode and not self.rect_box.isNull():
            painter.setPen(QPen(Qt.green, 2))
            painter.drawRect(self.rect_box)
            painter.setPen(QPen(Qt.red, 1))
            painter.setBrush(QBrush(Qt.red))
            for handle in self.get_handles():
                painter.drawRect(self.get_handle_rect(handle))
        elif self.has_rect and not self.rect_box.isNull():
            painter.setPen(QPen(Qt.green, 2))
            painter.drawRect(self.rect_box)

    def set_drawing_mode(self, enable):
        self.drawing_mode = enable
        self.adjusting_mode = False
        self.current_drawing_rect = None
        self.update()

    def reset_rect(self):
        self.rect_box = QRect()
        self.current_drawing_rect = None
        self.has_rect = False
        self.drawing_mode = False
        self.adjusting_mode = False
        self.update()

    def confirm_rect(self):
        self.drawing_mode = False
        self.adjusting_mode = False
        self.has_rect = True
        self.update()
        return self.rect_box


class MainApp(QMainWindow):
    """

    """
    infer_result_signal = pyqtSignal(dict)
    CONFIG_FILE = os.path.join(os.getcwd(), "frontend_config.json")
    CONFIG_MANAGER_FILE = os.path.join(os.getcwd(), "config/config.json")
    STYLE_FILE= os.path.join(os.getcwd(), "GUI/style.qss")

    def __init__(self):
        super().__init__()

        # ---------- initialization flags ----------
        self._initializing = True  # prevent writes during startup load
        self.frontend_config_exists = os.path.exists(self.CONFIG_FILE)

        self.ai_server = None
        self.expected_texts = None
        self.infer_result_signal.connect(self._update_infer_result)

        self.cam = HikCamera(device_index=0)
        self.config_manager = ConfigManager(self.CONFIG_MANAGER_FILE)

        # 必要状态先初始化，避免初始化期间被读取

        self.cn_roi_box = None  # roi
        self.cn_text_lines = []  # 期望文字

        self.save_ok_flag = False  # ok图片是否保存
        self.send_signal_flag = False  # 是否GPIO标志

        self.last_display_image_path = None  # 最后一张图像的路径

        # UI 初始化
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        # self.showFullScreen()  # 全屏显示
        self.load_stylesheet()

        # 连接关闭系统按钮（安全退出）
        self.ui.bnExit.clicked.connect(self.safe_exit)


        # 图像显示占位
        script_dir = os.path.dirname(__file__)
        default_img = os.path.join(script_dir, "test.bmp")
        if not os.path.exists(default_img):
            pm = QPixmap(640, 480)
            pm.fill(Qt.lightGray)
            pm.save(default_img, "BMP")

        #
        self.cn_img = AdjustableImageLabel(default_img)
        self.cn_img.setFixedSize(1200, 800)
        self._place_widget(self.ui.widget_cn_display, self.cn_img)

        self.run_img = AdjustableImageLabel(default_img)
        self.run_img.setFixedSize(1200, 800)
        self._place_widget(self.ui.widget_run_display, self.run_img)

        # OK、NG计数
        self.ok = 0
        self.ng = 0

        # 计时
        self.begin=0
        self.end=0

        # checkbox
        self.chk_save_ok = self.ui.chk_save_ok
        self.chk_send_signal = self.ui.chk_send_signal

        # Load config now that UI exists (do not auto-write during load)
        self.load_frontend_config()

        # debounce timers for saving line edits (avoid saving on every keystroke)
        self._save_timer_line1 = QtCore.QTimer(self)
        self._save_timer_line1.setSingleShot(True)
        self._save_timer_line1.setInterval(800)  # ms of inactivity before save; 可调整
        self._save_timer_line1.timeout.connect(lambda: self.sync_text(save=True))

        self._save_timer_line2 = QtCore.QTimer(self)
        self._save_timer_line2.setSingleShot(True)
        self._save_timer_line2.setInterval(800)
        self._save_timer_line2.timeout.connect(lambda: self.sync_text(save=True))

        # connect signals (user actions will trigger save; _initializing will prevent spurious writes)
        self.ui.bnSelectImage.clicked.connect(self.load_cn_image)  # 中文设置页面的选择图片按钮
        self.ui.bnDraw.clicked.connect(lambda: self.cn_img.set_drawing_mode(True))  # 绘制按钮（ROI)
        self.ui.bnReset.clicked.connect(self.cn_img.reset_rect)  # 重置（ROI框）按钮
        self.ui.bnConfirm.clicked.connect(self.confirm_cn_rect)  # 确定 按钮（发送消息给AIserver）

        def _line1_changed(text):
            try:
                self.ui.show1.setText(f"字符行1: {text}")
            except Exception:
                pass
            # restart debounce timer
            try:
                self._save_timer_line1.start()
            except Exception:
                # fallback: immediate save if timer fails
                self.sync_text(save=True)

        def _line2_changed(text):
            try:
                self.ui.show2.setText(f"字符行2: {text}")
            except Exception:
                pass
            try:
                self._save_timer_line2.start()
            except Exception:
                self.sync_text(save=True)

        self.ui.line1.textChanged.connect(_line1_changed)
        self.ui.line2.textChanged.connect(_line2_changed)

        # 点击文本框自动弹出键盘
        self.ui.line1.installEventFilter(self)
        self.ui.line2.installEventFilter(self)

        # start button
        try:
            self.ui.bnStartRun.clicked.disconnect()
        except Exception:
            pass

        self.ui.bnStartRun.clicked.connect(self.toggle_runner)
        self.ui.bnClear.clicked.connect(self.clear_stats)

        # show current text lines without saving
        self.sync_text(save=False)


        # checkbox callbacks (connect once)
        try:
            # avoid duplicate connection if any
            try:
                self.chk_save_ok.stateChanged.disconnect(self._on_chk_save_ok_changed)
            except Exception:
                pass
            try:
                self.chk_send_signal.stateChanged.disconnect(self._on_chk_send_signal_changed)
            except Exception:
                pass
            self.chk_save_ok.stateChanged.connect(self._on_chk_save_ok_changed)
            self.chk_send_signal.stateChanged.connect(self._on_chk_send_signal_changed)
        except Exception:
            pass

        # initialization complete
        self.runner_running = False
        self._initializing = False

    def load_stylesheet(self):
        try:
            with open(self.STYLE_FILE, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print("Load stylesheet failed:", e)

    def safe_exit(self):
        reply = QMessageBox.question(
            self,
            "安全退出确认",
            "确认关闭系统？\n当前运行将被终止。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                if self.runner_running:
                    self.stop_runner()

            except Exception as e:
                print("关闭资源异常:", e)

            QApplication.quit()



    def eventFilter(self, obj, event):

       if event.type() == QtCore.QEvent.FocusIn:
           if obj in (self.ui.line1, self.ui.line2):
               subprocess.Popen(["/usr/bin/onboard"])

       if event.type() == QtCore.QEvent.FocusOut:
           if obj in (self.ui.line1, self.ui.line2):
               # 延迟判断，避免在两个框之间切换时误关闭
               QtCore.QTimer.singleShot(100, self.check_close_keyboard)

       return super().eventFilter(obj, event)

    def check_close_keyboard(self):
       # 如果两个输入框都没有焦点，才关闭
       if not (self.ui.line1.hasFocus() or self.ui.line2.hasFocus()):
           self.close_virtual_keyboard()


    def close_virtual_keyboard(self):
       subprocess.call(["pkill", "onboard"])
      
    def _on_chk_save_ok_changed(self, state):
        """
        功能：是否保存ok图像按钮的处理，向TCP server发送CONFIG_UPDATE_SAVE_OK命令
        处理逻辑：
        1）
        """
        print("更改save_ok状态")
        self.save_ok_flag = (state == Qt.Checked)
        self.save_frontend_config()

        msg_type = MessageType.CONFIG_UPDATE_SAVE_OK
        data = {"image_save": {"save_ok": self.save_ok_flag}}
        ok, msg = self.config_manager.update(data)
        # ok = self.tcp_client.send(msg_type, data, source="UI")
        if ok:
            self.statusBar().showMessage("save_ok 已同步到 AI server", 3000)
        else:
            self.statusBar().showMessage("⚠ AI server 未连接，同步失败", 5000)

    def _on_chk_send_signal_changed(self, state):
        """ 点击是否连接GPIO 处理逻辑：
         1）设置self.send_signal_flag的值
         2）修改配置文件
         3）通知AI server
        """
        print("send_signal更新开始。。。。")
        self.send_signal_flag = bool(state == Qt.Checked)
        self.save_frontend_config()
        # 通知AI
        msg_type = MessageType.CONFIG_UPDATE_SEND_SIGNAL
        source = "UI"

        data = {"gpio": {"gpio_plc": {"enable": bool(state == Qt.Checked)}}}
        ok, msg = self.config_manager.update(data)

        # ok = self.tcp_client.send(msg_type, data, source)
        if ok:
            self.statusBar().showMessage("save_ok 已同步到 AI server", 3000)
        else:
            self.statusBar().showMessage("⚠ AI server 未连接，同步失败", 5000)


    def _update_infer_result(self, result: dict):
        """
        更新OK、NG等信息
                     msg = Message(
            #     msg_type=MessageType.FRAME_RESULT,
            #     source="SaveImageThread",
            #     data={
            #         "frame_id": packet.frame_id,
            #         "verify_code": packet.verify_code,
            #         "verify_msg": packet.verify_msg,
            #         "image_url": image_url,
            #
            #         # 系统统计
            #         "ok_count": stats["ok_count"],
            #         "ng_count": stats["ng_count"],
            #         "accuracy": stats["accuracy"]
            #     }
            # )
        """

        data = result.get("data")

        # 获得result_data中的信息
        if not data:
          return   # 防止空数据覆盖统计

        self.ok = int(data.get("ok_count", self.ok))
        self.ng = int(data.get("ng_count", self.ng))
    
        total = int(data.get("total_count", self.ok + self.ng))
        rate = (self.ok / total) if total > 0 else 0.0

        # print("更新中----------ok:", self.ok, "----------ng:", self.ng, "  total", total)

        # 更新组件
        self.ui.ok_label.setText(f"OK: {self.ok}")
        self.ui.ng_label.setText(f"NG: {self.ng}")
        self.ui.total_label.setText(f"检测: {total}")
        self.ui.rate_label.setText(f"合格率: {rate * 100.0:.2f}%")

        self.save_frontend_config()

        # ------------------ 显示可视化图像 ------------------
        # update visualization image if available (do NOT save to disk or persist)
        vis_bytes = data.get("vis_image_bytes", None)
        if vis_bytes:
            try:
                # directly display bytes without saving to disk or writing config
                self.run_img.set_pixmap_from_bytes(vis_bytes)
            except Exception as e:
                logger.error(f"set_pixmap_from_bytes exception: {e}")


    def _place_widget(self, placeholder: QWidget, widget: QWidget):
        layout = placeholder.layout()
        if layout is None:
            layout = QVBoxLayout(placeholder)
            layout.setContentsMargins(0, 0, 0, 0)

        # 清空已有控件
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        layout.addWidget(widget)


        # ------------------ UI端配置文件操作部分------------------

    def _load_config_data(self):
        """
        功能：装置配置文件
        处理逻辑：
        """
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Load frontend config failed: {e}")
        return {}

    def _write_config_data(self, data: dict):
        """
        功能：写配置文件
        """
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Write frontend config failed: {e}")

    def save_frontend_config(self):

        """
        保存配置文件
        Save config to disk. If we are initializing (startup load), skip writes.
        If no config file existed at startup, the first real user-triggered save
        will create it and flip frontend_config_exists=True.
        """
        if getattr(self, "_initializing", False):
            # avoid overwriting on startup
            return

        cfg = self._load_config_data()

        cfg['line1'] = self.ui.line1.text()
        cfg['line2'] = self.ui.line2.text()
        try:
            cfg['cn_image_path'] = self.cn_img.last_image_path
        except Exception:
            cfg['cn_image_path'] = None

        # roi image coords (if recorded)
        try:
            roi = cfg.get('roi_img_coords', None)
            # If cn_img currently has rect, prefer that
            if hasattr(self.cn_img, "rect_box") and not self.cn_img.rect_box.isNull():
                img_coords = self.cn_img.map_rect_to_image_coords(self.cn_img.rect_box)
                if img_coords:
                    cfg['roi_img_coords'] = [int(img_coords[0]), int(img_coords[1]), int(img_coords[2]),
                                             int(img_coords[3])]
            else:
                if roi:
                    cfg['roi_img_coords'] = [int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])]
        except Exception:
            pass

        # ---------- 统计 ----------
        total = self.ok + self.ng
        rate = (self.ok / total) if total > 0 else 0.0
        # print("保存为---------------------ok:",self.ok,"---------------------ng:",self.ng,"  total",total)

        cfg["ui_stats"] = {
            "ok": int(self.ok),
            "ng": int(self.ng),
            "total": int(total),
            "rate": round(float(rate), 4)
        }

        # ---------- checkbox 状态 ----------
        cfg["ui_flags"] = {
            "save_ok": bool(self.chk_save_ok.isChecked()),
            "send_signal": bool(self.chk_send_signal.isChecked())
        }

        self._write_config_data(cfg)
        # mark that config now exists on disk
        self.frontend_config_exists = True
        # logger.debug("Frontend config saved to %s" % self.CONFIG_FILE)

    def load_frontend_config(self):
        """
        从UI配置文件更新UI界面
        Load frontend config and apply to UI. Should be called after UI constructed.
        Does not auto-save during initialization.
        """
        cfg = self._load_config_data()
        if not cfg:
            # no config file found – keep defaults; do not create file now
            return
        try:
            self.ui.line1.setText(cfg.get('line1', ""))
            self.ui.line2.setText(cfg.get('line2', ""))
        except Exception:
            pass
        try:
            cn_path = cfg.get('cn_image_path', None)
            if cn_path and os.path.exists(cn_path):
                self.cn_img.set_image(cn_path)
                self.cn_img.last_image_path = cn_path
        except Exception:
            pass

        try:
            roi_coords = cfg.get('roi_img_coords', None)
            if roi_coords and self.cn_img.original_pixmap is not None:
                x1, y1, x2, y2 = roi_coords
                rect = self.cn_img.map_image_coords_to_label_rect(x1, y1, x2, y2)
                if not rect.isNull():
                    self.cn_img.rect_box = rect
                    self.cn_img.has_rect = True
                    self.cn_img.update()
                    self.run_img.rect_box = rect
                    self.run_img.has_rect = True
                    self.run_img.update()
        except Exception as e:
            logger.error(f"Restore roi failed: {e}")

        # ---------- 恢复 checkbox ----------
        try:
            flags = cfg.get("ui_flags", {})
            self.chk_save_ok.setChecked(bool(flags.get("save_ok", False)))
            self.chk_send_signal.setChecked(bool(flags.get("send_signal", False)))

            self.save_ok_flag = self.chk_save_ok.isChecked()
            self.send_signal_flag = self.chk_send_signal.isChecked()
        except Exception:
            pass

        # ---------- 恢复统计 ----------
        try:
            stats = cfg.get("ui_stats", {})

            self.ok = int(stats.get("ok", 0))
            self.ng = int(stats.get("ng", 0))
            total = int(stats.get("total", self.ok + self.ng))
            rate = float(stats.get("rate", 0.0))

            self.ui.ok_label.setText(f"OK: {self.ok}")
            self.ui.ng_label.setText(f"NG: {self.ng}")
            self.ui.total_label.setText(f"检测: {total}")
            self.ui.rate_label.setText(f"合格率: {rate * 100:.2f}%")

        except Exception as e:
            logger.error(f"Restore ui stats failed: {e}")

        # ---------------- image & ROI -----------------

    def load_cn_image(self):
        """
        装载图像
        """
        if self.runner_running:
            QMessageBox.information(self, "Info", "运行中不可修改输入图片。", QMessageBox.Ok)
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.bmp)")
        if path:
            self.cn_img.set_image(path)
            # store last shown image path in object
            self.cn_img.last_image_path = path
            self.save_frontend_config()

    def sync_text(self, save=True):
        """
        功能：更新运行界面的期望文字与中文设置页面同步
        参数：
            save

        """
        self.ui.show1.setText(f"字符行1: {self.ui.line1.text()}")
        self.ui.show2.setText(f"字符行2: {self.ui.line2.text()}")
        self.expected_texts = [self.ui.line1.text(), self.ui.line2.text()]
        code_rule = {"expected_texts": self.expected_texts}
        data = {"validator": code_rule}

        if save:
            # print("------------------------开始保存")
            self.save_frontend_config()
            self.config_manager.update(data)
            print("【MainApp】 同步文字：config：", self.config_manager.get_config())

    def confirm_cn_rect(self):
        """
        处理逻辑：
        1）获得ROI的坐标值，映射到实际的图像坐标
        2）更新到前端的配置文件
        3）显示已经同步到AI server

        """
        if self.runner_running:
            QMessageBox.information(self, "Info", "运行中不可修改检测区域。", QMessageBox.Ok)
            return

        # 获得ROI坐标
        rect = self.cn_img.confirm_rect()
        if not rect.isNull():
            self.run_img.rect_box = rect
            self.run_img.has_rect = True
            self.run_img.update()

            img_coords = self.cn_img.map_rect_to_image_coords(rect)
            if img_coords is None:
                QMessageBox.warning(self, "Error", "无法将 ROI 映射到原图坐标。")
                return

            # 更新配置文件
            cfg = self._load_config_data()
            cfg['roi_img_coords'] = [int(img_coords[0]), int(img_coords[1]), int(img_coords[2]), int(img_coords[3])]
            self._write_config_data(cfg)
            self.save_frontend_config()
            # QMessageBox.information(self, "Info", "检测区域已同步到运行界面，并更新裁剪参数。", QMessageBox.Ok)

            x1 = int(img_coords[0])
            y1 = int(img_coords[1])
            x2 = int(img_coords[2])
            y2 = int(img_coords[3])
            roi = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}

            # 发送UPDATE_CONFIG_ROI命令
            msg_type = MessageType.CONFIG_UPDATE_ROI
            data = {"roi": roi}
            source = "UI"
            ok, msg = self.config_manager.update(data)
            # ok = self.tcp_client.send(msg_type, data, source)
            if ok:
                # 显示已经同步到AI server
                self.ui.statusbar.showMessage("同步更新到AI server")
            else:
                self.ui.statusbar.showMessage(f"AI server连接失败，同步更新失败:{msg}")

    def clear_stats(self):
        """
        功能：清零，向TCP_Server发送"COMMAND_CLEAR"命令
        处理逻辑：
        1）UI界面上的组件显示清零
        2）发送TCP消息给AI端
        """
        # --------- UI组件清零-------------
        self.ok = 0
        self.ng = 0
        self.ui.ok_label.setText("OK: 0")
        self.ui.ng_label.setText("NG: 0")
        self.ui.total_label.setText("检测: 0")
        self.ui.rate_label.setText("合格率: 0%")

        self.save_frontend_config()

        if self.ai_server:
            if self.ai_server.system_stats:
                self.ai_server.system_stats.reset()


    def ts_ms_to_str(self,ts_ms: int, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """
        毫秒时间戳 -> 可读时间字符串

        参数
        ----
        ts_ms : int
            毫秒时间戳 (例如 int(time.time()*1000))

        fmt : str
            时间格式，默认 "%Y-%m-%d %H:%M:%S"

        返回
        ----
        str
            带毫秒的时间字符串
        """
        t = time.localtime(ts_ms / 1000)
        ms = ts_ms % 1000
        return time.strftime(fmt, t) + f".{ms:03d}"

        # ---------------- Runner control -----------------

    def toggle_runner(self):

        if not self.ai_server:
            t1 = int(time.time() * 1000)
            print("初次启动：", self.ts_ms_to_str(t1))

            self.start_runner()

            t2 = int(time.time() * 1000)

            print("初次启动完成：", self.ts_ms_to_str(t2))
            print("初次启动耗时：", t2 - t1, "ms")

            return

        if not self.runner_running:
            # resume
            t1 = int(time.time() * 1000)
            self.begin = t1
            print("再次启动：", self.ts_ms_to_str(t1))

            ok, msg = self.ai_server.resume()

            t2 = int(time.time() * 1000)

            print("再次启动完成：", self.ts_ms_to_str(t2))
            print("再次启动耗时：", t2 - t1, "ms")

            if ok:
                self.runner_running = True
                self.ui.bnStartRun.setText("暂停")
                self.ui.statusbar.showMessage("AI Server 启动中...")
        else:
            # pause
            ok, _ = self.ai_server.pause()
            print("暂停中……")
            if ok:
                self.runner_running = False
                self.ui.bnStartRun.setText("继续")
                self.ui.statusbar.showMessage("AI Server 暂停中...")

    def start_runner(self):
        """
        功能：启动AI端
        处理逻辑：
        1）只初始化一次，后续是暂停恢复
        4）更新状态条信息
        """

        self.load_frontend_config()

        self.ai_server = AIServer(
            camera=self.cam,
            config_manager=self.config_manager,
            status_callback=self.callback
        )

        ok, msg = self.ai_server.start()


        if ok:
            self.runner_running = True
            self.ui.bnStartRun.setText("暂停")
            self.ui.statusbar.showMessage("AI Server 启动中...")
        else:
            self.ui.statusbar.showMessage(f"AI server未连接，同步失败: {msg}")

    def stop_runner(self):
        """
        功能：停止AI端
        处理逻辑：
        1）发送TCP消息
        2）设置self.runner_running标志
        3）更新状态条信息
        """
        # 向TCP Server发送COMMAND_STOP命令
        # msg_type = MessageType.COMMAND_STOP
        # data = {}
        # source = "UI"
        # ok = self.tcp_c
        # lient.send(msg_type, data, source)

        if self.ai_server:
            t1 = int(time.time() * 1000)
            self.end=t1
            print("关闭：", self.ts_ms_to_str(t1))
            # print("总耗时：", (self.end - self.begin) / 1000, "s")
            # print("平均每张耗时：", (self.end - self.begin) / (self.ok+self.ng), "ms")

            ok, msg = self.ai_server.stop()
            # print("最终更新为-------ok:", self.ok, "----------ng:", self.ng)
            # self.save_frontend_config()

            if ok:
                self.runner_running = False
                self.ui.bnStartRun.setText("启动")
                self.ui.statusbar.showMessage("AI Server 已停止")
            else:
                self.ui.statusbar.showMessage(f"⚠ AI server未连接，同步失败: {msg}")

            t2 = int(time.time() * 1000)

            print("关闭完成：", self.ts_ms_to_str(t2))
            print("关闭耗时：", t2 - t1, "ms")

    def callback(self, result_dict):
        try:
            self.infer_result_signal.emit(result_dict)
        except Exception as e:
            logger.error(f"entry_callback emit exception: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    mainWin = MainApp()
    mainWin.show()
    sys.exit(app.exec_())

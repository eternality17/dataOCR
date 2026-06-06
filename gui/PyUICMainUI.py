# -*- coding: utf-8 -*-
from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1920, 920)

        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.verticalLayout = QtWidgets.QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName("verticalLayout")

        self.tabWidget = QtWidgets.QTabWidget(self.centralwidget)
        self.tabWidget.setObjectName("tabWidget")

        # ==========================================================
        # Tab: Chinese
        # ==========================================================
        self.tabChinese = QtWidgets.QWidget()
        self.tabChinese.setObjectName("tabChinese")
        self.horizontalLayout_cn = QtWidgets.QHBoxLayout(self.tabChinese)
        self.horizontalLayout_cn.setObjectName("horizontalLayout_cn")

        self.widget_cn_display = QtWidgets.QWidget(self.tabChinese)
        self.widget_cn_display.setObjectName("widget_cn_display")
        self.widget_cn_display.setMinimumSize(QtCore.QSize(720, 520))
        self.horizontalLayout_cn.addWidget(self.widget_cn_display)

        self.right_cn = QtWidgets.QWidget(self.tabChinese)
        self.right_cn.setObjectName("right_cn")
        self.vbox_right_cn = QtWidgets.QVBoxLayout(self.right_cn)
        self.vbox_right_cn.setObjectName("vbox_right_cn")

        self.imgGroup = QtWidgets.QGroupBox(self.right_cn)
        self.imgGroup.setObjectName("imgGroup")
        self.vbox_imgGroup = QtWidgets.QVBoxLayout(self.imgGroup)
        self.vbox_imgGroup.setObjectName("vbox_imgGroup")
        self.bnSelectImage = QtWidgets.QPushButton(self.imgGroup)
        self.bnSelectImage.setObjectName("bnSelectImage")
        self.vbox_imgGroup.addWidget(self.bnSelectImage)
        self.vbox_right_cn.addWidget(self.imgGroup)

        self.areaGroup = QtWidgets.QGroupBox(self.right_cn)
        self.areaGroup.setObjectName("areaGroup")
        self.hbox_area = QtWidgets.QHBoxLayout(self.areaGroup)
        self.hbox_area.setObjectName("hbox_area")
        self.bnDraw = QtWidgets.QPushButton(self.areaGroup)
        self.bnDraw.setObjectName("bnDraw")
        self.hbox_area.addWidget(self.bnDraw)
        self.bnReset = QtWidgets.QPushButton(self.areaGroup)
        self.bnReset.setObjectName("bnReset")
        self.hbox_area.addWidget(self.bnReset)
        self.bnConfirm = QtWidgets.QPushButton(self.areaGroup)
        self.bnConfirm.setObjectName("bnConfirm")
        self.hbox_area.addWidget(self.bnConfirm)
        self.vbox_right_cn.addWidget(self.areaGroup)

        self.textGroup_cn = QtWidgets.QGroupBox(self.right_cn)
        self.textGroup_cn.setObjectName("textGroup_cn")
        self.form_text_cn = QtWidgets.QFormLayout(self.textGroup_cn)
        self.form_text_cn.setObjectName("form_text_cn")
        self.label_line1 = QtWidgets.QLabel(self.textGroup_cn)
        self.label_line1.setObjectName("label_line1")
        self.form_text_cn.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.label_line1)
        self.line1 = QtWidgets.QLineEdit(self.textGroup_cn)
        self.line1.setObjectName("line1")
        self.form_text_cn.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.line1)
        self.label_line2 = QtWidgets.QLabel(self.textGroup_cn)
        self.label_line2.setObjectName("label_line2")
        self.form_text_cn.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.label_line2)
        self.line2 = QtWidgets.QLineEdit(self.textGroup_cn)
        self.line2.setObjectName("line2")
        self.form_text_cn.setWidget(1, QtWidgets.QFormLayout.FieldRole, self.line2)
        self.vbox_right_cn.addWidget(self.textGroup_cn)

        self.horizontalLayout_cn.addWidget(self.right_cn)
        self.tabWidget.addTab(self.tabChinese, "")

        # ==========================================================
        # Tab: Run
        # ==========================================================
        self.tabRun = QtWidgets.QWidget()
        self.tabRun.setObjectName("tabRun")
        self.horizontalLayout_run = QtWidgets.QHBoxLayout(self.tabRun)
        self.horizontalLayout_run.setObjectName("horizontalLayout_run")

        self.widget_run_display = QtWidgets.QWidget(self.tabRun)
        self.widget_run_display.setObjectName("widget_run_display")
        self.widget_run_display.setMinimumSize(QtCore.QSize(720, 520))
        self.horizontalLayout_run.addWidget(self.widget_run_display)

        self.right_run = QtWidgets.QWidget(self.tabRun)
        self.right_run.setObjectName("right_run")
        self.vbox_right_run = QtWidgets.QVBoxLayout(self.right_run)
        self.vbox_right_run.setObjectName("vbox_right_run")

        # ========== 关闭系统按钮 ==========
        self.bnExit = QtWidgets.QPushButton(self.right_run)
        self.bnExit.setObjectName("bnExit")
        self.vbox_right_run.addWidget(self.bnExit)

        self.statGroup = QtWidgets.QGroupBox(self.right_run)
        self.statGroup.setObjectName("statGroup")

        # 按行显示
        # self.vbox_stat = QtWidgets.QVBoxLayout(self.statGroup)
        # self.vbox_stat.setObjectName("vbox_stat")
        # self.ok_label = QtWidgets.QLabel(self.statGroup)
        # self.ok_label.setObjectName("ok_label")
        # self.vbox_stat.addWidget(self.ok_label)
        # self.ng_label = QtWidgets.QLabel(self.statGroup)
        # self.ng_label.setObjectName("ng_label")
        # self.vbox_stat.addWidget(self.ng_label)
        # self.total_label = QtWidgets.QLabel(self.statGroup)
        # self.total_label.setObjectName("total_label")
        # self.vbox_stat.addWidget(self.total_label)
        # self.rate_label = QtWidgets.QLabel(self.statGroup)
        # self.rate_label.setObjectName("rate_label")
        # self.vbox_stat.addWidget(self.rate_label)

        # 分两列
        self.grid_stat = QtWidgets.QGridLayout(self.statGroup)
        self.grid_stat.setObjectName("grid_stat")

        self.ok_label = QtWidgets.QLabel(self.statGroup)
        self.ok_label.setObjectName("ok_label")

        self.ng_label = QtWidgets.QLabel(self.statGroup)
        self.ng_label.setObjectName("ng_label")

        self.total_label = QtWidgets.QLabel(self.statGroup)
        self.total_label.setObjectName("total_label")

        self.rate_label = QtWidgets.QLabel(self.statGroup)
        self.rate_label.setObjectName("rate_label")

        # 两列布局
        self.grid_stat.addWidget(self.ok_label, 0, 0)
        self.grid_stat.addWidget(self.ng_label, 0, 1)
        self.grid_stat.addWidget(self.total_label, 1, 0)
        self.grid_stat.addWidget(self.rate_label, 1, 1)

        self.vbox_right_run.addWidget(self.statGroup)

        self.textGroup_run = QtWidgets.QGroupBox(self.right_run)
        self.textGroup_run.setObjectName("textGroup_run")
        self.vbox_text_run = QtWidgets.QVBoxLayout(self.textGroup_run)
        self.vbox_text_run.setObjectName("vbox_text_run")
        self.show1 = QtWidgets.QLabel(self.textGroup_run)
        self.show1.setObjectName("show1")
        self.vbox_text_run.addWidget(self.show1)
        self.show2 = QtWidgets.QLabel(self.textGroup_run)
        self.show2.setObjectName("show2")
        self.vbox_text_run.addWidget(self.show2)
        self.vbox_right_run.addWidget(self.textGroup_run)

        self.ctrlGroup = QtWidgets.QGroupBox(self.right_run)
        self.ctrlGroup.setObjectName("ctrlGroup")
        self.vbox_ctrl = QtWidgets.QVBoxLayout(self.ctrlGroup)
        self.vbox_ctrl.setObjectName("vbox_ctrl")

        self.hbox_ctrl = QtWidgets.QHBoxLayout()
        self.hbox_ctrl.setObjectName("hbox_ctrl")
        self.bnStartRun = QtWidgets.QPushButton(self.ctrlGroup)
        self.bnStartRun.setObjectName("bnStartRun")
        self.hbox_ctrl.addWidget(self.bnStartRun)
        self.bnClear = QtWidgets.QPushButton(self.ctrlGroup)
        self.bnClear.setObjectName("bnClear")
        self.hbox_ctrl.addWidget(self.bnClear)
        self.vbox_ctrl.addLayout(self.hbox_ctrl)

        self.hbox_chk = QtWidgets.QHBoxLayout()
        self.hbox_chk.setObjectName("hbox_chk")
        self.chk_save_ok = QtWidgets.QCheckBox(self.ctrlGroup)
        self.chk_save_ok.setObjectName("chk_save_ok")
        self.hbox_chk.addWidget(self.chk_save_ok)
        self.chk_send_signal = QtWidgets.QCheckBox(self.ctrlGroup)
        self.chk_send_signal.setObjectName("chk_send_signal")
        self.hbox_chk.addWidget(self.chk_send_signal)
        self.vbox_ctrl.addLayout(self.hbox_chk)

        self.vbox_right_run.addWidget(self.ctrlGroup)
        self.horizontalLayout_run.addWidget(self.right_run)
        self.tabWidget.addTab(self.tabRun, "")

        # ==========================================================
        self.verticalLayout.addWidget(self.tabWidget)
        MainWindow.setCentralWidget(self.centralwidget)

        self.statusbar = QtWidgets.QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "质检系统"))

        # Tab: Chinese
        self.imgGroup.setTitle(_translate("MainWindow", "图像输入"))
        self.bnSelectImage.setText(_translate("MainWindow", "选择图片"))
        self.areaGroup.setTitle(_translate("MainWindow", "检测区域"))
        self.bnDraw.setText(_translate("MainWindow", "绘制"))
        self.bnReset.setText(_translate("MainWindow", "重置"))
        self.bnConfirm.setText(_translate("MainWindow", "确定"))
        self.textGroup_cn.setTitle(_translate("MainWindow", "字符匹配"))
        self.label_line1.setText(_translate("MainWindow", "字符行1:"))
        self.label_line2.setText(_translate("MainWindow", "字符行2:"))
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tabChinese),
            _translate("MainWindow", "ROI内容设置")
        )

        # Tab: Run
        self.statGroup.setTitle(_translate("MainWindow", "统计"))
        self.bnExit.setText(_translate("MainWindow", "关闭系统"))
        self.ok_label.setText(_translate("MainWindow", "OK: 0"))
        self.ng_label.setText(_translate("MainWindow", "NG: 0"))
        self.total_label.setText(_translate("MainWindow", "检测: 0"))
        self.rate_label.setText(_translate("MainWindow", "合格率: 0%"))
        self.textGroup_run.setTitle(_translate("MainWindow", "字符匹配"))
        self.show1.setText(_translate("MainWindow", "字符行1:"))
        self.show2.setText(_translate("MainWindow", "字符行2:"))
        self.ctrlGroup.setTitle(_translate("MainWindow", "控制"))
        self.bnStartRun.setText(_translate("MainWindow", "启动"))
        self.bnClear.setText(_translate("MainWindow", "清零"))
        self.chk_save_ok.setText(_translate("MainWindow", "保存 OK 图片"))
        self.chk_send_signal.setText(_translate("MainWindow", "发送信号"))
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tabRun),
            _translate("MainWindow", "运行界面")
        )

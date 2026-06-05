# main.py

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

from TCP_UI.MainApp import MainApp

SERVER_NAME = "MyQtAppSingleton"


# -----------------------------
# 判断是否已有实例运行
# -----------------------------
def is_running():
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)

    if socket.waitForConnected(300):
        # 已运行 → 发送唤醒信号
        try:
            socket.write(b"activate")
            socket.flush()
            socket.waitForBytesWritten(300)
        except Exception:
            pass
        return True

    return False


# -----------------------------
# 主程序入口
# -----------------------------
def main():
    app = QApplication(sys.argv)

    # 🚨 如果已运行 → 直接退出
    if is_running():
        print("程序已运行，已唤醒窗口")
        sys.exit(0)

    # ✅ 清理异常残留（很重要）
    QLocalServer.removeServer(SERVER_NAME)

    # ✅ 创建唯一实例服务
    server = QLocalServer()
    if not server.listen(SERVER_NAME):
        print("无法创建本地服务")
        sys.exit(1)

    # -----------------------------
    # 创建主窗口
    # -----------------------------
    mainWin = MainApp()
    mainWin.show()

    # -----------------------------
    # 收到唤醒信号
    # -----------------------------
    def handle_new_connection():
        client = server.nextPendingConnection()
        if client:
            client.readAll()

        print("收到唤醒信号")

        # ✅ 恢复窗口
        mainWin.showNormal()
        mainWin.activateWindow()
        mainWin.raise_()

    server.newConnection.connect(handle_new_connection)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
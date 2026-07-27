from __future__ import annotations

import math
from PyQt6.QtWidgets import (
    QPushButton,
    QStyledItemDelegate,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
    QFrame,
    QGridLayout,
    QStyle,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPainter, QColor


class WorkerThread(QThread):
    finished = pyqtSignal(object)
    progress = pyqtSignal(int)

    def __init__(self, target, *args):
        super().__init__()
        self.target = target
        self.args = args

    def run(self):
        res = self.target(*self.args)

        if hasattr(res, 'send'):
            try:
                while True:
                    prog = next(res)
                    if isinstance(prog, int):
                        self.progress.emit(prog)
            except StopIteration as e:
                self.finished.emit(e.value)
        else:
            self.finished.emit(res)


class ModernButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class NoFocusDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter | None, option, index):
        if painter is None:
            return
        painter.save()

        is_selected = option.state & QStyle.StateFlag.State_Selected
        is_mouseover = option.state & QStyle.StateFlag.State_MouseOver

        if is_selected or is_mouseover:
            bg_color = QColor("#d63333")
        else:
            bg_color = QColor("#333333")

        painter.fillRect(option.rect, bg_color)

        text = index.data()
        painter.setPen(QColor("white"))
        rect = option.rect
        rect.setLeft(rect.left() + 2)
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 30)


class CoreTempDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Core Temperatures")
        self.resize(600, 400)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; }
            QLabel { font-size: 14px; padding: 2px; }
            QLabel[class="val"] { font-weight: bold; color: #d63333; }
            QLabel[class="pkg"] { font-size: 18px; font-weight: bold; color: #fff; padding: 10px; }
            QLabel[class="pkg_val"] { font-size: 24px; font-weight: bold; color: #d63333; }
        """)

        self.layout_main = QVBoxLayout(self)

        self.pkg_widget = QWidget()
        pkg_layout = QHBoxLayout(self.pkg_widget)
        pkg_layout.setContentsMargins(20, 10, 20, 10)

        self.lbl_cpu_name = QLabel("CPU Package 0")
        self.lbl_cpu_name.setProperty("class", "pkg")
        self.lbl_cpu_val = QLabel("--°C")
        self.lbl_cpu_val.setProperty("class", "pkg_val")

        self.lbl_gpu_name = QLabel("GPU")
        self.lbl_gpu_name.setProperty("class", "pkg")
        self.lbl_gpu_val = QLabel("--°C")
        self.lbl_gpu_val.setProperty("class", "pkg_val")

        pkg_layout.addWidget(self.lbl_cpu_name)
        pkg_layout.addWidget(self.lbl_cpu_val)
        pkg_layout.addSpacing(40)
        pkg_layout.addWidget(self.lbl_gpu_name)
        pkg_layout.addWidget(self.lbl_gpu_val)
        pkg_layout.addStretch()

        self.layout_main.addWidget(self.pkg_widget)

        self.grid_widget = QWidget()
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setSpacing(10)

        self.layout_main.addWidget(self.grid_widget)

        btn = ModernButton("Close")
        btn.clicked.connect(self.accept)
        self.layout_main.addWidget(btn)

        self.temp_labels: dict[str, QLabel] = {}

        self.refresh_temps()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_temps)
        self.timer.start(2000)

    def refresh_temps(self):
        temps = self.controller.get_all_core_temps()
        if not temps:
            return

        clean_temps = []
        package_found = None

        for label, temp in temps:
            clean_label = label.replace("id ", "").replace("id", "")
            if "Package" in clean_label:
                package_found = (clean_label, temp)
            else:
                clean_temps.append((clean_label, temp))

        if package_found:
            self.lbl_cpu_name.setText("CPU Package 0")
            self.lbl_cpu_val.setText(f"{package_found[1]}°C")
        else:
            self.lbl_cpu_name.setText("CPU")
            self.lbl_cpu_val.setText("--°C")

        gpu_temp = self.controller.get_gpu_temp()
        if gpu_temp > 0:
            self.lbl_gpu_name.setText("GPU Temperature")
            self.lbl_gpu_val.setText(f"{gpu_temp}°C")
            self.lbl_gpu_name.setVisible(True)
            self.lbl_gpu_val.setVisible(True)
        else:
            self.lbl_gpu_name.setVisible(False)
            self.lbl_gpu_val.setVisible(False)

        if not self.temp_labels or len(self.temp_labels) != len(clean_temps):
            self.build_grid(clean_temps)
        else:
            for label, temp in clean_temps:
                if label in self.temp_labels:
                    self.temp_labels[label].setText(f"{temp}°C")
                else:
                    self.build_grid(clean_temps)
                    return

    def build_grid(self, temps: list):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self.temp_labels = {}

        n = len(temps)
        if n == 0:
            return

        cols = math.ceil(math.sqrt(n * 1.5))

        for i, (label, temp) in enumerate(temps):
            row = i // cols
            col = i % cols

            item = QFrame()
            item.setStyleSheet("background-color: #252526; border-radius: 5px;")
            il = QVBoxLayout(item)

            lbl_name = QLabel(label)
            lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)

            lbl_val = QLabel(f"{temp}°C")
            lbl_val.setProperty("class", "val")
            lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_val.setStyleSheet("font-size: 18px; font-weight: bold; color: #d63333;")

            il.addWidget(lbl_name)
            il.addWidget(lbl_val)

            self.grid.addWidget(item, row, col)
            self.temp_labels[label] = lbl_val

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
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self):
        res = self.target(*self.args)

        if hasattr(res, 'send'):
            try:
                while True:
                    if self._stop_requested:
                        res.close()
                        return
                    prog = next(res)
                    if isinstance(prog, int):
                        self.progress.emit(prog)
            except StopIteration as e:
                if not self._stop_requested:
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


class FanSpeedDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Fan Speeds")
        self.setFixedSize(320, 140)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QFrame#FanCard {
                background-color: #252526;
                border: 1px solid #383838;
                border-radius: 6px;
            }
            QLabel {
                background-color: transparent;
                border: none;
                padding: 0px;
            }
            QLabel#FanTitle {
                font-size: 12px;
                font-weight: 600;
                color: #aaa;
            }
            QLabel#FanVal {
                font-size: 17px;
                font-weight: bold;
                color: #d63333;
            }
            QLabel#FanRev {
                font-size: 10px;
                font-weight: bold;
                color: #e65100;
            }
            QPushButton#CloseBtn {
                background-color: #333;
                color: #ccc;
                font-size: 12px;
                padding: 4px 16px;
                border-radius: 3px;
                border: 1px solid #444;
            }
            QPushButton#CloseBtn:hover {
                background-color: #444;
                color: #fff;
                border-color: #666;
            }
        """)

        self.layout_main = QVBoxLayout(self)
        self.layout_main.setContentsMargins(14, 12, 14, 12)
        self.layout_main.setSpacing(10)

        self.cards_widget = QWidget()
        self.cards_layout = QHBoxLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)

        self.layout_main.addWidget(self.cards_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn = QPushButton("Close")
        btn.setObjectName("CloseBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.accept)
        btn_row.addWidget(btn)
        btn_row.addStretch()
        self.layout_main.addLayout(btn_row)

        self.fan_cards: dict[str, tuple[QLabel, QLabel]] = {}
        self.refresh_fans()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_fans)
        self.timer.start(1000)

    def refresh_fans(self):
        fans = self.controller.get_both_fan_speeds()
        if not fans:
            return

        if not self.fan_cards:
            for name, rpm, is_rev in fans:
                card = QFrame()
                card.setObjectName("FanCard")
                card_layout = QVBoxLayout(card)
                card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                card_layout.setContentsMargins(10, 8, 10, 8)
                card_layout.setSpacing(2)

                lbl_name = QLabel(name)
                lbl_name.setObjectName("FanTitle")
                lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)

                rpm_text = f"-{rpm} RPM" if (is_rev and rpm > 0) else f"{rpm} RPM"
                lbl_val = QLabel(rpm_text)
                lbl_val.setObjectName("FanVal")
                lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)

                lbl_rev = QLabel("(Reverse)" if (is_rev and rpm > 0) else "")
                lbl_rev.setObjectName("FanRev")
                lbl_rev.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if not (is_rev and rpm > 0):
                    lbl_rev.setVisible(False)

                card_layout.addWidget(lbl_name)
                card_layout.addWidget(lbl_val)
                card_layout.addWidget(lbl_rev)

                self.cards_layout.addWidget(card)
                self.fan_cards[name] = (lbl_val, lbl_rev)
        else:
            for name, rpm, is_rev in fans:
                if name in self.fan_cards:
                    lbl_val, lbl_rev = self.fan_cards[name]
                    rpm_text = f"-{rpm} RPM" if (is_rev and rpm > 0) else f"{rpm} RPM"
                    lbl_val.setText(rpm_text)
                    if is_rev and rpm > 0:
                        lbl_rev.setText("(Reverse)")
                        lbl_rev.setVisible(True)
                    else:
                        lbl_rev.setVisible(False)



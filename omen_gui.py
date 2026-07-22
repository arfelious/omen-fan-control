import sys
import os
import signal
import json
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QFrame, QStackedWidget,
                            QComboBox, QSpinBox, QMessageBox, QTabWidget, QFileDialog,
                            QProgressBar, QScrollArea, QSizePolicy, QListView, QTextEdit, QStyle, 
                            QStyledItemDelegate, QCheckBox, QGraphicsDropShadowEffect, QLineEdit)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QFont, QIcon, QAction, QColor, QPainter, QBrush, QPen
from omen_logic import FanController, OMEN_FAN_DIR
from fan_curve_widget import FanCurveEditor

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
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

class NoFocusDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
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

    def sizeHint(self, option, index):
        return QSize(0, 30)

from PyQt6.QtWidgets import QDialog, QGridLayout

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
        
        # Top Package Section
        self.pkg_widget = QWidget()
        pkg_layout = QHBoxLayout(self.pkg_widget)
        pkg_layout.setContentsMargins(20, 10, 20, 10)
        
        # CPU Side
        self.lbl_cpu_name = QLabel("CPU Package 0")
        self.lbl_cpu_name.setProperty("class", "pkg")
        self.lbl_cpu_val = QLabel("--°C")
        self.lbl_cpu_val.setProperty("class", "pkg_val")
        
        # GPU Side
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
        
        # Init labels dict to update later
        self.temp_labels = {} 
        
        # Initial populate
        self.refresh_temps()
        
        # Auto refresh timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_temps)
        self.timer.start(2000)
        
    def refresh_temps(self):
        temps = self.controller.get_all_core_temps()
        if not temps: return
        
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
                    
    def build_grid(self, temps):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()
        self.temp_labels = {}
        
        import math
        n = len(temps)
        if n == 0: return
        
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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HP Omen Fan Control")
        self.resize(900, 600)
        
        # Set Window Icon
        icon_path = OMEN_FAN_DIR / "assets" / "logo_test.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        self.controller = FanController()
        self.watchdog_timer = QTimer()
        self.watchdog_timer.timeout.connect(self.run_watchdog)
        
        self.temp_history = []
        self.temp_history_len = self.controller.config.get("ma_window", 5)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        self.main_layout = QVBoxLayout(main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.nav_bar = QWidget()
        self.nav_bar.setObjectName("NavBar")
        nav_layout = QHBoxLayout(self.nav_bar)
        
        left_layout = QHBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("BackBtn")
        self.back_btn.setFixedWidth(60)
        self.back_btn.clicked.connect(self.go_home)
        self.back_btn.setVisible(False)
        left_layout.addWidget(self.back_btn)
        
        self.rpm_label = QLabel("0 RPM")
        self.rpm_label.setObjectName("HeaderRPM")
        self.rpm_label.setFixedWidth(120)
        left_layout.addWidget(self.rpm_label)
        
        nav_layout.addLayout(left_layout)
        
        self.title_label = QLabel("HP Omen Fan Control")
        self.title_label.setObjectName("Title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self.title_label, 1)
        
        self.sensor_pill = QFrame()
        self.sensor_pill.setObjectName("SensorPill")
        self.sensor_pill.setFixedSize(84, 24)
        pill_layout = QHBoxLayout(self.sensor_pill)
        pill_layout.setContentsMargins(2, 2, 2, 2)
        pill_layout.setSpacing(0)
        pill_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.cpu_pill_btn = QPushButton("CPU")
        self.cpu_pill_btn.setFixedSize(40, 20)
        self.cpu_pill_btn.clicked.connect(lambda: self.set_reference_sensor("cpu"))
        
        self.gpu_pill_btn = QPushButton("GPU")
        self.gpu_pill_btn.setFixedSize(40, 20)
        self.gpu_pill_btn.clicked.connect(lambda: self.set_reference_sensor("gpu"))
        
        pill_layout.addWidget(self.cpu_pill_btn)
        pill_layout.addWidget(self.gpu_pill_btn)
        nav_layout.addWidget(self.sensor_pill, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # Hide GPU side if not present
        if not self.controller.has_gpu():
            self.gpu_pill_btn.setVisible(False)
            self.sensor_pill.setFixedSize(44, 24) # Shrink pill

        self.temp_label = QLabel("0°C")
        self.temp_label.setObjectName("HeaderTemp")
        self.temp_label.setFixedWidth(70)
        self.temp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.temp_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.temp_label.mousePressEvent = self.show_core_temps
        nav_layout.addWidget(self.temp_label, alignment=Qt.AlignmentFlag.AlignRight)
        
        self.main_layout.addWidget(self.nav_bar)

        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)
        
        self.init_home_page()
        self.init_fan_control_page()
        self.init_calibration_page()
        self.init_driver_page()
        self.init_options_page()
        self.init_about_page()
        
        # Initialize cleaner page if system/board supports Fan Cleaner
        if self.controller.check_fan_cleaner_capability():
            self.init_cleaner_page()
        
        self.apply_dark_theme()
        
        self.status_label = QLabel("Checking...")
        self.status_label.setStyleSheet("color: #888; padding: 5px;")
        self.status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_label.mousePressEvent = self.on_status_click
        self.statusBar().addWidget(self.status_label)
        
        self.svc_status_label = QLabel("Service: Checking...")
        self.svc_status_label.setStyleSheet("color: #888;")
        self.statusBar().addPermanentWidget(self.svc_status_label)
        self.statusBar().setSizeGripEnabled(False)
        
        self.svc_timer = QTimer()
        self.svc_timer.timeout.connect(self.check_service_status)
        self.svc_timer.start(5000)
        self.check_service_status()
        
        self.rpm_timer = QTimer()
        self.rpm_timer.timeout.connect(self.update_status)
        self.rpm_timer.start(2000)
        self.update_status()

        self.update_cursors()
        self.center_window()

        self.center_window()

        # Root Check
        if os.geteuid() != 0 and not self.controller.config.get("bypass_root_warning", False):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Root Privileges Required")
            msg.setText("This application is not running as root.")
            msg.setInformativeText("Most features (fan control, driver installation) require root privileges to function correctly.\n\nIt is recommended to run this application with 'sudo'.")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            
            chk = QCheckBox("Don't show this again")
            msg.setCheckBox(chk)
            
            msg.exec()
            
            if chk.isChecked():
                self.controller.config["bypass_root_warning"] = True
                self.controller.save_config()

        if not self.controller.config.get("bypass_patch_warning", False) or self.controller.config.get("debug_experimental_ui", False):
            support_status, board_name = self.controller.check_board_support()
            
            if support_status == "UNSUPPORTED" and not self.controller.config.get("debug_experimental_ui", False):
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Unsupported Device")
                msg.setText(f"Warning: Your board '{board_name}' is not in the known compatible list.")
                msg.setInformativeText("This application could potentially cause system instability or damage on unsupported hardware.\n\nProceed at your own risk?")
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msg.setDefaultButton(QMessageBox.StandardButton.No)
                
                chk = QCheckBox("Don't show this again")
                msg.setCheckBox(chk)
                
                ret = msg.exec()
                
                if ret == QMessageBox.StandardButton.Yes:
                    if chk.isChecked():
                        self.controller.config["bypass_patch_warning"] = True
                        self.controller.save_config()
                else:
                    sys.exit(0)
            
            elif (support_status == "POSSIBLY_SUPPORTED" and not self.controller.config.get("enable_experimental", False)) or self.controller.config.get("debug_experimental_ui", False):
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Question)
                msg.setWindowTitle("Experimental Support Available")
                
                text = (f"Your board ({board_name}) is not officially verified, but community patches suggest it uses the Omen thermal path.\n\n"
                        "Enable Experimental List Support? This will attempt to load the kernel driver with Omen Thermal Profile. "
                        "If your fans behave erratically or controls don't work, disable this in Settings.")
                
                msg.setText(text)
                
                enable_btn = msg.addButton("Enable Experimental List Support", QMessageBox.ButtonRole.YesRole)
                msg.addButton("No", QMessageBox.ButtonRole.NoRole)
                msg.setDefaultButton(enable_btn)
                
                chk = QCheckBox("Don't ask again")
                msg.setCheckBox(chk)
                
                msg.exec()
                
                if msg.clickedButton() == enable_btn:
                    self.controller.config["enable_experimental"] = True
                    self.controller.config["thermal_profile"] = "omen"
                    if chk.isChecked():
                        self.controller.config["bypass_patch_warning"] = True
                    self.controller.save_config()
                    QMessageBox.information(self, "Enabled", "Experimental support enabled.\nPlease go to 'Driver Management' to install/update the driver patch.")
                    
                    # Force update options page if it exists
                    if hasattr(self, 'exp_check'):
                         self.exp_check.setChecked(True)
                         self.toggle_experimental_options(True)
                
                if chk.isChecked():
                    self.controller.config["bypass_patch_warning"] = True
                    self.controller.save_config()
                    
                if self.controller.config.get("debug_experimental_ui"):
                     print("Debug experimental UI shown.")

    def update_cursors(self):
        """Sets pointing hand cursor for non-destructive interactive elements."""
        for widget in self.findChildren((QPushButton, QComboBox, QCheckBox, QSpinBox)):
            is_destructive = False
            if isinstance(widget, QPushButton):
                text = widget.text().lower()
                # Define destructive keywords
                if any(x in text for x in ["remove service", "uninstall", "restore original", "disable bios"]):
                    is_destructive = True
            
            if not is_destructive:
                widget.setCursor(Qt.CursorShape.PointingHandCursor)

    def center_window(self):
        qr = self.frameGeometry()
        cp = self.screen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def apply_dark_theme(self):
        style = """
        QMainWindow { background-color: #1e1e1e; }
        QWidget { background-color: #1e1e1e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; }
        
        #NavBar { background-color: #252526; border-bottom: 1px solid #333; }
        #Title { font-size: 20px; font-weight: bold; color: #fff; background-color: transparent; }
        #HeaderRPM { font-size: 16px; color: #aaa; font-weight: bold; padding-left: 10px; }
        #HeaderTemp { font-size: 16px; color: #d63333; font-weight: bold; padding-right: 10px; }
        #HeaderTemp:hover { color: #ff6666; }
        
        #SensorPill { 
            background-color: #252526; 
            border-radius: 12px; 
            border: 1px solid #444; 
            margin-right: 10px;
            max-height: 24px;
            min-height: 24px;
        }
        #SensorPill QPushButton { 
            font-size: 9px; 
            font-weight: bold; 
            background-color: transparent; 
            color: #888; 
            border-radius: 10px;
            padding: 0px;
            margin: 0px;
            border: none;
            max-height: 20px;
            min-height: 20px;
        }
        #SensorPill QPushButton:hover { color: #ccc; }
        #SensorPill QPushButton[active="true"] { 
            background-color: #d63333; 
            color: white; 
        }
        
        #BackBtn { background-color: #3e3e42; border: none; padding: 8px; color: white; border-radius: 4px; }
        #BackBtn:hover { background-color: #505050; }
        
        QPushButton { font-size: 14px; padding: 10px 20px; border: none; border-radius: 5px; background-color: #333; color: white; outline: none; }
        QPushButton:hover { background-color: #444; }
        QPushButton:pressed { background-color: #2a2a2a; }
        QPushButton:focus { outline: none; border: none; }
        
        /* Modern Button Special Class */
        QPushButton[class="menu"] { font-size: 16px; text-align: center; padding: 15px; background-color: #2d2d30; margin: 10px; border: 1px solid #3e3e42; }
        QPushButton[class="menu"]:hover { background-color: #3e3e42; border-color: #d63333; }
        
        QComboBox { 
            padding: 2px;
            font-size: 14px; 
            background-color: #333; 
            color: white; 
            border: 1px solid #555; 
            border-radius: 3px; 
            min-width: 150px; 
        }
        QComboBox:focus { border: 1px solid #777; }
        
        QComboBox QAbstractItemView {
            background-color: #333; 
            color: white; 
            border: 1px solid #555;
            selection-background-color: #d63333;
            outline: 0px; 
            min-width: 152px;
        }
        
        QComboBox QAbstractItemView::item {
            height: 30px; 
            margin: 0px;
            padding: 0px;
            border: none; 
            outline: none;
        }
        
        QComboBox QAbstractItemView::item:selected {
            background-color: #d63333;
            border: none;
            outline: none;
        }

        QComboBox::drop-down { border: 0px; }
        QComboBox::down-arrow { 
            image: none; 
            border-left: 5px solid transparent; 
            border-right: 5px solid transparent; 
            border-top: 5px solid white; 
            margin-right: 5px; 
        }
        QComboBox:hover { border-color: #777; }
        
        QSpinBox { padding: 5px; background-color: #333; color: white; border: 1px solid #555; border-radius: 3px; min-height: 25px; }
        QSpinBox::up-button, QSpinBox::down-button {
            width: 25px;
            background: #3e3e42;
            border: none;
            border-left: 1px solid #555;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background: #505050;
        }
        QSpinBox::up-button {
            border-bottom: 1px solid #555;
            border-top-right-radius: 3px;
        }
        QSpinBox::down-button {
            border-bottom-right-radius: 3px;
        }
        
        QSpinBox::up-arrow {
            image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDEyIDEyIj48cGF0aCBmaWxsPSIjZmZmZmZmIiBkPSJNNiAzTDIgOWg4eiIvPjwvc3ZnPg==);
            width: 10px; 
            height: 10px;
            border: none;
            subcontrol-origin: margin;
            subcontrol-position: center center;
        }
        QSpinBox::down-arrow {
            image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDEyIDEyIj48cGF0aCBmaWxsPSIjZmZmZmZmIiBkPSJNNiA5TDIgM2g4eiIvPjwvc3ZnPg==);
            width: 10px; 
            height: 10px;
            border: none;
            subcontrol-origin: margin;
            subcontrol-position: center center;
        }
        
        QProgressBar { text-align: center; border: 1px solid #555; border-radius: 3px; background-color: #333; }
        QProgressBar::chunk { background-color: #d63333; }
        
        QTabWidget::pane { border: 1px solid #444; }
        """
        self.setStyleSheet(style)

    def init_home_page(self):
        self.home_page = QWidget()
        layout = QVBoxLayout(self.home_page)
        layout.addStretch()
        
        menu_items = [
            ("Fan Control", self.show_fan_control),
            ("Calibration", self.show_calibration),
            ("Driver Management", self.show_driver),
        ]
        
        # Check if system/board supports Fan Cleaner
        if self.controller.check_fan_cleaner_capability():
            menu_items.append(("Fan Cleaner", self.show_fan_cleaner))
            
        menu_items.extend([
            ("Options", self.show_options),
            ("About", self.show_about),
        ])
        
        for text, func in menu_items:
            btn = ModernButton(text)
            btn.setProperty("class", "menu")
            btn.setFixedWidth(300)
            btn.clicked.connect(func)
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
            
        layout.addStretch()
        self.stack.addWidget(self.home_page)

    def init_fan_control_page(self):
        self.fan_page = QWidget()
        self.fan_layout = layout = QVBoxLayout(self.fan_page)
        
        layout.addStretch()
        
        self.mode_container = container = QFrame()
        container.setStyleSheet("background-color: #252526; border-radius: 10px; padding: 10px 15px;")
        container.setFixedWidth(600)
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(4)
        c_layout.setContentsMargins(0, 0, 0, 0)
        
        mode_layout = QHBoxLayout()
        mode_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        lbl_mode = QLabel("Mode:")
        lbl_mode.setStyleSheet("font-size: 18px; font-weight: bold; color: #ddd;")
        mode_layout.addWidget(lbl_mode)
        
        self.mode_combo = QComboBox()
        self.mode_combo.setView(QListView()) # Force standard list view for consistent styling
        self.mode_combo.setItemDelegate(NoFocusDelegate()) # Fix focus rect artifact
        self.mode_combo.addItems(["Auto", "Max", "Manual", "Curve"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_change)
        mode_layout.addWidget(self.mode_combo)
        
        mode_layout.addSpacing(15)
        
        self.set_btn = QPushButton("Set Mode")
        self.set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_btn.setFixedWidth(120)
        self.set_btn.setStyleSheet("background-color: #d63333; font-weight: bold; padding: 10px; border-radius: 2px;")
        self.set_btn.clicked.connect(self.apply_fan_mode)
        mode_layout.addWidget(self.set_btn)
        
        c_layout.addLayout(mode_layout)
        
        self.manual_widget = QWidget()
        manual_outer_layout = QVBoxLayout(self.manual_widget)
        manual_outer_layout.setContentsMargins(0, 5, 0, 0)
        
        manual_row = QWidget()
        manual_row_layout = QHBoxLayout(manual_row)
        manual_row_layout.setContentsMargins(0, 0, 0, 0)
        manual_row_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        manual_row_layout.addWidget(QLabel("Manual Speed (0-100%):"))
        self.manual_spin = QSpinBox()
        self.manual_spin.setRange(0, 100)
        self.manual_spin.setSingleStep(5)
        self.manual_spin.setValue(50)
        self.manual_spin.setFixedHeight(40) 
        self.manual_spin.setStyleSheet("padding: 8px")
        self.manual_spin.valueChanged.connect(self.on_manual_changed)
        manual_row_layout.addWidget(self.manual_spin)
        
        manual_outer_layout.addWidget(manual_row)
        
        self.manual_unsaved_lbl = QLabel("Unsaved Changes")
        self.manual_unsaved_lbl.setVisible(False)
        self.manual_unsaved_lbl.setStyleSheet("color: #e65100; font-size: 11px; font-weight: bold;")
        
        # Do not retain size when hidden so container shrinks when no unsaved changes exist
        sp = self.manual_unsaved_lbl.sizePolicy()
        sp.setRetainSizeWhenHidden(False)
        self.manual_unsaved_lbl.setSizePolicy(sp)
        
        manual_outer_layout.addWidget(self.manual_unsaved_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        
        self.manual_widget.setVisible(False)
        c_layout.addWidget(self.manual_widget)
        layout.addWidget(container, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Curve Editor Container (Sits directly below Mode container)
        self.curve_editor_container = QWidget()
        self.curve_editor_container.setFixedHeight(360)
        curve_layout = QVBoxLayout(self.curve_editor_container)
        curve_layout.setContentsMargins(0, 5, 0, 5)
        curve_header = QHBoxLayout()
        lbl_curve_title = QLabel("Fan Curve Editor")
        lbl_curve_title.setToolTip("Controls:\n• Left-Click Drag: Move Point\n• Right-Click: Add New Point\n• Middle-Click: Remove Point")
        curve_header.addWidget(lbl_curve_title)
        
        lbl_hint = QLabel("(Right-click: Add | Middle-click: Remove)")
        lbl_hint.setStyleSheet("color: #777; font-size: 11px; margin-left: 8px;")
        curve_header.addWidget(lbl_hint)
        curve_header.addStretch()
        
        saved_curve = self.controller.config.get("curve", [])
        self.curve_editor = FanCurveEditor(points=saved_curve if saved_curve else None)
        self.curve_editor.curveChanged.connect(self.on_curve_changed)

        reset_btn = QPushButton("Reset Curve")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setFixedWidth(100)
        reset_btn.setStyleSheet("background-color: #444; font-size: 11px; padding: 4px; border-radius: 3px; color: white;")
        reset_btn.clicked.connect(lambda: self.reset_curve())
        curve_header.addWidget(reset_btn)
        
        curve_layout.addLayout(curve_header)
        curve_layout.addWidget(self.curve_editor)
        
        unsaved_row = QHBoxLayout()
        unsaved_row.addStretch()

        self.curve_unsaved_lbl = QLabel("Unsaved Changes")
        self.curve_unsaved_lbl.setVisible(False)
        self.curve_unsaved_lbl.setStyleSheet("color: #e65100; font-size: 11px; font-weight: bold; margin-right: 8px;") 
        sp_lbl = self.curve_unsaved_lbl.sizePolicy()
        sp_lbl.setRetainSizeWhenHidden(True)
        self.curve_unsaved_lbl.setSizePolicy(sp_lbl)
        unsaved_row.addWidget(self.curve_unsaved_lbl)

        self.curve_revert_btn = QPushButton("Revert")
        self.curve_revert_btn.setVisible(False)
        self.curve_revert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.curve_revert_btn.setFixedWidth(70)
        self.curve_revert_btn.setStyleSheet("""
            QPushButton { background-color: #333; color: #ddd; font-size: 11px; padding: 3px 8px; border-radius: 3px; border: 1px solid #555; }
            QPushButton:hover { background-color: #444; color: #fff; border: 1px solid #777; }
        """)
        self.curve_revert_btn.clicked.connect(self.revert_curve)
        sp_btn = self.curve_revert_btn.sizePolicy()
        sp_btn.setRetainSizeWhenHidden(True)
        self.curve_revert_btn.setSizePolicy(sp_btn)
        unsaved_row.addWidget(self.curve_revert_btn)

        curve_layout.addLayout(unsaved_row)
        
        self.curve_editor_container.setVisible(False)
        layout.addWidget(self.curve_editor_container)

        # Stress Test Controls (Always visible)
        self.stress_widget = QWidget()
        stress_layout = QHBoxLayout(self.stress_widget)
        stress_layout.setContentsMargins(0, 5, 0, 5)
        stress_layout.addStretch() # Add stretch at start to center
        stress_layout.addWidget(QLabel("CPU Stress Test:"))
        
        self.stress_duration = QComboBox()
        self.stress_duration.setView(QListView())
        self.stress_duration.setItemDelegate(NoFocusDelegate())
        self.stress_duration.addItems(["30s", "1m", "5m", "30m", "Indefinite"])
        self.stress_duration.setFixedWidth(80)
        stress_layout.addWidget(self.stress_duration)
        
        stress_layout.addSpacing(15)
        
        self.stress_btn = QPushButton("Start Stress")
        self.stress_btn.setCheckable(True)
        self.stress_btn.setFixedWidth(110)
        self.stress_btn.setStyleSheet("""
            QPushButton { background-color: #d63333; font-weight: bold; margin: 0px; border: none; padding: 5px; border-radius: 4px; color: white; }
            QPushButton:checked { background-color: #b71c1c; } 
            QPushButton:hover { background-color: #ef5350; }
        """)
        self.stress_btn.toggled.connect(self.toggle_stress_test)
        stress_layout.addWidget(self.stress_btn)
        
        stress_layout.addStretch()
        
        layout.addWidget(self.stress_widget)

        # Watchdog
        self.watchdog_check = QCheckBox("Enable Watchdog (Reset every 90s)")
        self.watchdog_check.toggled.connect(self.toggle_watchdog)
        layout.addWidget(self.watchdog_check)
        
        # Stretch at bottom pushes everything up snugly
        layout.addStretch()
        
        # Restore last saved mode and manual speed
        self.restore_saved_fan_settings()
        self.stack.addWidget(self.fan_page)

    def restore_saved_fan_settings(self):
        saved_mode = self.controller.config.get("mode", "auto").capitalize()
        if saved_mode in ["Auto", "Max", "Manual", "Curve"]:
            self.mode_combo.setCurrentText(saved_mode)
            
        saved_pwm = self.controller.config.get("manual_pwm", -1)
        if saved_pwm >= 0:
            percent_val = int(round((saved_pwm / 255.0) * 100))
            self.manual_spin.setValue(min(max(percent_val, 0), 100))

        self.on_mode_change(self.mode_combo.currentText())

    def init_calibration_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        center_widget = QWidget()
        c_layout = QVBoxLayout(center_widget)
        
        info = QLabel("Calibration spins fans at 100% speed for 30s to determine the Max RPM capability of your system.")
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(info)
        
        c_layout.addSpacing(20)
        
        self.cal_btn = QPushButton("Start Calibration")
        self.cal_btn.setFixedWidth(200)
        self.cal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cal_btn.clicked.connect(self.toggle_calibration)
        c_layout.addWidget(self.cal_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        c_layout.addSpacing(20)
        
        self.cal_progress = QProgressBar()
        self.cal_progress.setFixedWidth(300)
        self.cal_progress.setVisible(False)
        c_layout.addWidget(self.cal_progress, alignment=Qt.AlignmentFlag.AlignCenter)
        
        c_layout.addSpacing(20)
        
        self.cal_result = QLabel("")
        self.cal_result.setStyleSheet("font-size: 18px; color: #d63333; font-weight: bold;")
        self.cal_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(self.cal_result, alignment=Qt.AlignmentFlag.AlignCenter)
        
        layout.addStretch()
        layout.addWidget(center_widget)
        layout.addStretch()
        
        self.stack.addWidget(page)

    def init_driver_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        lbl = QLabel("Install drivers to enable functionality.")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 16px; margin-top: 10px;")
        layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        
        center_widget = QWidget()
        c_layout = QVBoxLayout(center_widget)
        
        c_layout.addSpacing(15)
        
        temp_btn = QPushButton("Install Patch (Temporary)")
        temp_btn.setFixedWidth(320)
        temp_btn.clicked.connect(lambda: self.run_driver_task("temp"))
        c_layout.addWidget(temp_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        lbl_temp = QLabel("Use for testing. Resets on reboot.")
        lbl_temp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(lbl_temp)
        
        c_layout.addSpacing(25)
        
        perm_btn = QPushButton("Install Patch (Permanent)")
        perm_btn.setFixedWidth(320)
        perm_btn.clicked.connect(lambda: self.run_driver_task("perm"))
        c_layout.addWidget(perm_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        lbl_perm = QLabel("Patches and installs kernel module. Persists after reboot.")
        lbl_perm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(lbl_perm)
        
        c_layout.addSpacing(25)
        
        restore_btn = QPushButton("Uninstall / Restore Original Driver")
        restore_btn.setFixedWidth(320)
        restore_btn.setStyleSheet("background-color: #555; color: white;")
        restore_btn.clicked.connect(lambda: self.run_driver_task("restore"))
        c_layout.addWidget(restore_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        lbl_restore = QLabel("Restores .bak files and reloads original driver.")
        lbl_restore.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(lbl_restore)
        
        layout.addStretch()
        layout.addWidget(center_widget)
        layout.addStretch()
        
        self.stack.addWidget(page)

    def init_options_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        form_widget = QWidget()
        form_grid = QGridLayout(form_widget)
        form_grid.setSpacing(20)
        form_grid.setVerticalSpacing(15)
        
        lbl1 = QLabel("Calibration Wait Time (s):")
        lbl1.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lbl1.setToolTip("Calibration Wait Time: How long (in seconds) the system waits at max fan speed to get a stable RPM reading during calibration.")
        form_grid.addWidget(lbl1, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.wait_spin = QSpinBox()
        self.wait_spin.setRange(5, 300)
        self.wait_spin.setFixedWidth(80) 
        self.wait_spin.setValue(self.controller.config.get("calibration_wait", 30))
        self.wait_spin.setToolTip("Calibration Wait Time: How long (in seconds) the system waits at max fan speed to get a stable RPM reading during calibration.")
        self.wait_spin.valueChanged.connect(self.save_options)
        form_grid.addWidget(self.wait_spin, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        lbl2 = QLabel("Temp Smoothing (N):")
        lbl2.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lbl2.setToolTip("Temp Smoothing: Number of temperature samples to average.\nHigher values prevent fans from 'pulsing' during rapid temperature spikes but slightly increase reaction time.")
        form_grid.addWidget(lbl2, 1, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.ma_spin = QSpinBox()
        self.ma_spin.setRange(1, 20)
        self.ma_spin.setFixedWidth(80)
        self.ma_spin.setValue(self.controller.config.get("ma_window", 5))
        self.ma_spin.setToolTip("Temp Smoothing: Number of temperature samples to average.\nHigher values prevent fans from 'pulsing' during rapid temperature spikes but slightly increase reaction time.")
        self.ma_spin.valueChanged.connect(self.save_options)
        form_grid.addWidget(self.ma_spin, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        lbl3 = QLabel("Curve Interpolation:")
        lbl3.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lbl3.setToolTip("Curve Interpolation Mode:\n- Smooth: Smoothly transitions fan speed between points (Responsive).\n- Discrete: Jumps between points like stairs. Can prevent fan motor wear by reducing the frequency of micro-adjustments.")
        form_grid.addWidget(lbl3, 2, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.interp_combo = QComboBox()
        self.interp_combo.addItems(["Smooth", "Discrete"])
        self.interp_combo.setFixedWidth(120)
        current_interp = self.controller.config.get("curve_interpolation", "smooth")
        self.interp_combo.setCurrentText(current_interp.capitalize())
        self.interp_combo.setToolTip("Curve Interpolation Mode:\n- Smooth: Smoothly transitions fan speed between points (Responsive).\n- Discrete: Jumps between points like stairs. Can prevent fan motor wear by reducing the frequency of micro-adjustments.")
        self.interp_combo.currentTextChanged.connect(self.save_options)
        form_grid.addWidget(self.interp_combo, 2, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        lbl_log = QLabel("Log Level:")
        lbl_log.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lbl_log.setToolTip("Controls logging verbosity:\n- DEBUG: Prints all raw WMI and fan events.\n- INFO: Operational logs (Default).\n- WARNING: Warnings and errors only.\n- ERROR: Critical errors only.\n- QUIET: Silent mode.")
        form_grid.addWidget(lbl_log, 3, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.loglevel_combo = QComboBox()
        self.loglevel_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "QUIET"])
        self.loglevel_combo.setFixedWidth(120)
        current_log_level = self.controller.config.get("log_level", "INFO").upper()
        self.loglevel_combo.setCurrentText(current_log_level)
        self.loglevel_combo.currentTextChanged.connect(self.save_options)
        form_grid.addWidget(self.loglevel_combo, 3, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.bypass_check = QCheckBox("Bypass Driver Patch Warning")
        self.bypass_check.setChecked(self.controller.config.get("bypass_patch_warning", False))
        self.bypass_check.toggled.connect(self.save_options)
        self.bypass_check.toggled.connect(lambda: self.controller.save_config())
        form_grid.addWidget(self.bypass_check, 4, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.bypass_root_check = QCheckBox("Bypass Root Warning")
        self.bypass_root_check.setChecked(self.controller.config.get("bypass_root_warning", False))
        self.bypass_root_check.toggled.connect(self.save_options)
        self.bypass_root_check.toggled.connect(lambda: self.controller.save_config())
        form_grid.addWidget(self.bypass_root_check, 5, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.shutdown_hook_check = QCheckBox("Enable Fan Cleanup on Shutdown (Set to 30%)")
        self.shutdown_hook_check.setToolTip("Creates a systemd shutdown hook to ensure fans are reset to a quiet 30% speed\nwhen shutting down or rebooting. Prevents fans being stuck at high speed\nuntil the service is back up")
        self.shutdown_hook_check.setChecked(self.controller.is_shutdown_service_enabled())
        self.shutdown_hook_check.toggled.connect(self.toggle_shutdown_hook)
        form_grid.addWidget(self.shutdown_hook_check, 6, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Experimental Support Section
        exp_group = QWidget()
        exp_layout = QVBoxLayout(exp_group)
        exp_layout.setContentsMargins(0, 10, 0, 0)
        
        self.exp_check = QCheckBox("Enable Experimental List Support")
        self.exp_check.setStyleSheet("color: #ff9800; font-weight: bold;")
        self.exp_check.setChecked(self.controller.config.get("enable_experimental", False))
        self.exp_check.toggled.connect(self.toggle_experimental_options)
        self.exp_check.toggled.connect(lambda: self.controller.save_config())
        
        supp_status, _ = self.controller.check_board_support()
        # Force POSSIBLY_SUPPORTED behavior for debugging
        if self.controller.config.get("debug_experimental_ui"):
            supp_status = "POSSIBLY_SUPPORTED"

        if supp_status == "SUPPORTED":
            self.exp_check.setEnabled(True)
            self.exp_check.setToolTip("WARNING: Your board is already officially supported. <br>Forcing experimental mode override may cause conflicts or instability. This setting is not recommended for your board.")
            self.exp_check.setStyleSheet("color: #ffa500;") # Orange warning color? Or keep standard? Let's leave clear warning style if possible, or just tooltip.
            
        elif supp_status == "UNSUPPORTED":
             self.exp_check.setEnabled(False)
             self.exp_check.setToolTip("Your motherboard id was not found on the experimental support list")
             self.exp_check.setStyleSheet("color: #777;")

        else: # POSSIBLY_SUPPORTED
             self.exp_check.setEnabled(True)
             self.exp_check.setToolTip("Enable support for unverified Omen/Victus boards")

        exp_layout.addWidget(self.exp_check)
        
        self.exp_options_widget = QWidget()
        exp_opt_layout = QHBoxLayout(self.exp_options_widget)
        exp_opt_layout.setContentsMargins(20, 0, 0, 0)
        
        exp_opt_layout.addWidget(QLabel("Force Thermal Profile:"))
        
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["Omen", "Omen V1", "Omen V1 Legacy", "Omen V1 No EC", "Victus", "Victus S"])
        self.profile_combo.setItemDelegate(NoFocusDelegate())
        
        # Map config value to index
        current_profile = self.controller.config.get("thermal_profile", "omen")
        index = {
            "omen": 0, 
            "omen_v1": 1, 
            "omen_v1_legacy": 2, 
            "omen_v1_no_ec": 3, 
            "victus": 4, 
            "victus_s": 5
        }.get(current_profile, 0)
        self.profile_combo.setCurrentIndex(index)
        
        exp_opt_layout.addWidget(self.profile_combo)
        
        self.exp_save_btn = QPushButton("Save")
        self.exp_save_btn.setFixedWidth(60)
        self.exp_save_btn.setStyleSheet("background-color: #2e7d32; padding: 5px;")
        self.exp_save_btn.clicked.connect(self.save_options)
        exp_opt_layout.addWidget(self.exp_save_btn)
        
        exp_opt_layout.addStretch()
        
        exp_layout.addWidget(self.exp_options_widget)
        
        form_grid.addWidget(exp_group, 6, 0, 1, 2)
        
        # Init visibility
        self.toggle_experimental_options(self.exp_check.isChecked())

        # 4. Manual Max Fan Speed (Calibration Bypass)
        manual_max_box = QVBoxLayout()
        manual_max_box.setSpacing(3)

        input_row = QHBoxLayout()
        self.manual_max_check = QCheckBox("Use Manual Max RPM (Bypass Calibration)")
        self.manual_max_check.setToolTip("Allows setting a manual Max Fan RPM (e.g. 5800 RPM) to patch the driver without needing live calibration.")
        self.manual_max_check.setChecked(self.controller.config.get("use_manual_max_rpm", False))
        self.manual_max_check.toggled.connect(self.toggle_manual_max_rpm)
        input_row.addWidget(self.manual_max_check)

        self.manual_max_spin = QSpinBox()
        self.manual_max_spin.setRange(4000, 7000)
        self.manual_max_spin.setSingleStep(100)
        self.manual_max_spin.setFixedWidth(80)
        self.manual_max_spin.setValue(self.controller.config.get("manual_max_rpm", 5800))
        self.manual_max_spin.setEnabled(self.manual_max_check.isChecked())
        self.manual_max_spin.valueChanged.connect(self.on_manual_max_spin_changed)
        input_row.addWidget(self.manual_max_spin)

        self.manual_max_save_btn = QPushButton("Save")
        self.manual_max_save_btn.setFixedWidth(60)
        self.manual_max_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_max_save_btn.setStyleSheet("""
            QPushButton { background-color: #3a3a3c; color: white; font-weight: bold; border-radius: 4px; padding: 4px; border: 1px solid #555; }
            QPushButton:hover { background-color: #4a4a4c; border: 1px solid #777; }
        """)
        self.manual_max_save_btn.setEnabled(self.manual_max_check.isChecked())
        self.manual_max_save_btn.clicked.connect(self.save_manual_max_rpm)
        input_row.addWidget(self.manual_max_save_btn)
        input_row.addStretch()

        manual_max_box.addLayout(input_row)

        self.manual_max_source_lbl = QLabel("")
        self.manual_max_source_lbl.setStyleSheet("margin-left: 24px; font-size: 11px;")
        manual_max_box.addWidget(self.manual_max_source_lbl)

        form_grid.addLayout(manual_max_box, 7, 0, 1, 2)

        # 5. Windows OMEN Config & Settings Backup Group (Symmetrical Layout)
        btn_group_box = QVBoxLayout()
        btn_group_box.setSpacing(10)

        self.get_win_cfg_btn = QPushButton("Get Configuration from Windows")
        self.get_win_cfg_btn.setToolTip("Import CleanCreek fan settings and Max Fan RPM from Windows PowerControlConfig.json or mount directory.")
        self.get_win_cfg_btn.setStyleSheet("background-color: #0e639c; font-weight: bold; padding: 9px; border-radius: 4px; color: white;")
        self.get_win_cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.get_win_cfg_btn.clicked.connect(self.import_windows_config_dialog)
        btn_group_box.addWidget(self.get_win_cfg_btn)

        backup_box = QHBoxLayout()
        backup_box.setSpacing(12)

        self.export_cfg_btn = QPushButton("Export Settings JSON")
        self.export_cfg_btn.setStyleSheet("background-color: #333; padding: 8px; border-radius: 4px; color: white;")
        self.export_cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_cfg_btn.clicked.connect(self.export_settings_dialog)
        backup_box.addWidget(self.export_cfg_btn, 1)

        self.import_cfg_btn = QPushButton("Import Settings JSON")
        self.import_cfg_btn.setStyleSheet("background-color: #333; padding: 8px; border-radius: 4px; color: white;")
        self.import_cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_cfg_btn.clicked.connect(self.import_settings_dialog)
        backup_box.addWidget(self.import_cfg_btn, 1)

        btn_group_box.addLayout(backup_box)
        form_grid.addLayout(btn_group_box, 8, 0, 1, 2)

        self.update_manual_max_source_label()
        
        layout.addWidget(form_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        
        layout.addStretch()
        
        bottom_layout = QVBoxLayout()
        bottom_layout.setSpacing(10)
        
        self.bios_btn = QPushButton("Disable BIOS Fan Control")
        self.bios_btn.setFixedWidth(250)
        self.bios_btn.setStyleSheet("""
            QPushButton { background-color: #500; color: white; border-radius: 4px; padding: 8px; }
            QPushButton:hover { background-color: #600; }
        """)
        self.bios_btn.clicked.connect(self.toggle_bios)
        bottom_layout.addWidget(self.bios_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        warn = QLabel("Warning: This writes directly to EC registers (0x62/0x63). Use at own risk.\n(Usually not necessary as driver handles overrides)")
        warn.setStyleSheet("color: #888; font-size: 11px;")
        bottom_layout.addWidget(warn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        layout.addLayout(bottom_layout)
        
        layout.addSpacing(60)
        
        svc_layout = QHBoxLayout()
        svc_layout.addStretch()
        
        svc_label = QLabel("Background Service:")
        svc_layout.addWidget(svc_label)
        
        svc_layout.addSpacing(20)
        
        self.svc_btn = QPushButton("Install Service")
        self.svc_btn.setFixedWidth(150)
        self.svc_btn.clicked.connect(self.toggle_service)
        
        if self.controller.is_service_installed():
             self.svc_btn.setText("Remove Service")
             self.svc_btn.setStyleSheet("background-color: #d63333;")
        else:
             self.svc_btn.setText("Install Service")
             self.svc_btn.setStyleSheet("background-color: #2e7d32;")
             
        svc_layout.addWidget(self.svc_btn)
        
        self.svc_restart_btn = QPushButton("Restart Service")
        self.svc_restart_btn.setFixedWidth(150)
        self.svc_restart_btn.setStyleSheet("background-color: #f57c00; color: white;")
        self.svc_restart_btn.clicked.connect(self.restart_service_request)
        self.svc_restart_btn.setVisible(self.controller.is_service_installed())
        
        svc_layout.addWidget(self.svc_restart_btn)
        svc_layout.addStretch()
        
        layout.addLayout(svc_layout)
        layout.addSpacing(20)
        
        self.stack.addWidget(page)

    def init_about_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        layout.addWidget(QLabel("<h2>HP Omen Fan Control</h2>"))
        layout.addWidget(QLabel("Version 1.0"))
        layout.addWidget(QLabel("Copyright 2026 Arfelious"))
        
        ack_btn = QPushButton("Acknowledgments")
        ack_btn.setFixedWidth(200)
        ack_btn.clicked.connect(self.show_acknowledgments)
        layout.addWidget(ack_btn)
        
        license_text = QTextEdit()
        license_text.setReadOnly(True)
        
        try:
            with open(OMEN_FAN_DIR / "LICENSE.md", "r") as f:
                content = f.read()
        except Exception as e:
            content = (f"This program is free software: you can redistribute it and/or modify\n"
                       f"it under the terms of the GNU General Public License as published by\n"
                       f"the Free Software Foundation, either version 3 of the License, or\n"
                       f"(at your option) any later version.\n\n"
                       f"(Error loading LICENSE.md: {e})")
            
        license_text.setText(content)
        layout.addWidget(license_text)
        
        layout.addStretch()
        self.stack.addWidget(page)

    def show_acknowledgments(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Acknowledgments")
        msg.setText("<h3>Acknowledgments</h3>")
        msg.setInformativeText(
            "<b>Built with:</b> PyQt6 (GPLv3)<br><br>"
            "<b>Probes:</b><br>"
            "<a href='https://github.com/alou-S/omen-fan/blob/main/docs/probes.md'>"
            "https://github.com/alou-S/omen-fan</a><br><br>"
            "<b>Linux 6.20 Kernel HP-WMI Driver:</b><br>"
            "<a href='https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c'>"
            "Kernel Commit 46be145</a>"
        )
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.exec()

    # Navigation Logic
    def show_core_temps(self, event):
        dlg = CoreTempDialog(self.controller, self)
        dlg.exec()

    def go_home(self):
        self.stack.setCurrentWidget(self.home_page)
        self.back_btn.setVisible(False)
        self.title_label.setText("HP Omen Fan Control")

    def show_page(self, widget, title):
        self.stack.setCurrentWidget(widget)
        self.back_btn.setVisible(True)
        self.title_label.setText(title)

    def show_fan_control(self): self.show_page(self.fan_page, "Fan Control")
    def show_calibration(self): self.show_page(self.stack.widget(2), "Calibration")
    def show_driver(self): self.show_page(self.stack.widget(3), "Driver Management")
    def show_options(self): self.show_page(self.stack.widget(4), "Options")
    def show_about(self): self.show_page(self.stack.widget(5), "About")
    def show_fan_cleaner(self): self.show_page(self.cleaner_page, "Fan Cleaner")

    def set_reference_sensor(self, sensor):
        self.controller.config["reference_sensor"] = sensor
        self.controller.save_config()
        self.update_status()

    # Core Logic
    def update_status(self, temp_override=None):
        rpm, in_reverse = self.controller.get_fan_speed_info()
        if temp_override is not None:
             temp = int(temp_override)
        else:
             temp = self.controller.get_reference_temp()

        rpm_str = f"-{rpm} RPM" if (in_reverse and rpm > 0) else f"{rpm} RPM"
        self.rpm_label.setText(rpm_str)
        self.temp_label.setText(f"{temp}°C")
        
        sensor = self.controller.config.get("reference_sensor", "cpu")
        self.cpu_pill_btn.setProperty("active", sensor == "cpu")
        self.gpu_pill_btn.setProperty("active", sensor == "gpu")
        
        # Refresh styling for property changes
        self.cpu_pill_btn.style().unpolish(self.cpu_pill_btn)
        self.cpu_pill_btn.style().polish(self.cpu_pill_btn)
        self.gpu_pill_btn.style().unpolish(self.gpu_pill_btn)
        self.gpu_pill_btn.style().polish(self.gpu_pill_btn)
        
        self.check_driver_status()
        self.update_cleaner_status()

    def check_driver_status(self):
        # Don't overwrite status if we are in the middle of an operation
        current_text = self.status_label.text()
        if any(x in current_text for x in ["Installing", "Restoring", "Calibrating", "Stress"]):
            return

        # Refresh paths if driver might have just been loaded
        if not self.controller.pwm1_path or not self.controller.pwm1_path.exists():
            self.controller._find_paths()
            
        if self.controller.pwm1_path and self.controller.pwm1_path.exists():
            if "Needs Driver Installation" in self.status_label.text() or "Checking..." in self.status_label.text():
                 self.status_label.setText("Ready")
                 self.status_label.setStyleSheet("color: #888; padding: 5px;")
        else:
            self.status_label.setText("Needs Driver Installation")
            self.status_label.setStyleSheet("color: #d63333; font-weight: bold; padding: 5px;")

    def on_status_click(self, event):
        if "Needs Driver Installation" in self.status_label.text():
            self.show_driver()
        
    def on_mode_change(self, text):
        self.manual_widget.setVisible(text == "Manual")
        self.curve_editor_container.setVisible(text == "Curve")
        
        self.manual_unsaved_lbl.setVisible(False)
        self.curve_unsaved_lbl.setVisible(False)
        if hasattr(self, "curve_revert_btn"):
            self.curve_revert_btn.setVisible(False)
        self.set_btn.setText("Set Mode")
        
        # Dynamically move stress controls depending on whether Curve Editor is visible
        if hasattr(self, "stress_widget") and hasattr(self, "fan_layout"):
            self.fan_layout.removeWidget(self.stress_widget)
            
            if text == "Curve":
                # Place below curve editor container (above watchdog)
                idx = self.fan_layout.indexOf(self.curve_editor_container)
                self.fan_layout.insertWidget(idx + 1, self.stress_widget)
            else:
                # Place directly below Mode Container (above the stretch)
                idx = self.fan_layout.indexOf(self.mode_container)
                self.fan_layout.insertWidget(idx + 1, self.stress_widget)

    def on_manual_changed(self):
        self.manual_unsaved_lbl.setVisible(True)
        if self.mode_combo.currentText() == "Manual":
            self.set_btn.setText("Save Speed")

    def on_curve_changed(self):
        self.curve_unsaved_lbl.setVisible(True)
        if hasattr(self, "curve_revert_btn"):
            self.curve_revert_btn.setVisible(True)
        if self.mode_combo.currentText() == "Curve":
            self.set_btn.setText("Save Curve")

    def reset_curve(self):
        default_points = [(40, 20), (55, 40), (70, 65), (85, 90), (95, 100)]
        self.curve_editor.set_points(default_points)
        self.on_curve_changed()

    def revert_curve(self):
        saved_curve = self.controller.config.get("curve", [])
        if not saved_curve:
            saved_curve = [(40, 20), (55, 40), (70, 65), (85, 90), (95, 100)]
        self.curve_editor.set_points(saved_curve)
        self.curve_unsaved_lbl.setVisible(False)
        if hasattr(self, "curve_revert_btn"):
            self.curve_revert_btn.setVisible(False)
        if self.mode_combo.currentText() == "Curve":
            self.set_btn.setText("Set Mode")
        self.status_label.setText("Fan curve reverted to saved settings.")

    def apply_fan_mode(self):
        mode = self.mode_combo.currentText().lower()
        
        # Check driver requirement for Manual/Curve
        if mode in ["manual", "curve"]:
            has_driver = False
            if self.controller.pwm1_path and self.controller.pwm1_path.exists():
                has_driver = True
            
            if not has_driver:
                QMessageBox.warning(self, "Driver Required", 
                    f"To use {mode.title()} mode, you must install the kernel driver patch.\n"
                    "Go to 'Driver Management' to install it.")
                return

        # Always update and save config first so service can see it
        self.controller.config["mode"] = mode
        
        if mode == "manual":
            percent = self.manual_spin.value()
            pwm_val = int(round(percent / 100 * 255))
            self.controller.config["manual_pwm"] = pwm_val
        elif mode == "curve":
            points = self.curve_editor.get_points()
            self.controller.config["curve"] = points
            
        self.controller.save_config()
        
        self.manual_unsaved_lbl.setVisible(False)
        self.curve_unsaved_lbl.setVisible(False)
        if hasattr(self, "curve_revert_btn"):
            self.curve_revert_btn.setVisible(False)
        self.set_btn.setText("Set Mode")
        
        # If service is running, we just save config and let service handle it
        if self.controller.is_service_running():
            self.status_label.setText(f"Settings saved. Service will apply {mode} mode.")
            # Ensure local loop is stopped
            if hasattr(self, 'curve_timer'):
                self.curve_timer.stop()
            return

        # Local application for non-service users
        if mode == "auto":
            self.controller.set_fan_mode("auto")
            self.status_label.setText("Set mode to Auto")
        elif mode == "max":
            self.controller.set_fan_mode("max")
            self.status_label.setText("Set mode to Max")
        elif mode == "manual":
            pwm_val = self.controller.config["manual_pwm"]
            self.controller.set_fan_pwm(pwm_val)
            self.status_label.setText(f"Set manual speed to {self.manual_spin.value()}% (PWM: {pwm_val})")
        elif mode == "curve":
            self.status_label.setText("Curve mode enabled")
            self.start_curve_loop()

    def start_curve_loop(self):
        if not hasattr(self, 'curve_timer'):
            self.curve_timer = QTimer()
            self.curve_timer.timeout.connect(self.apply_curve_step)
        
        # If service is running, do not run local loop
        if self.controller.is_service_running():
            self.curve_timer.stop()
            return

        if self.mode_combo.currentText() == "Curve":
            self.curve_timer.start(2000)
        else:
            self.curve_timer.stop()

    def apply_curve_step(self):
        raw_temp = self.controller.get_cpu_temp()
        
        self.temp_history.append(raw_temp)
        if len(self.temp_history) > self.temp_history_len:
            self.temp_history.pop(0)
            
        avg_temp = sum(self.temp_history) / len(self.temp_history)
        
        self.update_status(avg_temp)
        
        curve = self.controller.config.get("curve", [])
        if not curve: return
        
        curve.sort(key=lambda p: p[0])
        target_speed = 0
        
        temp = avg_temp
        
        target_pwm = self.controller.calculate_target_pwm(temp)
        if target_pwm is None:
             return
             
        pwm_val = target_pwm
        
        current_rpm = self.controller.get_fan_speed()
        max_rpm = self.controller.config.get("fan_max", 0)
        
        if max_rpm > 0:
            target_rpm = (pwm_val / 255) * max_rpm
            diff = abs(target_rpm - current_rpm)
            
            import time
            
            if diff < 200:
                if not hasattr(self, 'hysteresis_start_time') or self.hysteresis_start_time is None:
                    self.hysteresis_start_time = time.time()
                
                if time.time() - self.hysteresis_start_time > 60:
                    self.controller.set_fan_pwm(pwm_val)
                    self.hysteresis_start_time = None
                    pass 
                else:
                    return
            else:
                self.hysteresis_start_time = None
                self.controller.set_fan_pwm(pwm_val)
        else:
            self.controller.set_fan_pwm(pwm_val)

    def toggle_calibration(self):
        if getattr(self, "cal_running", False):
            self.stop_calibration()
        else:
            self.start_calibration()

    def start_calibration(self):
        if hasattr(self, 'curve_timer'):
            self.curve_timer.stop()
        
        self.last_mode_before_cal = self.controller.config.get("mode", "auto")
        self.cal_running = True
        self.controller.config["mode"] = "calibration"
        self.controller.save_config()
            
        self.cal_btn.setText("Stop Calibration")
        self.cal_btn.setStyleSheet("background-color: #d63333; color: white; font-weight: bold;")
        self.cal_progress.setVisible(True)
        self.cal_progress.setRange(0, 100)
        self.cal_progress.setValue(0)
        self.status_label.setText("Calibrating...")
        
        self.cal_thread = WorkerThread(self.controller.calibrate)
        self.cal_thread.progress.connect(self.cal_progress.setValue)
        self.cal_thread.finished.connect(self.on_cal_finished)
        self.cal_thread.start()

    def stop_calibration(self):
        self.cal_running = False
        if hasattr(self, "cal_thread") and self.cal_thread.isRunning():
            self.cal_thread.terminate()
            self.cal_thread.wait()
        
        self.cal_btn.setText("Start Calibration")
        self.cal_btn.setStyleSheet("")
        self.cal_progress.setVisible(False)
        self.status_label.setText("Calibration stopped. Fans restored to previous mode.")
        
        # Restore mode before calibration
        prev_mode = getattr(self, "last_mode_before_cal", "auto")
        if prev_mode == "calibration":
            prev_mode = "auto"
        self.controller.config["mode"] = prev_mode
        self.controller.save_config()
        self.apply_fan_mode()

    def on_cal_finished(self, max_rpm):
        if not getattr(self, "cal_running", False):
            return
        
        self.cal_running = False
        self.cal_btn.setText("Start Calibration")
        self.cal_btn.setStyleSheet("")
        self.cal_progress.setVisible(False)
        
        # Reset mode back to auto/previous
        prev_mode = getattr(self, "last_mode_before_cal", "auto")
        if prev_mode == "calibration":
            prev_mode = "auto"
        self.controller.config["mode"] = prev_mode
        self.controller.save_config()

        if max_rpm == 0:
            self.cal_result.setText("Max RPM: 0 (Sensor Unreadable)")
            self.status_label.setText("Calibration returned 0 RPM.")
            self.apply_fan_mode()
            
            warn_msg = (
                "Calibration returned 0 RPM!\n\n"
                "This typically occurs on Linux kernel versions where sysfs fan speed reading is unavailable.\n\n"
                "Recommended Solution:\n"
                "1. Go to Options and click 'Get Configuration from Windows' (Recommended).\n"
                "2. Or enable 'Use Manual Max RPM (Bypass Calibration)' to specify your Max RPM directly."
            )
            QMessageBox.warning(self, "Calibration Result: 0 RPM", warn_msg)
        else:
            self.cal_result.setText(f"Max RPM: {max_rpm}")
            self.status_label.setText(f"Calibration done. Max RPM: {max_rpm}")
            self.apply_fan_mode()
            QMessageBox.information(self, "Calibration", f"Calibration Complete.\nMax RPM: {max_rpm}")

    def run_driver_task(self, type_, force=False):
        if type_ == "temp":
            func = self.controller.install_driver_temp
        elif type_ == "perm":
            func = self.controller.install_driver_perm
        else: # restore
            func = self.controller.restore_driver
            # Restore doesn't need force usually
            
        action_name = "Restoring" if type_ == "restore" else "Installing"
        self.status_label.setText(f"{action_name} driver...")
        self.status_label.setStyleSheet("color: #888; padding: 5px;")
        
        # We need to pass force arg if installing
        if type_ != "restore":
             self.driver_thread = WorkerThread(func, force)
        else:
             self.driver_thread = WorkerThread(func)
             
        self.driver_thread.finished.connect(lambda result: self.on_driver_finished(result, type_))
        self.driver_thread.start()

    def on_driver_finished(self, result, type_):
        success, msg = result
        self.status_label.setText(msg)
        
        if success:
            self.status_label.setStyleSheet("color: #888; padding: 5px;")
            QMessageBox.information(self, "Driver Install", msg)
        else:
            if msg == "PWM_DETECTED":
                 # Ask user to force
                 reply = QMessageBox.question(self, "Driver Detected", 
                                              "The driver appears to be already active (pwm1 exists).\n\nDo you want to force install anyway?",
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                 if reply == QMessageBox.StandardButton.Yes:
                     # Retry with force=True
                     self.run_driver_task(type_, force=True)
                 else:
                     self.status_label.setText("Install cancelled.")
            else:
                QMessageBox.critical(self, "Driver Install Error", msg)

    def save_options(self):
        self.controller.config['calibration_wait'] = self.wait_spin.value()
        self.controller.config['ma_window'] = self.ma_spin.value()
        self.controller.config['curve_interpolation'] = self.interp_combo.currentText().lower()
        self.controller.config['log_level'] = self.loglevel_combo.currentText()
        self.controller.config['bypass_patch_warning'] = self.bypass_check.isChecked()
        self.controller.config['bypass_root_warning'] = self.bypass_root_check.isChecked()
        
        # Experimental settings
        self.controller.config['enable_experimental'] = self.exp_check.isChecked()
        
        profile_map = {
            0: "omen", 
            1: "omen_v1", 
            2: "omen_v1_legacy", 
            3: "omen_v1_no_ec", 
            4: "victus", 
            5: "victus_s"
        }
        self.controller.config['thermal_profile'] = profile_map.get(self.profile_combo.currentIndex(), "omen")

        self.temp_history_len = self.ma_spin.value()
        self.controller.save_config()
        
        # If save button was clicked on exp options, give feedback
        sender = self.sender()
        if sender == getattr(self, 'exp_save_btn', None):
             self.status_label.setText("Settings saved.")
             QTimer.singleShot(2000, self.check_driver_status)

    def toggle_experimental_options(self, checked):
        self.exp_options_widget.setVisible(checked)
        self.save_options()

    def toggle_manual_max_rpm(self, checked):
        self.controller.config["use_manual_max_rpm"] = checked
        self.manual_max_spin.setEnabled(checked)
        if hasattr(self, "manual_max_save_btn"):
            self.manual_max_save_btn.setEnabled(checked)
        self.save_manual_max_rpm()

    def on_manual_max_spin_changed(self):
        self.update_manual_max_source_label()

    def save_manual_max_rpm(self):
        val = self.manual_max_spin.value()
        self.controller.config["manual_max_rpm"] = val
        self.controller.save_config()
        self.update_manual_max_source_label()
        self.status_label.setText(f"Manual Max RPM set to {val} RPM.")

    def update_manual_max_source_label(self):
        if not hasattr(self, "manual_max_source_lbl"):
            return
        
        current_val = self.manual_max_spin.value()
        win_rpm = self.controller.config.get("windows_max_rpm")
        
        if win_rpm is not None and current_val == win_rpm and self.controller.config.get("windows_config_imported", False):
            self.manual_max_source_lbl.setText("(Sourced from Windows OMEN Config)")
            self.manual_max_source_lbl.setStyleSheet("color: #4caf50; font-size: 11px; font-weight: bold; margin-left: 24px;")
        elif self.manual_max_check.isChecked():
            self.manual_max_source_lbl.setText("(User Specified)")
            self.manual_max_source_lbl.setStyleSheet("color: #2196f3; font-size: 11px; font-weight: bold; margin-left: 24px;")
        elif self.controller.config.get("fan_max", 0) > 0:
            self.manual_max_source_lbl.setText("(Live Calibrated)")
            self.manual_max_source_lbl.setStyleSheet("color: #ff9800; font-size: 11px; font-weight: bold; margin-left: 24px;")
        else:
            self.manual_max_source_lbl.setText("")

    def import_windows_config_dialog(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Import Windows OMEN Configuration")
        msg_box.setText("Select your mounted Windows drive folder (e.g. /run/media/...) OR pick PowerControlConfig.json directly.")
        btn_dir = msg_box.addButton("Select Windows Mount Folder", QMessageBox.ButtonRole.ActionRole)
        btn_file = msg_box.addButton("Select PowerControlConfig.json File", QMessageBox.ButtonRole.ActionRole)
        btn_cancel = msg_box.addButton(QMessageBox.StandardButton.Cancel)

        msg_box.exec()
        clicked = msg_box.clickedButton()

        chosen_path = None
        if clicked == btn_dir:
            chosen_path = QFileDialog.getExistingDirectory(self, "Select Windows Mount Directory", "/run/media")
        elif clicked == btn_file:
            file_tuple = QFileDialog.getOpenFileName(self, "Select PowerControlConfig.json", "/run/media", "Config Files (*.json);;All Files (*)")
            chosen_path = file_tuple[0] if file_tuple else None

        if not chosen_path:
            return

        success, msg, parsed = self.controller.import_windows_omen_config(chosen_path)
        if success:
            cpu = parsed.get("cleaner_cpu_speed", 37)
            gpu = parsed.get("cleaner_gpu_speed", 39)
            dur = parsed.get("cleaner_duration_sec", 30)
            max_rpm = parsed.get("manual_max_rpm", 5800)
            
            # Refresh GUI widgets
            self.manual_max_check.setChecked(True)
            self.manual_max_spin.setValue(max_rpm)
            self.update_manual_max_source_label()

            info_text = (
                f"Configuration successfully imported!\n\n"
                f"• CleanCreek CPU Speed: {cpu} ({cpu*100} RPM)\n"
                f"• CleanCreek GPU Speed: {gpu} ({gpu*100} RPM)\n"
                f"• Active Clean Duration: {dur} seconds\n"
                f"• Extracted Max Fan RPM: {max_rpm} RPM\n\n"
                f"These values have been permanently saved to this program's own configuration.\n"
                f"You may now safely unmount your Windows drive if you desire to do so."
            )
            QMessageBox.information(self, "Import Successful", info_text)
        else:
            QMessageBox.critical(self, "Import Error", msg)

    def export_settings_dialog(self):
        file_tuple = QFileDialog.getSaveFileName(self, "Export Application Settings", "omen_fan_control_settings.json", "JSON Files (*.json)")
        if file_tuple[0]:
            success, msg = self.controller.export_app_settings(file_tuple[0])
            if success:
                QMessageBox.information(self, "Export Settings", msg)
            else:
                QMessageBox.critical(self, "Export Error", msg)

    def import_settings_dialog(self):
        file_tuple = QFileDialog.getOpenFileName(self, "Import Application Settings", "", "JSON Files (*.json)")
        if file_tuple[0]:
            success, msg = self.controller.import_app_settings(file_tuple[0])
            if success:
                # Refresh GUI controls to match imported config
                self.wait_spin.setValue(self.controller.config.get("calibration_wait", 30))
                self.ma_spin.setValue(self.controller.config.get("ma_window", 5))
                self.loglevel_combo.setCurrentText(self.controller.config.get("log_level", "INFO").upper())
                self.manual_max_check.setChecked(self.controller.config.get("use_manual_max_rpm", False))
                self.manual_max_spin.setValue(self.controller.config.get("manual_max_rpm", 5800))
                QMessageBox.information(self, "Import Settings", msg)
            else:
                QMessageBox.critical(self, "Import Error", msg)

    def toggle_shutdown_hook(self, enabled):
        if enabled:
            success, msg = self.controller.create_shutdown_service()
        else:
            success, msg = self.controller.remove_shutdown_service()
        
        if not success:
            QMessageBox.critical(self, "Service Error", msg)
            self.shutdown_hook_check.setChecked(not enabled)
        else:
            self.status_label.setText(msg)
            # Ensure main daemon is running if installed
            if self.controller.is_service_installed() and not self.controller.is_service_running():
                self.controller.start_service()
                QTimer.singleShot(1000, self.check_service_status)

    def toggle_bios(self):
        is_currently_enabled = "Disable" in self.bios_btn.text()
        
        if is_currently_enabled:
            confirm = QMessageBox.warning(self, "Warning", 
                                          "Disabling BIOS control involves writing to EC registers. This may cause system instability.\n\nAre you sure?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if confirm == QMessageBox.StandardButton.Yes:
                if self.controller.set_bios_control(enabled=False):
                    self.status_label.setText("BIOS Control Disabled")
                    self.bios_btn.setText("Enable BIOS Fan Control")
                    self.bios_btn.setStyleSheet("""
                        QPushButton { background-color: #2e7d32; color: white; border-radius: 4px; padding: 8px; }
                        QPushButton:hover { background-color: #388e3c; }
                    """)
                else:
                    self.status_label.setText("Failed to disable BIOS Control")
        else:
            if self.controller.set_bios_control(enabled=True):
                 self.status_label.setText("BIOS Control Enabled")
                 self.bios_btn.setText("Disable BIOS Fan Control")
                 self.bios_btn.setStyleSheet("""
                        QPushButton { background-color: #500; color: white; border-radius: 4px; padding: 8px; }
                        QPushButton:hover { background-color: #600; }
                    """)
            else:
                 self.status_label.setText("Failed to enable BIOS Control")

    def toggle_service(self):
        if self.controller.is_service_installed():
            success, msg = self.controller.remove_service()
            if success:
                self.svc_btn.setText("Install Service")
                self.svc_btn.setStyleSheet("background-color: #2e7d32;")
                QMessageBox.information(self, "Service", "Service Removed.")
            else:
                QMessageBox.critical(self, "Error", msg)
        else:
            self.controller.save_config()
            success, msg = self.controller.create_service()
            if success:
                self.svc_btn.setText("Remove Service")
                self.svc_btn.setStyleSheet("background-color: #d63333;")
                QMessageBox.information(self, "Service", "Service installed and started.\nIt will use the current configuration.")
            else:
                QMessageBox.critical(self, "Error", msg)
        self.check_service_status()

    def check_service_status(self):
        installed = self.controller.is_service_installed()
        
        if hasattr(self, 'svc_restart_btn'):
            self.svc_restart_btn.setVisible(installed)

        if not installed:
            self.svc_status_label.setText("Service: Not Installed")
            self.svc_status_label.setStyleSheet("color: #888;")
        else:
            running = self.controller.is_service_running()
            if running:
                self.svc_status_label.setText("Service: Active")
                self.svc_status_label.setStyleSheet("color: #4caf50; font-weight: bold;") # Green
                
                # Stop local loop if service is running
                if hasattr(self, 'curve_timer') and self.curve_timer.isActive():
                    self.curve_timer.stop()
            else:
                self.svc_status_label.setText("Service: Inactive")
                self.svc_status_label.setStyleSheet("color: #ff9800; font-weight: bold;") # Orange
                
                # Resume local loop if in Curve mode and service is not running
                if self.mode_combo.currentText() == "Curve" and not (hasattr(self, 'curve_timer') and self.curve_timer.isActive()):
                    self.start_curve_loop()

    def restart_service_request(self):
        self.svc_status_label.setText("Restarting Service...")
        self.svc_status_label.setStyleSheet("color: #ff9800; font-weight: bold;")
        self.svc_restart_btn.setEnabled(False)
        self.svc_btn.setEnabled(False)
        
        self.restart_thread = WorkerThread(self.controller.restart_service)
        self.restart_thread.finished.connect(self.on_svc_restart_finished)
        self.restart_thread.start()

    def on_svc_restart_finished(self, result):
        self.svc_restart_btn.setEnabled(True)
        self.svc_btn.setEnabled(True)
        success, msg = result
        if success:
             self.check_service_status()
             QMessageBox.information(self, "Service", "Service successfully restarted.")
        else:
             self.svc_status_label.setText("Restart Failed")
             self.svc_status_label.setStyleSheet("color: #d63333; font-weight: bold;")
             QMessageBox.critical(self, "Service Error", msg)

    def toggle_stress_test(self, checked):
        if checked:
            text = self.stress_duration.currentText()
            duration_map = {
                "30s": 30,
                "1m": 60,
                "5m": 300,
                "30m": 1800,
                "Indefinite": -1
            }
            duration = duration_map.get(text, 30)
            
            self.controller.start_stress_test(duration)
            self.stress_btn.setText("Stop Stress")
            self.status_label.setText(f"Stress test running ({text})...")
            
            if duration > 0:
                QTimer.singleShot(duration * 1000, self.stop_stress_test_timer)
                
        else:
            self.controller.stop_stress_test()
            self.stress_btn.setText("Start Stress")
            self.status_label.setText("Stress test stopped.")

    def stop_stress_test_timer(self):
        if self.stress_btn.isChecked():
             self.stress_btn.setChecked(False)

    def toggle_watchdog(self, checked):
        if checked:
            interval = self.controller.config.get("watchdog_interval", 90) * 1000
            self.watchdog_timer.start(interval)
            self.status_label.setText("Watchdog enabled")
        else:
            self.watchdog_timer.stop()
            self.status_label.setText("Watchdog disabled")

    def run_watchdog(self):
        self.apply_fan_mode()
        self.status_label.setText("Watchdog: Mode re-applied")

    def closeEvent(self, event):
        """Ensure clean shutdown of threads and processes."""
        if self.controller.config.get("cleaner_in_progress", False):
            self.controller.emergency_stop_fan_cleaning()
        self.controller.stop_stress_test()
        self.watchdog_timer.stop()
        self.rpm_timer.stop()
        event.accept()

    def init_cleaner_page(self):
        self.cleaner_page = QWidget()
        layout = QVBoxLayout(self.cleaner_page)
        
        layout.addStretch()
        
        container = QFrame()
        container.setStyleSheet("background-color: #252526; border-radius: 10px; padding: 12px 18px;")
        container.setFixedWidth(600)
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(9)
        
        # 1. Automatic Fan Cleaner Toggle & Description
        auto_box = QVBoxLayout()
        auto_box.setSpacing(2)

        self.auto_cleaner_check = QCheckBox("Enable Automatic Fan Cleaner")
        self.auto_cleaner_check.setStyleSheet("font-size: 15px; font-weight: bold; margin-bottom: 0px;")
        self.auto_cleaner_check.setChecked(self.controller.config.get("cleaner_enabled", False))
        self.auto_cleaner_check.toggled.connect(self.toggle_auto_cleaner)
        auto_box.addWidget(self.auto_cleaner_check)

        self.cleaner_info_lbl = QLabel("")
        self.cleaner_info_lbl.setWordWrap(True)
        self.cleaner_info_lbl.setMinimumHeight(38)
        self.cleaner_info_lbl.setStyleSheet("color: #aaa; font-size: 12px; margin-left: 24px; margin-top: 2px; margin-bottom: 2px;")
        auto_box.addWidget(self.cleaner_info_lbl)
        
        c_layout.addLayout(auto_box)

        # 2. Custom Interval Selection
        custom_box = QVBoxLayout()
        custom_box.setSpacing(4)

        self.custom_interval_check = QCheckBox("Use Custom Interval")
        self.custom_interval_check.setStyleSheet("font-size: 14px; font-weight: bold;")
        is_custom = self.controller.config.get("cleaner_custom_interval", False)
        self.custom_interval_check.setChecked(is_custom)
        self.custom_interval_check.toggled.connect(self.toggle_custom_interval)
        custom_box.addWidget(self.custom_interval_check)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(24, 0, 0, 0)
        input_row.setSpacing(10)

        self.interval_lbl = QLabel("Interval (hours):")
        input_row.addWidget(self.interval_lbl)

        self.interval_input = QLineEdit()
        self.interval_input.setFixedWidth(80)
        current_hours = self.controller.config.get("cleaner_interval", 14400) / 3600.0
        self.interval_input.setText(f"{current_hours:.1f}")
        input_row.addWidget(self.interval_input)

        self.save_interval_btn = QPushButton("Save")
        self.save_interval_btn.setFixedWidth(75)
        self.save_interval_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_interval_btn.clicked.connect(self.save_cleaner_interval)
        input_row.addWidget(self.save_interval_btn)
        input_row.addStretch()

        custom_box.addLayout(input_row)
        c_layout.addLayout(custom_box)

        self.update_custom_interval_style(is_custom)

        # 3. Cleaning Duration Override Section
        duration_box = QVBoxLayout()
        duration_box.setSpacing(2)

        duration_row = QHBoxLayout()
        duration_row.setContentsMargins(24, 0, 0, 0)
        duration_row.setSpacing(10)

        duration_lbl = QLabel("Cleaning Duration (seconds):")
        duration_lbl.setStyleSheet("font-size: 13px;")
        duration_row.addWidget(duration_lbl)

        self.cleaner_duration_spin = QSpinBox()
        self.cleaner_duration_spin.setRange(5, 120)
        self.cleaner_duration_spin.setSingleStep(5)
        self.cleaner_duration_spin.setFixedWidth(85)
        self.cleaner_duration_spin.setFixedHeight(30)
        self.cleaner_duration_spin.setStyleSheet("padding: 2px 4px;")
        current_dur = self.controller.config.get("cleaner_duration", 30)
        self.cleaner_duration_spin.setValue(current_dur)
        self.cleaner_duration_spin.valueChanged.connect(self.on_cleaner_duration_changed)
        duration_row.addWidget(self.cleaner_duration_spin)

        self.save_duration_btn = QPushButton("Save")
        self.save_duration_btn.setFixedWidth(75)
        self.save_duration_btn.setFixedHeight(30)
        self.save_duration_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_duration_btn.setStyleSheet("""
            QPushButton { background-color: #3a3a3c; color: white; font-weight: bold; border-radius: 4px; padding: 2px 10px; border: 1px solid #555; }
            QPushButton:hover { background-color: #4a4a4c; border: 1px solid #777; }
        """)
        self.save_duration_btn.clicked.connect(self.save_cleaner_duration)
        duration_row.addWidget(self.save_duration_btn)
        duration_row.addStretch()

        duration_box.addLayout(duration_row)

        self.cleaner_duration_source_lbl = QLabel("")
        duration_box.addWidget(self.cleaner_duration_source_lbl)

        c_layout.addLayout(duration_box)

        self.update_cleaner_info_text()
        self.update_cleaner_duration_source_label()

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setStyleSheet("background-color: #444;")
        c_layout.addWidget(sep)

        # Live Status Card
        status_card = QFrame()
        status_card.setObjectName("statusCard")
        status_card.setStyleSheet("QFrame#statusCard { background-color: #1a1a1a; border-radius: 8px; border: 1px solid #333; }")
        status_card_layout = QHBoxLayout(status_card)
        status_card_layout.setContentsMargins(14, 10, 14, 10)
        status_card_layout.setSpacing(20)

        # Direction badge
        dir_col = QVBoxLayout()
        dir_col.setSpacing(4)
        dir_title = QLabel("Fan Direction")
        dir_title.setStyleSheet("color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        dir_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cleaner_direction_lbl = QLabel("Forward")
        self.cleaner_direction_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cleaner_direction_lbl.setStyleSheet(
            "color: #4caf50; font-size: 13px; font-weight: bold; "
            "background: #1b3a1e; border-radius: 4px; padding: 4px 8px;"
        )
        dir_col.addWidget(dir_title)
        dir_col.addWidget(self.cleaner_direction_lbl)
        status_card_layout.addLayout(dir_col)

        # Vertical divider
        vdiv1 = QFrame()
        vdiv1.setFrameShape(QFrame.Shape.VLine)
        vdiv1.setStyleSheet("color: #333;")
        status_card_layout.addWidget(vdiv1)

        # Cleanup Status
        elapsed_col = QVBoxLayout()
        elapsed_col.setSpacing(4)
        elapsed_title = QLabel("Cleanup Status")
        elapsed_title.setStyleSheet("color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        elapsed_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cleaner_elapsed_lbl = QLabel("Idle")
        self.cleaner_elapsed_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cleaner_elapsed_lbl.setStyleSheet("color: #fff; font-size: 13px; font-weight: bold; padding: 2px;")
        elapsed_col.addWidget(elapsed_title)
        elapsed_col.addWidget(self.cleaner_elapsed_lbl)
        status_card_layout.addLayout(elapsed_col)

        # Vertical divider
        vdiv2 = QFrame()
        vdiv2.setFrameShape(QFrame.Shape.VLine)
        vdiv2.setStyleSheet("color: #333;")
        status_card_layout.addWidget(vdiv2)

        # Last run time
        lastrun_col = QVBoxLayout()
        lastrun_col.setSpacing(4)
        lastrun_title = QLabel("Last Run")
        lastrun_title.setStyleSheet("color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        lastrun_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cleaner_lastrun_lbl = QLabel("Never")
        self.cleaner_lastrun_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cleaner_lastrun_lbl.setStyleSheet("color: #ccc; font-size: 13px; padding: 2px;")
        lastrun_col.addWidget(lastrun_title)
        lastrun_col.addWidget(self.cleaner_lastrun_lbl)
        status_card_layout.addLayout(lastrun_col)

        c_layout.addWidget(status_card)

        # 3. Manual Clean Button and Emergency Stop Button
        btn_layout = QHBoxLayout()
        self.manual_clean_btn = QPushButton("Start Manual Fan Cleaning")
        self.manual_clean_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_clean_btn.setStyleSheet("""
            QPushButton { background-color: #2e7d32; font-weight: bold; padding: 10px; border-radius: 4px; color: white; }
            QPushButton:hover { background-color: #388e3c; }
        """)
        self.manual_clean_btn.clicked.connect(self.start_manual_cleaning)
        btn_layout.addWidget(self.manual_clean_btn)
        
        self.emergency_stop_btn = QPushButton("Stop Cleaning Immediately")
        self.emergency_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.emergency_stop_btn.setStyleSheet("""
            QPushButton { background-color: #c62828; font-weight: bold; padding: 10px; border-radius: 4px; color: white; }
            QPushButton:hover { background-color: #d32f2f; }
        """)
        self.emergency_stop_btn.clicked.connect(self.emergency_stop_cleaning)
        btn_layout.addWidget(self.emergency_stop_btn)
        
        c_layout.addLayout(btn_layout)
        
        # Safety warning note
        warn_lbl = QLabel("Safety Note: Fan cleaning does not run if CPU temperature is above 70°C.\n"
                          "In case of emergency or unexpected behavior, use the Stop button to restore functionality safely.")
        warn_lbl.setWordWrap(True)
        warn_lbl.setStyleSheet("color: #e65100; font-size: 10px; font-weight: bold;")
        c_layout.addWidget(warn_lbl)

        layout.addWidget(container, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        
        self.stack.addWidget(self.cleaner_page)

    def toggle_auto_cleaner(self, checked):
        self.controller.config["cleaner_enabled"] = checked
        self.controller.save_config()
        self.update_status()

    def toggle_custom_interval(self, checked):
        self.controller.config["cleaner_custom_interval"] = checked
        if not checked:
            # Revert to default 4 hours (14400 seconds)
            self.controller.config["cleaner_interval"] = 14400
            self.interval_input.setText("4.0")
        self.controller.save_config()
        self.update_custom_interval_style(checked)

    def update_custom_interval_style(self, checked):
        self.interval_input.setEnabled(checked)
        self.save_interval_btn.setEnabled(checked)
        if checked:
            self.interval_lbl.setStyleSheet("color: #e0e0e0; font-size: 13px;")
            self.interval_input.setStyleSheet("background-color: #333; color: #fff; border: 1px solid #555; padding: 4px; border-radius: 4px;")
            self.save_interval_btn.setStyleSheet("""
                QPushButton { background-color: #3a3a3c; color: white; font-weight: bold; border-radius: 4px; padding: 4px 10px; border: 1px solid #555; }
                QPushButton:hover { background-color: #4a4a4c; border: 1px solid #777; }
            """)
        else:
            self.interval_lbl.setStyleSheet("color: #555555; font-size: 13px;")
            self.interval_input.setStyleSheet("background-color: #1c1c1c; color: #555; border: 1px solid #333; padding: 4px; border-radius: 4px;")
            self.save_interval_btn.setStyleSheet("""
                QPushButton { background-color: #222224; color: #555555; border-radius: 4px; padding: 4px 10px; border: 1px solid #333; }
            """)

    def save_cleaner_interval(self):
        try:
            hours = float(self.interval_input.text())
            min_hours = 5.0 / 60.0 # 5 minutes = 0.0833 hours
            if hours < min_hours:
                QMessageBox.warning(self, "Interval Too Short", "Fan cleaning interval must be at least 5 minutes (0.08 hours).")
                return
            seconds = int(hours * 3600)
            self.controller.config["cleaner_interval"] = seconds
            self.controller.save_config()
            self.update_cleaner_info_text()
            self.status_label.setText(f"Cleaner interval set to {hours:.2f} hours.")
        except ValueError:
            QMessageBox.critical(self, "Invalid Input", "Please enter a valid numeric value for interval hours.")

    def update_cleaner_info_text(self):
        if not hasattr(self, "cleaner_info_lbl"):
            return
        
        sec = self.controller.config.get("cleaner_interval", 14400)
        if sec >= 3600:
            hrs = sec / 3600.0
            hrs_str = f"{hrs:.1f}".rstrip('0').rstrip('.')
            interval_str = f"{hrs_str} hour" if hrs_str == "1" else f"{hrs_str} hours"
        else:
            mins = int(round(sec / 60.0))
            interval_str = f"{mins} minute" if mins == 1 else f"{mins} minutes"
            
        dur = self.controller.config.get("cleaner_duration", 30)
        dur_str = f"{dur} second" if dur == 1 else f"{dur} seconds"
        
        self.cleaner_info_lbl.setText(
            f"Cleans dust by spinning fans in reverse direction (CleanCreek technology).\n"
            f"Runs automatically every {interval_str} for {dur_str} when enabled."
        )

    def on_cleaner_duration_changed(self):
        self.update_cleaner_duration_source_label()

    def save_cleaner_duration(self):
        val = self.cleaner_duration_spin.value()
        win_dur = self.controller.config.get("windows_cleaner_duration")
        win_imported = self.controller.config.get("windows_config_imported", False)
        
        self.controller.config["cleaner_duration"] = val
        if win_dur is not None and val == win_dur and win_imported:
            self.controller.config["cleaner_duration_user_override"] = False
        else:
            self.controller.config["cleaner_duration_user_override"] = True
            
        self.controller.save_config()
        self.update_cleaner_duration_source_label()
        self.update_cleaner_info_text()
        self.status_label.setText(f"Cleaner duration set to {val}s.")

    def update_cleaner_duration_source_label(self):
        if not hasattr(self, "cleaner_duration_source_lbl"):
            return
        
        current_val = self.cleaner_duration_spin.value()
        win_dur = self.controller.config.get("windows_cleaner_duration")
        win_imported = self.controller.config.get("windows_config_imported", False)
        user_override = self.controller.config.get("cleaner_duration_user_override", False)

        if win_dur is not None and current_val == win_dur and win_imported:
            self.cleaner_duration_source_lbl.setText("(Sourced from Windows OMEN Config)")
            self.cleaner_duration_source_lbl.setStyleSheet("color: #4caf50; font-size: 11px; font-weight: bold; margin-left: 24px;")
        elif user_override or (not win_imported and current_val != 30):
            self.cleaner_duration_source_lbl.setText("(User Specified)")
            self.cleaner_duration_source_lbl.setStyleSheet("color: #2196f3; font-size: 11px; font-weight: bold; margin-left: 24px;")
        elif win_imported:
            self.cleaner_duration_source_lbl.setText("(Sourced from Windows OMEN Config)")
            self.cleaner_duration_source_lbl.setStyleSheet("color: #4caf50; font-size: 11px; font-weight: bold; margin-left: 24px;")
        else:
            self.cleaner_duration_source_lbl.setText("(Default)")
            self.cleaner_duration_source_lbl.setStyleSheet("color: #888888; font-size: 11px; font-weight: bold; margin-left: 24px;")

    def start_manual_cleaning(self):
        import threading
        def _bg_start():
            success, msg = self.controller.start_fan_cleaning()
            if not success:
                print(f"[GUI] Cannot start cleaner: {msg}")
        
        threading.Thread(target=_bg_start, daemon=True).start()
        self.update_status()

    def auto_stop_manual_cleaning(self):
        import threading
        if self.controller.config.get("cleaner_in_progress", False):
            threading.Thread(target=self.controller.stop_fan_cleaning, daemon=True).start()

    def emergency_stop_cleaning(self):
        import threading
        threading.Thread(target=self.controller.emergency_stop_fan_cleaning, daemon=True).start()
        self.update_status()

    def update_cleaner_status(self):
        """Refreshes the live fan-direction / elapsed / last-run card on the cleaner page."""
        import time as _time
        if not hasattr(self, "cleaner_direction_lbl"):
            return

        # --- Fan direction ---
        try:
            in_reverse = self.controller.is_reverse_mode_active()
        except Exception:
            in_reverse = False

        if in_reverse:
            self.cleaner_direction_lbl.setText("\u25bc Reverse")
            self.cleaner_direction_lbl.setStyleSheet(
                "color: #ef5350; font-size: 14px; font-weight: bold; "
                "background: #3b1a1a; border-radius: 4px; padding: 4px 10px;"
            )
        else:
            self.cleaner_direction_lbl.setText("\u25b2 Forward")
            self.cleaner_direction_lbl.setStyleSheet(
                "color: #4caf50; font-size: 14px; font-weight: bold; "
                "background: #1b3a1e; border-radius: 4px; padding: 4px 10px;"
            )

        # --- Current attempt elapsed time ---
        in_progress = self.controller.config.get("cleaner_in_progress", False)
        start_ts = self.controller.config.get("cleaner_start_time")
        if in_progress and start_ts is None:
            self.cleaner_elapsed_lbl.setText("Starting...")
            self.cleaner_elapsed_lbl.setStyleSheet(
                "color: #ffb300; font-size: 13px; font-weight: bold;"
            )
        elif start_ts is not None:
            elapsed = int(_time.time() - start_ts)
            mins, secs = divmod(elapsed, 60)
            self.cleaner_elapsed_lbl.setText(f"{mins:02d}:{secs:02d}")
            self.cleaner_elapsed_lbl.setStyleSheet(
                "color: #ffb300; font-size: 14px; font-weight: bold;"
            )
        else:
            self.cleaner_elapsed_lbl.setText("\u2014")
            self.cleaner_elapsed_lbl.setStyleSheet(
                "color: #fff; font-size: 14px; font-weight: bold;"
            )

        # --- Last run ---
        last_ts = self.controller.config.get("cleaner_last_run")
        if last_ts is not None:
            ago = int(_time.time() - last_ts)
            if ago < 60:
                ago_str = f"{ago}s ago"
            elif ago < 3600:
                ago_str = f"{ago // 60}m ago"
            elif ago < 86400:
                ago_str = f"{ago // 3600}h ago"
            else:
                ago_str = f"{ago // 86400}d ago"
            self.cleaner_lastrun_lbl.setText(ago_str)
        else:
            self.cleaner_lastrun_lbl.setText("Never")

        # --- Update Button Enabled States ---
        in_progress = self.controller.config.get("cleaner_in_progress", False)
        transitioning = self.controller.config.get("cleaner_transitioning", False)
        active = in_progress or transitioning
        
        if hasattr(self, "manual_clean_btn"):
            self.manual_clean_btn.setEnabled(not active)
        if hasattr(self, "emergency_stop_btn"):
            self.emergency_stop_btn.setEnabled(active)

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    # Pre-flight Display Check
    if os.name == 'posix':
        display = os.environ.get("DISPLAY")
        if not display:
            print("Error: No DISPLAY environment variable found.")
            print("If you are running via SSH, ensure X11 forwarding is enabled (-X or -Y).")
            print("If you are running via sudo, try 'sudo -E python3 omen_gui.py' or 'pkexec python3 omen_gui.py'.")
            sys.exit(1)
        
        # Check if we can actually connect to X (prevents obscure segments faults/Qt errors)
        try:
            from subprocess import run, DEVNULL
            res = run(["xset", "q"], stdout=DEVNULL, stderr=DEVNULL)
            if res.returncode != 0 and os.geteuid() == 0:
                 print(f"Warning: Could not connect to display {display} as root.")
                 print("This is likely a permission issue with Xauthority.")
                 print("Fix: Use 'pkexec python3 omen_gui.py' or 'sudo -E python3 omen_gui.py'.")
                 # We don't exit here as xset might not be installed, 
                 # but we provide the hint.
        except Exception:
            pass
    
    app = QApplication(sys.argv)
    app.setStyle("Windows")
    
    # Set App Icon
    icon_path = OMEN_FAN_DIR / "assets" / "logo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
        
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

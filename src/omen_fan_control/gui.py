import sys
import os
import signal
import json
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QFrame, QStackedWidget,
                            QComboBox, QSpinBox, QMessageBox, QTabWidget, QFileDialog,
                            QProgressBar, QScrollArea, QSizePolicy, QListView, QTextEdit, QStyle, QStyledItemDelegate, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QFont, QIcon, QAction, QColor, QPainter, QBrush, QPen
from . import get_assets_dir, get_data_dir
from .logic import FanController
from .fan_curve_widget import FanCurveEditor

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
        self.lbl_pkg_name = QLabel("Package 0")
        self.lbl_pkg_name.setProperty("class", "pkg")
        self.lbl_pkg_val = QLabel("--°C")
        self.lbl_pkg_val.setProperty("class", "pkg_val")
        pkg_layout.addStretch()
        pkg_layout.addWidget(self.lbl_pkg_name)
        pkg_layout.addWidget(self.lbl_pkg_val)
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
            self.lbl_pkg_name.setText(package_found[0])
            self.lbl_pkg_val.setText(f"{package_found[1]}°C")
        else:
            self.lbl_pkg_name.setText("Package")
            self.lbl_pkg_val.setText("--")
        
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
        icon_path = get_assets_dir() / "logo_test.png"
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
        
        self.temp_label = QLabel("0°C")
        self.temp_label.setObjectName("HeaderTemp")
        self.temp_label.setFixedWidth(100)
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
        self.svc_timer.start(15000)
        self.check_service_status()
        
        self.rpm_timer = QTimer()
        self.rpm_timer.timeout.connect(self.update_status)
        self.rpm_timer.start(2000)

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

        if not self.controller.config.get("bypass_warning", False) or self.controller.config.get("debug_experimental_ui", False):
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
                        self.controller.config["bypass_warning"] = True
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
                    self.controller.save_config()
                    QMessageBox.information(self, "Enabled", "Experimental support enabled.\nPlease go to 'Driver Management' to install/update the driver patch.")
                    
                    # Force update options page if it exists
                    if hasattr(self, 'exp_check'):
                         self.exp_check.setChecked(True)
                         self.toggle_experimental_options(True)
                
                if chk.isChecked():
                    self.controller.config["bypass_warning"] = True
                    self.controller.save_config()
                    
                if self.controller.config.get("debug_experimental_ui"):
                     print("Debug experimental UI shown.")

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
            ("Options", self.show_options),
            ("About", self.show_about),
        ]
        
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
        layout = QVBoxLayout(self.fan_page)
        
        layout.addStretch()
        
        container = QFrame()
        container.setStyleSheet("background-color: #252526; border-radius: 10px; padding: 20px;")
        container.setFixedWidth(600)
        c_layout = QVBoxLayout(container)
        
        container = QFrame()
        container.setStyleSheet("background-color: #252526; border-radius: 10px; padding: 15px;")
        container.setFixedWidth(600)
        c_layout = QVBoxLayout(container)
        
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
        self.set_btn.setFixedWidth(100)
        self.set_btn.setStyleSheet("background-color: #d63333; font-weight: bold; padding: 10px; border-radius: 2px;")
        self.set_btn.clicked.connect(self.apply_fan_mode)
        mode_layout.addWidget(self.set_btn)
        
        c_layout.addLayout(mode_layout)
        
        self.manual_widget = QWidget()
        manual_outer_layout = QVBoxLayout(self.manual_widget)
        manual_outer_layout.setContentsMargins(0, 15, 0, 0)
        
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
        self.manual_spin.valueChanged.connect(lambda: self.manual_unsaved_lbl.setVisible(True))
        manual_row_layout.addWidget(self.manual_spin)
        
        manual_outer_layout.addWidget(manual_row)
        
        self.manual_unsaved_lbl = QLabel("Unsaved Changes")
        self.manual_unsaved_lbl.setVisible(False)
        self.manual_unsaved_lbl.setStyleSheet("color: #e65100; font-size: 11px; font-weight: bold;")
        
        sp = self.manual_unsaved_lbl.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.manual_unsaved_lbl.setSizePolicy(sp)
        
        manual_outer_layout.addWidget(self.manual_unsaved_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        
        self.manual_widget.setVisible(False)
        c_layout.addWidget(self.manual_widget)
        
        layout.addWidget(container, alignment=Qt.AlignmentFlag.AlignCenter)
        
        layout.addStretch()
        
        self.curve_editor_container = QWidget()
        self.curve_editor_container.setFixedHeight(450)
        curve_layout = QVBoxLayout(self.curve_editor_container)
        
        curve_header = QHBoxLayout()
        curve_header.addWidget(QLabel("Fan Curve Editor"))
        curve_header.addStretch()
        
        reset_btn = QPushButton("Reset Curve")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setFixedWidth(100)
        reset_btn.setStyleSheet("background-color: #444; font-size: 11px; padding: 4px; border-radius: 3px; color: white;")
        reset_btn.clicked.connect(lambda: self.curve_editor.set_points(None))
        curve_header.addWidget(reset_btn)
        
        curve_layout.addLayout(curve_header)
        
        saved_curve = self.controller.config.get("curve", [])
        self.curve_editor = FanCurveEditor(points=saved_curve if saved_curve else None)
        self.curve_editor.curveChanged.connect(lambda: self.curve_unsaved_lbl.setVisible(True))
        curve_layout.addWidget(self.curve_editor)
        
        self.curve_unsaved_lbl = QLabel("Unsaved Changes")
        self.curve_unsaved_lbl.setVisible(False)
        self.curve_unsaved_lbl.setStyleSheet("color: #e65100; font-size: 11px; font-weight: bold;") 
        
        sp_c = self.curve_unsaved_lbl.sizePolicy()
        sp_c.setRetainSizeWhenHidden(True)
        self.curve_unsaved_lbl.setSizePolicy(sp_c)
        
        curve_layout.addWidget(self.curve_unsaved_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        
        curve_layout.addSpacing(20)
        
        # Stress Test Controls in Curve Tab
        stress_layout = QHBoxLayout()
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
        
        curve_layout.addLayout(stress_layout)
        
        self.curve_editor_container.setVisible(False)
        layout.addWidget(self.curve_editor_container)

        # Watchdog
        self.watchdog_check = QCheckBox("Enable Watchdog (Reset every 90s)")
        self.watchdog_check.toggled.connect(self.toggle_watchdog)
        layout.addWidget(self.watchdog_check)
        
        self.stack.addWidget(self.fan_page)

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
        self.cal_btn.clicked.connect(self.start_calibration)
        c_layout.addWidget(self.cal_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        c_layout.addSpacing(20)
        
        self.cal_progress = QProgressBar()
        self.cal_progress.setFixedWidth(300)
        self.cal_progress.setVisible(False)
        c_layout.addWidget(self.cal_progress, alignment=Qt.AlignmentFlag.AlignCenter)
        
        c_layout.addSpacing(20)
        
        self.cal_result = QLabel("")
        self.cal_result.setStyleSheet("font-size: 18px; color: #d63333;")
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
        form_grid.addWidget(lbl1, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.wait_spin = QSpinBox()
        self.wait_spin.setRange(5, 300)
        self.wait_spin.setFixedWidth(80) 
        self.wait_spin.setValue(self.controller.config.get("calibration_wait", 30))
        self.wait_spin.valueChanged.connect(self.save_options)
        form_grid.addWidget(self.wait_spin, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        lbl2 = QLabel("Temp Smoothing (N):")
        lbl2.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form_grid.addWidget(lbl2, 1, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.ma_spin = QSpinBox()
        self.ma_spin.setRange(1, 20)
        self.ma_spin.setFixedWidth(80)
        self.ma_spin.setValue(self.controller.config.get("ma_window", 5))
        self.ma_spin.setToolTip("Moving Average Window: Number of temperature samples to average.\nHigher values smooth out fan response preventing rapid speed changes, but increase reaction latency.")
        self.ma_spin.valueChanged.connect(self.save_options)
        form_grid.addWidget(self.ma_spin, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        lbl3 = QLabel("Curve Interpolation:")
        lbl3.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form_grid.addWidget(lbl3, 2, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.interp_combo = QComboBox()
        self.interp_combo.addItems(["Smooth", "Discrete"])
        self.interp_combo.setFixedWidth(120)
        current_interp = self.controller.config.get("curve_interpolation", "smooth")
        self.interp_combo.setCurrentText(current_interp.capitalize())
        self.interp_combo.currentTextChanged.connect(self.save_options)
        form_grid.addWidget(self.interp_combo, 2, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.bypass_check = QCheckBox("Bypass Driver Patch Warning")
        self.bypass_check.setChecked(self.controller.config.get("bypass_patch_warning", False))
        self.bypass_check.toggled.connect(self.save_options)
        form_grid.addWidget(self.bypass_check, 3, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.bypass_root_check = QCheckBox("Bypass Root Warning")
        self.bypass_root_check.setChecked(self.controller.config.get("bypass_root_warning", False))
        self.bypass_root_check.toggled.connect(self.save_options)
        form_grid.addWidget(self.bypass_root_check, 4, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Experimental Support Section
        exp_group = QWidget()
        exp_layout = QVBoxLayout(exp_group)
        exp_layout.setContentsMargins(0, 10, 0, 0)
        
        self.exp_check = QCheckBox("Enable Experimental List Support")
        self.exp_check.setStyleSheet("color: #ff9800; font-weight: bold;")
        self.exp_check.setChecked(self.controller.config.get("enable_experimental", False))
        self.exp_check.toggled.connect(self.toggle_experimental_options)
        
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
        self.profile_combo.addItems(["Omen", "Victus", "Victus S"])
        self.profile_combo.setItemDelegate(NoFocusDelegate())
        
        # Map config value to index
        current_profile = self.controller.config.get("thermal_profile", "omen")
        index = {"omen": 0, "victus": 1, "victus_s": 2}.get(current_profile, 0)
        self.profile_combo.setCurrentIndex(index)
        
        exp_opt_layout.addWidget(self.profile_combo)
        
        self.exp_save_btn = QPushButton("Save")
        self.exp_save_btn.setFixedWidth(60)
        self.exp_save_btn.setStyleSheet("background-color: #2e7d32; padding: 5px;")
        self.exp_save_btn.clicked.connect(self.save_options)
        exp_opt_layout.addWidget(self.exp_save_btn)
        
        exp_opt_layout.addStretch()
        
        exp_layout.addWidget(self.exp_options_widget)
        
        form_grid.addWidget(exp_group, 5, 0, 1, 2)
        
        # Init visibility
        self.toggle_experimental_options(self.exp_check.isChecked())
        
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
            with open(get_data_dir() / "LICENSE.md", "r") as f:
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

    # Core Logic
    def update_status(self, temp_override=None):
        rpm = self.controller.get_fan_speed()
        if temp_override is not None:
             temp = int(temp_override)
        else:
             temp = self.controller.get_cpu_temp()
        
        self.rpm_label.setText(f"{rpm} RPM")
        self.temp_label.setText(f"{temp}°C")
        
        self.check_driver_status()

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

        self.controller.config["mode"] = mode
        self.controller.save_config()
        
        self.manual_unsaved_lbl.setVisible(False)
        self.curve_unsaved_lbl.setVisible(False)
        
        if mode == "auto":
            self.controller.set_fan_mode("auto")
            self.status_label.setText("Set mode to Auto")
        elif mode == "max":
            self.controller.set_fan_mode("max")
            self.status_label.setText("Set mode to Max")
        elif mode == "manual":
            percent = self.manual_spin.value()
            pwm_val = int(round(percent / 100 * 255))
            
            self.controller.config["manual_pwm"] = pwm_val
            self.controller.save_config()
            
            self.controller.set_fan_pwm(pwm_val)
            self.status_label.setText(f"Set manual speed to {percent}% (PWM: {pwm_val})")
        elif mode == "curve":
            points = self.curve_editor.get_points()
            self.controller.config["curve"] = points
            self.controller.save_config()
            self.status_label.setText("Curve mode enabled")
            self.start_curve_loop()

    def start_curve_loop(self):
        if not hasattr(self, 'curve_timer'):
            self.curve_timer = QTimer()
            self.curve_timer.timeout.connect(self.apply_curve_step)
        
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

    def start_calibration(self):
        if hasattr(self, 'curve_timer'):
            self.curve_timer.stop()
        
        self.controller.config["mode"] = "calibration"
        self.controller.save_config()
            
        self.cal_btn.setEnabled(False)
        self.cal_progress.setVisible(True)
        self.cal_progress.setRange(0, 100)
        self.cal_progress.setValue(0)
        self.status_label.setText("Calibrating...")
        
        self.cal_thread = WorkerThread(self.controller.calibrate)
        self.cal_thread.progress.connect(self.cal_progress.setValue)
        self.cal_thread.finished.connect(self.on_cal_finished)
        self.cal_thread.start()

    def on_cal_finished(self, max_rpm):
        self.cal_btn.setEnabled(True)
        self.cal_progress.setVisible(False)
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
        self.controller.config['bypass_patch_warning'] = self.bypass_check.isChecked()
        self.controller.config['bypass_root_warning'] = self.bypass_root_check.isChecked()
        
        # Experimental settings
        self.controller.config['enable_experimental'] = self.exp_check.isChecked()
        
        profile_map = {0: "omen", 1: "victus", 2: "victus_s"}
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
        if hasattr(self, "svc_restart_btn"):
            self.svc_restart_btn.setVisible(installed)
        if not installed:
            self.svc_status_label.setText("Service: Not Installed")
            self.svc_status_label.setStyleSheet("color: #888;")
        else:
            running = self.controller.is_service_running()
            if running:
                self.svc_status_label.setText("Service: Active")
                self.svc_status_label.setStyleSheet("color: #4caf50; font-weight: bold;")  # Green
            else:
                self.svc_status_label.setText("Service: Inactive")
                self.svc_status_label.setStyleSheet("color: #ff9800; font-weight: bold;")  # Orange
                # Resume local curve loop if in Curve mode and timer not already active
                if self.mode_combo.currentText() == "Curve" and not (
                    hasattr(self, "curve_timer") and self.curve_timer.isActive()
                ):
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
        self.controller.stop_stress_test()
        self.watchdog_timer.stop()
        self.rpm_timer.stop()
        event.accept()

def main():
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setStyle("Windows")
    icon_path = get_assets_dir() / "logo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
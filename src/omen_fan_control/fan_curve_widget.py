
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QLinearGradient
import sys

class FanCurveEditor(QWidget):
    curveChanged = pyqtSignal(list)

    def __init__(self, points=None):
        super().__init__()
        self.setMinimumSize(400, 300)
        self.max_temp = 105
        if points:
            self.points = [QPointF(x, y) for x, y in points]
            if self.points:
                last = self.points[-1]
                if last.x() != self.max_temp:
                    self.points[-1] = QPointF(self.max_temp, last.y())
        else:
            self.points = [
                QPointF(30, 0),
                QPointF(40, 10),
                QPointF(50, 25),
                QPointF(60, 40),
                QPointF(70, 55),
                QPointF(80, 70),
                QPointF(90, 85),
                QPointF(95, 100),
                QPointF(105, 100)
            ]
        
        self.dragging_index = -1
        self.hover_index = -1
        self.margin = 40
        
        self.bg_color = QColor(20, 20, 20)
        self.grid_color = QColor(60, 60, 60)
        self.line_color = QColor(255, 50, 50)
        self.point_color = QColor(255, 255, 255)
        self.fill_color = QColor(255, 50, 50, 50)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.fillRect(self.rect(), self.bg_color)
        
        w = self.width() - 2 * self.margin
        h = self.height() - 2 * self.margin
        
        painter.setPen(QPen(self.grid_color, 1, Qt.PenStyle.DashLine))
        for i in range(0, 11, 2):
            y = self.margin + h - (i * h / 10)
            painter.drawLine(self.margin, int(y), self.margin + w, int(y))
            painter.drawText(5, int(y) + 5, f"{i*10}%")
        
        steps = 7
        for i in range(steps + 1):
            val = i * (self.max_temp / steps)
            x = self.margin + (val / self.max_temp * w)
            painter.drawLine(int(x), self.margin, int(x), self.margin + h)
            painter.drawText(int(x) - 10, self.height() - 10, f"{int(val)}°C")

        screen_points = []
        for p in self.points:
            sx = self.margin + (p.x() / self.max_temp * w)
            sy = self.margin + h - (p.y() / 100 * h)
            screen_points.append(QPointF(sx, sy))

        if not screen_points:
            return

        from PyQt6.QtGui import QPainterPath
        path = QPainterPath()
        path.moveTo(self.margin, self.margin + h)
        
        for p in screen_points:
            path.lineTo(p)
            
        path.lineTo(screen_points[-1].x(), self.margin + h)
        path.closeSubpath()
        
        gradient = QLinearGradient(self.margin, 0, self.margin + w, 0)
        gradient.setColorAt(0, QColor(255, 220, 30, 100)) 
        gradient.setColorAt(1, QColor(214, 51, 51, 100))
        
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
        
        # Line Gradient (Orange -> Red)
        line_gradient = QLinearGradient(self.margin, 0, self.margin + w, 0)
        line_gradient.setColorAt(0, QColor("#ff9800")) 
        line_gradient.setColorAt(1, QColor("#d63333"))
        
        line_pen = QPen(QBrush(line_gradient), 3)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        
        painter.setPen(line_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        line_path = QPainterPath()
        if screen_points:
            line_path.moveTo(screen_points[0])
            for p in screen_points[1:]:
                line_path.lineTo(p)
        
        painter.drawPath(line_path)

        for i, p in enumerate(screen_points):
            size = 12 if i == self.hover_index or i == self.dragging_index else 8
            painter.setBrush(self.point_color)
            if i == self.hover_index:
                painter.setBrush(QColor(255, 100, 100))
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(p, size/2, size/2)
            
            text = f"{int(self.points[i].x())}°C, {int(self.points[i].y())}%"
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(int(p.x()) - 20, int(p.y()) - 15, text)

    def mousePressEvent(self, event):
        w = self.width() - 2 * self.margin
        h = self.height() - 2 * self.margin
        pos = event.position()
        
        for i, p in enumerate(self.points):
            sx = self.margin + (p.x() / self.max_temp * w)
            sy = self.margin + h - (p.y() / 100 * h)
            dist = ((pos.x() - sx)**2 + (pos.y() - sy)**2)**0.5
            if dist < 15:
                self.dragging_index = i
                self.update()
                return

    def mouseMoveEvent(self, event):
        w = self.width() - 2 * self.margin
        h = self.height() - 2 * self.margin
        pos = event.position()
        
        self.hover_index = -1
        for i, p in enumerate(self.points):
            sx = self.margin + (p.x() / self.max_temp * w)
            sy = self.margin + h - (p.y() / 100 * h)
            dist = ((pos.x() - sx)**2 + (pos.y() - sy)**2)**0.5
            if dist < 15:
                self.hover_index = i
                break
        
        if self.dragging_index != -1:
            new_x = (pos.x() - self.margin) / w * self.max_temp
            new_y = (self.margin + h - pos.y()) / h * 100
            
            min_x = 0
            if self.dragging_index > 0:
                min_x = self.points[self.dragging_index - 1].x()
                
            max_x = self.max_temp
            if self.dragging_index < len(self.points) - 1:
                max_x = self.points[self.dragging_index + 1].x()
            
            new_x = max(min_x, min(max_x, new_x))

            min_y = 0
            if self.dragging_index > 0:
                min_y = self.points[self.dragging_index - 1].y()
                
            max_y = 100
            if self.dragging_index < len(self.points) - 1:
                max_y = self.points[self.dragging_index + 1].y()
            
            new_y = max(min_y, min(max_y, new_y))
            
            if self.dragging_index == len(self.points) - 1:
                new_x = self.max_temp
            
            self.points[self.dragging_index] = QPointF(new_x, new_y)
            
            self.curveChanged.emit([(p.x(), p.y()) for p in self.points])
            
        self.update()

    def mouseReleaseEvent(self, event):
        self.dragging_index = -1
        self.update()

    def get_points(self):
        return [(p.x(), p.y()) for p in self.points]

    def set_points(self, points):
        if points is None:
            self.points = [
                QPointF(30, 0), QPointF(40, 10), QPointF(50, 25), QPointF(60, 40),
                QPointF(70, 55), QPointF(80, 70), QPointF(90, 85), QPointF(95, 100), QPointF(105, 100),
            ]
        else:
            self.points = [QPointF(x, y) for x, y in points]
        if self.points:
             last = self.points[-1]
             if last.x() != self.max_temp:
                 self.points[-1] = QPointF(self.max_temp, last.y())
        self.update()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = FanCurveEditor()
    ex.show()
    sys.exit(app.exec())

#!/usr/bin/env python3
#
#

import argparse
import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

from functools import partial

import graphviz
import hal

parser = argparse.ArgumentParser()
parser.add_argument("--interval", "-i", help="update interval", type=int, default=100)
parser.add_argument("--buffer", "-b", help="linechart buffer size", type=int, default=50)
parser.add_argument("--setup", "-s", help="setup file", type=str, default="")
parser.add_argument("--qt5", "-5", help="using pyqt5", default=False, action="store_true")
parser.add_argument("--qt6", "-6", help="using pyqt6", default=False, action="store_true")
parser.add_argument("--svg", "-S", help="save to svg and exit", type=str, default="")
parser.add_argument("--file", "-f", help="read halcmd show from dump file", type=str, default="")
parser.add_argument("--direct", "-d", help="direct search / no enter needed", default=False, action="store_true")
args = parser.parse_args()
qtversion = "5"
if args.qt6:
    qtversion = "6"

if qtversion == "5":
    from PyQt5.QtCore import QPoint, QPointF, QRectF, QStringListModel, QTimer, Qt
    from PyQt5.QtGui import (
        QBrush,
        QColor,
        QFont,
        QKeySequence,
        QMouseEvent,
        QPainter,
        QPainterPath,
        QPen,
    )
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QCompleter,
        QDialog,
        QDialogButtonBox,
        QGraphicsItem,
        QGraphicsPathItem,
        QGraphicsScene,
        QGraphicsView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPushButton,
        QScrollArea,
        QShortcut,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
else:
    from PyQt6.QtCore import QPoint, QPointF, QRectF, QStringListModel, QTimer, Qt
    from PyQt6.QtGui import (
        QBrush,
        QColor,
        QCompleter,
        QFont,
        QKeySequence,
        QMouseEvent,
        QPainter,
        QPainterPath,
        QPen,
        QShortcut,
    )
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QGraphicsItem,
        QGraphicsPathItem,
        QGraphicsScene,
        QGraphicsView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPushButton,
        QScrollArea,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )


class NodeEdge(QGraphicsPathItem):
    width = 3
    width_selected = 6

    def __init__(self, parent, signal, source_node, source_port, des_node, des_port):
        super().__init__(None)
        self.parent = parent
        self.signal = signal
        self._source_node = source_node
        self._source_port = source_port
        self._target_node = des_node
        self._target_port = des_port
        self.color = Qt.GlobalColor.gray
        self.style = Qt.PenStyle.SolidLine
        self._pen_default = QPen(self.color)
        self._pen_default.setWidthF(2)
        # self.setZValue(-1)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.update_edge_path()
        self.hover = False

    def paint(self, painter: QPainter, option, widget):
        self._pen_default = QPen(self.color)
        if self.hover:
            self._pen_default.setWidthF(self.width_selected)
        else:
            self._pen_default.setWidthF(self.width)
        painter.setPen(self._pen_default)
        self.update_edge_path()
        painter.drawPath(self.path())

    def update_edge_path(self):
        if not self._source_node or not self._target_node:
            return
        pos1 = self._source_node.port_pos(self._source_port, self._target_node)
        pos2 = self._target_node.port_pos(self._target_port, self._source_node)
        distance = (pos2.x() - pos1.x()) / 2
        control_x_start = distance
        control_x_end = -distance
        path = QPainterPath(pos1)
        path.cubicTo(
            QPointF(pos1.x() + control_x_start, pos1.y()),
            QPointF(pos2.x() + control_x_end, pos2.y()),
            pos2,
        )
        self.setPath(path)

    def hoverEnterEvent(self, event):
        self.hover = True
        self.parent.info.setText(self.signal)
        self.update()

    def hoverLeaveEvent(self, event):
        self.hover = False
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.parent.port_disconnect((self._source_node, self._source_port), (self._target_node, self._target_port))


class CompNode(QGraphicsItem):
    name = ""
    radius = 5
    border_size = 4
    border_color = QColor(150, 150, 150)
    border_color_selected = QColor(250, 250, 250)
    border_color_hover = QColor(200, 200, 200)
    bg_color = QColor(100, 100, 100)
    title_size = 9
    info_size = 7
    text_scale = 1.8
    text_font = "Times"
    title_color = QColor(255, 255, 255)
    info_color = QColor(200, 200, 200)
    action_color = QColor(225, 225, 225)
    port_selected_color = QColor(225, 0, 0)
    port_marked_color = QColor(0, 255, 0)
    port_size = 10
    port_border = 2
    port_top = 40
    port_bottom = 10
    port_diff = 15

    def __init__(self, parent, x, y, w, h, title, pins):
        super().__init__()
        self.parent = parent
        self.width = w
        self.height = h
        self.title = title
        self.pins = pins
        if x is not None and y is not None:
            self.setPos(x, y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.hover = False

    def port_selected(self, mpos):
        mpos_y = mpos.y()
        idx = int((mpos_y - self.radius - 16) // 16)
        if idx >= 0 and idx < len((self.pins)):
            return list(self.pins)[idx]
        return None

    def port_pos(self, port, other_node):
        pos = self.pos()
        pos_x = pos.x()
        pos_y = pos.y()
        opos = other_node.pos()
        if pos_x < opos.x():
            pos_x += self.width - 8
        else:
            pos_x += 8
        if port in self.pins:
            idx = list(self.pins).index(port)
            pos_y += self.radius + 16 + idx * 16 + 8
        return QPointF(pos_x, pos_y)

    def boundingRect(self):
        self.height = len(self.pins) * 16 + 16 + self.radius * 2
        return QRectF(0, 0, self.width, self.height)

    def paintArrow(self, painter, x, y, direction):
        if direction == "LEFT":
            path = QPainterPath()
            path.moveTo(QPointF(x - 5, y))
            path.lineTo(QPointF(x + 5, y + 5))
            path.lineTo(QPointF(x + 5, y - 5))
            path.lineTo(QPointF(x - 5, y))
        elif direction == "RIGHT":
            path = QPainterPath()
            path.moveTo(QPointF(x + 5, y))
            path.lineTo(QPointF(x - 5, y + 5))
            path.lineTo(QPointF(x - 5, y - 5))
            path.lineTo(QPointF(x + 5, y))
        else:
            path = QPainterPath()
            path.moveTo(QPointF(x + 5, y + 5))
            path.lineTo(QPointF(x - 5, y + 5))
            path.lineTo(QPointF(x - 5, y - 5))
            path.lineTo(QPointF(x + 5, y - 5))
            path.lineTo(QPointF(x + 5, y + 5))
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        painter.setBrush(QBrush(Qt.GlobalColor.yellow))
        painter.fillPath(path, painter.brush())
        painter.drawPath(path)

    def paint(self, painter, option, widget):
        if self.hover:
            pen = QPen(self.border_color_hover, self.border_size)
        elif self.isSelected():
            pen = QPen(self.border_color_selected, self.border_size)
        else:
            pen = QPen(self.border_color, self.border_size)
        painter.setPen(QPen(self.title_color, 1))
        painter.setFont(QFont(self.text_font, self.title_size))

        # title
        rect = self.boundingRect()
        rect = QRectF(0, 0, self.width, self.radius + 16)
        title_path = QPainterPath()
        title_path.addRoundedRect(rect, self.radius, self.radius)
        painter.setClipPath(title_path)

        # path
        rect = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        painter.setClipPath(path)

        # background
        brush = QBrush(self.bg_color)
        painter.setBrush(brush)
        painter.fillPath(path, painter.brush())

        # title background
        brush = QBrush(QColor(150, 150, 200))
        painter.setBrush(brush)
        painter.fillPath(title_path, painter.brush())
        py = self.radius
        painter.setPen(QPen(self.title_color, 1))
        painter.drawText(
            QRectF(0, py - 3, self.width, 16),
            Qt.AlignmentFlag.AlignCenter,
            self.title,
        )
        py += 16

        # border
        painter.setPen(pen)
        painter.strokePath(path, painter.pen())

        # pin text
        for pin_name, pin_data in self.pins.items():
            pin_title = pin_data["pin"]
            value = pin_data["value"]
            pininfo = pin_data["pininfo"]
            marked = pin_data["marked"]
            if not pininfo:
                print(f"ERROR: name: {pin_name} pininfo: {pininfo}")
                continue
            direction = pininfo["direction"]
            signal = pininfo["signal"]
            if signal is None:
                painter.setPen(QPen(self.info_color, 1))
                title = f"{pin_title}={value}"
                if not signal and direction == "IN":
                    title = f">{pin_title}={value}<"
                    painter.setPen(QPen(self.action_color, 1))
                if self.parent.port_source and self.parent.port_source == (self, pin_name):
                    painter.setPen(QPen(self.port_selected_color, 1))
                elif marked:
                    painter.setPen(QPen(self.port_marked_color, 1))
                painter.drawText(
                    QRectF(0, py, self.width, 16),
                    Qt.AlignmentFlag.AlignCenter,
                    title,
                )
            else:
                if direction == "IN":
                    self.paintArrow(painter, 8, py + 8, "RIGHT")
                    self.paintArrow(painter, self.width - 8, py + 8, "LEFT")
                elif direction == "OUT":
                    self.paintArrow(painter, 8, py + 8, "LEFT")
                    self.paintArrow(painter, self.width - 8, py + 8, "RIGHT")
                else:
                    self.paintArrow(painter, 8, py + 8, "BOTH")
                    self.paintArrow(painter, self.width - 8, py + 8, "BOTH")

                if self.parent.port_source and self.parent.port_source == (self, pin_name):
                    painter.setPen(QPen(self.port_selected_color, 1))
                elif marked:
                    painter.setPen(QPen(self.port_marked_color, 1))
                else:
                    painter.setPen(QPen(self.title_color, 1))
                painter.drawText(
                    QRectF(0, py, self.width, 16),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{pin_title}={value}",
                )
            py += 16

    def hoverEnterEvent(self, event):
        self.hover = True
        self.parent.info.setText(f"Group: {self.title}")
        self.update()

    def hoverLeaveEvent(self, event):
        self.hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            port = self.port_selected(event.pos())
            if port:
                self.parent.searchtext.setText(f"{self.title}.{port}")
            else:
                self.parent.searchtext.setText(self.title)
            self.parent.search()
        elif event.button() == Qt.MouseButton.LeftButton:
            port = self.port_selected(event.pos())
            if port:
                self.parent.port_select((self, port))
            else:
                QGraphicsItem.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        pos = self.pos()
        self.parent.nodesetup["positions"][self.title] = (pos.x(), pos.y())
        self.parent.writeSetup()
        QGraphicsItem.mouseReleaseEvent(self, event)

    def mouseDoubleClickEvent(self, event):
        port = None
        if event.button() == Qt.MouseButton.LeftButton:
            port = self.port_selected(event.pos())
            if port:
                signal = None
                if port in self.pins:
                    pin_data = self.pins[port]
                    pininfo = pin_data["pininfo"]
                    signal = pininfo["signal"]
                    direction = pininfo["direction"]
                    vtype = pininfo["vtype"]
                    pinname = f"{self.title}.{port}"
                    if not signal and direction == "IN":
                        if not self.parent.nodesetup["editable"]:
                            return
                        # change value
                        value = hal.get_value(pinname)
                        if vtype == "bit":
                            value = str(int(not value))
                            hal.set_p(pinname, value)
                            print(f"setp {pinname} {value}")
                        else:
                            dialog = QDialog()
                            dialog.setWindowTitle(f"setp {pinname}")
                            dialog.setMinimumWidth(500)
                            dialog.layout = QVBoxLayout()
                            dialog.setLayout(dialog.layout)
                            dialog_buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
                            dialog_buttonBox.accepted.connect(dialog.accept)
                            dialog_buttonBox.rejected.connect(dialog.reject)
                            edit = QLineEdit()
                            edit.setText(str(value))
                            vbox = QVBoxLayout()
                            vbox.addWidget(QLabel(pinname), stretch=1)
                            vbox.addWidget(edit, stretch=2)
                            dialog.layout.addLayout(vbox)
                            dialog.layout.addWidget(dialog_buttonBox)
                            if dialog.exec():
                                value = edit.text()
                                hal.set_p(pinname, value)
                                print(f"setp {pinname} {value}")
                        return
                self.parent.toggle_pin_graph(pinname)
            else:
                self.parent.toggle_group_graph(f"{self.title.split('.')[0]}.")


class NodeScene(QGraphicsScene):
    def __init__(self, x, y, w, h, parent):
        super().__init__(x, y, w, h)
        self.parent = parent
        self.setBackgroundBrush(QColor("#262626"))


class NodeViewer(QGraphicsView):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.scene = parent.scene
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)

        self.button_pressed = 0
        self.mouse_pos_last = QPoint()
        self.mouse_pos = QPoint()

    def getZoom(self):
        transform = self.transform()
        return transform.m11()

    def setZoom(self, zoomFactor):
        transform = self.transform()
        transform.reset()
        transform.scale(zoomFactor, zoomFactor)
        self.setTransform(transform)

    def wheelEvent(self, event):
        zoom = self.getZoom()
        angle = event.angleDelta().y()
        zoomFactor = max(min(1 + (angle / 1000), 1.2), 0.2)
        if zoom < 0.06 and zoomFactor < 0.5:
            return
        if self.getZoom() > 5.0 and zoomFactor > 1.0:
            return
        self.scale(zoomFactor, zoomFactor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        self.mouse_pos = event.pos()
        self.button_pressed = event.button()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.mouse_pos = event.pos()
        self.button_pressed = 0
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() in [Qt.MouseButton.RightButton]:
            self.parent.fit_view()
        else:
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.mouse_pos_last = event.pos()
        if self.button_pressed in [Qt.MouseButton.LeftButton]:
            pass

        elif self.button_pressed in [Qt.MouseButton.MiddleButton]:
            offset = self.mouse_pos - event.pos()
            self.mouse_pos = event.pos()
            dx, dy = offset.x(), offset.y()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() + dx))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() + dy))

        super().mouseMoveEvent(event)


class LineCharts(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.data = self.parent.pin_graph_data
        self.width = 0
        self.height = 0
        self.resize(self.width, self.height)

    def resizeEvent(self, event):
        self.width = event.size().width()

    def mouseDoubleClickEvent(self, event):
        mpos_y = event.pos().y()
        py = 10
        gh = 70
        idx = int((mpos_y - py) // (22 + gh + 5))
        if idx < len(self.parent.nodesetup["linecharts"]):
            self.parent.nodesetup["linecharts"].pop(idx)
        self.parent.writeSetup()
        self.parent.check_splitter()

    def paintEvent(self, event):
        if self.width < 10:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Arial", 12))
        painter.setPen(QPen(Qt.GlobalColor.black, 1))

        try:
            gw = self.width - 10
            gh = 70
            px = 5
            py = 10
            for pin, data in self.data.items():
                painter.setPen(QPen(Qt.GlobalColor.black, 1))
                if not data["data"]:
                    painter.drawText(QRectF(5, py, gw, 22), Qt.AlignmentFlag.AlignLeft, pin)
                    py += 22
                else:
                    painter.drawText(
                        QRectF(5, py, gw, 22),
                        Qt.AlignmentFlag.AlignLeft,
                        f"{pin}: {data['data'][0]}",
                    )
                    py += 22

                    if data["min"] is None:
                        data["min"] = float(data["data"][0])
                        data["max"] = float(data["data"][0])
                    for point in data["data"]:
                        data["min"] = min(data["min"], float(point))
                        data["max"] = max(data["max"], float(point))
                    vdiff = data["max"] - data["min"]

                    painter.fillRect(QRectF(px, py - 1, gw + 2, gh + 2), Qt.GlobalColor.gray)
                    painter.setPen(QPen(Qt.GlobalColor.blue, 1))

                    if vdiff != 0:
                        point = data["data"][0]
                        gy_last = (float(point) - data["min"]) / vdiff * gh
                        gx_last = gw
                        for gn, point in enumerate(data["data"][1:]):
                            gy = (float(point) - data["min"]) / vdiff * gh
                            gx = px + gw - (gn * gw / data["len"])
                            painter.drawLine(QPointF(gx_last, py + gy_last), QPointF(gx, py + gy))
                            gy_last = gy
                            gx_last = gx

                py += gh + 5

            self.height = py + 10
            self.setFixedHeight(self.height)

        except Exception:
            pass


class MainWindow(QMainWindow):
    search_str = ""
    default_grouping = ["halui.", "pyvcp.", "qtpyvcp.", "gladevcp.", "qtdragon.", "flexhal.", "rio-gui.", "cmsg."]
    grouping = []
    cfilter = (
        "halui.",
        "joint.",
        "pid.",
        "spindle.",
        "iocontrol.",
        "axis.",
        "motion.digital-in-",
        "motion.digital-out-",
        "motion.feed-",
        "motion.tooloffset.",
        "motion.analog-in-",
        "motion.analog-out-",
        "motion-command-handler.time",
        "motion-controller.time",
        "motion.adaptive-feed",
        "motion.coord-error",
        "motion.coord-mode",
        "motion.current-vel",
        "motion.distance-to-go",
        "motion.eoffset-active",
        "motion.eoffset-limited",
        "motion.homing-inhibit",
        "motion.in-position",
        "motion.jog-inhibit",
        "motion.jog-is-active",
        "motion.jog-stop",
        "motion.jog-stop-immediate",
        "motion.on-soft-limit",
        "motion.requested-vel",
        "motion.servo.last-period",
        "motion.tp-reverse",
    )
    pfilter = (
        "-not",
        "-abs",
        "-s32",
        "-u32",
        ".maxcmdD",
        ".maxcmdDD",
        ".maxcmdDDD",
        ".maxerror",
        ".maxerrorD",
        ".maxerrorI",
        ".maxoutput",
        ".saturated",
        ".saturated-count",
        ".saturated-s",
        ".tune-cycles",
        ".tune-effort",
        ".tune-mode",
        ".tune-start",
        ".tune-type",
        ".command-deriv",
        ".do-pid-calcs.time",
        ".error-previous-target",
        ".feedback-deriv",
    )

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LinuxCNC - HalViewer")
        self.port_source = None
        self.nodesetup = {}
        if not args.setup:
            result = subprocess.run(["halreport"], stdout=subprocess.PIPE, check=False)
            for line in result.stdout.decode().split("\n"):
                if line.startswith("INI_FILE_NAME:"):
                    args.setup = f"{os.path.dirname(line.split()[-1])}/halviewer.json"
        if args.setup:
            print(f"INFO: savefile is: {args.setup}")
        if args.setup and os.path.isfile(args.setup):
            self.nodesetup = json.loads(open(args.setup, "r").read())
        if "linecharts" not in self.nodesetup:
            self.nodesetup["linecharts"] = []
        if "positions" not in self.nodesetup:
            self.nodesetup["positions"] = {}
        if "grouping" not in self.nodesetup:
            self.nodesetup["grouping"] = self.default_grouping[0:]
        if "unconnected" not in self.nodesetup:
            self.nodesetup["unconnected"] = False
        if "namesort" not in self.nodesetup:
            self.nodesetup["namesort"] = False
        if "dirsort" not in self.nodesetup:
            self.nodesetup["dirsort"] = False
        if "filter" not in self.nodesetup:
            self.nodesetup["filter"] = True
        if "search" not in self.nodesetup:
            self.nodesetup["search"] = ""
        if "editable" not in self.nodesetup:
            self.nodesetup["editable"] = False

        self.pin_graph_data = {}
        self.run = True
        self.resize(1200, 900)
        self.scene = NodeScene(-7000, -7000, 12000, 12000, self)
        self.view = NodeViewer(self)
        self.charts = LineCharts(self)

        if args.svg:
            print(f"saving svg to {args.svg}")
            svg_data = self.export()
            open(args.svg, "w").write(svg_data.decode())
            sys.exit(0)

        self.h = hal.component(f"halview-{uuid.uuid4()}")
        self.h.ready()

        hboxButtons = QHBoxLayout()
        hboxBoxes = QHBoxLayout()

        for tval in ("unconnected", "namesort", "dirsort", "filter", "editable"):
            checkbox = QCheckBox(tval.title())
            checkbox.setChecked(self.nodesetup[tval])
            checkbox.stateChanged.connect(partial(self.toggle, tval))
            hboxBoxes.addWidget(checkbox, stretch=0)

        self.searchtext = QLineEdit()
        self.searchtext.setText(self.nodesetup["search"])
        if args.direct:
            self.searchtext.textChanged.connect(self.search)
        else:
            self.searchtext.returnPressed.connect(self.search)
        hboxBoxes.addWidget(self.searchtext, stretch=0)

        self._completer_activated = False
        self.completer = QCompleter(self)
        self.completer_model = QStringListModel()
        self.completer.setModel(self.completer_model)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setMaxVisibleItems(20)
        self.searchtext.setCompleter(self.completer)
        self.completer.activated.connect(self.on_search_activated)

        button_reset_grouping = QPushButton("Reset grouping")
        button_reset_grouping.clicked.connect(self.reset_grouping)
        hboxButtons.addWidget(button_reset_grouping, stretch=0)

        button_reset_layout = QPushButton("Reset layout")
        button_reset_layout.clicked.connect(self.reset_layout)
        hboxButtons.addWidget(button_reset_layout, stretch=0)

        button_fit = QPushButton("Fit to Window")
        button_fit.clicked.connect(self.fit_view)
        hboxButtons.addWidget(button_fit, stretch=0)

        button_freeze = QPushButton("Freeze")
        button_freeze.clicked.connect(self.freeze)
        hboxButtons.addWidget(button_freeze, stretch=0)

        vboxMain = QVBoxLayout()
        hboxButtons.addStretch()
        vboxMain.addLayout(hboxButtons, stretch=0)

        linecharts = QScrollArea()
        linecharts.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        linecharts.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        linecharts.setWidgetResizable(True)
        linecharts.setWidget(self.charts)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(linecharts)
        self.splitter.setSizes([self.geometry().width() - self.charts.width, 0])
        vboxMain.addWidget(self.splitter, stretch=1)
        hboxBoxes.addStretch()
        vboxMain.addLayout(hboxBoxes, stretch=0)

        hboxCmd = QHBoxLayout()
        self.cmd = QLineEdit()
        self.cmd.returnPressed.connect(self.halcmd)
        hboxCmd.addWidget(QLabel("Hall-Command:"), stretch=0)
        hboxCmd.addWidget(self.cmd, stretch=1)
        vboxMain.addLayout(hboxCmd, stretch=0)

        self.info = QLabel("--")
        vboxMain.addWidget(self.info, stretch=0)

        self.main = QWidget()
        self.setCentralWidget(self.main)
        self.main.setLayout(vboxMain)

        svg_data = self.export()
        self.root = ET.fromstring(svg_data)
        if self.root is None:
            print("ERROR parsing ini file")
            exit(0)

        self.readGraph()
        self.check_splitter()
        self.show()
        self.fit_view()

        self.timer = QTimer()
        self.timer.timeout.connect(self.runTimer)
        self.timer.start(args.interval)

        # Keyboard shortcuts
        zoom_in_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_Equal), self)
        zoom_in_shortcut.activated.connect(self.zoom_in)

        zoom_out_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_Minus), self)
        zoom_out_shortcut.activated.connect(self.zoom_out)

        fit_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_0), self)
        fit_shortcut.activated.connect(self.fit_view)

        search_shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_F), self)
        search_shortcut.activated.connect(self.focus_search)

    def zoom_in(self):
        old_anchor = self.view.transformationAnchor()
        self.view.setTransformationAnchor(self.view.ViewportAnchor.AnchorViewCenter)
        self.view.scale(1.15, 1.15)
        self.view.setTransformationAnchor(old_anchor)

    def zoom_out(self):
        old_anchor = self.view.transformationAnchor()
        self.view.setTransformationAnchor(self.view.ViewportAnchor.AnchorViewCenter)
        self.view.scale(1 / 1.15, 1 / 1.15)
        self.view.setTransformationAnchor(old_anchor)

    def focus_search(self):
        self.searchtext.setFocus()
        self.searchtext.selectAll()

    def on_search_activated(self, text=None):
        self._completer_activated = True
        if not text:
            text = self.searchtext.text()
        self.nodesetup["search"] = ""
        self.searchtext.blockSignals(True)
        self.searchtext.clear()
        self.searchtext.blockSignals(False)
        self.reload()
        self.zoom_to_item(text)
        QTimer.singleShot(0, self._reset_completer_flag)

    def _reset_completer_flag(self):
        self._completer_activated = False

    def zoom_to_item(self, text):
        name = text.strip()
        if not name:
            return
        if name in self.nodesdict:
            instance = name
        elif name in self.pinsdict:
            instance = self.pinsdict[name]["node"]
        else:
            return
        self.zoom_to_instance(instance)

    def zoom_to_instance(self, name):
        node = self.nodesdict.get(name)
        if node is None:
            return
        node.boundingRect()
        px = node.pos().x()
        py = node.pos().y()
        w = node.width
        h = node.height
        slider_size = 20
        vw = self.view.width() - slider_size
        vh = self.view.height() - slider_size
        border = 80
        scale = min((vw - border) / w, (vh - border) / h)
        scale = min(scale, 4.0)
        if scale <= 0:
            return
        pos_x = int(px * scale)
        pos_y = int(py * scale)
        diff_x = vw - w * scale
        diff_y = vh - h * scale
        pos_x -= diff_x / 2
        pos_y -= diff_y / 2
        self.view.setZoom(scale)
        self.view.horizontalScrollBar().setSliderPosition(int(pos_x))
        self.view.verticalScrollBar().setSliderPosition(int(pos_y))
        self.update()

    def port_select(self, port):
        if not self.nodesetup["editable"]:
            return
        if self.port_source == port:
            self.port_source = None
            port[0].update()
        elif self.port_source:
            self.port_connect(port)
        else:
            source_pin_data = port[0].pins[port[1]]
            source_pininfo = source_pin_data["pininfo"]
            source_name = source_pininfo["name"]
            source_signal = source_pininfo["signal"]
            source_direction = source_pininfo["direction"]
            source_vtype = source_pininfo["vtype"]
            if self.port_source:
                self.port_source[0].update()
            print("port_select", source_direction)
            if source_direction in ("OUT", "I/O"):
                self.port_source = port
                if not source_signal:
                    source_signal = "sig_" + source_name.replace(".", "_")
                self.cmd.setText(f"net {source_signal} {source_name} => ")

                for item in self.scene.items():
                    if isinstance(item, CompNode):
                        for pin_name, pin_data in item.pins.items():
                            pininfo = pin_data["pininfo"]
                            signal = pininfo["signal"]
                            direction = pininfo["direction"]
                            vtype = pininfo["vtype"]
                            if item != self.port_source[0] and vtype == source_vtype and direction != source_direction and not signal:
                                pin_data["marked"] = True
                            else:
                                pin_data["marked"] = False
                        item.update()

    def port_disconnect(self, source, target):
        if not self.nodesetup["editable"]:
            return
        source_pin_data = source[0].pins[source[1]]
        source_pininfo = source_pin_data["pininfo"]
        source_name = source_pininfo["name"]
        target_pin_data = target[0].pins[target[1]]
        target_pininfo = target_pin_data["pininfo"]
        target_name = target_pininfo["name"]
        target_direction = target_pininfo["direction"]
        if target_direction == "IN":
            hal.disconnect(target_name)
        else:
            hal.disconnect(source_name)
        self.reload()
        # self.fit_view()

    def port_connect(self, target, source=None):
        if not self.nodesetup["editable"]:
            return
        if source:
            self.port_source = source
        if self.port_source and target:
            source_pin_data = self.port_source[0].pins[self.port_source[1]]
            source_pininfo = source_pin_data["pininfo"]
            source_name = source_pininfo["name"]
            source_signal = source_pininfo["signal"]
            source_direction = source_pininfo["direction"]
            source_vtype = source_pininfo["vtype"]
            target_pin_data = target[0].pins[target[1]]
            target_pininfo = target_pin_data["pininfo"]
            target_name = target_pininfo["name"]
            target_signal = target_pininfo["signal"]
            target_direction = target_pininfo["direction"]
            target_vtype = target_pininfo["vtype"]

            if source_vtype != target_vtype:
                print(f"ERROR: can not connect {source_vtype} to {target_vtype}")
            if source_direction == target_direction:
                print(f"ERROR: can not connect {source_direction} to {target_direction}")

            if source_direction == "OUT":
                if source_signal == target_signal:
                    print("  disconnect", target_name)
                    hal.disconnect(target_name)
                elif source_signal:
                    print(f"  source_signal({source_signal}) -> {target_name}")
                    hal.connect(target_name, source_signal)
                else:
                    print(f"  {source_name} -> {target_name}")
                self.reload()
                # self.fit_view()

        self.cmd.setText("")
        self.port_source = None

    def toggle(self, name, value):
        self.nodesetup[name] = bool(value)
        self.reload()
        self.fit_view()

    def halcmd(self):
        cmd = self.cmd.text()
        print("halcmd:", cmd)
        if cmd:
            result = subprocess.run(["halcmd", cmd], stdout=subprocess.PIPE, check=False)
            print(result.stdout.decode())

    def search(self, text=None):
        if self._completer_activated:
            return
        self.nodesetup["search"] = self.searchtext.text()
        self.reload()
        self.fit_view()

    def reload(self):
        svg_data = self.export()
        self.root = ET.fromstring(svg_data)
        self.readGraph()
        self.writeSetup()

    def reset_grouping(self):
        self.nodesetup["grouping"] = self.default_grouping[0:]
        self.reload()
        self.fit_view()

    def reset_layout(self):
        self.nodesetup["positions"] = {}
        self.reload()
        self.fit_view()

    def check_splitter(self):
        if self.nodesetup["linecharts"]:
            if self.charts.width < 10:
                self.charts.width = 200
                self.splitter.setSizes([self.geometry().width() - self.charts.width, self.charts.width])
        elif self.charts.width > 100:
            self.charts.width = 0
            self.splitter.setSizes([self.geometry().width(), 0])

    def toggle_group_graph(self, group):
        if group in self.nodesetup["grouping"]:
            self.nodesetup["grouping"].remove(group)
        else:
            self.nodesetup["grouping"].append(group)
        self.reload()

    def toggle_pin_graph(self, pin):
        if pin in self.nodesetup["linecharts"]:
            self.nodesetup["linecharts"].remove(pin)
        else:
            self.nodesetup["linecharts"].append(pin)
        self.check_splitter()
        self.writeSetup()

    def export(self):
        colors = {
            "bg": "",
            "edge": "black",
            "header_bg": "black",
            "header_text": "white",
            "port_bg": "white",
            "port_text": "black",
            "setp_bg": "gray",
            "setp_text": "black",
        }

        engine = "dot"  # 'circo', 'dot', 'fdp', 'neato', 'osage', 'patchwork', 'sfdp', 'twopi'
        ranksep = "1.5"
        self.gAll = graphviz.Digraph("G", format="svg", engine=engine)
        self.gAll.attr(ranksep=ranksep)
        self.gAll.attr(rankdir="LR")

        self.pininfo = {}
        self.signals = {}
        self.components = {}
        self.setps = []

        if args.file:
            result = open(args.file, "r").read()
        else:
            result = subprocess.run(["halcmd", "show"], stdout=subprocess.PIPE, check=False).stdout.decode()

        sfilters = []
        if self.nodesetup["search"]:
            section = ""
            for line in result.split("\n"):
                if line == "Parameters:":
                    section = "params"
                elif line == "Component Pins:":
                    section = "pins"
                elif not line:
                    section = ""
                elif section == "pins" and line.split()[0].isnumeric():
                    if "=" in line:
                        owner, vtype, direction, value, name, arrow, signal = line.split()
                        for part in self.nodesetup["search"].split(","):
                            if part.strip() and (part.strip() in name or part.strip() in signal):
                                sfilters.append(name)
                                sfilters.append(signal)
                                sfilters.append(".".join(name.split(".")[0:-1]))

                    elif self.nodesetup["unconnected"]:
                        owner, vtype, direction, value, name = line.split()
                        if self.nodesetup["search"]:
                            for part in self.nodesetup["search"].split(","):
                                if part.strip() and part.strip() in name:
                                    sfilters.append(name)

        section = ""
        for line in result.split("\n"):
            if line == "Parameters:":
                section = "params"
            elif line == "Component Pins:":
                section = "pins"
            elif not line:
                section = ""
            elif section == "pins" and line.split()[0].isnumeric():
                if "=" in line:
                    owner, vtype, direction, value, name, arrow, signal = line.split()

                    # handle ini pins as output
                    if name.startswith("ini."):
                        direction = "I/O"
                        arrow = "==>"

                    if (self.nodesetup["search"] or sfilters) and not name.startswith(tuple(sfilters)) and signal not in sfilters:
                        continue

                    self.pininfo[name] = {
                        "owner": owner,
                        "vtype": vtype,
                        "direction": direction,
                        "value": value,
                        "name": name,
                        "arrow": arrow,
                        "signal": signal,
                    }
                    if signal not in self.signals:
                        self.signals[signal] = {
                            "source": "",
                            "targets": [],
                            "pins": [],
                        }
                    self.signals[signal]["pins"].append(name)
                    if arrow == "<==":
                        self.signals[signal]["targets"].append(name)
                    elif arrow == "==>":
                        self.signals[signal]["source"] = name
                    elif arrow == "<=>":
                        if self.signals[signal]["source"]:
                            self.signals[signal]["targets"].append(name)
                        else:
                            self.signals[signal]["source"] = name
                elif self.nodesetup["unconnected"]:
                    owner, vtype, direction, value, name = line.split()
                    if (self.nodesetup["search"] or sfilters) and not name.startswith(tuple(sfilters)):
                        continue

                    self.pininfo[name] = {
                        "owner": owner,
                        "vtype": vtype,
                        "direction": direction,
                        "value": value,
                        "name": name,
                        "arrow": None,
                        "signal": None,
                    }
                    if not self.nodesetup["filter"] or (not name.startswith((self.cfilter)) and not name.endswith(self.pfilter)):
                        self.setps.append(name)

        groups = {}
        basenames = set()
        for signal_name, parts in self.signals.items():
            source_parts = parts["source"].split(".")
            source_group = ".".join(source_parts[0:-1])
            source_pin = source_parts[-1]
            if source_group.startswith(tuple(self.nodesetup["grouping"])):
                source_group = ".".join(source_parts[0:1])
                source_pin = ".".join(source_parts[1:])
            if not source_group:
                source_group = source_pin
            basenames.add(source_parts[0])
            source = f"{source_group}:{source_pin}"
            if not source_group:
                source_group = source_parts[0]
            if source_group:
                if source_group not in groups:
                    groups[source_group] = []
                groups[source_group].append(source_pin)
            for target in parts["pins"]:
                target_parts = target.split(".")
                target_group = ".".join(target_parts[:-1])
                target_pin = target_parts[-1]
                if target_group.startswith(tuple(self.nodesetup["grouping"])):
                    target_group = ".".join(target_parts[0:1])
                    target_pin = ".".join(target_parts[1:])
                target_name = f"{target_group}:{target_pin}"
                if not target_group:
                    target_group = target_parts[0]
                if target_group not in groups:
                    groups[target_group] = []
                groups[target_group].append(target_pin)
                # if not source_group and not source_pin:
                #    continue
                # if not target_name:
                #    continue
                source_name = source.split("=")[0]
                eid = source_name.replace(":", ".")

                self.gAll.edge(
                    source_name,
                    target_name,
                    id=eid,
                    penwidth="2",
                    color=colors["edge"],
                    label=signal_name,
                )

        """
        for name in self.pininfo:
            base = name.split(".")[0]
            if base in groups or base in basenames:
                continue
            source_parts = name.split(".")
            source_group = ".".join(source_parts[:-1])
            source_pin = source_parts[-1]
            if source_group.startswith(tuple(self.nodesetup["grouping"])):
                source_group = ".".join(source_parts[0:1])
            if source_group:
                if source_group not in groups:
                    groups[source_group] = []
        """

        used = []
        for group_name in sorted(groups, reverse=True):
            pin_strs = []
            pinlist = groups[group_name]
            if self.nodesetup["namesort"]:
                pinlist = sorted(pinlist)
            for pin_name in pinlist:
                pin_str = f'<tr><td bgcolor="{colors["port_bg"]}" port="{pin_name}"><font color="{colors["port_text"]}">{pin_name}=000.000</font></td></tr>'
                pin_strs.append(pin_str)

            pinlist = self.setps
            if self.nodesetup["namesort"]:
                pinlist = sorted(pinlist)
            for setp_raw in pinlist:
                if setp_raw.startswith(f"{group_name}.") and setp_raw not in used:
                    used.append(setp_raw)
                    setp = setp_raw.replace(f"{group_name}.", "")
                    pin_str = f'<tr><td bgcolor="{colors["setp_bg"]}" port="{setp}"><font color="{colors["setp_text"]}">{setp}=000.000</font></td></tr>'
                    pin_strs.append(pin_str)

            title = group_name.replace("\\n", "<br/>")
            label = f'<<table border="0" cellborder="1" cellspacing="0"><tr><td bgcolor="{colors["header_bg"]}"><font color="{colors["header_text"]}">{title}</font></td></tr>{"".join(pin_strs)}</table>>'
            self.gAll.node(
                group_name,
                shape="plaintext",
                label=label,
                fontsize="11pt",
                style="",
            )

        # self.gAll.render(filename='/tmp/g1.dot')
        print("INFO: rendering graph using graphviz...", end="", flush=True)
        self.info.setText("INFO: rendering graph using graphviz...")
        ret = self.gAll.pipe()
        print("..done")
        self.info.setText("INFO: rendering graph using graphviz.....done")
        return ret

    def readGraph(self):
        # clean scene
        for item in self.scene.items():
            self.scene.removeItem(item)

        self.pinsdict = {}
        self.nodesdict = {}

        min_x = 0
        min_y = 0
        max_x = 0
        max_y = 0
        nodes = self.root.findall(".//*[@class='node']")
        for node in nodes:
            title = node.find(".//{http://www.w3.org/2000/svg}title")
            if title is not None:
                polygon = node.find(".//{http://www.w3.org/2000/svg}polygon")
                if polygon is None:
                    continue
                x1 = float(polygon.attrib["points"].split()[0].split(",")[0])
                y1 = float(polygon.attrib["points"].split()[0].split(",")[1])
                x2 = float(polygon.attrib["points"].split()[2].split(",")[0])
                y2 = float(polygon.attrib["points"].split()[2].split(",")[1])
                for polygon in node.findall(".//{http://www.w3.org/2000/svg}polygon"):
                    for point in polygon.attrib["points"].split():
                        x, y = point.split(",")
                        x1 = min(float(x), x1)
                        y1 = min(float(y), y1)
                        x2 = max(float(x), x2)
                        y2 = max(float(y), y2)

                pins = {}
                pinlist = []
                pintext = node.findall(".//{http://www.w3.org/2000/svg}text")
                for text in pintext:
                    pinlist.append(text.text.split("=")[0])

                if self.nodesetup["dirsort"] or len(pintext) < 7:
                    sorting = ("IN", "I/O", "OUT", None)
                else:
                    sorting = ("OFF",)
                for skey in sorting:
                    for pin_name in pinlist:
                        if title.text == pin_name:
                            continue
                        if skey != "OFF":
                            check = self.pininfo.get(f"{title.text}.{pin_name}", {}).get("direction")
                            if self.pininfo.get(f"{title.text}.{pin_name}", {}).get("signal") is None:
                                check = None
                            if check != skey:
                                continue
                        pdict = {
                            "node": title.text,
                            "pin": pin_name,
                            "value": None,
                            "marked": False,
                            "pininfo": self.pininfo.get(f"{title.text}.{pin_name}", {}),
                        }
                        pins[pin_name] = pdict
                        self.pinsdict[f"{title.text}.{pin_name}"] = pdict

                w = abs(x2 - x1) + 30
                h = abs(y2 - y1)
                w = max(w, 70)
                h = max(h, 40)
                if title.text in self.nodesetup["positions"]:
                    x1, y1 = self.nodesetup["positions"][title.text]
                self.nodesdict[title.text] = CompNode(self, x1, y1, w, h, title.text, pins)
                self.scene.addItem(self.nodesdict[title.text])

                min_x = min(min_x, x1)
                min_y = min(min_y, y1)
                max_x = max(max_x, x1 + w)
                max_y = max(max_y, y1 + h)

        width = max_x - min_x
        height = max_y - min_y
        self.scene.setSceneRect(min_x - 500, min_y - 500, width + 1000, height + 1000)

        self.edges = {}
        edges = self.root.findall(".//*[@class='edge']")
        for edge in edges:
            title = edge.find(".//{http://www.w3.org/2000/svg}title")
            signal = edge.find(".//{http://www.w3.org/2000/svg}text")
            if title is not None:
                begin, end = title.text.split("->")
                if ":" not in begin:
                    continue
                begin_node, begin_pin = begin.split(":")
                end_node, end_pin = end.split(":")
                if end_node not in self.nodesdict or begin_node not in self.nodesdict:
                    continue

                edgenode = NodeEdge(
                    self,
                    f"Signal: {signal.text}",
                    self.nodesdict[begin_node],
                    begin_pin,
                    self.nodesdict[end_node],
                    end_pin,
                )
                self.scene.addItem(edgenode)
                pin = f"{begin_node}.{begin_pin}"
                if pin not in self.edges:
                    self.edges[pin] = []
                self.edges[pin].append(edgenode)
        self.writeSetup()
        if hasattr(self, "completer_model"):
            self.completer_model.setStringList(
                sorted(set(list(self.nodesdict.keys()) + list(self.pinsdict.keys())))
            )

    def writeSetup(self):
        if args.setup:
            open(args.setup, "w").write(json.dumps(self.nodesetup, indent=4))

    def runTimer(self):
        if not self.run:
            return

        for pin in self.nodesetup["linecharts"]:
            if pin not in self.pin_graph_data:
                self.pin_graph_data[pin] = {
                    "data": [],
                    "min": None,
                    "max": None,
                    "len": args.buffer,
                }
        for pin in list(self.pin_graph_data):
            if pin not in self.nodesetup["linecharts"]:
                del self.pin_graph_data[pin]

        # get hal data
        listOfDicts = hal.get_info_pins()
        updates = set()
        for part in listOfDicts:
            pinName = part.get("NAME")
            pinValue = part.get("VALUE")
            pinType = part.get("TYPE")

            try:
                # pin graph
                if pinName in self.pin_graph_data:
                    self.pin_graph_data[pinName]["data"] = [
                        pinValue,
                        *self.pin_graph_data[pinName]["data"][: self.pin_graph_data[pin]["len"]],
                    ]
            except Exception:
                pass

            dataColor = Qt.GlobalColor.white
            if pinType == 1:
                if pinValue:
                    dataColor = Qt.GlobalColor.green
                else:
                    dataColor = Qt.GlobalColor.red
            elif pinType == 2:
                pinValue = f"{pinValue:0.3f}"
            if pinName in self.pinsdict:
                node_name = self.pinsdict[pinName]["node"]
                pin_name = self.pinsdict[pinName]["pin"]
                node = self.nodesdict[node_name]
                if node.pins[pin_name]["value"] != pinValue:
                    node.pins[pin_name]["value"] = pinValue
                    updates.add(node)

            if pinName in self.edges:
                for edge in self.edges[pinName]:
                    edge.color = dataColor
                    updates.add(edge)

        for node in updates:
            node.update()

        self.charts.update()

    def freeze(self):
        self.run = 1 - self.run

    def fit_view(self):
        min_x = 9999999
        min_y = 9999999
        max_x = -9999999
        max_y = -9999999
        for item in self.scene.items():
            if isinstance(item, NodeEdge):
                continue
            px = item.pos().x()
            py = item.pos().y()
            min_x = min((min_x, px))
            min_y = min((min_y, py))
            max_x = max(max_x, px + item.width)
            max_y = max(max_y, py + item.height)
        # calc scale and offsets
        if min_x == 9999999:
            min_x = 0
            max_x = 800
            min_y = 0
            max_y = 800
        w = max_x - min_x
        h = max_y - min_y
        slider_size = 20
        vw = self.view.width() - slider_size
        vh = self.view.height() - slider_size

        border = 50
        scale = min((vw - border) / w, (vh - border) / h)
        pos_x = int(min_x * scale)
        pos_y = int(min_y * scale)
        # center
        diff_x = vw - w * scale
        diff_y = vh - h * scale
        pos_x -= diff_x / 2
        pos_y -= diff_y / 2

        self.view.setZoom(scale)
        self.view.horizontalScrollBar().setSliderPosition(int(pos_x))
        self.view.verticalScrollBar().setSliderPosition(int(pos_y))

        self.update()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
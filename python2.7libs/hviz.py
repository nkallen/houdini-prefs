import hou, traceback, sys
from hou import parmTemplateType
from PySide2 import QtCore, QtWidgets, QtGui
from PySide2.QtCore import Qt
import math
import hcommander

this = sys.modules[__name__]

"""
This is a simple extension to display parameters of nodes directly in the network
editor, next to the node. It shows only those params with non-default values.
"""

def createEventHandler(uievent, pending_actions):
    if uievent.eventtype == 'keydown' and uievent.key == 'Shift+Space':
        viz = Overlay(uievent.editor, hou.qt.mainWindow())
        viz.show()
        return None, True

    return None, False

DPI=2 # FIXME

class Overlay(QtWidgets.QWidget):
    def __init__(self, editor, parent=None):
        super(Overlay, self).__init__(parent)
        self._editor = editor
        self._setup_ui()

    def _setup_ui(self):
        # Create a transparent window on top of the network editor.
        bounds = self._editor.screenBounds()
        size = bounds.size()
        self.resize(size.x()/DPI, size.y()/DPI)

        # This is a hacky way to get the global/absolute position of the editor using the 3 cursor
        # coordinate systems.
        self._xoffset = (QtGui.QCursor.pos().x()*DPI - self._editor.posToScreen(self._editor.cursorPosition()).x())/DPI
        self._yoffset = (QtGui.QCursor.pos().y()*DPI + self._editor.posToScreen(self._editor.cursorPosition()).y())/DPI - size.y()/DPI
        self.move(self._xoffset, self._yoffset)

        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.X11BypassWindowManagerHint)
        self.setStyleSheet("QWidget{background-color:rgba(1,1,1,0.1)}")
        # self.grabKeyboard()

        for item, rect in self._editor.allVisibleRects(()):
            if not isinstance(item, hou.Node): continue

            posx = self._editor.posToScreen(rect.max()).x()/DPI
            posy = size.y()/DPI - self._editor.posToScreen(rect.min()).y()/DPI
            unit = self._editor.lengthToScreen(1)/DPI
            marginx = unit/10
            marginy = -unit/30
            posx += marginx
            posy += marginy
           
            initialposx = posx
            initialposy = posy
            for i, parm_tuple in enumerate(item.parmTuples()):
                if parm_tuple.isHidden(): continue
                if parm_tuple.isAtDefault(): continue
                type = parm_tuple.parmTemplate().type()
                if not type in (parmTemplateType.Int, parmTemplateType.Float, parmTemplateType.String, parmTemplateType.Toggle): continue

                button = Button(parm_tuple, parent=self)
                button.move(posx, posy)
                font_size = math.ceil(self._editor.lengthToScreen(1)/DPI/6)
                button.setStyleSheet("QPushButton{ padding: 0; font-size: " + str(font_size) + "px; background-color: rgb(38,56,76);}")
                button.clicked.connect(self._clicked)
                button.show()
                button.setProperty("parm_tuple", parm_tuple)
                posx += button.frameGeometry().width()
                if posx-initialposx > unit:
                    posx = initialposx
                    posy += button.frameGeometry().height()
                if posy-initialposy >= 0.5*unit:
                    break

        self.setAutoFillBackground(False)

    def event(self, event):
        if event.type() == QtCore.QEvent.KeyRelease and event.key() == Qt.Key_Shift:
            self.close()
            return True

        return QtWidgets.QWidget.event(self, event)

    def paintEvent(self, event):
        opt = QtWidgets.QStyleOption()
        opt.initFrom(self)
        painter = QtGui.QPainter(self)
        self.style().drawPrimitive(QtWidgets.QStyle.PE_Widget, opt, painter, self)

    def close(self):
        self.setParent(None)
        self.releaseKeyboard()
        QtWidgets.QWidget.close(self)

    def _clicked(self):
        parm_tuple = self.sender().property("parm_tuple")
        type = parm_tuple.parmTemplate().type()
        if type == parmTemplateType.Toggle:
            parm_tuple.set([not parm_tuple.eval()[0]])
            self.sender().setText(Overlay.summarize(parm_tuple))
        else:
            self.close()
            hcommander.edit(self._editor, parm_tuple)

"""
NOTE: Currently the value ladder stuff doesn't work because ofa  bug in Houdini
"""

class Button(QtWidgets.QPushButton):
    epsilon = 0.01
    @staticmethod
    def summarize(parm_tuple):
        vs = []
        for v in parm_tuple.eval():
            type = parm_tuple.parmTemplate().type()
            if type == parmTemplateType.Float:
                if v - math.floor(v) < Button.epsilon:
                    vs.append("{:.0f}".format(v))
                else:
                    vs.append("{:.1f}".format(v))
            else:
                vs.append(str(v))
        v = vs[0] if len(vs) == 1 else ",".join(vs)
        kvp = "{}={}".format(parm_tuple.name(), v)
        return kvp[0:20]

    def __init__(self, parm_tuple, parent=None):
        text = Button.summarize(parm_tuple)
        super(Button, self).__init__(text=text, parent=parent)
        self._parm_tuple = parm_tuple
        self._pressed = False
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton and len(self._parm_tuple) == 1:
            try:
                hou.ui.openValueLadder(
                    self._parm_tuple.eval()[0],
                    self._ladderchange,
                    data_type=hou.valueLadderDataType.Float if self._parm_tuple.parmTemplate().type() == parmTemplateType.Float else hou.valueLadderDataType.Int
                )
            except hou.OperationFailed:
                # A ladder is already open somewhere
                print "here?"
                return
            else:
                self._pressed = True
        else:
            return QtWidgets.QPushButton.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self._pressed:
            hou.ui.updateValueLadder(
                event.globalX(),
                event.globalY(),
                bool(event.modifiers() & Qt.AltModifier),
                bool(event.modifiers() & Qt.ShiftModifier)
            )
        else:
            return QtWidgets.QPushButton.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pressed:
            hou.ui.closeValueLadder()
            self._pressed = False
        else:
            return QtWidgets.QPushButton.mouseReleaseEvent(self, event)

    def _ladderchange(self, new_value):
        self._parm_tuple.set([new_value])
        self.setText(str(Button.summarize(self._parm_tuple)))

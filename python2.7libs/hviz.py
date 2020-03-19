import hou, traceback, sys
from hou import parmTemplateType
from PySide2 import QtCore, QtWidgets, QtGui
from PySide2.QtCore import Qt

this = sys.modules[__name__]

"""
Currently this is a very simple extension to display parameters of nodes directly in the network
editor, next to the node. It shows only those params with non-default values. It creates a parm with
a summary of the non-default key-value-paris, and hacks them into the "descriptiveparm" user attr.
"""

__name = "nk_parm_summary"

def createEventHandler(uievent, pending_actions):
    if uievent.eventtype == 'keydown' and uievent.key == 'Shift+Space':
        visualize(uievent)
        # this.visualizing = True
        return None, True

    elif uievent.eventtype == 'keyup':
        # this.visualizing = False
        unvisualize(uievent)
    
    return None, False

this.viz = None

DPI=2 # FIXME

class Foo(QtWidgets.QWidget):
    def __init__(self, editor, parent=None):
        super(Foo, self).__init__(parent)
        self._editor = editor
        self._setup_ui()

    def _setup_ui(self):
        bounds = self._editor.screenBounds()
        size = bounds.size()
        self._xoffset = (QtGui.QCursor.pos().x()*DPI - self._editor.posToScreen(self._editor.cursorPosition()).x())/DPI
        self._yoffset = (QtGui.QCursor.pos().y()*DPI + self._editor.posToScreen(self._editor.cursorPosition()).y())/DPI - size.y()/DPI
        self.move(self._xoffset, self._yoffset)
        self.resize(size.x()/DPI, size.y()/DPI)

        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.X11BypassWindowManagerHint)
        self.setStyleSheet("QWidget{background-color:rgba(1,1,1,0.1)}")
        self.grabKeyboard()

        for (item, rect) in self._editor.allVisibleRects(()):
            if not isinstance(item, hou.Node): continue
            button = QtWidgets.QPushButton(text=item.name(), parent=self)
            posx = self._editor.posToScreen(rect.max()).x()/DPI
            posy = size.y()/DPI - self._editor.posToScreen(rect.min()).y()/DPI
            unit = self._editor.lengthToScreen(1)/DPI
            marginx = unit/10
            marginy = unit/22
            button.move(posx + marginx, posy + marginy)
            import math
            font_size = math.ceil(self._editor.lengthToScreen(1)/DPI/6)
            button.setStyleSheet("QPushButton{padding:0;font-size: " + str(font_size) + "px; background-color: rgb(38,56,76);}");
            button.show()

        self.setAutoFillBackground(False)

    def event(self, event):
        if event.type() == QtCore.QEvent.KeyRelease:
            self.close()
            self.releaseKeyboard()
            self.setParent(None)
            this.viz = None
            return True

        return super(Foo, self).event(event)
    
    def paintEvent(self, event):
        opt = QtWidgets.QStyleOption()
        opt.initFrom(self)
        painter = QtGui.QPainter(self)
        self.style().drawPrimitive(QtWidgets.QStyle.PE_Widget, opt, painter, self)

def visualize(uievent):
    viz = Foo(uievent.editor, hou.qt.mainWindow())


    viz.show()

    # viz.grabMouse()
    # viz.setFocus()
    # viz.setMouseTracking(True)

    # pos, size = getViewportRenderViewPosSize()

    # viz.resize(size.width(), size.height() + vizTopMaskHeight)
    # viz.setMask(QtGui.QRegion(0, vizTopMaskHeight, size.width(), size.height()))

    this.viz = viz

# def pos():
#     qtWindow = hou.qt.mainWindow()
#     viewportWidgets = []
#     for w in qtWindow.findChildren(QtCore.QObject):
#         if not hasattr(w, "size"): continue
#         print w.objectName()
#         print w, w.size(), w.pos()

def visualize2(uievent):
    pwd = uievent.editor.pwd()
    for child in pwd.children():
        try:
            if not child.parmTuple(__name):
                template = hou.StringParmTemplate(__name, __name, 1)
                template.hide(True)
                child.addSpareParmTuple(template)
            parm_tuple = child.parmTuple(__name)
            kvps = []
            for parm_tuple in child.parmTuples():
                type = parm_tuple.parmTemplate().type()
                if not type in (parmTemplateType.Int, parmTemplateType.Float, parmTemplateType.String, parmTemplateType.Toggle):
                    continue
                if not parm_tuple.isAtDefault() and parm_tuple.name() != __name:
                    vs = []
                    for v in parm_tuple.eval():
                        if type == hou.parmTemplateType.Float:
                            vs.append("{:.1f}".format(v))
                        else:
                            vs.append(str(v))
                    v = vs[0] if len(vs) == 1 else "(" + ",".join(vs) + ")"
                    kvp = "{}={}".format(parm_tuple.name(), v)
                    kvps.append(kvp)
            text = ", ".join(kvps)
            parm_tuple.set([text])
            child.setUserData("descriptiveparm", __name)
        except hou.OperationFailed as e:
            print "Skipping", child
            print "This may indicate a bug in Houdini: ", e

def unvisualize(uievent):
    return
    pwd = uievent.editor.pwd()
    for child in pwd.children():
        parm_tuple = child.parmTuple(__name)
        if parm_tuple:
            child.removeSpareParmTuple(parm_tuple)
    child.destroyUserData("descriptiveparm")
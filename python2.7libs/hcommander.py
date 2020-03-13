import hou, nodegraph, os, csv, sys
from hou import parmTemplateType
from collections import defaultdict
import nodegraphbase as base
from canvaseventtypes import *
from PySide2 import QtCore, QtWidgets, QtGui
from PySide2.QtCore import Qt
from nodegraphbase import EventHandler

"""
Commander is a "graphical" command line interface for Houdini's Network Editor. You can
quickly run commands or edit nodes using only the keyboard.

The commander can be triggered in two ways. First, hitting Shift+Space, which works like
Spotlight on Mac, opening a dialog. Alternatively, it holding space down, the dialog opens;
and releasing the space key closes it, accepting the user's selection. This is
referred to as "volatile" mode.

Commands can be global: e.g., "turn on normals in the scene view". They can be specific
to the selection "orient the currently selected line node along X/Y/Z". Or they can just
edit parameters directly.
"""

"""
The basic state-machine works as follows. 1. Open the commander window; 2. The user makes
selection; 3. based on the selection/command, open another window if more input is required;
4. incrementally update the world, and finally, 5. save the user's changes or undo.

The co-routine code is a bit confusing but the idea this: the SetParam window listens to
events from the NetworkEditor PLUS the events it receives directly. Specifically, it wants
mousewheel events from the network editor in order to increment and decrement parameter
values. An important edge-case is when the param window is closed (e.g., the user
hits ENTER or ESC). ENTER/ESC are events that are sent directly to the window -- no network
editor involvement; but the window's event handler was listening for a (mousewheel) event
before it closed. Thus we must send it a (fake) event when the window is closed, or it will
accidentally consume the next event destined for the network editor.

This problem arises also in a non-coroutine implementation (e.g., using hou's EventHandler
class directly) but it's even more convoluted to solve.
"""

this = sys.modules[__name__]

this.cc = None
def handleEvent(uievent):
    if uievent.eventtype == 'keydown' and uievent.key == 'Space':
        this.cc = handleEventCoroutine(uievent.editor, volatile=True)
        next(this.cc)
        return None, True

    if uievent.eventtype == 'keyhit' and uievent.key == 'Shift+Space':
        this.cc = handleEventCoroutine(uievent.editor, volatile=False)
        next(this.cc)
        return None, True

    if this.cc:
        if uievent.eventtype == 'keyup' and uievent.key == 'Space':
            return None, True

        try:
            this.cc.send(uievent)
            return None, True
        except StopIteration:
            this.cc = None
            return None, False

    return None, False

def handleEventCoroutine(editor, volatile=True):
    window = HCommanderWindow(editor, volatile)
    window.exec_()
    selection = window.selection()
    if type(selection) is hou.ParmTuple:
        if selection:
            window = SetParamWindow(editor, selection)
            window.show()
            window.activateWindow()
            while window.isVisible():
                uievent = (yield) # NOTE: the SetParamWindow sends a None event when closed
                if uievent and uievent.eventtype == 'mousewheel':
                    window.delta(uievent.wheelvalue)
    elif type(selection) is Action:
        selection.call()
    yield # one yield must correspond to the initial next() call, otherwise it throws.

class HCommanderWindow(QtWidgets.QDialog):
    def __init__(self, editor, volatile):
        super(HCommanderWindow, self).__init__(
            hou.qt.floatingPanelWindow(editor.pane().floatingPanel())
        )
        self._volatile = volatile

        self.editor = editor
        self.setMinimumWidth(500)
        self.setMinimumHeight(100)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.X11BypassWindowManagerHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowOpacity(0.95)

        selected_node = hou.selectedNodes()[0]
        self._model = CompositeModel(self, [
            ParmTupleModel(self, HCommanderWindow._filter(selected_node.parmTuples())),
            ActionModel(self, Action.find(selected_node))])

        self._setup_ui()
        self._selection = None
    
    @staticmethod
    def _filter(parmTuples):
        valid_types = { parmTemplateType.Int, parmTemplateType.Float, parmTemplateType.String }
        return list(pt for pt in parmTuples if pt.parmTemplate().type() in valid_types and not pt.isHidden() and not pt.isDisabled())

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.setLayout(layout)
        self._textbox = QtWidgets.QLineEdit(self)
        self._textbox.installEventFilter(self)
        self._textbox.returnPressed.connect(self.accept)
        self._textbox.setStyleSheet("font-size: 18px; height: 24px; border: none; background: transparent")
        layout.addWidget(self._textbox)

        self._textbox.textChanged.connect(self._text_changed)

        self._list = QtWidgets.QTableView()
        self._list.setShowGrid(True)

        self._proxy_model = AutoCompleteModel()
        self._proxy_model.setSourceModel(self._model)
        self._list.setModel(self._proxy_model)

        self._list.setGridStyle(Qt.NoPen)
        self._list.clicked.connect(self.accept)
        self._list.verticalHeader().hide()
        self._list.horizontalHeader().hide()
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._list.setStyleSheet("border: none")
        self._list.setColumnWidth(0, 45)
        self._list.setColumnWidth(1, 320)
        self._list.setColumnWidth(2, 100)

        layout.addWidget(self._list)
    
    def eventFilter(self, obj, event):
        if self._volatile:
            if event.type() == QtCore.QEvent.KeyPress and event.key() == Qt.Key_Space and event.isAutoRepeat():
                return True

            elif event.type() == QtCore.QEvent.KeyRelease and event.key() == Qt.Key_Space:
                self.accept()
                return True

        if event.type() == QtCore.QEvent.KeyPress:
            return self._handle_keys(event)

        return False

    def _text_changed(self, text):
        self._proxy_model.filter(text)
        index = self._list.model().index(0, 0)
        self._list.setCurrentIndex(index)

    def changeEvent(self, event): # Close when losing focus
        if event.type() == QtCore.QEvent.ActivationChange:
            if not self.isActiveWindow():
                self.close()
    
    def _handle_keys(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key in (Qt.Key_Enter, Qt.Key_Return):
            self.accept()
            return True

        elif key == Qt.Key_Up:
            self._cursor(self._list.MoveUp, modifiers)
            return True
        elif key == Qt.Key_Down:
            self._cursor(self._list.MoveDown, modifiers)
            return True

        return False

    def _cursor(self, action, modifiers):
        index = self._list.moveCursor(action, modifiers)
        path = index.data(Qt.EditRole)
        self._list.setCurrentIndex(index)
        
    def accept(self):
        for index in self._list.selectedIndexes():
            self._selection = index.data(Qt.UserRole)
        self.close()
    
    def selection(self):
        return self._selection

class AutoCompleteModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super(AutoCompleteModel, self).__init__(parent)
        self._filter = None

    def setSourceModel(self, model):
        super(AutoCompleteModel, self).setSourceModel(model)
        i = 0
        self._bitsets = []
        # Construct a bitset for each word for fast(ish) fuzzy-matching
        while i < model.rowCount():
            x = 0
            for char in model.index(i, 1).data(Qt.EditRole).upper():
                x |= 1 << ord(char) - 48 # inlude 0-9 ... A-Z
            self._bitsets.append(x)
            i += 1

    def filterAcceptsRow(self, sourceRow, sourceParent):
        if not self._filter: return True
        selector_bitset, selector_text = self._filter

        text = self.sourceModel().index(sourceRow, 1, sourceParent).data()
        bitset = self._bitsets[sourceRow]
        return selector_bitset & bitset == selector_bitset
    
    def filter(self, text):
        if text == "":
            self._filter = None

        x = 0
        # construct a filter bitset
        for char in text.upper():
            x |= 1 << ord(char) - 48
        self._filter = (x, text)
        self.beginResetModel()
        self.endResetModel()
    
class ParmTupleModel(QtCore.QAbstractTableModel):
    def __init__(self, parent, parmTuples):
        super(ParmTupleModel, self).__init__(parent)
        self._parmTuples = sorted(parmTuples, key=lambda x: x.isAtDefault())

    def rowCount(self, parentindex=None):
        return len(self._parmTuples)
    
    def columnCount(self, parentindex=None):
        return 3
    
    def data(self, index, role):
        if not index.isValid(): return None
        if not 0 <= index.row() < len(self._parmTuples): return None

        parm = self._parmTuples[index.row()]
        if role == Qt.UserRole:
            return parm
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return "P"
            elif index.column() == 1:
                label = parm.parmTemplate().label() + ": " + parm.name()
                if len(parm) > 1:
                    if parm.parmTemplate().namingScheme() == hou.parmNamingScheme.XYZW:
                        label += " - " + "XYZW"[0:len(parm)]
                    elif parm.parmTemplate().namingScheme() == hou.parmNamingScheme.Base1:
                        label += " - " + "123456789"[0:len(parm)]
                    else:
                        print "FIXME: need to implement other naming schemes", parm.parmTemplate().namingScheme()
                return label
            elif index.column() == 2:
                return ", ".join(str(v) for v in parm.eval())
        
        if role == Qt.ForegroundRole:
            if index.column() == 2:
                if parm.isAtDefault():
                    return QtGui.QColor(Qt.darkGray)
                else:
                    return QtGui.QColor(Qt.white)
            return None
        if role == Qt.EditRole:
            return parm.name()
        
        return None

class ActionModel(QtCore.QAbstractTableModel):
    def __init__(self, parent, actions):
        super(ActionModel, self).__init__(parent)
        self._actions = actions

    def columnCount(self, parentindex=None):
        return 3

    def rowCount(self, parentindex=None):
        return len(self._actions)
    
    def data(self, index, role):
        action = self._actions[index.row()]

        if role == Qt.UserRole:
            return action

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return "A"
            elif index.column() == 1:
                label = action.label + ": " + action.name
                return label
            else:
                return None
        
        if role == Qt.EditRole:
            return action.name
        
        return None

class CompositeModel(QtCore.QAbstractTableModel):
    def __init__(self, parent, models):
        super(CompositeModel, self).__init__(parent)
        self._models = models

    def columnCount(self, parentindex=None):
        return 3
        
    def rowCount(self, parentindex=None):
        sum = 0
        for model in self._models:
            sum += model.rowCount(parentindex)
        return sum
    
    def data(self, index, role):
        row = index.row()
        model = None
        for model_ in self._models:
            if row < model_.rowCount():
                model = model_
                break
            row -= model_.rowCount()
        index = model.index(row, index.column())
        return model.data(index, role)

"""
Command can quickly set params of the current selection. Params can be of various types,
like String and Float; for the latter, special interaction like the arrow keys or the mouse
scrollwheel will modify values. Special care is made for ParamTuples, e.g., XYZ parameters,
which three text fields appear simultaneously.
"""
class SetParamWindow(QtWidgets.QDialog):
    def __init__(self, editor, parmTuple):
        super(SetParamWindow, self).__init__(
            hou.qt.floatingPanelWindow(editor.pane().floatingPanel())
        )
        self._editor = editor
        self._undo_context = hou.undos.disabler()
        self._undo_context.__enter__()
        self._parmTuple = parmTuple
        self._original_value = parmTuple.eval()

        self.setMinimumWidth(400)
        self.setMinimumHeight(100)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.X11BypassWindowManagerHint)
        self.setWindowOpacity(0.95)
        # NOTE: This window in every way acts like its modal. HOWEVER, modality
        # makes live-previewing user updates impossible. So 

        self._accepted = False

        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.setLayout(layout)
        self._textboxes = []
        for i, parm in enumerate(self._parmTuple):
            textbox = QtWidgets.QLineEdit(self)
            textbox.textEdited.connect(self._update)
            textbox.returnPressed.connect(self.accept)
            textbox.setStyleSheet("font-size: 18px; height: 24px; border: none; background: transparent")
            textbox.setText(str(self._parmTuple.eval()[i]))
            textbox.selectAll()
            textbox.installEventFilter(self)
            textbox.setProperty("parm", parm)
            layout.addWidget(textbox)
            self._textboxes.append(textbox)

    def wheelEvent(self, event):
        self.delta(event.angleDelta().y())

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.ActivationChange:
            if not self.isActiveWindow() and not self._accepted:
                self._parmTuple.set(self._original_value)
                self._undo_context.__exit__(None, None, None)

                self.close()

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                self.delta(1)
                return True
            elif event.key() == Qt.Key_Down:
                self.delta(-1)
                return True

        return False

    def _update(self, value):
        parm = self.sender().property("parm")
        if value != "":
            parm.set(float(self.sender().text()))
        else:
            parm.revertToDefaults()

    def accept(self):
        self._accepted = True
        self._undo_context.__exit__(None, None, None)
        hou.undos.group("Parameter Change")
        for i, parm in enumerate(self._parmTuple):
            parm.set(float(self._textboxes[i].text()))
        self.close()

    def close(self):
        super(SetParamWindow, self).close()
        this.cc.send(None) # see coroutine note above

    def delta(self, delta):
        textbox = self.focusWidget()
        parm = textbox.property("parm")
        result = float(textbox.text()) + delta * 0.1
        textbox.setText(str(result))
        parm.set(result)

"""
ACTIONS are loaded from a CSV config file. Actions can apply EITHER to selected objects,
e.g., "orient a line in X/Y/Z"; or they can be global, e.g., "turn on wireframe mode".
"""
class Action(object):
    """
    Load the configuration file. It has various actions with descriptions and commands to run.
    Watch for changes to the filesystem.
    """
    _userdir = hou.getenv('HOUDINI_USER_PREF_DIR')
    configfile = os.path.join(_userdir, "hcommander.csv")

    _actions = None
    @staticmethod
    def load():
        print "Reloading hcommander actions..."
        Action._actions = defaultdict(list)
        with open(Action.configfile) as f:
            reader = csv.DictReader(f)
            for row in reader:
                Action._actions[row["Selection"]].append(Action(row["Label"], row["Name"], row["fn"]))

    @staticmethod
    def find(selected_node):
        selector = selected_node.type().name()
        if selector in Action._actions:
            return Action._actions[selector]
        else:
            return []

    def __init__(self, label, name, fn):
        self.label = label
        self.name = name
        self.fn = fn

    def call(self):
        try:
            with hou.undos.group("Invoke custom user function"):
                exec(self.fn, {}, {'hou': hou})
            return True
        except Exception as e:
            print(e)
            print(self.fn)

Action.load()

__fs_watcher = QtCore.QFileSystemWatcher()
__fs_watcher.addPath(Action.configfile)
__fs_watcher.fileChanged.connect(Action.load)

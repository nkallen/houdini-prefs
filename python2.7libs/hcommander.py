import hou, nodegraph, os, csv, sys, traceback
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
    if uievent.eventtype == 'keydown' and uievent.key == 'Space' and not this.cc:
        this.cc = handleEventCoroutine(uievent.editor, volatile=True)
        next(this.cc)
        return None, True

    if uievent.eventtype == 'keyhit' and uievent.key == 'Ctrl+Space':
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
    selection, which_match = window.selection()
    if type(selection) is hou.ParmTuple:
        if selection:
            window = SetParamWindow(editor, selection, which_match, volatile)
            window.show()
            window.activateWindow()
            while window.isActiveWindow():
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
        self.setMinimumHeight(300)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.X11BypassWindowManagerHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowOpacity(0.95)

        selected_node = hou.selectedNodes()[0]
        self._model = CompositeModel(self, [
            ParmTupleModel(self, HCommanderWindow._filter(selected_node.parmTuples())),
            ActionModel(self, Action.find(selected_node))])

        self._setup_ui()
        self._selection = (None, None)
    
    @staticmethod
    def _filter(parmTuples):
        valid_types = { parmTemplateType.Int, parmTemplateType.Float, parmTemplateType.String, parmTemplateType.Toggle }
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

        self._item_delegate = ItemDelegate()

        self._list.setGridStyle(Qt.NoPen) # FIXME?
        self._list.clicked.connect(self._clicked)
        self._list.verticalHeader().hide()
        self._list.horizontalHeader().hide()
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._list.setStyleSheet("border: none")
        self._list.setColumnWidth(0, 45)
        self._list.setColumnWidth(1, 320)
        self._list.setColumnWidth(2, 100)
        self._list.setItemDelegate(self._item_delegate)

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
        self._item_delegate.filter(text)
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
            parm_tuple = index.data(ParmTupleRole)

            if isinstance(parm_tuple, Action):
                self._selection = (parm_tuple, 0)
                self.close()
                return

            type = parm_tuple.parmTemplate().type()
            if type == parmTemplateType.Toggle:
                parm_tuple.set([int(not parm_tuple.eval()[0])])
            else:
                self._selection = (parm_tuple, (index.data(WhichMatchRole) or 1) - 1)
        self.close()

    def _clicked(self):
        self.accept()

    def selection(self):
        return self._selection
    
    def close(self):
        QtWidgets.QDialog.close(self)
        self.setParent(None)

"""
This class represents items matching the autocomplete text in the hcommander. It highlights matching
characters in bold. It's honestly absurd how hard this is to do in QT.
"""
class ItemDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent=None):
        super(ItemDelegate, self).__init__(parent)
        self.doc = QtGui.QTextDocument(self)
        self._highlight_format = QtGui.QTextCharFormat()
        self._highlight_format.setFontWeight(QtGui.QFont.Bold)
        self._filter = None

    def filter(self, text):
        self._filter = text

    def paint(self, painter, options, index):
        if index.column() == 1:
            painter.save()
            self.initStyleOption(options, index)

            # draw everything we would normally draw, minus the text:
            options.text = ""
            style = options.widget.style()
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, options, painter, options.widget)

            # now issue low-level drawing commands to render the text with special formatting
            text_rect = style.subElementRect(
                QtWidgets.QStyle.SE_ItemViewItemText, options, options.widget)

            margin = style.pixelMetric(QtWidgets.QStyle.PM_FocusFrameHMargin, None, options.widget) + 1
            text_rect.adjust(margin, margin, 0, 0)

            if self._filter:
                self.doc.setPlainText("")
                cursor = QtGui.QTextCursor(self.doc)
                plain = cursor.charFormat()
                cursor.mergeCharFormat(self._highlight_format)
                highlight = cursor.charFormat()
                filter = self._filter.upper()
                first = True
                match = index.data(WhichMatchRole)
                for x, text in enumerate(index.data()):
                    if x == match:
                        i = 0
                        for char in text:
                            if i < len(self._filter) and char.upper() == filter[i]:
                                i += 1
                                cursor.setCharFormat(highlight)
                            else:
                                cursor.setCharFormat(plain)
                            cursor.insertText(char)
                    else:
                        cursor.setCharFormat(plain)
                        cursor.insertText(text)
                    if first: cursor.insertText(": ")
                    else: cursor.insertText(" ")
                    first = False
            else:
                labels = index.data()
                first, rest = labels[0], labels[1:]
                self.doc.setPlainText(first + ": " + " ".join(rest) + "")

            painter.translate(text_rect.topLeft())
            painter.setClipRect(text_rect.translated(-text_rect.topLeft()))
            ctx = QtGui.QAbstractTextDocumentLayout.PaintContext()
            self.doc.documentLayout().draw(painter, ctx)
            
            painter.restore()
        else:
            super(ItemDelegate, self).paint(painter, options, index)

ParmTupleRole = Qt.UserRole 
AutoCompleteRole = Qt.UserRole + 1
WhichMatchRole = Qt.UserRole + 2

"""
This is a custom autocompleter that can match either the "label" or the "name(s)" in an item. Its key
feature is when a user types "upr" it can match "upper", "super", etc. which differs from the
default QT prefix/suffix matching. Items have labels like "translation" and names like "tx", "ty",
etc.
"""
class AutoCompleteModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super(AutoCompleteModel, self).__init__(parent)
        self._filter = None

    def setSourceModel(self, model):
        super(AutoCompleteModel, self).setSourceModel(model)
        i = 0
        self._bitsetss = []
        # Construct a bitset for each word for fast(ish) fuzzy-matching
        while i < model.rowCount():
            labels = model.index(i, 1).data(AutoCompleteRole)
            bitsets = []
            for text in labels:
                bitset = 0
                for char in text.upper():
                    o = ord(char)
                    if o < 48: continue
                    bitset |= 1 << ord(char) - 48 # inlude 0-9 ... A-Z
                bitsets.append(bitset)
            self._bitsetss.append(tuple(bitsets))
            i += 1

    def filterAcceptsRow(self, sourceRow, sourceParent):
        if not self._filter: return True
        selector_bitset, selector_text = self._filter
        if selector_bitset == 0: return True
        
        labels = self.sourceModel().index(sourceRow, 1, sourceParent).data(AutoCompleteRole)
        bitsets = self._bitsetss[sourceRow]

        # check every character is present in any of the labels or names ...
        match = False
        for bitset in bitsets:
            match = match or bitset & selector_bitset == selector_bitset
        if not match:
            return False
        
        # make sure the characters are in order in any text
        for text in labels:
            i = 0
            for char in text.upper():
                if char == selector_text[i]:
                    i += 1
                    if len(selector_text) == i: return True
    
        return False

    def data(self, index, role):
        if role == WhichMatchRole:
            if not self._filter: return None
        
            bitsets = self._bitsetss[self.mapToSource(index).row()]
            selector_bitset, selector_text = self._filter

            # check every character is present in any of the labels or names ...
            i = 0
            for bitset in bitsets:
                if bitset & selector_bitset == selector_bitset: return i
                i += 1
            return None
        else:
            return super(AutoCompleteModel, self).data(index, role)

    def filter(self, text):
        if text == "":
            self._filter = None

        x = 0
        # construct a filter bitset
        text = text.upper()
        for char in text:
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

        parm_tuple = self._parmTuples[index.row()]
        type = parm_tuple.parmTemplate().type()

        if role == ParmTupleRole:
            return parm_tuple
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return "P"
            elif index.column() == 1:
                return self.data(index, AutoCompleteRole)
            elif index.column() == 2:
                if type == parmTemplateType.Toggle: return None

                vs = []
                for v in parm_tuple.eval():
                    if type == hou.parmTemplateType.Float:
                        vs.append("{:.1f}".format(v))
                    else:
                        vs.append(str(v))
                return ", ".join(vs)
        
        if role == Qt.ForegroundRole:
            if index.column() == 2:
                if parm_tuple.isAtDefault():
                    return QtGui.QColor(Qt.darkGray)
                else:
                    return QtGui.QColor(Qt.white)
            return None
        if role == AutoCompleteRole:
            if index.column() == 1:
                return [parm_tuple.parmTemplate().label()] + map(lambda x: x.name(), parm_tuple)
        if role == Qt.CheckStateRole:
            if index.column() == 1 and type == parmTemplateType.Toggle:
                return Qt.Checked if parm_tuple.eval()[0] == 1 else Qt.Unchecked
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

        if role == ParmTupleRole:
            return action

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return "A"
            elif index.column() == 1:
                return self.data(index, AutoCompleteRole)
            else:
                return None
        
        if role == AutoCompleteRole:
            return (action.label, action.name)
        
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

Note that ESC closes the window and aborts changes. But ENTER or LEFT MOUSECLICK accepts the changes.
"""
class SetParamWindow(QtWidgets.QDialog):
    def __init__(self, editor, parm_tuple, which_match, volatile):
        super(SetParamWindow, self).__init__(
            hou.qt.floatingPanelWindow(editor.pane().floatingPanel())
        )
        self._editor = editor
        self._volatile = volatile
        # Disable undos while the user makes interactive edits. We'll renable them when ESC or RETURN is hit.
        self._undo_context = hou.undos.disabler()
        self._undo_context.__enter__()
        self._parm_tuple = parm_tuple
        self._original_value = parm_tuple.eval()

        self.setMinimumWidth(500)
        self.setMinimumHeight(100)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.X11BypassWindowManagerHint)
        self.setWindowOpacity(0.95)
        # NOTE: This window in every way acts like its modal. HOWEVER, modality
        # makes live-previewing user updates impossible. So it's not.

        self._reset = None
        self._setup_ui(which_match)

    def _setup_ui(self, which_match):
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.setLayout(layout)
        self._textboxes = []
        for i, parm in enumerate(self._parm_tuple):
            textbox = QtWidgets.QLineEdit(self)
            textbox.textEdited.connect(self._update)
            textbox.returnPressed.connect(self.accept)
            textbox.setStyleSheet("font-size: 18px; height: 24px; border: none; background: transparent")
            textbox.setText(str(self._parm_tuple.eval()[i]))
            textbox.selectAll()
            textbox.installEventFilter(self)
            textbox.setProperty("parm", parm)
            layout.addWidget(textbox)
            if i == which_match:
                textbox.setFocus()
            self._textboxes.append(textbox)
    
    def wheelEvent(self, event):
        self.delta(event.angleDelta().y())
    
    # Centralize saving and canceling when the window closes;
    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.ActivationChange:
            if not self.isActiveWindow():
                self.releaseMouse()
                self.setParent(None)

                if self._reset:
                    self._parm_tuple.set(self._original_value)
                    self._undo_context.__exit__(None, None, None)
                else:
                    self._undo_context.__exit__(None, None, None)
                    with hou.undos.group("Parameter Change"):
                        for i, parm in enumerate(self._parm_tuple):
                            parm.set(float(self._textboxes[i].text()))

    _foo = {Qt.Key_X: [1,0,0,0], Qt.Key_Y: [0,1,0,0], Qt.Key_Z: [0,0,1,0], Qt.Key_W: [0,0,0,1]}
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                self.delta(1)
                return True
            elif event.key() == Qt.Key_Down:
                self.delta(-1)
                return True
            elif event.key() == Qt.Key_Escape:
                self._reset = True
                self.close()
                return True
            elif event.key() == Qt.Key_Space and self._volatile:
                return True
            elif self._parm_tuple.parmTemplate().namingScheme() == hou.parmNamingScheme.XYZW:
                if event.key() in SetParamWindow._foo:
                    l = len(self._parm_tuple)
                    self._parm_tuple.set(SetParamWindow._foo[event.key()][0:l])
                    for i, parm in enumerate(self._parm_tuple):
                        textbox = self._textboxes[i]
                        textbox.setText(str(self._parm_tuple.eval()[i]))
                        if SetParamWindow._foo[event.key()][i] == 1:
                            textbox.selectAll()
                            textbox.setFocus()
                        
                    return True
        return False

    # FIXME move into model?
    def _update(self, value):
        parm = self.sender().property("parm")
        if value != "":
            parm.set(float(self.sender().text()))
        else:
            parm.revertToDefaults()

    def accept(self):
        self._reset = False
        self.close()
        this.cc.send(None)

    def delta(self, delta):
        scale = 0.1
        f = float
        type = self._parm_tuple.parmTemplate().type()
        if type == parmTemplateType.Int:
            f = int
            scale = 1
            
        textbox = self.focusWidget()
        parm = textbox.property("parm")
        result = f(textbox.text()) + delta * scale
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

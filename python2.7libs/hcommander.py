import hou, nodegraph, os, csv, sys, traceback
from hou import parmTemplateType
from collections import defaultdict
import nodegraphbase as base
from canvaseventtypes import *
from PySide2 import QtCore, QtWidgets, QtGui
from PySide2.QtCore import Qt
from nodegraphbase import EventHandler
import utility_ui
from PySide2.QtWidgets import QAbstractItemView, QStyledItemDelegate, QWidget, QStyle
from PySide2.QtCore import Signal

"""
Commander is a "graphical" command line interface for Houdini's Network Editor. You can
quickly run commands or edit nodes using only the keyboard.
"""

this = sys.modules[__name__]

this.window = None
def handleEvent(uievent, pending_actions):
    def reset_state(): this.window = None

    if this.window:
        result = this.window.handleEvent(uievent, pending_actions)
        return this, result
    else:
        if uievent.eventtype == 'keydown' and uievent.key == 'Space':
            window = HCommanderWindow(uievent.editor, True)
            window.show()
            window.activateWindow()
            window.finished.connect(reset_state)
            this.window = window
            return this, True

        return None, False

class HCommanderWindow(QtWidgets.QDialog):
    @staticmethod
    def _filter(parmTuples):
        valid_types = { parmTemplateType.Int, parmTemplateType.Float, parmTemplateType.String, parmTemplateType.Toggle }
        return list(pt for pt in parmTuples if pt.parmTemplate().type() in valid_types and not pt.isHidden() and not pt.isDisabled())
    
    def __init__(self, editor, volatile):
        super(HCommanderWindow, self).__init__(
            hou.qt.floatingPanelWindow(editor.pane().floatingPanel())
        )
        self._volatile = volatile

        self.editor = editor
        self.setMinimumWidth(700)
        self.setMinimumHeight(300)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.X11BypassWindowManagerHint)
        self.setWindowOpacity(0.95)

        selected_node = hou.selectedNodes()[0]
        self._model = CompositeModel(self, [
            ParmTupleModel(self, HCommanderWindow._filter(selected_node.parmTuples())),
            ActionModel(self, Action.find(selected_node))])

        self._setup_ui()
        self.selection = (None, None)

    def handleEvent(self, uievent, pending_actions):
        return True
        # FIXME

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

        self._list = QtWidgets.QListView()

        self._proxy_model = AutoCompleteModel()
        self._proxy_model.setSourceModel(self._model)
        self._list.setModel(self._proxy_model)

        self._item_delegate = ItemDelegate(self)
        self._list.setItemDelegate(self._item_delegate)

        # self._list.clicked.connect(self.accept)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setEditTriggers(QAbstractItemView.SelectedClicked | QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)

        layout.addWidget(self._list)
    
    def eventFilter(self, obj, event):
        if self._volatile:
            if event.type() == QtCore.QEvent.KeyPress and event.key() == Qt.Key_Space and event.isAutoRepeat():
                return True

            elif event.type() == QtCore.QEvent.KeyRelease and event.key() == Qt.Key_Escape:
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
    
    def _handle_keys(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key in (Qt.Key_Enter, Qt.Key_Return):
            # self.accept()
            return False

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
        print "in accept"
        if not self._list.selectedIndexes():
            self.reject()
            return

        index = self._list.selectedIndexes()[0]
        self._list.edit(index)
        return
        parm_tuple = index.data(ParmTupleRole)

        if isinstance(parm_tuple, Action):
            self.selection = (parm_tuple, 0)
        else:
            type = parm_tuple.parmTemplate().type()
            if type == parmTemplateType.Toggle:
                parm_tuple.set([int(not parm_tuple.eval()[0])])
            else:
                self.selection = (parm_tuple, (index.data(WhichMatchRole) or 1) - 1)
    
    def close(self):
        print "in close"
        QtWidgets.QDialog.close(self)
        self.setParent(None)
        this.window = None

    def changeEvent(self, event): # Close when losing focus
        if event.type() == QtCore.QEvent.ActivationChange:
            if not self.isActiveWindow():
                self.close()

class ItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super(ItemDelegate, self).__init__(parent)
        self._filter = None

    def sizeHint(self, option, index):
        return QtCore.QSize(0, 50)

    def filter(self, text):
        self._filter = text

    def paint(self, painter, option, index):
        painter.save()
        style = option.widget.style()
        self.initStyleOption(option, index)
        painter.setClipRect(option.rect)

        parm_tuple = index.data(ParmTupleRole)
        
        # Draw the background but nothing else
        option.text = ""
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
        text_rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, option, option.widget)

        painter.translate(option.rect.topLeft())

        field = InputField(self.parent(), parm_tuple, self._filter, index.data(WhichMatchRole), index.data(AutoCompleteRole))
        field.setGeometry(option.rect)
        field.render(painter, QtCore.QPoint(0, 0), QtGui.QRegion(0, 0, option.rect.width(), option.rect.height()), QWidget.RenderFlag.DrawChildren)

        painter.restore()

    def createEditor(self, parent, option, index):
        field = InputField(parent, index.data(ParmTupleRole), self._filter, index.data(WhichMatchRole), index.data(AutoCompleteRole))
        return field

    def setEditorData(self, editor, index):
        print "setEditorData"
    
    def setModelData(self, editor, model, index):
        print "setModelData"
        QStyledItemDelegate.setModelData(self, editor, model, index)

    def commitAndCloseEditor(self):
        print "commit and close"
        editor = self.sender()

        # The commitData signal must be emitted when we've finished editing
        # and need to write our changed back to the model.
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)

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
        QtCore.QSortFilterProxyModel.setSourceModel(self, model)
        i = 0
        self._bitsetss = []
        # Construct a bitset for each word for fast(ish) fuzzy-matching
        while i < model.rowCount():
            labels = model.index(i).data(AutoCompleteRole)
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
        
        labels = self.sourceModel().index(sourceRow, 0, sourceParent).data(AutoCompleteRole)
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
    
class ParmTupleModel(QtCore.QAbstractListModel):
    def __init__(self, parent, parmTuples):
        super(ParmTupleModel, self).__init__(parent)
        self._parmTuples = sorted(parmTuples, key=lambda x: x.isAtDefault())

    def rowCount(self, parentindex=None):
        return len(self._parmTuples)
    
    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled

    def setData(self, index, value, role = QtCore.Qt.EditRole):
        print "set data"

    def data(self, index, role):
        if not index.isValid(): return None
        if not 0 <= index.row() < len(self._parmTuples): return None

        parm_tuple = self._parmTuples[index.row()]
        type = parm_tuple.parmTemplate().type()

        if role == ParmTupleRole:
            return parm_tuple
        if role == Qt.DisplayRole:
            if type == parmTemplateType.Toggle: return None

            vs = []
            for v in parm_tuple.eval():
                if type == hou.parmTemplateType.Float:
                    vs.append("{:.1f}".format(v))
                else:
                    vs.append(str(v))
            return ", ".join(vs)
        if role == Qt.ForegroundRole:
            if parm_tuple.isAtDefault():
                return QtGui.QColor(Qt.darkGray)
            else:
                return QtGui.QColor(Qt.white)
        if role == AutoCompleteRole:
            return [parm_tuple.parmTemplate().label()] + map(lambda x: x.name(), parm_tuple)

        return None

class ActionModel(QtCore.QAbstractListModel):
    def __init__(self, parent, actions):
        super(ActionModel, self).__init__(parent)
        self._actions = actions

    def rowCount(self, parentindex=None):
        return len(self._actions)
    
    def data(self, index, role):
        action = self._actions[index.row()]

        if role == ParmTupleRole:
            return action

        if role == AutoCompleteRole:
            return (action.label, action.name)
        
        return None

    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

class CompositeModel(QtCore.QAbstractListModel):
    def __init__(self, parent, models):
        super(CompositeModel, self).__init__(parent)
        self._models = models
        
    def rowCount(self, parentindex=None):
        sum = 0
        for model in self._models:
            sum += model.rowCount(parentindex)
        return sum
    
    def data(self, index, role):
        index = self.map_to_source(index)
        return index.data(role)
    
    def flags(self, index):
        return self.map_to_source(index).flags()
    
    def map_to_source(self, index):
        row = index.row()
        model = None
        for model_ in self._models:
            if row < model_.rowCount():
                model = model_
                break
            row -= model_.rowCount()
        index = model.index(row)
        return index

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
        self.delta(event.angleDelta().y(), event.modifiers())
    
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
                self.delta(1, event.modifiers())
                return True
            elif event.key() == Qt.Key_Down:
                self.delta(-1, event.modifiers())
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
        # this.cc.send(None)

    def delta(self, delta, modifiers):
        scale = 0.01
        f = float
        type = self._parm_tuple.parmTemplate().type()
        if type == parmTemplateType.Int:
            f = int
            scale = 1
        else:
            if modifiers & Qt.ShiftModifier:
                scale = 0.001
            if modifiers & Qt.MetaModifier:
                scale = 0.1
            if modifiers & Qt.AltModifier:
                scale = 1
            if modifiers & Qt.MetaModifier and modifiers & Qt.AltModifier:
                scale = 10
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

class InputField(QtWidgets.QWidget):
    valueChanged = QtCore.Signal()

    @staticmethod
    def type2icon(type):
        typename = type.name()
        iconname = None
        if typename == "Float":
            iconname = "DATATYPES_float"
        elif typename == "Int":
            iconname = "DATATYPES_int"
        elif typename == "Toggle":
            iconname = "DATATYPES_boolean"
        elif typename == "String":
            iconname = "DATATYPES_string"
        else:
            print typename
        return hou.qt.Icon(iconname)
        
    def __init__(self, parent, parm_tuple, filter, which_match, autocompletes):
        super(InputField, self).__init__(parent)
        self.parm_tuple = parm_tuple

        self.setStyleSheet("background: transparent; border: 1px solid black")
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        icon = InputField.type2icon(parm_tuple.parmTemplate().type())
        if icon:
            icon_size = hou.ui.scaledSize(16)
            pixmap = icon.pixmap(QtCore.QSize(icon_size, icon_size))
            label = QtWidgets.QLabel(self)
            label.setPixmap(pixmap)
            layout.addWidget(label)

        layout.addWidget(_Label(filter, which_match, autocompletes))

        self.line_edits = []
        for i, parm in enumerate(parm_tuple):
            self.line_edits.append(QtWidgets.QLineEdit(self))

            self.line_edits[i].setStyleSheet("border: 1px solid black; background: transparent;")
            self.line_edits[i].setText(str(parm_tuple.eval()[i]))

            # self.line_edits[i].textChanged.connect(self._handleTextChanged)
            # self.line_edits[i].textEdited.connect(self._handleLineEditChanged)
            # self.line_edits[i].editingFinished.connect(self._handleEditingFinished)
            layout.addWidget(self.line_edits[i])
        self.setLayout(layout)

    def _handleLineEditChanged(self, text):
        self.hasPendingChanges = True

    def _handleEditingFinished(self):
        if self.hasPendingChanges:
            self.valueChanged.emit()

        self.hasPendingChanges = False

    def _handleTextChanged(self, text):
        self.valueChanged.emit()

class _Label(QtWidgets.QWidget):
    doc = QtGui.QTextDocument()
    doc.setDocumentMargin(0)

    def __init__(self, filter, which_match, autocompletes):
        super(_Label, self).__init__()
        self._filter = filter
        self._which_match = which_match
        self._autocompletes = autocompletes
        self._highlight_format = QtGui.QTextCharFormat()
        self._highlight_format.setFontWeight(QtGui.QFont.Bold)

    def sizeHint(self):
        return QtCore.QSize(220, 1)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        if self._filter:
            self.doc.setPlainText("")
            cursor = QtGui.QTextCursor(self.doc)
            plain = cursor.charFormat()
            cursor.mergeCharFormat(self._highlight_format)
            highlight = cursor.charFormat()
            filter = self._filter.upper()
            first = True
            for x, text in enumerate(self._autocompletes):
                if x == self._which_match:
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
            labels = self._autocompletes
            first, rest = labels[0], labels[1:]
            _Label.doc.setPlainText(first + ": " + " ".join(rest) + "")

        padding = (self.geometry().height() - _Label.doc.size().height())/2
        painter.translate(0, padding)

        ctx = QtGui.QAbstractTextDocumentLayout.PaintContext()
        _Label.doc.documentLayout().draw(painter, ctx)

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
        self.setMinimumWidth(500)
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
        self._list.setStyleSheet("QListView::item { padding: 10px; }")

        self._proxy_model = AutoCompleteModel()
        self._proxy_model.setSourceModel(self._model)
        self._list.setModel(self._proxy_model)

        self._item_delegate = ItemDelegate()
        self._list.setItemDelegate(self._item_delegate)

        # self._list.clicked.connect(self.accept)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setEditTriggers(QAbstractItemView.SelectedClicked | QAbstractItemView.DoubleClicked)

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
        print "in accept"
        if not self._list.selectedIndexes():
            self.reject()
            return

        index = self._list.selectedIndexes()[0]
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
        self.doc = QtGui.QTextDocument(self)
        self.doc.setDocumentMargin(0)
        self._highlight_format = QtGui.QTextCharFormat()
        self._highlight_format.setFontWeight(QtGui.QFont.Bold)
        self._filter = None

    def filter(self, text):
        self._filter = text

    def paint(self, painter, option, index):
        painter.save()
        style = option.widget.style()
        self.initStyleOption(option, index)
        marginx = style.pixelMetric(QtWidgets.QStyle.PM_FocusFrameHMargin, None, option.widget) + 1
        painter.setClipRect(option.rect)

        label = index.data(ParmTupleRole).parmTemplate().label()
        
        # Draw the background, icon, and checkbox, but not the label
        option.text = ""
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
        text_rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, option, option.widget)

        # move to position to draw the rest
        if option.state & QStyle.State_Selected: text_rect.adjust(0, -1, 0, 0)
        painter.translate(text_rect.topLeft())

        # paint the label, highlight matches
        docsize = self._paintLabel(painter, index)

        # paint the widget for the values
        painter.translate(docsize.width() + marginx, 0)
        field = InputField(InputField.FloatType, 1, label)
        field.setGeometry(text_rect.adjusted(docsize.width() + marginx, 0, 0, 0))
        field.render(painter, QtCore.QPoint(0, 0), QtGui.QRegion(0, 0, option.rect.width(), option.rect.height()), QWidget.RenderFlag.DrawChildren)

        painter.restore()

    def _paintLabel(self, painter, index):
        if self._filter:
            self.doc.setPlainText("")
            cursor = QtGui.QTextCursor(self.doc)
            plain = cursor.charFormat()
            cursor.mergeCharFormat(self._highlight_format)
            highlight = cursor.charFormat()
            filter = self._filter.upper()
            first = True
            match = index.data(WhichMatchRole)
            for x, text in enumerate(index.data(AutoCompleteRole)):
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
            labels = index.data(AutoCompleteRole)
            first, rest = labels[0], labels[1:]
            self.doc.setPlainText(first + ": " + " ".join(rest) + "")

        ctx = QtGui.QAbstractTextDocumentLayout.PaintContext()
        self.doc.documentLayout().draw(painter, ctx)
        return self.doc.size()

    def createEditor(self, parent, option, index):
        print "createEditor"
        # if index.column() == 3:
        #     editor = StarEditor(parent)
        #     editor.editingFinished.connect(self.commitAndCloseEditor)
        #     return editor
        # else:
        return QStyledItemDelegate.createEditor(self, parent, option, index)

    def setEditorData(self, editor, index):
        print "setEditorData"
        # if index.column() == 3:
        #     editor.starRating = StarRating(index.data())
        # else:
        QStyledItemDelegate.setEditorData(self, editor, index)
    
    def setModelData(self, editor, model, index):
        print "setModelData"
        # if index.column() == 3:
        #     model.setData(index, editor.starRating.starCount)
        # else:
        QStyledItemDelegate.setModelData(self, editor, model, index)

    def commitAndCloseEditor(self):
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
    @staticmethod
    def type2icon(type):
        typename = type.name()
        iconname = None
        if typename == "Float":
            iconname = "DATATYPES_float"
        elif typename == "Int":
            iconname = "DATATYPES_int"
        elif typename == "Toggle":
            # the checkbox takes the place of the icon
            return None
        elif typename == "String":
            iconname = "DATATYPES_string"
        else:
            print typename
        return hou.qt.Icon(iconname)

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
        if role == Qt.DecorationRole:
            return ParmTupleModel.type2icon(type)
        if role == Qt.ForegroundRole:
            if parm_tuple.isAtDefault():
                return QtGui.QColor(Qt.darkGray)
            else:
                return QtGui.QColor(Qt.white)
        if role == AutoCompleteRole:
            return [parm_tuple.parmTemplate().label()] + map(lambda x: x.name(), parm_tuple)
        if role == Qt.CheckStateRole:
            if type == parmTemplateType.Toggle:
                return Qt.Checked if parm_tuple.eval()[0] == 1 else Qt.Unchecked
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
    IntegerType = 0
    FloatType = 1
    StringType = 2

    valueChanged = QtCore.Signal()
    hotkeyInvoked = QtCore.Signal(str)

    def __init__(self, data_type, num_components, label=None, mouse_hotkeys={}):
        super(InputField, self).__init__()

        assert data_type in (
            InputField.IntegerType,
            InputField.FloatType,
            InputField.StringType)
        self.dataType = data_type

        self.setStyleSheet("margin: 0; padding: 0; border: 1px solid black")

        # We support between 1 and 4 components.
        assert num_components >= 1 and num_components <= 4
        self.numComponents = num_components

        self.mouse_hotkeys = mouse_hotkeys

        # For keeping track of whether any of the line edits
        # has a pending text change.
        self.hasPendingChanges = False

        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create (optional) label.
        # if label is not None and label != "":
        #     layout.addWidget(hou.qt.FieldLabel(label))

        # Create line edit widgets.
        self.lineEdits = []
        for i in range(self.numComponents):
            self.lineEdits.append(_LineEdit(self.dataType,
                                            mouse_hotkeys=self.mouse_hotkeys))

            # Set default text.
            if self.dataType in (InputField.IntegerType, InputField.FloatType):
                self.lineEdits[i].setText("0")

            # Listen for text changes in the line edit.
            self.lineEdits[i].textChanged.connect(self._handleTextChanged)
            self.lineEdits[i].textEdited.connect(self._handleLineEditChanged)
            self.lineEdits[i].editingFinished.connect(
                self._handleEditingFinished)
            self.lineEdits[i].hotkeyInvoked.connect(self.hotkeyInvoked.emit)

            layout.addWidget(self.lineEdits[i])

        self.setLayout(layout)

    def setValue(self, value, index=0):
        assert index >= 0 and index <= self.numComponents
        if sys.version_info.major >= 3:
            is_string = type(value) in (str, )
        else:
            is_string = type(value) in (str, unicode)
        assert (self.dataType == InputField.StringType
                and is_string) \
            or (self.dataType in (InputField.IntegerType, InputField.FloatType)
                and type(value) in (int, float))

        strvalue = str(value)
        if type(value) is float:
            strvalue = strvalue.rstrip('0').rstrip('.')
        self.lineEdits[index].setText(strvalue)

    def setValues(self, values):
        # First pass.  Check value types.
        assert len(values) == self.numComponents
        for i in range(self.numComponents):
            assert (self.dataType == InputField.StringType
                and type(values[i]) == str) \
            or (self.dataType in (InputField.IntegerType, InputField.FloatType)
                and type(values[i]) in (int, float))

        # Second pass.  Set values.
        for i in range(self.numComponents):
            self.lineEdits[i].setText(str(values[i]))

            # Do this so that the beginning of the text is visible.
            self.lineEdits[i].setCursorPosition(0)

    def value(self, index=0):
        assert index >= 0 and index <= self.numComponents
        text = self.lineEdits[index].text()

        if self.dataType == InputField.IntegerType:
            try:
                val = int(text)
            except:
                val = 0
        elif self.dataType == InputField.FloatType:
            try:
                val = float(text)
            except:
                val = 0.0
        else:
            val = text

        return val

    def values(self):
        return_values = []

        for i in range(self.numComponents):
            text = self.lineEdits[i].text()

            if self.dataType == InputField.IntegerType:
                try:
                    val = int(text)
                except:
                    val = 0
            elif self.dataType == InputField.FloatType:
                try:
                    val = float(text)
                except:
                    val = 0.0
            else:
                val = text

            return_values.append(val)

        return return_values

    def setAlignment(self, a):
        for i in range(self.numComponents):
            self.lineEdits[i].setAlignment(a)

    def setState(self, state_name, state_value, index=0):
        assert index >= 0 and index <= self.numComponents
        current = self.lineEdits[index].property(state_name)
        if current != state_value:
            self.lineEdits[index].setProperty(state_name, state_value)
            self.style().unpolish(self.lineEdits[index])
            self.style().polish(self.lineEdits[index])
            self.update()

    def state(self, state_name, index=0):
        assert index >= 0 and index <= self.numComponents
        return self.lineEdits[index].property(state_name)

    def setMenu(self, menu):
        for i in range(self.numComponents):
            self.lineEdits[i].setMenu(menu)

    def menu(self):
        return list(self.lineEdits[i].menu() for i in range(self.numComponents))

    def _handleLineEditChanged(self, text):
        self.hasPendingChanges = True

    def _handleEditingFinished(self):
        # If there were pending changes, then notify observers that the value
        # has changed.
        if self.hasPendingChanges:
            self.valueChanged.emit()

        self.hasPendingChanges = False

    def _handleTextChanged(self, text):
        self.valueChanged.emit()




class _LineEdit(QtWidgets.QLineEdit):
    """Private helper class representing a single line edit widget
       in the input field."""
    hotkeyInvoked = QtCore.Signal(str)

    def __init__(self, data_type, mouse_hotkeys={}):
        QtWidgets.QLineEdit.__init__(self)

        self._menu = None
        self.mouse_hotkeys = mouse_hotkeys
        self.setObjectName("parm_edit")
        self.dataType = data_type
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)

        self.isValueLadderOpen = False
        self.setStyleSheet("margin: 0; padding: 0")

    def sizeHint(self):
        size_hint = QtWidgets.QLineEdit.sizeHint(self)
        size_hint.setWidth(50)
        return size_hint

    def _handleXCFValueChange(self, ladder_value):
        str_value = str(ladder_value)
        self.setText(str_value)

        # Notify observers that the text contents have changed.
        self.textChanged.emit(str_value)

    def mousePressEvent(self, event):
        buttons = int(event.buttons())
        modifiers = int(event.modifiers())
        # First check for menu
        if (buttons, modifiers) == (QtCore.Qt.RightButton, 0) and self._menu:
            self._menu.popup(self.mapToGlobal(event.pos()))
            return

        # Next check for XCF slider
        if event.button() == QtCore.Qt.MiddleButton and modifiers == 0:
            hou.ui.openValueLadder(
                self.xcfValue(), self._handleXCFValueChange,
                hou.valueLadderType.Generic,
                hou.valueLadderDataType.Float
                    if self.dataType == InputField.FloatType
                    else hou.valueLadderDataType.Int)
            self.isValueLadderOpen = True
            return

        # Next check for hotkeys
        hotkey_symbol = self.mouse_hotkeys.get((buttons, modifiers))
        if hotkey_symbol:
            self.hotkeyInvoked.emit(hotkey_symbol)
            return

        # Nothing so just go to the base class
        super(_LineEdit, self).mousePressEvent(event)

    def setMenu(self, menu):
        self._menu = menu

    def menu(self):
        return self._menu

    def mouseMoveEvent(self, event):
        if self.isValueLadderOpen:
            hou.ui.updateValueLadder(
                event.globalX(), event.globalY(),
                bool(event.modifiers() & QtCore.Qt.AltModifier),
                bool(event.modifiers() & QtCore.Qt.ShiftModifier))

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton and self.isValueLadderOpen:
            hou.ui.closeValueLadder()
            self.isValueLadderOpen = False

    def xcfValue(self):
        """Return the numeric value of the line edit's text that should be used
           in the XCF ladder window."""
        if self.dataType == InputField.IntegerType:
            try:
                val = int(self.text())
            except:
                val = 0
        elif self.dataType == InputField.FloatType:
            try:
                val = float(self.text())
            except:
                val = 0.0
        else:
            # InputField.StringType.
            # TODO: Parse out numeric value under cursor if any.
            val = 0

        return val
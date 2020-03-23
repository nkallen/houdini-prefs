import hou, nodegraph, os, csv, sys, traceback, math
from hou import parmTemplateType
from collections import defaultdict
import nodegraphbase as base
from canvaseventtypes import *
from PySide2 import QtCore, QtWidgets, QtGui
from PySide2.QtCore import Qt
from nodegraphbase import EventHandler
import utility_ui
from PySide2.QtWidgets import QAbstractItemView, QStyledItemDelegate, QWidget, QStyle, QAbstractItemDelegate
from PySide2.QtCore import Signal

# volatility is broken
 
"""
Commander is a "graphical" command line interface for Houdini's Network Editor. You can
quickly run commands or edit nodes using only the keyboard.
"""

this = sys.modules[__name__]
ParmTupleRole = Qt.UserRole 
AutoCompleteRole = Qt.UserRole + 1
WhichMatchRole = Qt.UserRole + 2

this.window = None
def handleEvent(uievent, pending_actions):
    def reset_state(): this.window = None

    if this.window:
        result = this.window.handleEvent(uievent, pending_actions)
        return this, result
    else:
        if uievent.eventtype == 'keydown' and uievent.key == 'Space':
            window = HCommanderWindow(uievent.editor, False)
            window.show()
            window.activateWindow()
            this.window = window
            window.finished.connect(reset_state)
            return this, True

        return None, False

class HCommanderWindow(QtWidgets.QDialog):
    width = 700

    @staticmethod
    def _filter(parmTuples):
        valid_types = { parmTemplateType.Int, parmTemplateType.Float, parmTemplateType.String, parmTemplateType.Toggle }
        return list(pt for pt in parmTuples if pt.parmTemplate().type() in valid_types and not pt.isHidden() and not pt.isDisabled())
    
    def __init__(self, editor, volatile):
        super(HCommanderWindow, self).__init__(hou.qt.mainWindow())
        self._volatile = volatile

        self.editor = editor
        self.setMinimumWidth(HCommanderWindow.width)
        self.setMinimumHeight(350)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.X11BypassWindowManagerHint)
        self.setWindowOpacity(0.95)

        models = []
        if len(hou.selectedNodes()) == 1:
            models.append(ParmTupleModel(self, HCommanderWindow._filter(hou.selectedNodes()[0].parmTuples())))
            models.append(ActionModel(self, Action.find(hou.selectedNodes()[0])))
        self._model = CompositeModel(self, models)

        self._setup_ui()

    def handleEvent(self, uievent, pending_actions):
        return True
        # FIXME

    def _setup_ui(self):
        self.setStyleSheet(hou.qt.styleSheet())
        self._textbox = QtWidgets.QLineEdit(self)
        self._textbox.installEventFilter(self)
        self._textbox.returnPressed.connect(self.accept)
        self._textbox.setStyleSheet("font-size: 18px; height: 24px; border: none; background-color: transparent")
        self._textbox.textChanged.connect(self._text_changed)
        self._textbox.setFocus()
        self._textbox.setFocusPolicy(Qt.ClickFocus)

        self._list = ListView(self)
        self._proxy_model = AutoCompleteModel()
        self._proxy_model.setSourceModel(self._model)
        self._list.setModel(self._proxy_model)
        item_delegate = ItemDelegate(parent=self._list) # passing a parent= is necessary for child InputFields to inherit style
        item_delegate.closeEditor.connect(self._textbox.setFocus)
        self.finished.connect(item_delegate.windowClosed.emit)
        self._list.setItemDelegate(item_delegate) 
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setFocusPolicy(Qt.NoFocus)

        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(10)
        self.setLayout(layout)
        layout.addWidget(self._textbox)
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
        self._list.itemDelegate().filter(text)
        index = self._list.model().index(0, 0)
        self._list.setCurrentIndex(index)
    
    def _handle_keys(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_Up:
            self._cursor(self._list.MoveUp, modifiers)
            return True
        elif key == Qt.Key_Down:
            self._cursor(self._list.MoveDown, modifiers)
            return True
        elif key == Qt.Key_Tab:
            return True

        return False

    def _cursor(self, action, modifiers):
        index = self._list.moveCursor(action, modifiers)
        self._list.setCurrentIndex(index)
        
    def accept(self):
        if not self._list.selectedIndexes():
            self.reject()
            return

        index = self._list.selectedIndexes()[0]
        parm_tuple = index.data(ParmTupleRole)

        if isinstance(parm_tuple, Action):
            pass # FIXME
        else:
            type = parm_tuple.parmTemplate().type()
            if type == parmTemplateType.Toggle:
                parm_tuple.set([int(not parm_tuple.eval()[0])])
            else:
                self._list.edit(index)

class ItemDelegate(QStyledItemDelegate):
    windowClosed = QtCore.Signal(object)

    def __init__(self, parent=None):
        super(ItemDelegate, self).__init__(parent)
        self._filter = None
        self._last_event = None
        self.closeEditor.connect(self._closeEditor)

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

        if option.state & QStyle.State_Selected:
            # Draw the background but nothing else
            option.text = ""
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
            text_rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, option, option.widget)
        elif not parm_tuple.isAtDefault():
            painter.fillRect(option.rect, hou.qt.getColor("ListBG"))

        painter.translate(option.rect.topLeft())
        field = InputField(self.parent(), index, self._filter, highlight=option.state & QStyle.State_Selected)
        field.setGeometry(option.rect)
        field.render(painter, QtCore.QPoint(0, 0), QtGui.QRegion(0, 0, option.rect.width(), option.rect.height()), QWidget.RenderFlag.DrawChildren)

        painter.restore()

    def createEditor(self, parent, option, index):
        which_match = index.data(WhichMatchRole)
        editor = InputField(parent, index, self._filter, highlight=False)

        # focus the best autocomplete match
        which_match = index.data(WhichMatchRole)
        focus_proxy = editor.line_edits[(which_match or 1) - 1]
        editor.setFocusProxy(focus_proxy)

        # but if the user clicked on a field, focus that instead
        if self._last_event:
            clicked = editor.line_edit_at(self._last_event.pos())
            if clicked: editor.setFocusProxy(clicked)

        editor.editingFinished.connect(self.editingFinished)
        editor.valueChanged.connect(self.valueChanged)
        self.windowClosed.connect(lambda _: editor.editingFinished.emit())

        return editor

    def setEditorData(self, editor, index):
        # Disable undos while the user makes interactive edits
        editor.undo_context = hou.undos.disabler()
        editor.undo_context.__enter__()
        parm_tuple = index.data(ParmTupleRole)
        editor.original_value = parm_tuple.eval()

    def setModelData(self, editor, model, index):
        editor.undo_context.__exit__(None, None, None)
        if editor.parm_tuple.eval() != editor.original_value:
            with hou.undos.group("Parameter Change"):
                for i, parm in enumerate(editor.parm_tuple):
                    self.valueChanged(parm, editor.line_edits[i].text())
    
    def _closeEditor(self, editor, edit_hint):
        self.windowClosed.disconnect()
        if edit_hint == QAbstractItemDelegate.EndEditHint.RevertModelCache:
            editor.parm_tuple.set(editor.original_value)
            editor.undo_context.__exit__(None, None, None)

    def editingFinished(self):
        editor = self.sender()
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)
    
    def valueChanged(self, parm, value):
        type = parm.parmTemplate().type()
        if value != "":
            if type == parmTemplateType.Int:
                try: parm.set(int(value))
                except: pass
            elif type == parmTemplateType.Float:
                try: parm.set(float(value))
                except: pass
            elif type == parmTemplateType.String:
                parm.set(value)
        else:
            parm.revertToDefaults()

    def mousePressEvent(self, list, event):
        index = list.indexAt(event.pos())
        self._last_event = event
        list.edit(index)
        self._last_event = None
        
class ListView(QtWidgets.QListView):
    def mousePressEvent(self, event):
        QtWidgets.QListView.mousePressEvent(self, event)
        item_delegate = self.itemDelegate()
        item_delegate.mousePressEvent(self, event)

class InputField(QtWidgets.QWidget):
    label_width = 220
    margin = 10
    valueChanged = QtCore.Signal(hou.Parm, str)
    editingFinished = QtCore.Signal()

    @staticmethod
    def type2icon(type):
        typename = type.name()
        iconname = None
        if typename == "Float":    iconname = "DATATYPES_float"
        elif typename == "Int":    iconname = "DATATYPES_int"
        elif typename == "Toggle": iconname = "DATATYPES_boolean"
        elif typename == "String": iconname = "DATATYPES_string"
        return hou.qt.Icon(iconname)
    
    @staticmethod
    def format(text, filter):
        if not filter: return text
        result = ""
        i = 0
        for char in text:
            if i < len(filter) and char.upper() == filter[i].upper():
                i += 1
                result += "<b>{}</b>".format(char)
            else:
                result += char
        return result

    def __init__(self, parent, index, filter, highlight=False):
        super(InputField, self).__init__(parent)

        autocompletes = index.data(AutoCompleteRole)
        which_match = index.data(WhichMatchRole)
        parm_tuple = index.data(ParmTupleRole)
        self.parm_tuple = parm_tuple

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(InputField.margin, 0, InputField.margin, 0)
        self.setLayout(layout)

        icon = InputField.type2icon(parm_tuple.parmTemplate().type())
        if icon:
            icon_size = hou.ui.scaledSize(16)
            pixmap = icon.pixmap(QtCore.QSize(icon_size, icon_size))
            label = QtWidgets.QLabel(self)
            label.setPixmap(pixmap)
            layout.addWidget(label)

        label = QtWidgets.QLabel(InputField.format(autocompletes[0], filter if which_match == 0 else None))
        label.setFixedWidth(InputField.label_width)
        layout.addWidget(label)

        self.line_edits = []
        for i, parm in enumerate(parm_tuple):
            edit_layout = QtWidgets.QVBoxLayout()
            edit_layout.setContentsMargins(0,InputField.margin,0,0)
            edit_layout.setSpacing(0)
            line_edit = QtWidgets.QLineEdit(self)
            border = "yellow" if highlight and which_match and i == which_match - 1 else "black"
            line_edit.setStyleSheet("QLineEdit { border: 1px solid " + border + "; background-color:" + hou.qt.getColor("PaneEmptyBG").name() + " }")
            line_edit.setText(str(parm_tuple.eval()[i]))
            line_edit.setProperty("parm", parm)
            line_edit.installEventFilter(self)
            line_edit.textEdited.connect(self._update)
            self.line_edits.append(line_edit)
            edit_layout.addWidget(line_edit)
            label = QtWidgets.QLabel(InputField.format(autocompletes[i+1], filter if which_match == i + 1 else None))
            label.setStyleSheet("font: italic 9px; color: darkgray")
            sizepolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            label.setSizePolicy(sizepolicy)
            edit_layout.addWidget(label)
            edit_layout.setAlignment(label, Qt.AlignHCenter)
            layout.addLayout(edit_layout)

    def line_edit_at(self, pos):
        x = pos.x() - InputField.label_width - InputField.margin*2
        if x < 0: return None
        width = HCommanderWindow.width - InputField.label_width - InputField.margin*2
        i = int(math.floor( x * len(self.line_edits) / width))
        return self.line_edits[i]

    _axis = {Qt.Key_X: [1,0,0,0], Qt.Key_Y: [0,1,0,0], Qt.Key_Z: [0,0,1,0], Qt.Key_W: [0,0,0,1]}
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Wheel:
            self.delta(event.angleDelta().y(), event.modifiers(), obj)
            event.accept()
            return True
        elif event.type() == QtCore.QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                self.delta(1, event.modifiers(), obj)
                return True
            elif event.key() == Qt.Key_Down:
                self.delta(-1, event.modifiers(), obj)
                return True
            # elif event.key() == Qt.Key_Space and self._volatile:
            #     return True
            elif self.parm_tuple.parmTemplate().namingScheme() == hou.parmNamingScheme.XYZW:
                if event.key() in InputField._axis:
                    l = len(self.parm_tuple)
                    self.parm_tuple.set(InputField._axis[event.key()][0:l])
                    for i, parm in enumerate(self.parm_tuple):
                        textbox = self.line_edits[i]
                        textbox.setText(str(parm.eval()))
                        if InputField._axis[event.key()][i] == 1:
                            textbox.selectAll()
                            textbox.setFocus()
                        
                    return True
        return False

    def delta(self, delta, modifiers, obj):
        scale = 0.01
        f = float
        type = self.parm_tuple.parmTemplate().type()
        if type == parmTemplateType.Int:
            f = int
            scale = 1
        else:
            if modifiers & Qt.ShiftModifier: scale = 0.001
            if modifiers & Qt.MetaModifier: scale = 0.1
            if modifiers & Qt.AltModifier: scale = 1
            if modifiers & Qt.MetaModifier and modifiers & Qt.AltModifier: scale = 10
        textbox = obj
        parm = textbox.property("parm")
        result = f(textbox.text()) + delta * scale
        value = str(result)
        textbox.setText(value)
        self.valueChanged.emit(parm, value)
    
    def _update(self, value):
        parm = self.sender().property("parm")
        self.valueChanged.emit(parm, value)

class AutoCompleteModel(QtCore.QSortFilterProxyModel):
    """
    This is a custom autocompleter that can match either the "label" or the "name(s)" in an item. Its key
    feature is when a user types "upr" it can match "upper", "super", etc. which differs from the
    default QT prefix/suffix matching. Items have labels like "translation" and names like "tx", "ty",
    etc.
    """

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


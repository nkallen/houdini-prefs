import hou, nodegraph, os, csv, sys, traceback, math, houdinihelp, weakref, utility_ui, inspect
from hou import parmTemplateType
from collections import defaultdict
import nodegraphbase as base
from canvaseventtypes import *
from PySide2 import QtCore, QtWidgets, QtGui
from PySide2.QtCore import Qt
from nodegraphbase import EventHandler
from PySide2.QtWidgets import QAbstractItemView, QStyledItemDelegate, QWidget, QStyle, QAbstractItemDelegate
from PySide2.QtCore import Signal
from houdinihelp.server import get_houdini_app

"""
Commander is a "graphical" command line interface for Houdini's Network Editor. You can
quickly run commands or edit nodes using only the keyboard.
"""

this = sys.modules[__name__]

ParmTupleRole    = Qt.UserRole 
AutoCompleteRole = Qt.UserRole + 1
WhichMatchRole   = Qt.UserRole + 2
CallbackRole     = Qt.UserRole + 3
NodeTypeRole     = Qt.UserRole + 4
SortKeyRole      = Qt.UserRole + 5
ActionRole       = Qt.UserRole + 5

this.window = None
def reset_state(): this.window = None

def handleEvent(uievent, pending_actions):
    if this.window:
        result = this.window.handleEvent(uievent, pending_actions)
        return this, result
    else:
        if uievent.eventtype == 'keydown' and uievent.key == 'Space':
            this.window = HCommanderWindow(uievent.editor, volatile=True, selection=hou.selectedNodes())
        elif uievent.eventtype == 'keyhit' and uievent.key == 'Ctrl+Space':
            this.window = HCommanderWindow(uievent.editor, volatile=False, selection=hou.selectedNodes())
        elif uievent.eventtype == 'keyhit' and uievent.key == 'Shift+Tab':
            this.window = HCommanderWindow(uievent.editor, volatile=False, selection=[uievent.editor.pwd()])
        else:
            return None, False
        this.window.finished.connect(reset_state)
        this.window.show()
        return this, True

def edit(editor, parm_tuple):
    assert not this.window
    this.window = HCommanderWindow(editor, volatile=False, selection=[parm_tuple.node()], item=parm_tuple)
    this.window.finished.connect(reset_state)
    window.show()
    
class HCommanderWindow(QtWidgets.QDialog):
    width = 700
    
    def __init__(self, editor, volatile=False, selection=hou.selectedNodes(), item=None):
        super(HCommanderWindow, self).__init__(hou.qt.mainWindow())
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose) # NECESSARY TO AVOID LEAKING MEMORY
        self._volatile = volatile
        self.editor = editor
        self.setMinimumWidth(HCommanderWindow.width)
        self.setMinimumHeight(400)
        # Popups steal events, allowing us to receive the the space keyup to terminate volatile mode.
        # However, it swallows useful events in non-volatile mode. THIS FIXES BUG: ctrl-space, escape, space -- opens once but should twice.
        windowflag = Qt.Popup if self._volatile else Qt.Tool
        self.setWindowFlags(windowflag | Qt.FramelessWindowHint | Qt.X11BypassWindowManagerHint)
        self.setWindowOpacity(0.95)

        self._setup_models(editor, selection)
        self._setup_ui()

        if item:
            index = self.list.model().index_of(item)
            self.list.setCurrentIndex(index)
            self.list.edit(index)

    def _setup_models(self, editor, selection):
        node = selection[0] if len(selection) == 1 else None
        models = []
        if node:
            if node != editor.pwd():
                ptm = ParmTupleModel(ParmTupleModel._filter(node.parmTuples()))
                models.append(ptm)
            am = Action.find(node)
            category = node.childTypeCategory()
            if category:
                ntm = NodeTypeModel(category.nodeTypes())
                models.append(ntm)
            models.append(ActionModel(am))
        self._model = CompositeModel(models)
        self._proxy_model = AutoCompleteModel()
        self._proxy_model.setSourceModel(self._model)
        self._proxy_model.sort(0, Qt.AscendingOrder)

    def _setup_ui(self):
        self.setStyleSheet(hou.qt.styleSheet())
        textbox = QtWidgets.QLineEdit(self)
        textbox.installEventFilter(self)
        textbox.returnPressed.connect(self.accept)
        textbox.setStyleSheet("font-size: 18px; height: 24px; border: none; background-color: transparent")
        textbox.textChanged.connect(self._text_changed)
        textbox.setFocus()
        textbox.setFocusPolicy(Qt.ClickFocus)
        self._textbox = textbox

        list = ListView(self)
        list.setModel(self._proxy_model)
        item_delegate = ItemDelegate(parent=list) # passing a parent= is necessary for child InputFields to inherit style
        item_delegate.closeEditor.connect(self.closeEditor)
        list.ctrlClicked.connect(self.saveItem)
        list.clicked.connect(self.accept)
        self.finished.connect(item_delegate.windowClosed.emit)
        list.setItemDelegate(item_delegate) 
        list.setSelectionMode(QAbstractItemView.SingleSelection)
        list.setFocusPolicy(Qt.NoFocus)
        self.list = list

        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(10)
        self.setLayout(layout)
        layout.addWidget(self._textbox)
        layout.addWidget(self.list)

        saved = ListView(self)
        model = hou.session._hcommander_saved
        saved.setModel(model)
        saved.ctrlClicked.connect(self.unsaveItem)
        saved.clicked.connect(self.accept)
        item_delegate = ItemDelegate(parent=saved)
        item_delegate.closeEditor.connect(self.closeEditor)
        self.finished.connect(item_delegate.windowClosed.emit)
        saved.setItemDelegate(item_delegate) 
        saved.setSelectionMode(QAbstractItemView.SingleSelection)
        saved.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(saved)
        sizepolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        saved.setSizePolicy(sizepolicy)
        self._saved = saved
        if not hou.session._hcommander_saved.parm_tuples:
            saved.setVisible(False)

    def handleEvent(self, uievent, pending_actions):
        if self._volatile and uievent.eventtype == 'keyup' and uievent.key == 'Space':
            self.accept(self.list)

    def closeEditor(self):
        if self._volatile: self.close()
        else: self._textbox.setFocus()

    def saveItem(self, index):
        hou.session._hcommander_saved.append(index.data(ParmTupleRole))
        if hou.session._hcommander_saved.parm_tuples:
            self._saved.setVisible(True)

    def unsaveItem(self, index):
        hou.session._hcommander_saved.remove(index.data(ParmTupleRole))
        if not hou.session._hcommander_saved.parm_tuples:
            self._saved.setVisible(False)

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
        self.list.itemDelegate().filter(text)
        index = self.list.model().index(0, 0)
        self.list.setCurrentIndex(index)
    
    def _handle_keys(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_Up:
            self._cursor(self.list.MoveUp, modifiers)
            return True
        elif key == Qt.Key_Down:
            self._cursor(self.list.MoveDown, modifiers)
            return True
        elif key == Qt.Key_Tab:
            return True

        return False

    def _cursor(self, action, modifiers):
        index = self.list.moveCursor(action, modifiers)
        self.list.setCurrentIndex(index)
        
    def accept(self, list=None):
        list = list or self.list
        if not list.selectedIndexes():
            self.reject()
            return

        index = list.selectedIndexes()[0]
        callback = index.data(CallbackRole)
        callback(index, self, list)

    # Losing focus should save any unsaved changes (calling close will trigger save via `finished` signal)
    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.ActivationChange:
            if not self.isActiveWindow():
                self.close()

class ItemDelegate(QStyledItemDelegate):
    windowClosed = QtCore.Signal(object)

    def __init__(self, parent=None):
        super(ItemDelegate, self).__init__(parent)
        self._filter = None
        self.triggering_event = None
        self.closeEditor.connect(self._closeEditor)

    def sizeHint(self, option, index):
        return QtCore.QSize(0, 50)

    def filter(self, text):
        self._filter = text.upper()

    def paint(self, painter, option, index):
        painter.save()
        style = option.widget.style()
        self.initStyleOption(option, index)
        painter.setClipRect(option.rect)

        parm_tuple = index.data(ParmTupleRole)
        background = index.data(Qt.BackgroundRole)

        if option.state & QStyle.State_Selected:
            # Draw the background but nothing else
            option.text = ""
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
            text_rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, option, option.widget)
        elif background:
            painter.fillRect(option.rect, background)

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
        if self.triggering_event:
            clicked = editor.line_edit_at(self.triggering_event.pos())
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
            editor.parm_tuple.set(editor.original_value)
            ParmTupleModel.record(editor.parm_tuple)
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
        
class ListView(QtWidgets.QListView):
    ctrlClicked = QtCore.Signal(QtCore.QModelIndex)
    clicked = QtCore.Signal(QtWidgets.QListView)

    def sizeHint(self):
        s = QtWidgets.QListView.sizeHint(self)
        rowheight = self.sizeHintForRow(0)
        s.setHeight(min(s.height(), rowheight * self.model().rowCount()))
        return s

    def mousePressEvent(self, event):
        if event.modifiers() == Qt.NoModifier:
            index = self.indexAt(event.pos())
            self.setCurrentIndex(index)
            item_delegate = self.itemDelegate()
            item_delegate.triggering_event = event
            try: self.clicked.emit(self)
            finally: item_delegate.triggering_event = None
        elif event.modifiers() & Qt.ControlModifier:
            self.ctrlClicked.emit(self.indexAt(event.pos()))

class InputField(QtWidgets.QWidget):
    label_width = 160
    margin = 10
    valueChanged = QtCore.Signal(hou.Parm, str)
    editingFinished = QtCore.Signal()

    @staticmethod
    def format(text, filter):
        if not filter: return text
        result = ""
        alignment = AutoCompleteModel.align(text.upper(), filter)
        current = alignment.pop()
        for i, char in enumerate(text):
            if i == current[0]:
                result += "<b>{}</b>".format(char)
                current = alignment.pop() if alignment else (None,None)
            else:
                result += char
        return result

    def __init__(self, parent, index, filter, highlight=False):
        super(InputField, self).__init__(parent)

        autocompletes = index.data(AutoCompleteRole)
        which_match = index.data(WhichMatchRole)
        parm_tuple = index.data(ParmTupleRole)
        whats_this = index.data(Qt.WhatsThisRole)
        icon = index.data(Qt.DecorationRole)
        self.parm_tuple = parm_tuple

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(InputField.margin, 0, InputField.margin, 0)
        self.setLayout(layout)

        if icon:
            icon_size = hou.ui.scaledSize(64)
            pixmap = icon.pixmap(QtCore.QSize(icon_size, icon_size))
            label = QtWidgets.QLabel(self)
            label.setPixmap(pixmap)
            layout.addWidget(label)

        label = QtWidgets.QLabel(InputField.format(autocompletes[0], filter if which_match == 0 else None))
        label.setFixedWidth(InputField.label_width)
        layout.addWidget(label)

        self.line_edits = []
        if whats_this:
            label = QtWidgets.QLabel(whats_this)
            label.setFixedWidth(HCommanderWindow.width - InputField.label_width - InputField.margin)
            layout.addWidget(label)
        elif parm_tuple:
            for i, parm in enumerate(parm_tuple):
                edit_layout = QtWidgets.QVBoxLayout()
                edit_layout.setContentsMargins(0,InputField.margin,0,0)
                edit_layout.setSpacing(0)
                line_edit = QtWidgets.QLineEdit(self)
                border = "yellow" if highlight and which_match and i == which_match - 1 else "black"
                line_edit.setStyleSheet("QLineEdit { border: 1px solid " + border + "; background-color:" + hou.qt.getColor("PaneEmptyBG").name() + " }")
                line_edit.setText(str(parm_tuple[i].eval()))
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
        else:
            spacer = QtWidgets.QSpacerItem(1,1, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            layout.addStretch()

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
                    bitset |= 1 << o - 48 # inlude 0-9 ... A-Z
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
            selector_bitset, selector_text = self._filter

            # first check for exact matches
            autocompletes = index.data(AutoCompleteRole)
            for i, text in enumerate(autocompletes):
                if text.upper() == selector_text: return i

            bitsets = self._bitsetss[self.mapToSource(index).row()]

            # check every character is present in any of the labels or names ...
            for i, bitset in enumerate(bitsets):
                if bitset & selector_bitset == selector_bitset:
                    return i
            return None
        else:
            return super(AutoCompleteModel, self).data(index, role)

    def filter(self, text):
        selector_bitset = 0
        text = text.upper()
        for char in text:
            o = ord(char)
            if o < 48: continue
            selector_bitset |= 1 << o - 48

        if selector_bitset == 0: return
        self._filter = (selector_bitset, text)
        self.beginResetModel()
        self.endResetModel()
    
    def index_of(self, item):
        source_index = self.sourceModel().index_of(item)
        return self.mapFromSource(source_index)
    
    def lessThan(self, left, right):
        lkey, rkey = left.data(SortKeyRole), right.data(SortKeyRole)
        if lkey < rkey: return True
        if rkey < lkey: return False

        if not self._filter: return False
        _, selector_text = self._filter

        lautocompletes = left.data(AutoCompleteRole)
        rautocompletes = right.data(AutoCompleteRole)

        align = lambda x: AutoCompleteModel.align(x.upper(), selector_text)
        lalignments, ralignments = map(align, lautocompletes), map(align, rautocompletes)
        score = lambda x: x[0][1]
        lmax, rmax = max(lalignments, key=score), max(ralignments, key=score)

        return score(lmax) > score(rmax)

    @staticmethod
    def align(text, selector):
        """ A largest-common-substring algorithm with tweaks to prefer characters at the beginning of words (vmerge->VolumeMERGE note VoluMEmeRGE)"""
        m = len(text); n = len(selector)
        table = [[(-1,-1) for k in range(m+1)] for l in range(n+1)] 
        for j in range(1, n+1): 
            prevmax = -1; iprevmax = 0
            for i in range(1, m+1):
                k, prev = table[j-1][i-1]
                if prev > prevmax: prevmax = prev; iprevmax = i-1
                if text[i-1] == selector[j-1]:
                    if   i == 1:              incr = 3 # beginning of string e.g., V,Volume merge
                    elif text[i-2] == ' ':    incr = 2 # beginning of word         M,volume Merge
                    else:                     incr = 0
                    contig = 2 if k == i-2 else 1      # len of contiguous match   POL,"POLyBevel old" vs "Polybevel OLd"
                    # pick the path that gives the highest score to here:
                    table[j][i] = (i-1, prev+incr+contig) if prev+incr+contig > prevmax+incr else (iprevmax, prevmax+incr)

        # find the max score reaching the end
        prev = 0; max = -1; pos = -1
        for i in range(1, m+1):
            prev_, score = table[n][i]
            if score > max:
                max = score
                prev = prev_
                pos = i
        
        # walk the path back to the beginning
        result = [(pos-1, max)]
        for i in range(n-1, 0, -1):
            pos = prev
            prev, max = table[i][prev]
            result.append((pos-1, max))
        return result

class ParmTupleModel(QtCore.QAbstractListModel):
    history = set()

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
    def _filter(parmTuples):
        valid_types = { parmTemplateType.Int, parmTemplateType.Float, parmTemplateType.String, parmTemplateType.Toggle }
        parmTuples = list(pt for pt in parmTuples if pt.parmTemplate().type() in valid_types and not pt.isHidden() and not pt.isDisabled())
        return parmTuples

    def __init__(self, parm_tuples, parent=None):
        super(ParmTupleModel, self).__init__(parent)
        self.parm_tuples = parm_tuples

    def rowCount(self, parentindex=None):
        return len(self.parm_tuples)
    
    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled

    def data(self, index, role):
        if not index.isValid(): return None
        if not 0 <= index.row() < len(self.parm_tuples): return None

        parm_tuple = self.parm_tuples[index.row()]
        type = parm_tuple.parmTemplate().type()

        if role == ParmTupleRole:
            return parm_tuple 
        elif role == AutoCompleteRole:
            return [parm_tuple.parmTemplate().label()] + map(lambda x: x.name(), parm_tuple)
        elif role == Qt.BackgroundRole:
            if parm_tuple.isAtDefault():
                return QtGui.QBrush(hou.qt.getColor("ListBG"))
        elif role == Qt.DecorationRole:
            ParmTupleModel.type2icon(parm_tuple.parmTemplate().type())
        elif role == CallbackRole:
            return self.callback
        elif role == SortKeyRole:
            if not parm_tuple.isAtDefault(): return 0
            if ParmTupleModel.isrecorded(parm_tuple): return 1
            else: return 2

        return None
    
    def append(self, parm_tuple):
        self.beginInsertRows(QtCore.QModelIndex(), len(self.parm_tuples) - 1, len(self.parm_tuples))
        self.parm_tuples.append(weakref.proxy(parm_tuple, self.remove))
        self.endInsertRows()
    
    def remove(self, parm_tuple):
        i = self.parm_tuples.index(parm_tuple)
        self.beginRemoveRows(QtCore.QModelIndex(), i, i+1)
        self.parm_tuples.remove(parm_tuple)
        self.endRemoveRows()

    def index_of(self, item):
        i = self.parm_tuples.index(item)
        return self.index(i, 0)

    def callback(self, index, hcommander, list):
        parm_tuple = index.data(ParmTupleRole)
        type = parm_tuple.parmTemplate().type()
        if type == parmTemplateType.Toggle:
            parm_tuple.set([int(not parm_tuple.eval()[0])])
        else:
            list.edit(index)

    @staticmethod
    def record(parm_tuple):
        ParmTupleModel.history.add((parm_tuple.node().type(), parm_tuple.parmTemplate()))

    @staticmethod
    def isrecorded(parm_tuple):
        return (parm_tuple.node().type(), parm_tuple.parmTemplate()) in ParmTupleModel.history

class ActionModel(QtCore.QAbstractListModel):
    def __init__(self, actions, parent=None):
        super(ActionModel, self).__init__(parent)
        self._actions = actions

    def rowCount(self, parentindex=None):
        return len(self._actions)
    
    def data(self, index, role):
        action = self._actions[index.row()]

        if   role == ActionRole:       return action
        elif role == AutoCompleteRole: return (action.label, action.name)
        elif role == Qt.WhatsThisRole: return action.description
        elif role == SortKeyRole:      return 100
        elif role == CallbackRole:     return self.callback

        return None

    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    def index_of(self, item):
        return None
    
    def callback(self, index, hcommander, list):
        action = index.data(ActionRole)
        with hou.undos.group("Invoke custom user function"):
            try: exec(action.fn, {}, {'hou': hou})
            except Exception as e:
                print(e)
                print(self.fn)

class NodeTypeModel(QtCore.QAbstractListModel):
    app = houdinihelp.server.get_houdini_app()
    type2tooltip = {}
    history = weakref.WeakSet()

    @staticmethod
    def filter(node_types):
        visible = list(nt for nt in node_types.values()
            if not nt.hidden() and not nt.deprecated())
        return visible

    def __init__(self, node_types, parent=None):
        super(NodeTypeModel, self).__init__(parent)
        self._node_types = NodeTypeModel.filter(node_types)

    def rowCount(self, parentindex=None):
        return len(self._node_types)
    
    def data(self, index, role):
        node_type = self._node_types[index.row()]
    
        if role == AutoCompleteRole:
            return [node_type.description()]
        elif role == Qt.WhatsThisRole:
            if node_type in NodeTypeModel.type2tooltip: return NodeTypeModel.type2tooltip[node_type]
            # FIXME load from a file since it's too slow!
            with NodeTypeModel.app.app_context():
                url = houdinihelp.api.urlToPath(node_type.defaultHelpUrl())
                tooltip = houdinihelp.api.getTooltip(url)
                NodeTypeModel.type2tooltip[node_type] = tooltip
            return NodeTypeModel.type2tooltip[node_type]
        elif role == Qt.DecorationRole:
            try: return hou.qt.Icon(node_type.icon())
            except: pass
        elif role == CallbackRole:
            return self.callback
        elif role == NodeTypeRole:
            return node_type
        elif role == SortKeyRole:
            return 0 if node_type in NodeTypeModel.history else 1

        return None

    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    def index_of(self, item):
        return None

    def callback(self, index, hcommander, list):
        with hou.undos.group("Create Node"):
            path = hcommander.editor.pwd().path()
            node_type = index.data(NodeTypeRole)
            new_node = hou.node(path).createNode(node_type.name())

            selected = hou.selectedNodes()
            if selected:
                ninputs = new_node.type().maxNumInputs()
                if ninputs > 1:
                    selected = sorted(selected, key=lambda n: n.position().x())

                index = 0
                for i in range(len(selected)):
                    if selected[i].type().maxNumOutputs() > 0 and index < ninputs:
                        new_node.setInput(index, selected[i])
                        index += 1

            new_node.moveToGoodPosition(move_inputs=False)
            new_node.setSelected(True, clear_all_selected=True)
            new_node.setDisplayFlag(True)
            if hasattr(new_node, "setRenderFlag"): new_node.setRenderFlag(True)

            NodeTypeModel.history.add(node_type)
            hcommander.close()

class CompositeModel(QtCore.QAbstractListModel):
    def __init__(self, models, parent=None):
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
    
    def index_of(self, item):
        offset = 0
        for model in self._models:
            index = model.index_of(item)
            if index: return self.index(index.row(), 0)
            offset += model.rowCount()
        return None
    
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
        Action._actions = defaultdict(lambda: defaultdict(list))
        with open(Action.configfile) as f:
            reader = csv.DictReader(f)
            for row in reader:
                klass = eval(row["Class"], {'hou': hou})
                action = Action(row["Label"], row["Name"], row["Description"], row["fn"])
                Action._actions[klass][row["Selection"]].append(action)

    @staticmethod
    def find(obj):
        selector = obj.type().name()
        ancestors = inspect.getmro(obj.__class__)
        result = []
        for ancestor in ancestors:
            if not ancestor in Action._actions: continue
            actions_for_class = Action._actions[ancestor]
            result += actions_for_class[""]
            result += actions_for_class[selector]
        return result

    def __init__(self, label, name, description, fn):
        self.label = label
        self.name = name
        self.description = description
        self.fn = fn

Action.load()

__fs_watcher = QtCore.QFileSystemWatcher()
__fs_watcher.addPath(Action.configfile)
__fs_watcher.fileChanged.connect(Action.load)

hou.session._hcommander_saved = ParmTupleModel([])

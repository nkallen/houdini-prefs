# FIXME set the text at the bottom of the screen with instructions

import hou, sys
from canvaseventtypes import MouseEvent
import nodegraphbase as base
import nodegraphautoscroll as autoscroll
import nodegraphutils as utils
import nodegraphview as view
from canvaseventtypes import KeyboardEvent

this = sys.modules[__name__]

"""
This nodegraphhook is a keyboard based cursor and selection tool. Arrow keys move a cursor around the
grid, shift+arrow keys selects using something like the box select tool. Alt-shift-select is an
experimental feature that moves the entire selection box around. Finally, if you hold ctrl, the
cursor will move by 10 units rather than 1.
"""

class Cursor(object):
    def __init__(self, position=hou.Vector2(0,0)):
        self.position = position
        self.half_extent = hou.Vector2(-0.25,-0.25)

    def move(self, dx=0, dy=0):
        self.position += hou.Vector2(dx, dy)

    def select(self, uievent):
        pos1 = self.position + self.half_extent
        pos2 = self.position - self.half_extent
        pos1 = uievent.editor.posToScreen(pos1)
        pos2 = uievent.editor.posToScreen(pos2)

        items = uievent.editor.networkItemsInBox(pos1,pos2,for_select=True)
        items = BoxPickHandler.getItemsInBox(items)
        uievent.editor.setPreSelectedItems(())
        view.modifySelection(uievent, None, items)

this.cursor = Cursor()

def createEventHandler(uievent, pending_actions):
    if isinstance(uievent, MouseEvent) and uievent.eventtype == 'mousedown' and uievent.mousestate.lmb:
        pos = uievent.editor.posFromScreen(uievent.mousestartpos)
        this.cursor.position = hou.Vector2(round(pos.x()), round(pos.y()))
        return None, False

    if not (isinstance(uievent, KeyboardEvent) and uievent.eventtype == 'keyhit'): return None, False
    if uievent.modifierstate.alt: return None, False
    dx, dy = _interpret(uievent)
    if dx == 0 and dy == 0: return None, False

    if uievent.modifierstate.shift:
        return BoxPickHandler(uievent, this.cursor), True

    this.cursor.move(dx=dx, dy=dy)
    this.cursor.select(uievent)

    return None, True

def _interpret(uievent):
    dx = dy = 0
    if isinstance(uievent, KeyboardEvent) and uievent.eventtype == 'keyhit':
        key = uievent.key
        if key.endswith('UpArrow'):
            dy = 1
        elif key.endswith('DownArrow'):
            dy = -1
        elif key.endswith('LeftArrow'):
            dx = -1
        elif key.endswith('RightArrow'):
            dx = 1

    if uievent.modifierstate.ctrl:
        dx *= 10
        dy *= 10

    return dx, dy

class BoxPickHandler(base.EventHandler):
    @staticmethod
    def getItemsInBox(items):
        items = list(item[0] for item in items)
        # If we have any non-wires in the box, ignore the wires.
        has_non_wire = any((not isinstance(item, hou.NodeConnection)
                            for item in items))
        if has_non_wire:
            items = list(item for item in items
                         if not isinstance(item, hou.NodeConnection))
            # Select box picked nodes in visual order.
            if utils.isNetworkHorizontal(items[0].parent()):
                items.sort(key = lambda item : -item.position().y())
            else:
                items.sort(key = lambda item : item.position().x())

        return items
        
    def __init__(self, uievent, cursor):
        super(BoxPickHandler, self).__init__(uievent)
        self._cursor = cursor
        self._drag_cursor = Cursor(cursor.position)

    def handleEvent(self, uievent, pending_actions):
        if not isinstance(uievent, KeyboardEvent) and not isinstance(uievent, MouseEvent):
            return None

        if not uievent.modifierstate.shift:
            self.handleBoxPickComplete(uievent)
            return None

        dx, dy = _interpret(uievent)
        if uievent.modifierstate.alt:
            self._cursor.move(dx=dx, dy=dy)
            self._drag_cursor.move(dx=dx, dy=dy)
            self._redraw(uievent, pending_actions)
            return self

        self._drag_cursor.move(dx=dx, dy=dy)
        self._redraw(uievent, pending_actions)
        return self

    def _redraw(self, uievent, pending_actions):
        autoscroll.startAutoScroll(self, uievent, [self]) # FIXME doesn't work

        pos1 = uievent.editor.posToScreen(self._cursor.position)
        pos2 = uievent.editor.posToScreen(self._drag_cursor.position)
        rect = hou.BoundingRect(pos1, pos2)
        pickbox = hou.NetworkShapeBox(rect,
                        hou.ui.colorFromName('GraphPickFill'), alpha=0.3,
                        fill=True, screen_space=True)
        pickboxborder = hou.NetworkShapeBox(rect,
                        hou.ui.colorFromName('GraphPickFill'), alpha=0.8,
                        fill=False, screen_space=True)
        self.editor_updates.setOverlayShapes([pickbox, pickboxborder])
        items = uievent.editor.networkItemsInBox(pos1,pos2,for_select=True)
        items = BoxPickHandler.getItemsInBox(items)
        uievent.editor.setPreSelectedItems(items)

    def handleBoxPickComplete(self, uievent):
        pos1 = uievent.editor.posToScreen(self._cursor.position)
        pos2 = uievent.editor.posToScreen(self._drag_cursor.position)
        items = uievent.editor.networkItemsInBox(pos1,pos2,for_select=True)
        items = BoxPickHandler.getItemsInBox(items)
        uievent.editor.setPreSelectedItems(())
        view.modifySelection(uievent, None, items)

"""
The cursor is visualized with a little box. To keep it on the screen we need to hack into the 
EditorUpdates class, or it will get cleared after every event.
"""
if not hasattr(this, '_OriginalEditorUpdates'):
    _OriginalEditorUpdates = utils.EditorUpdates

class EditorUpdates(_OriginalEditorUpdates):
    def applyToEditor(self, editor):
        rect = hou.BoundingRect(
            this.cursor.position + this.cursor.half_extent,
            this.cursor.position - this.cursor.half_extent)
        pickbox = hou.NetworkShapeBox(rect,
                hou.ui.colorFromName('GraphPickFill'), alpha=0.3,
                fill=True, screen_space=False)
        self.shapes.append(pickbox)
        super(EditorUpdates, self).applyToEditor(editor)

# I know this is a crime against humanity. I'm sorry.
utils.EditorUpdates = this.EditorUpdates
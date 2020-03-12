import hou, os, sys
from PySide2 import QtCore
from canvaseventtypes import KeyboardEvent
import utility_hotkey_system, hcommander

this = sys.modules[__name__]

__userdir = hou.getenv('HOUDINI_USER_PREF_DIR')
__pythonlibs = os.path.join(__userdir, "python2.7libs")

def __reload_pythonlibs():
    print "Reloading libraries..."
    reload(this)
    reload(utility_hotkey_system)
    reload(hcommander)

fs_watcher = QtCore.QFileSystemWatcher()
fs_watcher.addPath(os.path.join(__pythonlibs, "nodegraphhooks.py"))
fs_watcher.addPath(os.path.join(__pythonlibs, "utility_hotkey_system.py"))
fs_watcher.addPath(os.path.join(__pythonlibs, "hcommander.py"))
fs_watcher.fileChanged.connect(__reload_pythonlibs)


def createEventHandler(uievent, pending_actions):
    handler, handled = BoxPickHandler(uievent).shouldHandleEvent(uievent, pending_actions)
    if handler or handled:
        return handler, handled

    handler, handled = hcommander.handleEvent(uievent)
    if handler or handled:
        return handler, handled

    if isinstance(uievent, KeyboardEvent):
        return utility_hotkey_system.invoke_action_from_key(uievent)

    return None, False

# TODO: clean code
# make ctrl work to "leap" (both in the volatile and non volatile states)
# make shift alt to drag including all ancestors
# when laying out, make the last nodes align to grid
# mouse click moves cursor

from canvaseventtypes import MouseEvent
import nodegraphbase as base
import nodegraphstates as states
import nodegraphautoscroll as autoscroll
import nodegraphutils as utils
import nodegraphview as view

this.cursor_position = hou.Vector2(0,0)
class BoxPickHandler(base.EventHandler):
    def __init__(self, uievent):
        super(BoxPickHandler, self).__init__(uievent)
        self.drag_cursor_position = this.cursor_position

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
    
    def _interpret(self, uievent):
        dx = dy = 0
        print uievent

    def shouldHandleEvent(self, uievent, pending_actions):
        if isinstance(uievent, KeyboardEvent) and uievent.eventtype == 'keyhit':
            self._interpret(uievent)
            key = uievent.key
            dx = dy = 0
            if key == 'UpArrow':
                dy = 1
            elif key == 'DownArrow':
                dy = -1
            elif key == 'LeftArrow':
                dx = -1
            elif key == 'RightArrow':
                dx = 1
            if dx != 0 or dy != 0:
                self.move_cursor(dx=dx, dy=dy)
                return None, True

            if key == 'Shift+UpArrow':
                dy = 1
            elif key == 'Shift+DownArrow':
                dy = -1
            elif key == 'Shift+LeftArrow':
                dx = -1
            elif key == 'Shift+RightArrow':
                dx = 1

            if dx != 0 or dy != 0:
                self.move_drag_cursor(uievent, pending_actions, dy=1)
                return self, True

        return None, False

    def handleEvent(self, uievent, pending_actions):
        print uievent

        if isinstance(uievent, KeyboardEvent) and uievent.eventtype == 'keyhit':
            key = uievent.key
            dx = dy = 0
            if key == 'UpArrow':
                dy = 1
            elif key == 'DownArrow':
                dy = -1
            elif key == 'LeftArrow':
                dx = -1
            elif key == 'RightArrow':
                dx = 1
            if dx != 0 or dy != 0:
                self.move_cursor(dx=dx, dy=dy)
                return None

            if key == 'Shift+UpArrow':
                dy = 1
            elif key == 'Shift+DownArrow':
                dy = -1
            elif key == 'Shift+LeftArrow':
                dx = -1
            elif key == 'Shift+RightArrow':
                dx = 1

            if dx != 0 or dy != 0:
                self.move_drag_cursor(uievent, pending_actions, dx=dx, dy=dy)
                return self

            if key == 'Alt+Shift+UpArrow':
                dy = 1
            elif key == 'Alt+Shift+DownArrow':
                dy = -1
            elif key == 'Alt+Shift+LeftArrow':
                dx = -1
            elif key == 'Alt+Shift+RightArrow':
                dx = 1

            if dx != 0 or dy != 0:
                self.move_cursor(dx=dx, dy=dy)
                self.move_drag_cursor(uievent, pending_actions, dx=dx, dy=dy)
                return self

        if isinstance(uievent, KeyboardEvent) or isinstance(uievent, MouseEvent):
            if uievent.modifierstate.shift:
                return self

            else:
                self.handleBoxPickComplete(uievent)
        return None

    def handleBoxPickComplete(self, uievent):
        pos1 = uievent.editor.posToScreen(this.cursor_position)
        pos2 = uievent.editor.posToScreen(self.drag_cursor_position)
        items = uievent.editor.networkItemsInBox(pos1,pos2,for_select=True)
        items = BoxPickHandler.getItemsInBox(items)
        uievent.editor.setPreSelectedItems(())
        view.modifySelection(uievent, None, items)

    def move_cursor(self, dx=0, dy=0):
        this.cursor_position += hou.Vector2(dx, dy)

    def move_drag_cursor(self, uievent, pending_actions, dx=0, dy=0):
        self.drag_cursor_position += hou.Vector2(dx, dy)

        # FIXME check if works
        autoscroll.startAutoScroll(self, uievent, [this])

        pos1 = uievent.editor.posToScreen(this.cursor_position)
        pos2 = uievent.editor.posToScreen(self.drag_cursor_position)
        rect = hou.BoundingRect(pos1, pos2)
        pickbox = hou.NetworkShapeBox(rect,
                        hou.ui.colorFromName('GraphPickFill'), alpha=0.3,
                        fill=True, screen_space=True)
        pickboxborder = hou.NetworkShapeBox(rect,
                        hou.ui.colorFromName('GraphPickFill'), alpha=0.8,
                        fill=False, screen_space=True)
        self.editor_updates.setShapes([pickbox, pickboxborder])
        # uievent.editor.setShapes([pickbox])
        items = uievent.editor.networkItemsInBox(pos1,pos2,for_select=True)
        items = BoxPickHandler.getItemsInBox(items)
        uievent.editor.setPreSelectedItems(items)

import nodegraphutils

if not hasattr(this, 'foo'):
    foo = nodegraphutils.EditorUpdates

class EditorUpdates(foo):
    def clear(self):
        super(EditorUpdates, self).clear()
        rect = hou.BoundingRect(
            this.cursor_position + hou.Vector2(-0.5,-0.5),
            this.cursor_position + hou.Vector2(0.5,0.5))
        pickbox = hou.NetworkShapeBox(rect,
                hou.ui.colorFromName('GraphPickFill'), alpha=0.3,
                fill=True, screen_space=False)
        self.shapes = [pickbox]


# I know this is a crime against humanity. I'm sorry.
nodegraphutils.EditorUpdates = this.EditorUpdates
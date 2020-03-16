import hou, os, sys
from PySide2 import QtCore
from canvaseventtypes import KeyboardEvent, MouseEvent
import utility_hotkey_system, hcommander, hviz, hcursor

this = sys.modules[__name__]

__userdir = hou.getenv('HOUDINI_USER_PREF_DIR')
__pythonlibs = os.path.join(__userdir, "python2.7libs")

def __reload_pythonlibs():
    print "Reloading libraries..."
    reload(this)
    reload(utility_hotkey_system)
    reload(hcommander)
    reload(hcursor)
    reload(hviz)

fs_watcher = QtCore.QFileSystemWatcher()
fs_watcher.addPath(os.path.join(__pythonlibs, "nodegraphhooks.py"))
fs_watcher.addPath(os.path.join(__pythonlibs, "utility_hotkey_system.py"))
fs_watcher.addPath(os.path.join(__pythonlibs, "hcommander.py"))
fs_watcher.addPath(os.path.join(__pythonlibs, "hcursor.py"))
fs_watcher.addPath(os.path.join(__pythonlibs, "hviz.py"))
fs_watcher.fileChanged.connect(__reload_pythonlibs)

def createEventHandler(uievent, pending_actions):
    handler, handled = hviz.createEventHandler(uievent, pending_actions)
    if handler or handled: return handler, handled

    handler, handled = hcursor.createEventHandler(uievent, pending_actions)
    if handler or handled: return handler, handled

    handler, handled = hcommander.handleEvent(uievent)
    if handler or handled: return handler, handled

    # FIXME refactor to support above interface
    if isinstance(uievent, KeyboardEvent):
        return utility_hotkey_system.invoke_action_from_key(uievent)

    # ditto
    if isinstance(uievent, MouseEvent):
        if uievent.eventtype == 'mousedown' and uievent.modifierstate.alt:
            utility_hotkey_system.move_selection_to_mouse(uievent, include_ancestors=uievent.modifierstate.shift)
            return None, True

    return None, False

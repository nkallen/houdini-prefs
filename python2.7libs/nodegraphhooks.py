import hou, os, sys
from PySide2 import QtCore
from canvaseventtypes import KeyboardEvent
import utility_hotkey_system, hcommander

import traceback

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
    handler, handled = hcommander.handleEvent(uievent)
    if handled:
        return handler, handled

    if isinstance(uievent, KeyboardEvent):
        return utility_hotkey_system.invoke_action_from_key(uievent)

    return None, False

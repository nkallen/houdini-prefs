import os, sys
import hdefereval
from utility_ui import hideObsoleteOperators

userdir = hou.getenv('HOUDINI_USER_PREF_DIR')

hdefereval.execute_deferred(hideObsoleteOperators)

overlay_network_editor_file = os.path.join(userdir, "scripts", "initialize_overlay_network_editor.py")
hou.session.isOverlayNetworkEditorInstalled = os.path.exists(overlay_network_editor_file)
if (hou.session.isOverlayNetworkEditorInstalled):
    execfile(overlay_network_editor_file)
    # hdefereval.execute_deferred(initializeOverlayNetworkEditor)
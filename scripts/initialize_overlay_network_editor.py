import hou, hdefereval
from PySide2 import QtCore, QtGui
from utility_ui import findFloatingPanelByName, getWidgetByName, getViewportRenderViewPosSize

overlayNetworkEditorOpacity = 0.75
networkEditorTopMaskHeight = 47

def initializeOverlayNetworkEditor():
    name = "animatrix_overlay_network_editor"
    editor = findFloatingPanelByName(name)

    if not editor:
        desktop = hou.ui.curDesktop()
        panel = desktop.createFloatingPanel(hou.paneTabType.NetworkEditor)
        panel.setName(name)
        panel.setSize((500,500))

    editor = panel.paneTabs()[0]
    editor.setPin(False)
    editor.setShowNetworkControls(False)
    editor.setPref('gridxstep', '1')
    editor.setPref('gridystep', '1')
    editor.setPref('showmenu', '0')
    editor.pane().setShowPaneTabs(False)

    hdefereval.execute_deferred(initializeOverlayNetworkEditorDeferred)

def initializeOverlayNetworkEditorDeferred():
    name = "animatrix_overlay_network_editor"
    network_editor = getWidgetByName(name)

    # FIXME we have to keep a reference to the window because it seems to switch during startup
    hou.session.mainQtWindow = hou.qt.mainWindow()

    network_editor.setParent(hou.qt.mainWindow(), QtCore.Qt.Tool)
    network_editor.setWindowFlags(network_editor.windowFlags() | QtCore.Qt.FramelessWindowHint | QtCore.Qt.X11BypassWindowManagerHint)
    network_editor.setWindowOpacity(overlaynetwork_editorOpacity)

    network_editor.show()

    pos, size = getViewportRenderViewPosSize()

    network_editor.move(pos.x(), pos.y() - network_editorTopMaskHeight - 16)
    network_editor.resize(size.width(), size.height() + network_editorTopMaskHeight)
    network_editor.setMask(QtGui.QRegion(0, network_editorTopMaskHeight, size.width(), size.height()))

    return network_editor

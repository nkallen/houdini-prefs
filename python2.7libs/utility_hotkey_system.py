import hou, nodegraph, os, csv, sys
import hdefereval
import types
import ctypes
from PySide2 import QtCore, QtWidgets, QtGui
from utility_ui import *
from canvaseventtypes import *
from collections import defaultdict
from nodegraphpopupmenus import MenuProvider

this = sys.modules[__name__]

__userdir = hou.getenv('HOUDINI_USER_PREF_DIR')
__hotkeysfile = os.path.join(__userdir, "hotkeys.csv")

__actions = None
def __load_actions():
    print "Reloading hotkeys..."
    global __actions
    __actions = defaultdict(lambda: defaultdict(list))
    with open(__hotkeysfile) as f:
        reader = csv.DictReader(f)
        for row in reader:
            for context in ("OBJECT", "SOP", "VOP", "DOP", "COP", "CHOP", "SHOP", "ROP", "TOP", "LOP"):
                if row[context] != '':
                    __actions[context][row["Key Name"]].append((row["Selection"], row[context]))
__load_actions()

# If this module is reloaded, destroy old fs_watcher so that there aren't multiple watchers.
if hasattr(this, 'fs_watcher'):
    this.fs_watcher.setParent(None)

this.fs_watcher = QtCore.QFileSystemWatcher()
this.fs_watcher.addPath(__hotkeysfile)
this.fs_watcher.fileChanged.connect(__load_actions)


def invoke_action_from_key(uievent):
    editor = uievent.editor

    context = editor.pwd().childTypeCategory().name()
    csv_context = context.upper()
    if csv_context in __actions and uievent.key in __actions[csv_context]:
        selectors = __actions[csv_context][uievent.key]
        if selectors:
            for selector in selectors:
                if selector_matches(selector[0]):
                    return None, execute_action_string(uievent, selector[1])

    return None, False


def selector_matches(selector):
    if selector == "":
        return True

    selected_nodes = hou.selectedNodes()
    if len(selected_nodes) == 0:
        return False
        
    if selector == '+':
        return True

    return selected_nodes[0].type().name() == selector

def execute_action_string(uievent, action):
    editor = uievent.editor
    opfunc = action[3:]

    if action.startswith('op:'):
        with hou.undos.group("Create new node"):
            createNewNode(editor, opfunc)
            return True
    elif action.startswith('fn:'):
        try:
            with hou.undos.group("Invoke custom user function"):
                exec(opfunc, {}, {'uievent': uievent, 'hou': hou})
            return True
        except Exception as e:
            print(e)
            print(opfunc)
    elif action.startswith('mn:'):
        menu = MenuProvider()
        try:
            menu.menuitems = eval(opfunc, {}, {'uievent': uievent, 'hou': hou, })
            get_popup_menu_result(menu, uievent)
            return True
        except Exception as e:
            print(e)
            print(opfunc)
    
    return False


def get_popup_menu_result(menu_provider, uievent):
    # If we have no menu items, don't pop up the menu. This action will
    # be completed on the next event.
    if len(menu_provider.menuitems) == 0:
        result = menu_provider.result
    else:
        menu = FixKeyPressBugMenu(hou.qt.mainWindow(), uievent)
        build_menu(menu, menu_provider.title, menu_provider.menuitems)
        result = menu.exec_(QtCore.QPoint(QtGui.QCursor.pos()))
        if result is not None:
           result = result.data()

    return result

# At least on mac, keyboard shortcuts for menus added to the main window
# simply do not work. This class intercepts keypresses to ensure they
# and handles them directly.
class FixKeyPressBugMenu(QtWidgets.QMenu):
    def __init__(self, parent, uievent):
        super(FixKeyPressBugMenu, self).__init__(parent)
        self.uievent = uievent


    def keyPressEvent(self, event):
        for action in self.actions():
            if action.shortcut()[0] == (event.key() | event.modifiers()):
                action.trigger()
                self.close()
                execute_action_string(self.uievent, action.data())
                return True

        super(FixKeyPressBugMenu, self).keyPressEvent(event)

def build_menu(menu, title, menuitems):
    menu.setStyleSheet(hou.ui.qtStyleSheet())

    if title:
        action = menu.addAction(title)
        action.setEnabled(False)
        menu.addSeparator()
    for item in menuitems:
        if item is None:
            menu.addSeparator()
        elif isinstance(item[1], basestring):
            action = menu.addAction(item[0])
            action.setText(item[0])
            action.setData(item[1])
            action.setShortcut(item[2])
            action.setEnabled(True)
        else:
            submenu = menu.addMenu(item[0])
            build_menu(submenu, None, item[1])

def findNodeByType(context, pattern):
    import fnmatch

    nodeTypeCategories = {}
    nodeTypeCategories['Object'] = hou.objNodeTypeCategory()
    nodeTypeCategories['Sop'] = hou.sopNodeTypeCategory()
    nodeTypeCategories['Vop'] = hou.vopNodeTypeCategory()
    nodeTypeCategories['Dop'] = hou.dopNodeTypeCategory()
    nodeTypeCategories['Cop2'] = hou.cop2NodeTypeCategory()
    nodeTypeCategories['Chop'] = hou.chopNodeTypeCategory()
    nodeTypeCategories['Shop'] = hou.shopNodeTypeCategory()
    nodeTypeCategories['Driver'] = hou.ropNodeTypeCategory()
    nodeTypeCategories['Top'] = hou.topNodeTypeCategory()
    nodeTypeCategories['Lop'] = hou.lopNodeTypeCategory()

    category = nodeTypeCategories[context]

    nodes = [nodetype
        for nodetypename, nodetype in category.nodeTypes().items()
        if fnmatch.fnmatch(nodetypename, pattern)]

    if nodes:
        return nodes[0]
    else:
        return None


def createNewNode(editor, nodetypename, parms=None):
    pwd = editor.pwd()
    path = pwd.path()
    context = pwd.childTypeCategory().name()
    pos = editor.cursorPosition()

    if not findNodeByType(context, nodetypename):
        return None

    newNode = hou.node(path).createNode(nodetypename)

    selNodes = hou.selectedNodes()
    nodecount = len(selNodes)
    if nodecount > 0:
        ninputs = newNode.type().maxNumInputs()
        if ninputs > 1:
            #sort nodes from left to right and connect by position
            selNodes = sorted(selNodes, key=lambda n: n.position().x())

        index = 0
        for i in range(nodecount):
            if selNodes[i].type().maxNumOutputs() > 0 and index < ninputs:
                newNode.setInput(index, selNodes[i])
                index += 1

    size = newNode.size()
    pos[0] -= size[0] / 2
    pos[1] -= size[1] / 2
    # newNode.setPosition(pos)
    newNode.moveToGoodPosition(move_inputs=False)
    newNode.setSelected(True, clear_all_selected=True)

    if nodecount != 0:
        if context != "Driver" and context != "Shop" and context != "Chop" and context != "Vop":
            newNode.setDisplayFlag(True)
        if context != "Object" and context != "Driver" and context != "Dop" and context != "Shop" and context != "Chop" and context != "Vop" and context != "Lop":
            newNode.setRenderFlag(True)

    if parms:
        if isinstance(parms, types.DictType):
            for i, (key, value) in enumerate(parms.items()):
                newNode.parm(key).set(value)
        elif isinstance(parms, types.StringTypes):
            hou.hscript("oppresetload " + newNode.path() + " '{0}'".format(parms))

    return newNode

# FIXME these belong in another file.
#####################################

def findNearestNode(editor):
    pos = editor.cursorPosition()
    currentPath = editor.pwd().path()

    nodes = hou.node(currentPath).children()
    nearestNode = None
    dist = 999999999.0
    for node in nodes:
        d = (node.position() + (node.size() * 0.5)).distanceTo(pos)
        if d < dist:
            nearestNode = node
            dist = d

    return nearestNode


def selectNearestNode(uievent):
    editor = uievent.editor
    nearestNode = findNearestNode(editor)
    if nearestNode:
        nearestNode.setSelected(True, clear_all_selected=True)


def displayNearestNode(uievent, context):
    editor = uievent.editor
    nearestNode = findNearestNode(editor)
    if nearestNode:
        if context != "Driver" and context != "Shop" and context != "Chop" and context != "Vop":
            nearestNode.setDisplayFlag(not nearestNode.isDisplayFlagSet())
        if context != "Object" and context != "Driver" and context != "Dop" and context != "Shop" and context != "Chop" and context != "Vop" and context != "Lop":
            nearestNode.setRenderFlag(not nearestNode.isRenderFlagSet())


def displaySelectNearestNode(uievent, context):
    editor = uievent.editor
    nearestNode = findNearestNode(editor)
    if nearestNode:
        nearestNode.setSelected(True, clear_all_selected=True)
        if context != "Driver" and context != "Shop" and context != "Chop" and context != "Vop":
            nearestNode.setDisplayFlag(not nearestNode.isDisplayFlagSet())
        if context != "Object" and context != "Driver" and context != "Dop" and context != "Shop" and context != "Chop" and context != "Vop" and context != "Lop":
            nearestNode.setRenderFlag(not nearestNode.isRenderFlagSet())



def templateNearestNode(uievent):
    editor = uievent.editor
    nearestNode = findNearestNode(editor)
    if nearestNode:
        nearestNode.setGenericFlag(hou.nodeFlag.Template, not nearestNode.isGenericFlagSet(hou.nodeFlag.Template))



def selectableTemplateNearestNode(uievent):
    editor = uievent.editor
    nearestNode = findNearestNode(editor)
    if nearestNode:
        nearestNode.setGenericFlag(hou.nodeFlag.Footprint, not nearestNode.isGenericFlagSet(hou.nodeFlag.Footprint))



def bypassNearestNode(uievent):
    editor = uievent.editor
    nearestNode = findNearestNode(editor)
    if nearestNode:
        nearestNode.setGenericFlag(hou.nodeFlag.Bypass, not nearestNode.isGenericFlagSet(hou.nodeFlag.Bypass))



def templateSelectedNodes():
    selNodes = hou.selectedNodes()
    for n in selNodes:
        n.setGenericFlag(hou.nodeFlag.Template, not n.isGenericFlagSet(hou.nodeFlag.Template))



def selectableTemplateSelectedNodes():
    selNodes = hou.selectedNodes()
    for n in selNodes:
        n.setGenericFlag(hou.nodeFlag.Footprint, not n.isGenericFlagSet(hou.nodeFlag.Footprint))



def bypassSelectedNodes(uievent):
    editor = uievent.editor
    selNodes = hou.selectedNodes()
    for n in selNodes:
        n.setGenericFlag(hou.nodeFlag.Bypass, not n.isGenericFlagSet(hou.nodeFlag.Bypass))



def objectMergeFromSelection(uievent):
    editor = uievent.editor
    pos = editor.cursorPosition()
    currentPath = editor.pwd().path()
    currentNode = hou.node(currentPath)
    selNodes = hou.selectedNodes()
    for n in selNodes:
        mergeNode = currentNode.createNode("object_merge")
        mergeNode.setName("IN_" + n.name(), unique_name=True)
        mergeNode.parm("objpath1").set("../" + n.name())

        if len(selNodes) > 1:
            mergeNode.moveToGoodPosition(move_unconnected=False)
        else:
            size = mergeNode.size ( )
            pos[0] -= size[0] / 2
            pos[1] -= size[1] / 2
            mergeNode.setPosition ( pos )



def toggleNetworkEditorGrid():
    networkEditor = hou.ui.paneTabUnderCursor()
    if networkEditor.type() == hou.paneTabType.NetworkEditor:
        networkEditor.setPref("gridmode", "2" if networkEditor.getPref("gridmode") != "2" else "0")



def jumpUpOneLevel():
    currentPaneTab = hou.ui.paneTabUnderCursor()
    if currentPaneTab:
        parent = currentPaneTab.pwd().parent()
        if parent:
            currentPaneTab.setPwd(parent)



def randomConstantColor(uievent):
    import random

    editor = uievent.editor
    newNode = createNewNode(editor, "color")
    if newNode:
        newNode.parm("colortype").set(0)
        colors = ((1,0,0), (0,1,0), (0,0,1), (1,0.35,0), (1,1,0), (0,1,1), (1,0,1), (0.45,0,1), (0.45,1,0), (0,0.45,1))
        newNode.parmTuple("color").set(random.choice(colors))

def pushNodes(inside=True):
    import toolutils
    pane = kwargs["pane"] 
    center = pane.cursorPosition() 
    nodes = pane.pwd().children() 

    for node in nodes:
        p = node.position() 
        n = (p - center).normalized()
        amount = -8.0 if inside else 8.0
        node.setPosition(p + n * amount)



def togglePointNumbers():
    import toolutils
    pt = None

    try:
        # cycle
        pts = hou.session.pt[:]
        pts = pts[1:]+pts[:1]
        pt = pts[0]
        hou.session.pt = pts
    except:
        # set up default vars
        hou.session.pt = ['on', 'off']
        pt = hou.session.pt[0]

    pts = { 'on':'on', 'off':'off'}
    hou.hscript("viewdispset -c %s on display *" % pts[pt].lower())



def togglePointMarkers():
    import toolutils
    pt = None

    try:
        # cycle
        pts = hou.session.ptm[:]
        pts = pts[1:]+pts[:1]
        pt = pts[0]
        hou.session.ptm = pts
    except:
        # set up default vars
        hou.session.ptm = ['on', 'off']
        pt = hou.session.ptm[0]

    pts = { 'on':'on', 'off':'off'}
    hou.hscript("viewdispset -m %s on display *" % pts[pt].lower())



def togglePointNormals():
    import toolutils
    pt = None

    try:
        # cycle
        pts = hou.session.ptn[:]
        pts = pts[1:]+pts[:1]
        pt = pts[0]
        hou.session.ptn = pts
    except:
        # set up default vars
        hou.session.ptn = ['on', 'off']
        pt = hou.session.ptn[0]

    pts = { 'on':'on', 'off':'off'}
    hou.hscript("viewdispset -n %s on display *" % pts[pt].lower())



def togglePrimitiveNormals():
    import toolutils
    pt = None

    try:
        # cycle
        pts = hou.session.prn[:]
        pts = pts[1:]+pts[:1]
        pt = pts[0]
        hou.session.prn = pts
    except:
        # set up default vars
        hou.session.prn = ['on', 'off']
        pt = hou.session.prn[0]

    pts = { 'on':'on', 'off':'off'}
    hou.hscript("viewdispset -N %s on display *" % pts[pt].lower())



def toggleHiddenLineShaded():
    hou.hscript("viewdisplay -M all hidden_invis VFX.FloatingPanel.world")



def createVolumeLights():
    editor = kwargs['pane']
    currentPath = editor.pwd ( ).path ( )
    pos = editor.cursorPosition ( ) 

    newNode = hou.node ( currentPath ).createNode ( "hlight" )
    size = newNode.size ( )
    pos [ 0 ] -= size [ 0 ] / 2
    pos [ 1 ] -= size [ 1 ] / 2
    newNode.setPosition ( pos )

    hou.hscript("oppresetload " + newNode.path() + " 'Volume Light 1'")

    newNode = hou.node ( currentPath ).createNode ( "hlight" )
    size = newNode.size ( )
    pos [ 0 ] -= size [ 0 ] / 2
    pos [ 1 ] -= size [ 1 ] / 2
    newNode.setPosition ( pos - size )

    hou.hscript("oppresetload " + newNode.path() + " 'Volume Light 2'")



def toggleUpdateMode():
    mode = hou.updateModeSetting()
    if mode != hou.updateMode.AutoUpdate:
        hou.setUpdateMode(hou.updateMode.AutoUpdate)
    else:
        hou.setUpdateMode(hou.updateMode.Manual)



def currentViewportFrameSelected():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        viewport.curViewport().frameSelected()
    


def currentViewportFrameAll():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        viewport.curViewport().frameAll()



def currentViewportSwitchToPerspective():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        view.changeType(hou.geometryViewportType.Perspective)



def currentViewportSwitchToTop():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        if view.type() == hou.geometryViewportType.Top:
            view.changeType(hou.geometryViewportType.Bottom)
        else:
            view.changeType(hou.geometryViewportType.Top)



def currentViewportSwitchToFront():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        if view.type() == hou.geometryViewportType.Front:
            view.changeType(hou.geometryViewportType.Back)
        else:
            view.changeType(hou.geometryViewportType.Front)



def currentViewportSwitchToRight():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        if view.type() == hou.geometryViewportType.Right:
            view.changeType(hou.geometryViewportType.Left)
        else:
            view.changeType(hou.geometryViewportType.Right)



def currentViewportSwitchToUV():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        view.changeType(hou.geometryViewportType.UV)



def currentViewportSetToWireframe():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        displaySet = view.settings().displaySet(hou.displaySetType.DisplayModel)
        displaySet.setShadedMode(hou.glShadingType.WireGhost)



def currentViewportSetToHiddenLineInvisible():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        displaySet = view.settings().displaySet(hou.displaySetType.DisplayModel)
        displaySet.setShadedMode(hou.glShadingType.HiddenLineInvisible)



def currentViewportSetToFlatShaded():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        displaySet = view.settings().displaySet(hou.displaySetType.DisplayModel)
        displaySet.setShadedMode(hou.glShadingType.Flat)



def currentViewportSetToFlatWireShaded():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        displaySet = view.settings().displaySet(hou.displaySetType.DisplayModel)
        displaySet.setShadedMode(hou.glShadingType.FlatWire)



def currentViewportSetToSmoothShaded():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        displaySet = view.settings().displaySet(hou.displaySetType.DisplayModel)
        displaySet.setShadedMode(hou.glShadingType.Smooth)



def currentViewportSetToSmoothWireShaded():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        displaySet = view.settings().displaySet(hou.displaySetType.DisplayModel)
        displaySet.setShadedMode(hou.glShadingType.SmoothWire)



def currentViewportToggleWireframe():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        displaySet = view.settings().displaySet(hou.displaySetType.DisplayModel)
        shadingMode = displaySet.shadedMode()

        if shadingMode != hou.glShadingType.WireGhost:
            setSessionVariable("lastViewportShadingMode", shadingMode)
            displaySet.setShadedMode(hou.glShadingType.WireGhost)
        else:
            displaySet.setShadedMode(getSessionVariable("lastViewportShadingMode"))



def currentViewportToggleHiddenLineInvisible():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        view = viewport.curViewport()
        displaySet = view.settings().displaySet(hou.displaySetType.DisplayModel)
        shadingMode = displaySet.shadedMode()

        if shadingMode != hou.glShadingType.HiddenLineInvisible:
            setSessionVariable("lastViewportShadingMode", shadingMode)
            displaySet.setShadedMode(hou.glShadingType.HiddenLineInvisible)
        else:
            displaySet.setShadedMode(getSessionVariable("lastViewportShadingMode"))



def currentViewportEnterViewState():
    desktop = hou.ui.curDesktop()
    viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewport.isCurrentTab():
        viewport.enterViewState()
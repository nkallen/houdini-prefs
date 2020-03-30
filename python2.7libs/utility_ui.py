import hou
import hdefereval
import types
import os
import math
import ctypes
import shiboken2
from PySide2 import QtCore, QtWidgets, QtGui
from canvaseventtypes import *

node_centroid = hou.Vector2(0.5, -0.15)
def snap_to_grid(item):
    position = item.position()
    item.setPosition(node_centroid + hou.Vector2(math.floor(position.x()), math.ceil(position.y())))


class WeakParmTupleList(object):
    def __init__(self):
        self._underlying = list()
        self._uniq = set()

    def append(self, parm_tuple):
        path = WeakParmTupleList.parm_tuple_path(parm_tuple)
        if not path in self._uniq:
            self._uniq.add(path)
            self._underlying.append(path)

    def items(self):
        result = list()
        underlying = []
        for path in self._underlying:
            try:
                result.append(hou.parmTuple(path))
                underlying.append(path)
            except hou.NotAvailable: pass
        self._underlying = underlying
        self._uniq = set(underlying)
        return result
    
    def __iter__(self):
        return self.items().__iter__()

    def __len__(self):
        return self.items().__len__()
    
    def __getitem__(self, index):
        return self.items().__getitem__(index)

    @staticmethod
    def parm_tuple_path(parm_tuple):
        return parm_tuple.node().path() + "/" + parm_tuple.name()


def modifierstate2modifiers(modifierstate):
    modifiers = 0
    if modifierstate.shift:
        modifiers |= Qt.ShiftModifier
    if modifierstate.ctrl:
        modifiers |= Qt.MetaModifier
    if modifierstate.alt:
        modifiers |= Qt.AltModifier
    return modifiers


def getWidgetByName(name):
    hasHandle = hasattr(hou.session, name)
    if not hasHandle or (hasHandle and getattr(hou.session, name) and not shiboken2.isValid(getattr(hou.session, name))):
        allWidgets = QtWidgets.QApplication.allWidgets()
        for w in allWidgets:
            if name in w.windowTitle():
                setattr(hou.session, name, w)
                break

    if not hasattr(hou.session, name):
        return None

    return getattr(hou.session, name)


def getViewportRenderViewPosSize():
    qtWindow = hou.qt.mainWindow()
    viewportWidgets = []
    for w in qtWindow.findChildren(QtWidgets.QWidget, "RE_Window"):
        if w.windowTitle() == "DM_ViewLayout":
            for w2 in w.findChildren(QtWidgets.QVBoxLayout):
                if w2.count() == 1:
                    w = w2.itemAt(0).widget()
                    if w.objectName() == 'RE_GLDrawable':
                        viewportWidgets.append(w)

    if viewportWidgets:
        pos = [w.pos() for w in viewportWidgets]
        size = [w.size() for w in viewportWidgets]

        return w.mapToGlobal(pos[-1]), size[-1]

    return QtCore.QPoint(0, 0), QtCore.QSize(400, 400)



def getSessionVariable(name):
    if hasattr(hou.session, name):
        return getattr(hou.session, name)
    else:
        return None



def setSessionVariable(name, value):
    return setattr(hou.session, name, value)



def findFloatingPanelByName(name):
    desktop = hou.ui.curDesktop()
    panels = desktop.floatingPanels()
    for p in panels:
        if p.name() == name:
            return p
            break

    return None



def togglePanel(paneTabName, paneTabType, splitFraction):
    desktop = hou.ui.curDesktop()
    paneTab = desktop.findPaneTab(paneTabName)
    if not paneTab:
        paneTab = desktop.paneTabOfType(paneTabType)

    if paneTab:
        pane = paneTab.pane()
        if pane:
            pane.setIsSplitMaximized(pane.isSplitMinimized())
            pane.setSplitFraction(splitFraction)



def resetViewportPosSize():
    name = "animatrix_viewport"
    viewport = getSessionVariable(name)
    if not viewport:
        desktop = hou.ui.curDesktop()
        viewport = desktop.findPaneTab(name)

    size = viewport.contentSize()
    pos = hou.qt.mainWindow().pos()

    setSessionVariable("viewportSize", size)
    setSessionVariable("applicationPos", pos)


def toggleSceneRenderView():
    desktop = hou.ui.curDesktop()
    viewport = desktop.findPaneTab("animatrix_viewport")
    if not viewport:
        viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)

    if viewport:
        pane = viewport.pane()
        if pane:
            if pane.isSplitMinimized():
                pane.setIsSplitMaximized(True)

            if not viewport.isCurrentTab():
                viewport.setIsCurrentTab()
            else:
                renderview = desktop.findPaneTab("animatrix_renderview")
                if not renderview:
                    renderview = desktop.paneTabOfType(hou.paneTabType.IPRViewer)

                if renderview:
                    renderview.setIsCurrentTab()



def toggleParameterEditorMaterialPalette():
    desktop = hou.ui.curDesktop()
    parameterEditor = desktop.findPaneTab("animatrix_parameter_editor")
    if not parameterEditor:
        parameterEditor = desktop.paneTabOfType(hou.paneTabType.Parm)

    if parameterEditor:
        pane = parameterEditor.pane()
        if pane:
            if pane.isSplitMinimized():
                pane.setIsSplitMaximized(True)

            if not parameterEditor.isCurrentTab():
                parameterEditor.setIsCurrentTab()
            else:
                materialPalette = desktop.findPaneTab("animatrix_material_palette")
                if not materialPalette:
                    materialPalette = desktop.paneTabOfType(hou.paneTabType.MaterialPalette)

                if materialPalette:
                    materialPalette.setIsCurrentTab()



def resetNetworkEditorZoomLevelFromCenter(editor):
    screenbounds = editor.screenBounds()
    # Figure out how much we need to scale the current bounds to get to
    # a zoom level of 100 pixels per network editor unit.
    bounds = editor.visibleBounds()
    currentzoom = editor.screenBounds().size().x() / bounds.size().x()
    desiredzoom = getSessionVariable("networkEditorDefaultZoomLevel")
    scale = currentzoom / desiredzoom

    zoomcenter = editor.posFromScreen(screenbounds.center())
    bounds.translate(-zoomcenter)
    bounds.scale((scale, scale))
    bounds.translate(zoomcenter)

    editor.setVisibleBounds(bounds)

    bounds = editor.visibleBounds()
    currentzoom = editor.screenBounds().size().x() / bounds.size().x()



def resetNetworkEditorZoomLevel(uievent):
    editor = uievent.editor
    screenbounds = editor.screenBounds()
    # Figure out how much we need to scale the current bounds to get to
    # a zoom level of 100 pixels per network editor unit.
    bounds = editor.visibleBounds()
    currentzoom = editor.screenBounds().size().x() / bounds.size().x()
    desiredzoom = getSessionVariable("networkEditorDefaultZoomLevel")
    scale = currentzoom / desiredzoom

    zoomcenter = editor.posFromScreen(uievent.mousepos)
    bounds.translate(-zoomcenter)
    bounds.scale((scale, scale))
    bounds.translate(zoomcenter)

    editor.setVisibleBounds(bounds)



def toggleNetworkEditor():
    desktop = hou.ui.curDesktop()
    networkEditor = desktop.findPaneTab("animatrix_network_editor")
    if not networkEditor:
        networkEditor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    if networkEditor:
        pane = networkEditor.pane()
        isMinimized = pane.isSplitMinimized()
        
        pane.setIsSplitMaximized(isMinimized)
        pane.setSplitFraction(0.5)



def hideObsoleteOperators():
    hou.hscript("ophide Object auto_rig_biped_arm")
    hou.hscript("ophide Object auto_rig_biped_hand_4f_2s")
    hou.hscript("ophide Object auto_rig_biped_hand_4f_3s")
    hou.hscript("ophide Object auto_rig_biped_hand_5f_3s")
    hou.hscript("ophide Object auto_rig_biped_head_and_neck")
    hou.hscript("ophide Object auto_rig_biped_leg")
    hou.hscript("ophide Object auto_rig_biped_spine_3pc")
    hou.hscript("ophide Object auto_rig_biped_spine_5pc")
    hou.hscript("ophide Object auto_rig_character_placer")
    hou.hscript("ophide Object auto_rig_quadruped_back_leg")
    hou.hscript("ophide Object auto_rig_quadruped_front_leg")
    hou.hscript("ophide Object auto_rig_quadruped_head_and_neck")
    hou.hscript("ophide Object auto_rig_quadruped_ik_spine")
    hou.hscript("ophide Object auto_rig_quadruped_tail")
    hou.hscript("ophide Object auto_rig_quadruped_toes_4f")
    hou.hscript("ophide Object auto_rig_quadruped_toes_5f")
    hou.hscript("ophide Object biped_auto_rig")
    hou.hscript("ophide Object fourpointmuscle")
    hou.hscript("ophide Object muscle")
    hou.hscript("ophide Object quadruped_auto_rig_4f")
    hou.hscript("ophide Object quadruped_auto_rig_5f")
    hou.hscript("ophide Object toon_character")
    hou.hscript("ophide Object threepointmuscle")
    hou.hscript("ophide Object twopointmuscle")
    hou.hscript("ophide Shop rsl_vopvolume")
    hou.hscript("ophide Shop rsl_vopsurfacetype")
    hou.hscript("ophide Shop rsl_vopstruct")
    hou.hscript("ophide Shop rsl_vopdisplacetype")
    hou.hscript("ophide Shop rsl_vopsurface")
    hou.hscript("ophide Shop rsl_voplight")
    hou.hscript("ophide Shop rsl_voplighttype")
    hou.hscript("ophide Shop rsl_vopshaderclass")
    hou.hscript("ophide Shop rsl_vopdisplace")
    hou.hscript("ophide Shop rsl_vopmaterial")
    hou.hscript("ophide Shop rsl_vopvolumetype")
    hou.hscript("ophide Shop rsl_vopimager")
    hou.hscript("ophide Object pxrspherelight")
    hou.hscript("ophide Object pxrgobolightfilter")
    hou.hscript("ophide Object pxraovlight")
    hou.hscript("ophide Object pxrintmultlightfilter")
    hou.hscript("ophide Object pxrstdarealight")
    hou.hscript("ophide Object pxrcookielightfilter")
    hou.hscript("ophide Object pxrportallight")
    hou.hscript("ophide Object pxrdisklight")
    hou.hscript("ophide Object pxrblockerlightfilter")
    hou.hscript("ophide Object pxrdistantlight")
    hou.hscript("ophide Object pxrrodlightfilter")
    hou.hscript("ophide Object pxrenvdaylight")
    hou.hscript("ophide Object pxrdomelight")
    hou.hscript("ophide Object pxrrectlight")
    hou.hscript("ophide Object pxrstdenvmaplight")
    hou.hscript("ophide Object pxrramplightfilter")
    hou.hscript("ophide Object pxrstdenvdaylight")
    hou.hscript("ophide Object pxrbarnlightfilter")
    hou.hscript("ophide Vop rsl_surfacecolor")
    hou.hscript("ophide Vop rsl_calculatenormal")
    hou.hscript("ophide Vop pxrmarschnerhair::2.0")
    hou.hscript("ophide Vop pxrlmmixer")
    hou.hscript("ophide Vop pxrfilmictonemappersamplefilter")
    hou.hscript("ophide Vop pxrintmultlightfilter")
    hou.hscript("ophide Vop pxrcolorcorrect")
    hou.hscript("ophide Vop pxrvisualizer")
    hou.hscript("ophide Vop pxrcookielightfilter")
    hou.hscript("ophide Vop pxrexposure")
    hou.hscript("ophide Vop rsl_environment")
    hou.hscript("ophide Vop pxrdisklight")
    hou.hscript("ophide Vop pxrdisplace")
    hou.hscript("ophide Vop pxrcopyaovdisplayfilter")
    hou.hscript("ophide Vop pxrmanifold3d")
    hou.hscript("ophide Vop pxrocclusion")
    hou.hscript("ophide Vop pxrenvdaylight")
    hou.hscript("ophide Vop pxrlmdiffuse")
    hou.hscript("ophide Vop pxrdisplayfiltercombiner")
    hou.hscript("ophide Vop pxrseexpr")
    hou.hscript("ophide Vop pxrthreshold")
    hou.hscript("ophide Vop pxrvolume")
    hou.hscript("ophide Vop pxrprojectionstack")
    hou.hscript("ophide Vop rsl_import")
    hou.hscript("ophide Vop rsl_log")
    hou.hscript("ophide Vop pxrvcm")
    hou.hscript("ophide Vop pxrgradedisplayfilter")
    hou.hscript("ophide Vop pxrstdarealight")
    hou.hscript("ophide Vop rsl_transform")
    hou.hscript("ophide Vop pxrtofloat")
    hou.hscript("ophide Vop pxrconstant")
    hou.hscript("ophide Vop pxrblackbody")
    hou.hscript("ophide Vop pxrmultitexture")
    hou.hscript("ophide Vop pxrlayer")
    hou.hscript("ophide Vop rsl_illuminate")
    hou.hscript("ophide Vop pxrtee")
    hou.hscript("ophide Vop pxrbakepointcloud")
    hou.hscript("ophide Vop pxrprimvar")
    hou.hscript("ophide Vop pxrfractalize")
    hou.hscript("ophide Vop pxrdisplacement")
    hou.hscript("ophide Vop rsl_indirectdiffuse")
    hou.hscript("ophide Vop pxrsurface")
    hou.hscript("ophide Vop pxrbarnlightfilter")
    hou.hscript("ophide Vop pxrworley")
    hou.hscript("ophide Vop pxrprojectionlayer")
    hou.hscript("ophide Vop pxrdot")
    hou.hscript("ophide Vop pxrdirectlighting")
    hou.hscript("ophide Vop pxraovlight")
    hou.hscript("ophide Vop pxrhalfbuffererrorfilter")
    hou.hscript("ophide Vop pxrgradesamplefilter")
    hou.hscript("ophide Vop pxrtangentfield")
    hou.hscript("ophide Vop rsl_illuminance")
    hou.hscript("ophide Vop pxrgobo")
    hou.hscript("ophide Vop pxrglass")
    hou.hscript("ophide Vop pxrmarschnerhair")
    hou.hscript("ophide Vop pxrgeometricaovs")
    hou.hscript("ophide Vop rsl_shadow")
    hou.hscript("ophide Vop rsl_step")
    hou.hscript("ophide Vop pxrmatteid")
    hou.hscript("ophide Vop pxrstdenvmaplight")
    hou.hscript("ophide Vop pxrhsl")
    hou.hscript("ophide Vop pxrrectlight")
    hou.hscript("ophide Vop pxrlmlayer")
    hou.hscript("ophide Vop pxrmeshlight")
    hou.hscript("ophide Vop pxrinvert")
    hou.hscript("ophide Vop rsl_rayinfo")
    hou.hscript("ophide Vop rsl_depth")
    hou.hscript("ophide Vop pxrrandomtexturemanifold")
    hou.hscript("ophide Vop pxrblocker")
    hou.hscript("ophide Vop pxrmanifold3dn")
    hou.hscript("ophide Vop pxrbackgroundsamplefilter")
    hou.hscript("ophide Vop pxrlmplastic")
    hou.hscript("ophide Vop pxrtexture")
    hou.hscript("ophide Vop rsl_textureinfo")
    hou.hscript("ophide Vop pxradjustnormal")
    hou.hscript("ophide Vop pxrlmmetal")
    hou.hscript("ophide Vop rsl_deriv")
    hou.hscript("ophide Vop pxrlayermixer")
    hou.hscript("ophide Vop pxrramp")
    hou.hscript("ophide Vop pxrspherelight")
    hou.hscript("ophide Vop pxrcombinerlightfilter")
    hou.hscript("ophide Vop pxrvoronoise")
    hou.hscript("ophide Vop pxrblack")
    hou.hscript("ophide Vop pxrlayeredtexture")
    hou.hscript("ophide Vop pxrvalidatebxdf")
    hou.hscript("ophide Vop pxrportallight")
    hou.hscript("ophide Vop pxrnormalmap")
    hou.hscript("ophide Vop pxrskin")
    hou.hscript("ophide Vop pxrblockerlightfilter")
    hou.hscript("ophide Vop pxrrodlightfilter")
    hou.hscript("ophide Vop pxrarealight")
    hou.hscript("ophide Vop pxrblend")
    hou.hscript("ophide Vop pxrcopyaovsamplefilter")
    hou.hscript("ophide Vop pxrdomelight")
    hou.hscript("ophide Vop pxrbaketexture")
    hou.hscript("ophide Vop pxrpathtracer")
    hou.hscript("ophide Vop pxrtofloat3")
    hou.hscript("ophide Vop pxrshadedside")
    hou.hscript("ophide Vop rsl_texture")
    hou.hscript("ophide Vop pxrosl")
    hou.hscript("ophide Vop pxrupbp")
    hou.hscript("ophide Vop pxrramplightfilter")
    hou.hscript("ophide Vop pxrwhitepointdisplayfilter")
    hou.hscript("ophide Vop pxrlightprobe")
    hou.hscript("ophide Vop rsl_ctransform")
    hou.hscript("ophide Vop rsl_bias")
    hou.hscript("ophide Vop pxrimageplanefilter")
    hou.hscript("ophide Vop pxrgrid")
    hou.hscript("ophide Vop pxrlightemission")
    hou.hscript("ophide Vop pxrcamera")
    hou.hscript("ophide Vop pxrremap")
    hou.hscript("ophide Vop rsl_oglass")
    hou.hscript("ophide Vop pxrshadowfilter")
    hou.hscript("ophide Vop pxrwhitepointsamplefilter")
    hou.hscript("ophide Vop pxrstdenvdaylight")
    hou.hscript("ophide Vop pxrimagedisplayfilter")
    hou.hscript("ophide Vop pxrfractal")
    hou.hscript("ophide Vop pxrattribute")
    hou.hscript("ophide Vop pxrgobolightfilter")
    hou.hscript("ophide Vop pxrlayeredblend")
    hou.hscript("ophide Vop pxrvariable")
    hou.hscript("ophide Vop pxrsamplefiltercombiner")
    hou.hscript("ophide Vop pxrmanifold2d")
    hou.hscript("ophide Vop pxrptexture")
    hou.hscript("ophide Vop pxrshadowdisplayfilter")
    hou.hscript("ophide Vop rsl_gain")
    hou.hscript("ophide Vop pxrfacingratio")
    hou.hscript("ophide Vop rsl_occlusion")
    hou.hscript("ophide Vop pxrmix")
    hou.hscript("ophide Vop pxrdispvectorlayer")
    hou.hscript("ophide Vop pxrdisptransform")
    hou.hscript("ophide Vop pxrdirt")
    hou.hscript("ophide Vop pxrclamp")
    hou.hscript("ophide Vop pxrroundcube::2.0")
    hou.hscript("ophide Vop pxrfilmictonemapperdisplayfilter")
    hou.hscript("ophide Vop pxrdiffuse")
    hou.hscript("ophide Vop pxrroundcube")
    hou.hscript("ophide Vop pxrvary")
    hou.hscript("ophide Vop pxrflakes")
    hou.hscript("ophide Vop pxrthinfilm")
    hou.hscript("ophide Vop rsl_random")
    hou.hscript("ophide Vop pxrbumpmanifold2d")
    hou.hscript("ophide Vop pxrlmglass")
    hou.hscript("ophide Vop pxrdispscalarlayer")
    hou.hscript("ophide Vop pxrchecker")
    hou.hscript("ophide Vop pxrtilemanifold")
    hou.hscript("ophide Vop pxrdebugshadingcontext")
    hou.hscript("ophide Vop rsl_renderstate")
    hou.hscript("ophide Vop pxrhaircolor")
    hou.hscript("ophide Vop pxrbump")
    hou.hscript("ophide Vop pxrlmsubsurface")
    hou.hscript("ophide Vop pxrdistantlight")
    hou.hscript("ophide Vop pxrrollingshutter")
    hou.hscript("ophide Vop pxrdisney")
    hou.hscript("ophide Vop pxrprojector")
    hou.hscript("ophide Vop pxrgamma")
    hou.hscript("ophide Vop pxrcross")
    hou.hscript("ophide Vop pxrbackgrounddisplayfilter")
    hou.hscript("ophide Vop pxrdefaultintegrator")
    hou.hscript("ophide Vop rsl_dudv")
    hou.hscript("ophide VopNet rsl_surface")
    hou.hscript("ophide VopNet rsl_light")
    hou.hscript("ophide VopNet rsl_displace")
    hou.hscript("ophide VopNet rsl_volume")
    hou.hscript("ophide VopNet rsl_imager")

    hou.hscript("ophide Sop bakeode")
    hou.hscript("ophide Sop duplicate")
    hou.hscript("ophide Sop starburst")
    hou.hscript("ophide Sop pointmap")
    hou.hscript("ophide Sop vex")
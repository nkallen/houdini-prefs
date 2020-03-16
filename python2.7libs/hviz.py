import hou, traceback, sys
from hou import parmTemplateType

this = sys.modules[__name__]

"""
Currently this is a very simple extension to display parameters of nodes directly in the network
editor, next to the node. It shows only those params with non-default values. It creates a parm with
a summary of the non-default key-value-paris, and hacks them into the "descriptiveparm" user attr.
"""

__name = "nk_parm_summary"

this.visualizing = False

def createEventHandler(uievent, pending_actions):
    if uievent.eventtype == 'keydown' and uievent.key == 'Shift+Space':
        visualize(uievent)
        this.visualizing = True
        return None, True

    elif uievent.eventtype == 'keyup' and this.visualizing:
        this.visualizing = False
        unvisualize(uievent)
    
    visualizing = False
    return None, False


def visualize(uievent):
    pwd = uievent.editor.pwd()
    for child in pwd.children():
        try:
            if not child.parmTuple(__name):
                template = hou.StringParmTemplate(__name, __name, 1)
                template.hide(True)
                child.addSpareParmTuple(template)
            parm_tuple = child.parmTuple(__name)
            kvps = []
            for parm_tuple in child.parmTuples():
                type = parm_tuple.parmTemplate().type()
                if not type in (parmTemplateType.Int, parmTemplateType.Float, parmTemplateType.String, parmTemplateType.Toggle):
                    continue
                if not parm_tuple.isAtDefault() and parm_tuple.name() != __name:
                    vs = []
                    for v in parm_tuple.eval():
                        if type == hou.parmTemplateType.Float:
                            vs.append("{:.2f}".format(v))
                        else:
                            vs.append(str(v))
                    v = vs[0] if len(vs) == 1 else "(" + ",".join(vs) + ")"
                    kvp = "{}={}".format(parm_tuple.name(), v)
                    kvps.append(kvp)
            text = ", ".join(kvps)
            parm_tuple.set([text])
            child.setUserData("descriptiveparm", __name)
        except hou.OperationFailed as e:
            print "Skipping", child
            print "This may indicate a bug in Houdini: ", e

def unvisualize(uievent):
    pwd = uievent.editor.pwd()
    for child in pwd.children():
        parm_tuple = child.parmTuple(__name)
        if parm_tuple:
            child.removeSpareParmTuple(parm_tuple)
    child.destroyUserData("descriptiveparm")
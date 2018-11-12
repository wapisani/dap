import argparse, numpy as np, vtk
from davtk_parse_utils import ThrowingArgumentParser

def piecewise_linear(x, t):
    i = np.searchsorted(t[::4], x)
    if i == 0:
        return t[1:4]
    elif i == len(t)/4:
        return t[-3:]
    else:
        f = t[i*4]-x
        return f*t[(i-1)*4+1:(i-1)*4+4] + (1.0-f)*t[i*4+1:i*4+4]

class UnknownConfigKeywordError(Exception):
    pass

class DavTKConfig(object):
    def __init__(self):
        self.config = { "atom_types" : {}, "bond_types" : {}, "colormaps" : {},
            "cell_box_color" : [1.0, 1.0, 1.0], "background_color" : [0.0, 0.0, 0.0],
            "picked_color" : [1.0, 1.0, 0.0] }

        self.parsers = {}

        self.parser_colormap = ThrowingArgumentParser(prog="colormap")
        self.parser_colormap.add_argument("-name",type=str)
        self.parser_colormap.add_argument("colormap",nargs='+',type=float)
        self.parsers["colormap"] = self.parse_colormap

        self.parser_atom_type = ThrowingArgumentParser(prog="atom_type")
        self.parser_atom_type.add_argument("-name",type=str)
        self.parser_atom_type.add_argument("-color",nargs=3,type=float,default=None)
        self.parser_atom_type.add_argument("-colormap",nargs=2,type=str,default=None)
        self.parser_atom_type.add_argument("-radius",type=float,default=None)
        self.parser_atom_type.add_argument("-radius_field",type=str,default=None)
        self.parser_atom_type.add_argument("-opacity",type=float,default=None)
        self.parser_atom_type.add_argument("-label",type=str,default=None)
        self.parsers["atom_type"] = self.parse_atom_type

        self.parser_bond_type = ThrowingArgumentParser(prog="bond_type")
        self.parser_bond_type.add_argument("-name",type=str)
        self.parser_bond_type.add_argument("-color",nargs=3,type=float,default=None)
        self.parser_bond_type.add_argument("-radius",type=float,default=None)
        self.parser_bond_type.add_argument("-opacity",type=float,default=None)
        self.parsers["bond_type"] = self.parse_bond_type

        self.parser_cell_box_color = ThrowingArgumentParser(prog="cell_box_color")
        self.parser_cell_box_color.add_argument("-color",nargs=3,type=float,default=None)
        self.parsers["cell_box_color"] = self.parse_bond_type

        self.parser_picked_color = ThrowingArgumentParser(prog="picked_color")
        self.parser_picked_color.add_argument("-color",nargs=3,type=float,default=None)
        self.parsers["picked_color"] = self.parse_bond_type

        self.parser_background_color = ThrowingArgumentParser(prog="background_color")
        self.parser_background_color.add_argument("-color",nargs=3,type=float,default=None)
        self.parsers["background_color"] = self.parse_bond_type

        # properties
        for f in ["cell_box","picked"]:
            prop = vtk.vtkProperty()
            prop.SetOpacity(1.0)
            prop.SetColor(self.config[f+"_color"])
            self.config[f+"_prop"] = prop

    def __getitem__(self,key):
        return self.config[key]

    def parse_colormap(self, args):
        args = self.parser_colormap.parse_args(args)
        if len(args.colormap) % 4 != 0:
            raise ValueError("colormap arguments must be multiple of 4: v r g b")
        self.config["colormaps"][args.name] = lambda x : piecewise_linear(x, np.array(args.colormap))

    def parse_atom_type(self, args):
        refresh = None
        args = self.parser_atom_type.parse_args(args)
        if args.name not in self.config["atom_types"]:
            self.config["atom_types"][args.name] = {}
            self.config["atom_types"][args.name]["radius"] = 0.3
            self.config["atom_types"][args.name]["colormap_func"] = None
            self.config["atom_types"][args.name]["colormap_field"] = None
            self.config["atom_types"][args.name]["radius_field"] = None
            self.config["atom_types"][args.name]["label"] = None
            prop = vtk.vtkProperty()
            prop.SetOpacity(1.0)
            prop.SetSpecularColor(1.0,1.0,1.0)
            prop.SetSpecularPower(10.0)
            self.config["atom_types"][args.name]["prop"] = prop
            refresh = "all"
        if args.color is not None:
            refresh = None
            if self.config["atom_types"][args.name]["colormap_func"] is not None:
                refresh = "all"
            self.config["atom_types"][args.name]["prop"].SetColor(args.color)
            self.config["atom_types"][args.name]["colormap_func"] = None
            self.config["atom_types"][args.name]["colormap_field"] = None
        if args.colormap is not None:
            refresh = "all"
            self.config["atom_types"][args.name]["colormap_func"] = self.config["colormaps"][args.colormap[0]]
            self.config["atom_types"][args.name]["colormap_field"] = args.colormap[1]
            self.config["atom_types"][args.name]["color"] = None
        if args.opacity is not None:
            self.config["atom_types"][args.name]["prop"].SetOpacity(args.opacity)
        if args.radius is not None:
            refresh = None
            if self.config["atom_types"][args.name]["radius_field"] is not None:
                refresh = "all"
            self.config["atom_types"][args.name]["radius"] = args.radius
            self.config["atom_types"][args.name]["radius_field"] = None
        if args.radius_field is not None:
            refresh = "all"
            self.config["atom_types"][args.name]["radius_field"] = args.radius_field
            self.config["atom_types"][args.name]["radius"] = None
        if args.label is not None:
            refresh = "all"
            if args.label == 'NONE':
                print "unsetting label field"
                self.config["atom_types"][args.name]["label"] = None
            else:
                self.config["atom_types"][args.name]["label"] = args.label
        return refresh

    def parse_bond_type(self, args):
        refresh = None
        args = self.parser_bond_type.parse_args(args)
        if args.name not in self.config["bond_types"]:
            self.config["bond_types"][args.name] = {}
            self.config["bond_types"][args.name]["opacity"] = 1.0
            self.config["bond_types"][args.name]["radius"] = 0.3
            prop = vtk.vtkProperty()
            prop.SetOpacity(1.0)
            prop.SetSpecularColor(1.0,1.0,1.0)
            prop.SetSpecularPower(10.0)
            self.config["bond_types"][args.name]["prop"] = prop
            refresh = "all"
        if args.color is not None:
            self.config["bond_types"][args.name]["prop"].SetColor(args.color)
        if args.opacity is not None:
            self.config["bond_types"][args.name]["prop"].SetOpacity(args.opacity)
        if args.radius is not None:
            refresh = "all"
            self.config["bond_types"][args.name]["radius"] = args.radius
        return refresh

    def parse_cell_box_color(self, args):
        args = self.parser_cell_box_color.parse_args(args)
        self.config["cell_box_color"] = args.color
        self.config["cell_box_prop"].SetColor(self.config["cell_box_color"])
        return "none"

    def parse_picked_color(self, args):
        args = self.parser_picked_color.parse_args(args)
        self.config["picked_color"] = args.color
        self.config["picked_prop"].SetColor(self.config["picked_color"])
        return "none"

    def parse_background_color(self, args):
        args = self.parser_background_color.parse_args(args)
        self.config["background_color"] = args.color
        return "renderer"

    def parse_line(self, line):
        args = line.split()
        if args[0] in self.parsers:
            return self.parsers[args[0]](args[1:])
        else:
            raise UnknownConfigKeywordError(args[0])

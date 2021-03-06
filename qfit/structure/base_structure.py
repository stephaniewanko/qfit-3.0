'''
Excited States software: qFit 3.0

Contributors: Saulo H. P. de Oliveira, Gydo van Zundert, and Henry van den Bedem.
Contact: vdbedem@stanford.edu

Copyright (C) 2009-2019 Stanford University
Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

This entire text, including the above copyright notice and this permission notice
shall be included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS, CONTRIBUTORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
'''

import logging
from collections import defaultdict, Iterable
from operator import eq, gt, ge, le, lt

import numpy as np

from .elements import ELEMENTS
from .math import dihedral_angle
from .pdbfile import PDBFile
from .selector import _Selector

logger = logging.getLogger(__name__)

class _BaseStructure:

    REQUIRED_ATTRIBUTES = ["record", "name", "b", "q", "coor", "resn", "resi",
                           "icode", "e", "charge", "chain", "altloc"]
    _DTYPES = [str, str, float, float, float, str, int, str, str, str, str, float]
    _selector = _Selector()
    _COMPARISON_DICT = {'==': eq, '!=': eq, '>': gt, '>=': ge, '<=': le, '<': lt}

    def __init__(self, data, selection=None, parent=None, **kwargs):

        self.parent = parent
        self.data = data
        self._selection = selection
        # Save extra kwargs for general extraction and duplication methods.
        self._kwargs = kwargs
        self.link_data = None
        for attr, array in data.items():
            hattr = '_' + attr
            setattr(self, hattr, array)
            prop = self._structure_property(hattr)
            setattr(self.__class__, attr, prop)
        self._x, self._y, self._z = self._coor.T
        for attr in 'xyz':
            hattr = '_' + attr
            prop = self._structure_property(hattr)
            setattr(self.__class__, attr, prop)

        for key, value in kwargs.items():
            if key == "link_data":
                self.link_data = value

        if selection is None:
            self.natoms = self._coor.shape[0]
        else:
            self.natoms = self._selection.size

    def _structure_property(self, property_name, docstring=None):
        def getter(self):
            if self._selection is None:
                return self.__getattribute__(property_name).copy()
            else:
                return self.__getattribute__(property_name)[self._selection]

        def setter(self, value):
            if self._selection is None:
                getattr(self, property_name)[:] = value
            else:
                getattr(self, property_name)[self._selection] = value

        return property(getter, setter, doc=docstring)

    def _get_property(self, ptype):
        elements, ind = np.unique(self.e, return_inverse=True)
        values = []
        for e in elements:
            try:
                value = getattr(ELEMENTS[e.capitalize()], ptype)
            except KeyError:
                logger.warning("Unknown element {:s}. Using Carbon parameter instead.".format(e))
                value = getattr(ELEMENTS['C'], ptype)
            values.append(value)
        out = np.asarray(values, dtype=np.float64)[ind]
        return out

    @property
    def covalent_radius(self):
        return self._get_property('covrad')

    @property
    def vdw_radius(self):
        return self._get_property('vdwrad')

    def copy(self):
        data = {}
        for attr in self.data:
            data[attr] = getattr(self, attr).copy()
        return self.__class__(data, parent=None, selection=None, **self._kwargs)

    def get_dihedral_angle(self, coor):
        return dihedral_angle(coor)

    def extract(self, *args):
        if not isinstance(args[0], str):
            selection = args[0]
        else:
            selection = self.select(*args)
        return self.__class__(self.data, selection=selection, parent=self, **self._kwargs)

    def rotate(self, R):
        """Rotate structure"""
        coor = np.dot(self.coor, R.T)
        self.coor = coor

    def rmsd(self, structure):
        coor1 = self.coor
        coor2 = structure.coor
        if coor1.shape != coor2.shape:
            raise ValueError("Coordinate shapes are not equivalent")
        if "TYR" in self.resn:
            idx_cd1 = structure.name.tolist().index("CD1")
            idx_cd2 = structure.name.tolist().index("CD2")
            idx_ce1 = structure.name.tolist().index("CE1")
            idx_ce2 = structure.name.tolist().index("CE2")
            coor3 = np.copy(coor2)
            coor3[idx_cd1],coor3[idx_cd2] = coor2[idx_cd2],coor2[idx_cd1]
            coor3[idx_ce1],coor3[idx_ce2] = coor2[idx_ce2],coor2[idx_ce1]
            diff = (coor1 - coor2).ravel()
            diff2 = (coor1 - coor3).ravel()
            return min(np.sqrt(3 * np.inner(diff, diff) / diff.size),
                       np.sqrt(3 * np.inner(diff2, diff2) / diff2.size))
        if "PHE" in self.resn:
            idx_cd1 = structure.name.tolist().index("CD1")
            idx_cd2 = structure.name.tolist().index("CD2")
            idx_ce1 = structure.name.tolist().index("CE1")
            idx_ce2 = structure.name.tolist().index("CE2")
            coor3 = np.copy(coor2)
            coor3[idx_cd1],coor3[idx_cd2] = coor2[idx_cd2], coor2[idx_cd1]
            coor3[idx_ce1],coor3[idx_ce2] = coor2[idx_ce2], coor2[idx_ce1]
            diff = (coor1 - coor2).ravel()
            diff2 = (coor1 - coor3).ravel()
            return min(np.sqrt(3 * np.inner(diff, diff) / diff.size),
                       np.sqrt(3 * np.inner(diff2, diff2) / diff2.size))
        else:
            diff = (coor1 - coor2).ravel()
            return np.sqrt(3 * np.inner(diff, diff) / diff.size)

    def select(self, string, values=None, comparison="=="):
        if values is None:
            self._selector.set_structure(self)
            selection = self._selector(string)
        else:
            selection = self._simple_select(string, values, comparison)
        return selection

    def _simple_select(self, attr, values, comparison_str):
        data = getattr(self, attr)
        comparison = self._COMPARISON_DICT[comparison_str]
        if not isinstance(values, Iterable) or isinstance(values, str):
            values = (values,)
        mask = np.zeros(self.natoms, bool)
        for value in values:
            mask2 = comparison(data, value)
            np.logical_or(mask, mask2, mask)
        if comparison_str == '!=':
            np.logical_not(mask, out=mask)
        if self._selection is None:
            selection = np.flatnonzero(mask)
        else:
            selection = self._selection[mask]
        return selection

    def tofile(self, fname):
        PDBFile.write(fname, self)

    def translate(self, translation):
        """Translate atoms"""
        self.coor += translation

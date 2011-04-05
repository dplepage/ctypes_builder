import numpy as np
import ctypes

from ctypes import *

# typemap maps numpy typestrings to ctypes types
typemap = {}
for t in (c_byte, c_short, c_int, c_long, c_longlong):
    typemap["<i%s" % sizeof(t)] = t.__ctype_le__
    typemap[">i%s" % sizeof(t)] = t.__ctype_be__
for t in (c_ubyte, c_ushort, c_uint, c_ulong, c_ulonglong):
    typemap["<u%s" % sizeof(t)] = t.__ctype_le__
    typemap[">u%s" % sizeof(t)] = t.__ctype_be__
for t in (c_float, c_double):
    typemap["<f%s" % sizeof(t)] = t.__ctype_le__
    typemap[">f%s" % sizeof(t)] = t.__ctype_be__
typemap["|b1"] = c_bool
typemap["|i1"] = c_byte
typemap["|u1"] = c_ubyte

invtypemap = {}
for key, value in typemap.items():
    invtypemap[value] = key

def get_ctype(a):
    '''Get the ctype corresponding to a
    
    If a is a string or dtype, convert it to a ctypes type.
    If a is an ndarray, convert a.dtype to a ctypes type.
    '''
    if type(a) == np.ndarray:
        dt = a.dtype
    else:
        dt = np.dtype(a)
    if dt.descr[0][1] in typemap:
        return typemap[dt.descr[0][1]]
    else:
        print dt.descr
        import pprint
        pprint.pprint(typemap)
        raise ValueError("Cannot convert dtype to ctype: {0}".format(dt))

def get_ntype(a):
    '''Get the numpy type corresponding to a ctypes type
    
    Returns numpy.dtypes
    '''
    if str(a) == a:
        a = getattr(ctypes, 'c_'+a)
    return np.dtype(invtypemap[a])

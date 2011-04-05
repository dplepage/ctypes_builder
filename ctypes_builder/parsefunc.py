import ctypes
from functools import wraps

from pygccxml.declarations import cpptypes, typedef
from numpy.ctypeslib import ndpointer

from parsexml import getattrs
from dtypes import get_ntype, invtypemap

_base_typemap = {
    cpptypes.bool_t					    : ctypes.c_bool ,
    cpptypes.char_t					    : ctypes.c_char ,
    cpptypes.double_t				    : ctypes.c_double ,
    cpptypes.float_t				    : ctypes.c_float ,
    cpptypes.int_t					    : ctypes.c_int,
    cpptypes.long_double_t			    : ctypes.c_longdouble,
    cpptypes.long_int_t				    : ctypes.c_long,
    cpptypes.long_long_int_t		    : ctypes.c_longlong,
    cpptypes.long_long_unsigned_int_t	: ctypes.c_ulonglong,
    cpptypes.long_unsigned_int_t		: ctypes.c_ulong,
    cpptypes.short_int_t				: ctypes.c_short,
    cpptypes.short_unsigned_int_t		: ctypes.c_ushort,
    cpptypes.signed_char_t				: ctypes.c_byte,
    cpptypes.unsigned_char_t			: ctypes.c_ubyte,
    cpptypes.unsigned_int_t				: ctypes.c_uint,
    cpptypes.void_t					    : None,
    cpptypes.wchar_t					: ctypes.c_wchar,
}

class CTypeException(Exception):
    '''Raise this if the type conversion fails; the message will be logged.'''
    pass

class _NotApplicable(Exception):
    '''Raise this if this type shouldn't be converted by this func anyway.'''
    pass

NotApplicable = _NotApplicable()

def pgxtype_to_ctype(ns, name, pgxtype, attrs):
    if isinstance(pgxtype, cpptypes.pointer_t):
        base = pgxtype_to_ctype(ns, name, pgxtype.base, attrs)
        # If it's a pointer to a base type, get the right type
        if base is None:
            return ctypes.c_void_p
        if base is ctypes.c_char:
            return ctypes.c_char_p
        if base is ctypes.c_wchar:
            return ctypes.c_wchar_p
        return ctypes.POINTER(base)
    # discard const
    # TODO discard other qualifiers (currently we bail on e.g. volatile)
    if isinstance(pgxtype, cpptypes.const_t):
        return pgxtype_to_ctype(ns, name, pgxtype.base, attrs)
    if isinstance(pgxtype, cpptypes.declarated_t):
        if isinstance(pgxtype.declaration, typedef.typedef_t):
            return pgxtype_to_ctype(ns, name, pgxtype.declaration.type, attrs)
    # TODO support classes? (read from the namespace)
    if type(pgxtype) not in _base_typemap:
        raise NotApplicable
    return _base_typemap[type(pgxtype)]

def marked_pgxtype_to_ndpointer(ns, name, pgxtype, attrs):
    if 'arr' not in attrs or attrs.pop('arr') != 'true':
        raise NotApplicable
    try:
        ctype = pgxtype_to_ctype(ns, name, pgxtype, attrs)
    except NotApplicable:
        raise CTypeException("Cannot create ndpointer class for type '{0}'."
                             .format(pgxtype.decl_string))
    if not isinstance(ctype, type(ctypes._Pointer)) or ctype._type_ not in invtypemap:
        raise CTypeException("Cannot create ndpointer class for type '{0}'."
                             .format(pgxtype.decl_string))
    flags = ["C"]
    dtype = get_ntype(ctype._type_)
    nullable = attrs.pop('nullable', '0')
    if nullable in ['false', '0']:
        nullable = False
    else:
        nullable = True
    ndim = attrs.pop('ndim', None)
    shape = attrs.pop('shape', None)
    if shape:
        dims = shape.split('x')
        if ndim is not None and ndim != len(dims):
            raise ValueError("Conflict on type '{2}': ndpointer cannot have ndim={0} and shape={1}".format(ndim, shape, pgxtype.decl_string))
        ndim = len(dims)
        try:
            dims = map(int, dims)
            shape = tuple(dims)
        except ValueError:
            shape = None
            # self.shape_constraints[name] = dims
    if attrs:
        raise AttributeError("Unrecognized GCCXML attributes on arg '{0} {1}': ".format(pgxtype.decl_string, name)+' '.join(attrs.keys()))
    return ndpointer(dtype=dtype, flags=flags, allow_null=nullable, shape=shape, ndim=ndim)

def pgxtype_to_ndpointer(ns, name, pgxtype, attrs):
    t = pgxtype_to_ctype(ns, name, pgxtype, attrs)
    if isinstance(t, type(ctypes.POINTER(ctypes.c_int))):
        if t._type_ in invtypemap:
            return ndpointer(dtype=get_ntype(t._type_), allow_null=True, flags=['C'])
    raise NotApplicable
    

class Func(object):
    default_mappers = (marked_pgxtype_to_ndpointer, pgxtype_to_ndpointer, pgxtype_to_ctype)
    """Wrapper around a C Function"""
    def __init__(self, namespace, fn, mappers=(), failsilently=True, usedefaults=True):
        super(Func, self).__init__()
        self.shape_constraints = {}
        self.ns = namespace
        self.fn = fn
        self.mappers = list(mappers)
        if usedefaults:
            self.mappers = self.mappers + list(self.default_mappers)
        self.mangled_name = fn.mangled if fn.mangled else fn.name
        self.name = fn.name
        self.valid_types = True
        self.failsilently = failsilently
        self.reason = None
        self.restype = self.parseType('__retval', fn.return_type, getattrs(fn))
        self.argtypes = map(self.parseArg, fn.arguments)
    
    def parseArg(self, pgxarg):
        return self.parseType(pgxarg.name, pgxarg.type, getattrs(pgxarg))
    
    def parseType(self, name, pgxtype, attrs):
        for mapper in self.mappers:
            try:
                return mapper(self.ns, name, pgxtype, attrs)
            except _NotApplicable:
                continue
            except CTypeException:
                if self.failuremode != 'silent':
                    raise
                self.valid_types = False
                self.reason = ' '.join([pgxtype.decl_string, name])
                return None
        self.valid_types = False
        self.reason = ' '.join([pgxtype.decl_string, name])
        return None
    
    def assign(self, lib):
        '''Set types on lib.<mangled_name>, copy to lib.<name>'''
        fn = getattr(lib, self.mangled_name)
        fn.__name__ = self.name
        newfn = fn
        if self.valid_types:
            fn.argtypes = self.argtypes
            fn.restype = self.restype
            if self.shape_constraints:
                @wraps(fn)
                def newfn(*args, **kwargs):
                    # TODO: Check shape constraints here
                    # Note: this will require knowing which of *args is each argument
                    # Also, it'd be awesome if we automatically built docstrings from the arg info!
                    return fn(*args, **kwargs)
                setattr(lib, '_raw_'+self.name, fn)
        setattr(lib, self.name, newfn)

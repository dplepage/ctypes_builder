import os.path as pth
import re

import pygccxml
from pygccxml.declarations import cpptypes

def parse(files, working_directory='.', include_paths=None, define_symbols=None, undefine_symbols=None):
    conf = pygccxml.parser.config_t(
        working_directory = working_directory,
        include_paths = include_paths,
        define_symbols = define_symbols,
        undefine_symbols = undefine_symbols)
    return pygccxml.parser.parse(files, conf)[0]

attrblock = re.compile(r'gccxml\((?P<body>[^)]*)\)')
attrre = re.compile(r'([^=]+)=([^,]+),? ?')
def getattrs(pgxobj):
    if pgxobj.attributes:
        m = attrblock.search(pgxobj.attributes)
        if m:
            return dict(attrre.findall(m.group('body')))
    return {}

def extract_fns(ns, export_dirs=('.',)):
    fns = []
    for dir in export_dirs:
        fns.extend(ns.free_funs(header_dir=pth.abspath(dir), allow_empty=True))
    fns = [f for f in fns if not f.has_inline and not f.has_extern]
    return fns

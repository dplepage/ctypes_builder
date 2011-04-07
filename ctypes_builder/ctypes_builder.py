import ctypes
import os
import tempfile
import shutil
import cPickle
import inspect

import numpy as np
from numpy.ctypeslib import ndpointer
from fabricate import Builder
from danutils.ostools import chdir

from proxy import lazy as makelazy, LocalProxy

from parsexml import parse, extract_fns
from parsefunc import Func

def UnloadedFn(name, reason):
    def fail():
        raise AttributeError("Method {0} skipped (can't parse type {1})".format(name, reason))
    return LocalProxy(fail)

def allabs(iter):
    return map(os.path.abspath, iter)

class CtypesBuilder(object):
    def __init__(self, storage_dir = None, depdirs = (), include_paths = (),
                 define_symbols = (), undefine_symbols = (), extra_opts = (),
                 working_dir = None, type_mappers = ()):
        if storage_dir is None:
            self.storage_dir = tempfile.mkdtemp()
            self.scrap_dir = True
        else:
            self.storage_dir = os.path.abspath(storage_dir)
            self.scrap_dir = False
        self.depdirs = allabs(list(depdirs))+[self.storage_dir]
        self.include_paths = allabs(include_paths)
        self.define_symbols = define_symbols
        self.undefine_symbols = undefine_symbols
        self.extra_opts = extra_opts
        if working_dir is None:
            self.working_dir = self.storage_dir
        else:
            self.working_dir = os.path.abspath(working_dir)
        self.type_mappers = type_mappers
        self.depfile = os.path.join(self.storage_dir, 'deps.json')
        self.builder = Builder(dirs = self.depdirs, depsname = self.depfile, debug=True)
        self.libcache = {}

    def lazy_getlib(self, *args, **kwargs):
        return self.buildlib(*args, **kwargs)
    
    def getlib(self, *args, **kwargs):
        lazy = kwargs.pop('lazy', True)
        if lazy:
            return self.lazy_buildlib(*args, **kwargs)
        return self.buildlib(*args, **kwargs)

    def buildlib(self, libfile, sources=(), depdirs = (), include_paths = (),
                     define_symbols = (), undefine_symbols = (), extra_opts = (),
                     working_dir = None, export_dirs = (), cmd=(), force_rebuild=False, extra_mappers=()):
        if working_dir is None:
            raise Exception("Must specify working_dir.")
        if isinstance(sources, basestring):
            sources = [sources]
        if not export_dirs and working_dir:
            export_dirs = (working_dir,)
        export_dirs = allabs(export_dirs)
        depdirs = allabs(list(depdirs) + list(self.depdirs))
        include_paths = allabs(list(include_paths) + list(self.include_paths))
        define_symbols = list(define_symbols) + list(self.define_symbols)
        undefine_symbols = list(undefine_symbols) + list(self.undefine_symbols)
        extra_opts = list(extra_opts) + list(self.extra_opts)
        type_mappers = list(extra_mappers) + list(self.type_mappers)
        if working_dir is None:
            working_dir = self.working_dir
        else:
            working_dir = os.path.abspath(working_dir)
        with chdir(working_dir):
            if force_rebuild and os.path.exists(libfile):
                 shutil.mv(libfile, libfile+'.bkp')
            if cmd:
                return self.dumb_get(libfile, cmd, depdirs)
            else:
                return self.smart_get(libfile, sources, depdirs, include_paths,
                                 define_symbols, undefine_symbols, extra_opts,
                                 working_dir, export_dirs, type_mappers=type_mappers)
    
    lazy_buildlib = makelazy(buildlib)
    
    def smart_get(self, libfile, sources, depdirs, include_paths,
                     define_symbols, undefine_symbols, extra_opts,
                     working_dir, export_dirs, type_mappers=()):
        key = `[libfile, sources, depdirs, include_paths, define_symbols, undefine_symbols, extra_opts, working_dir, export_dirs]`
        cmd = ['g++', '-Wno-attributes', '-Wno-deprecated', '-shared'] + sources + ['-o', libfile, '-fPIC']
        cmd += ['-I'+inc for inc in include_paths]
        cmd += ['-D'+sym for sym in define_symbols]
        cmd += ['-U'+sym for sym in undefine_symbols]
        cmd += extra_opts
        command, deps, outputs = self.builder.run(cmd)
        rebuilt = (deps is not None) or (outputs is not None)
        retyped = False
        xml = self.getxml(libfile, force_rebuild=rebuilt)
        if xml is None:
            xml = parse(sources, working_directory=working_dir,
                include_paths = include_paths, define_symbols = define_symbols,
                undefine_symbols = undefine_symbols)
            self.savexml(libfile, xml)
            retyped = True
        return self.loadlib(key, libfile, rebuilt or retyped, xml, export_dirs, type_mappers = type_mappers)
    
    def loadlib(self, key, libfile, force_retype = False, xml = None, export_dirs = None, type_mappers=()):
        if force_retype or key not in self.libcache:
            lib = ctypes.cdll.LoadLibrary(libfile)
            if xml is not None and export_dirs is not None:
                for fn in extract_fns(xml, export_dirs = export_dirs):
                    func = Func(xml, fn, mappers=type_mappers)
                    if func.valid_types:
                        func.assign(lib)
                    else:
                        setattr(lib, func.name, UnloadedFn(func.name, func.reason))
            self.libcache[key] = lib
        return self.libcache[key]
    
    def dumb_get(self, libfile, command, depdirs):
        depdirs = list(depdirs) + self.depdirs
        key = `[libfile, command, depdirs]`
        cmdstr, deps, outputs = self.builder.run(command)
        rebuilt = (deps is not None) or (outputs is not None)
        return self.loadlib(key, libfile, force_retype = rebuilt)
           
    def xmlname(self, libfile):
        return libfile + '.typeinfo.pickle'
    
    def getxml(self, libfile, force_rebuild=False):
        name = self.xmlname(libfile)
        if os.path.exists(name) and not force_rebuild:
            return cPickle.load(open(name))
        return None
    
    def savexml(self, libfile, funcs):
        cPickle.dump(funcs, open(self.xmlname(libfile),'w'))
    
    def __del__(self):
        # Somehow yaml's cleanup seems to clobber shutil?
        # or at least, I get errors without this hack, but only if I import yaml...
        global shutil
        try: import shutil
        except: pass
        if self.scrap_dir and shutil is not None:
            shutil.rmtree(self.storage_dir)

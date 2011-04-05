from functools import wraps

from werkzeug.local import LocalProxy

def cachethunk(fn):
    class Dummy: pass
    fn.result = Dummy
    @wraps(fn)
    def newfn():
        if fn.result is Dummy:
            fn.result = fn()
        return fn.result
    return newfn

def thunkify(fn):
    '''Convert a function to a thunk generator.
    
    Given a function f, return a new function that takes (*args, **kwargs) and
    returns a new callable g such that calling g without arguments calls f 
    on (*args, **kwargs). For example:
    
    >>> def f(x):    
    ...     print x
    ... 
    >>> t = thunkify(f)
    >>> f(12)
    12
    >>> t(12)
    <function <lambda> at 0x...>
    >>> g = t(12)
    >>> g()
    12    
    '''
    @wraps(fn)
    def newfn(*args, **kwargs):
        return lambda : fn(*args, **kwargs)
    return newfn

def lazy(fn):
    @wraps(fn)
    def newfn(*args, **kwargs):
        return LocalProxy(cachethunk(thunkify(fn)(*args, **kwargs)))
    return newfn

import sys
try:
	import builtins
except ImportError:
	builtins = __builtins__
import types
import imp


__all__ = ['_get',
           '_set',
           '_create_closure_cell',
           'rebase_function',
           'rebase_class',
           'rebase',
           '_get_default']

_get_default = object()
def _get(obj, name, default=_get_default):
	if isinstance(obj, dict):
		if default is _get_default:
			return obj[name]
		else:
			return obj.get(name, default)
	else:
		if default is _get_default:
			return getattr(obj, name)
		else:
			return getattr(obj, name, default)

def _set(obj, name, val):
	if isinstance(obj, dict):
		obj[name] = val
	else:
		return setattr(obj, name, val)

def _create_closure_cell(obj):
	def ret(): obj
	return ret.__closure__[0]

def rebase_function(f, target, new_name=None, ns=None):
	if not new_name:
		new_name = f.__name__
	ns = ns or dict()

	if f.__closure__:
		new_closure = []
		for c in f.__closure__:
			name = _get(c.cell_contents, '__name__', False)
			if name and name in ns:
				new_closure.append(_create_closure_cell(ns[name]))
			else:
				new_closure.append(c)
		new_closure = tuple(new_closure)
	else:
		new_closure = f.__closure__

	new_f = types.FunctionType(
		f.__code__,
		ns,
		new_name,
		f.__defaults__,
		new_closure
	)
	
	_set(target, new_name, new_f)

def rebase_class(cls, target, new_name=None, ns=None):
	if not new_name:
		new_name = cls.__name__
	ns = ns or dict()

	new_bases = []
	for base in cls.__bases__:
		new_base = _get(target, base.__name__, False)
		if new_base and isinstance(new_base, type):
			new_bases.append(new_base)
		else:
			new_bases.append(base)
	new_bases = tuple(new_bases)

	new_cls = type(new_name, new_bases, dict())
	ns[new_name] = new_cls
	new_cls._my_class = new_cls

	for name, item in cls.__dict__.items():
		if name in ('__dict__', '__slots__', '__bases__', '__weakref__', '__name__', '__module__', '__doc__'): continue
		if isinstance(item, types.MemberDescriptorType): continue
		rebase(item, new_cls, name, ns)

	_set(target, new_name, new_cls)

def rebase(obj, target, new_name=None, ns=None):

	if isinstance(obj, type):
		rebase_class(obj, target, new_name, ns)
	elif isinstance(obj, types.FunctionType):
		rebase_function(obj, target, new_name, ns)
	else:
		_set(target, new_name, obj) 


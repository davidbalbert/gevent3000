import sys
try:
	import builtins
except ImportError:
	builtins = __builtins__
import types
import imp


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
			name = getattr(c.cell_contents, '__name__', False)
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

	if isinstance(target, dict):
		target[new_name] = new_f
	else:
		setattr(target, new_name, new_f)

def rebase_class(cls, target, new_name=None, ns=None):
	if not new_name:
		new_name = cls.__name__
	ns = ns or dict()

	new_bases = []
	for base in cls.__bases__:
		new_base = getattr(target, base.__name__, False)
		if new_base and isinstance(new_base, type):
			new_bases.append(new_base)
		else:
			new_bases.append(base)
	new_bases = tuple(new_bases)

	new_cls = type(new_name, new_bases, dict())
	ns[new_name] = new_cls
	new_cls._my_class = new_cls

	for name, item in cls.__dict__.items():
		if name in ('__dict__', '__bases__', '__weakref__', '__name__', '__module__', '__doc__'): continue
		rebase(item, new_cls, name, ns)

	if isinstance(target, dict):
		target[new_name] = new_cls
	else:
		setattr(target, new_name, new_cls)

def rebase(obj, target, new_name=None, ns=None):

	if isinstance(obj, type):
		rebase_class(obj, target, new_name, ns)
	elif isinstance(obj, types.FunctionType):
		rebase_function(obj, target, new_name, ns)
	else:
		if isinstance(target, dict):
			target[new_name] = obj
		else:
			setattr(target, new_name, obj)
# Copyright (c) 2009-2012 Denis Bilenko. See LICENSE for details.
"""
gevent is a coroutine-based Python networking library that uses greenlet
to provide a high-level synchronous API on top of libev event loop.

See http://www.gevent.org/ for the documentation.
"""

version_info = (1, 0, 0, 'dev', None)
__version__ = '1.0dev'


__all__ = ['get_hub',
           'Greenlet',
           'GreenletExit',
           'spawn',
           'spawn_later',
           'spawn_raw',
           'joinall',
           'killall',
           'Timeout',
           'with_timeout',
           'getcurrent',
           'sleep',
           'idle',
           'kill',
           'signal',
           'fork',
           'reinit',
           'run',
       'socket',
       'ssl']


import sys
if sys.platform == 'win32':
    __import__('socket')  # trigger WSAStartup call


from gevent.hub import get_hub
from gevent.greenlet import Greenlet, joinall, killall
spawn = Greenlet.spawn
spawn_later = Greenlet.spawn_later
from gevent.timeout import Timeout, with_timeout
from gevent.hub import getcurrent, GreenletExit, spawn_raw, sleep, idle, kill, signal, PY3
try:
    from gevent.hub import fork
except ImportError:
    __all__.remove('fork')

# if PY3:
#   socket = __import__('gevent.py3.socket')
#   ssl = __import__('gevent.py3.ssl')
# else:
#   socket = __import__('gevent.py2.socket')
#   ssl = __import__('gevent.py2.ssl')


if PY3:
    from gevent.py3 import socket
    sys.modules['gevent.socket'] = socket
    from gevent.py3 import ssl
    sys.modules['gevent.ssl'] = ssl
else:
    from gevent.py2 import socket
    sys.modules['gevent.socket'] = socket
    from gevent.py2 import ssl
    sys.modules['gevent.ssl'] = ssl

del sys

def reinit():
    return get_hub().loop.reinit()


def run(timeout=None, event=None):
    return get_hub().join(timeout=timeout, event=event)

import sys
import socket as __socket__
from gevent.hub import get_hub
from gevent.timeout import Timeout

# standard functions and classes that this module re-implements in a gevent-aware way:
__implements__ = ['create_connection',
                  'socket',
                  'SocketType',
                  'fromfd',
                  'socketpair']

__dns__ = ['getaddrinfo',
           'gethostbyname',
           'gethostbyname_ex',
           'gethostbyaddr',
           'getnameinfo',
           'getfqdn']

__implements__ += __dns__

# non-standard functions that this module provides:
__extensions__ = ['wait_read',
                  'wait_write',
                  'wait_readwrite']

# standard functions and classes that this module re-imports
__imports__ = ['error',
               'gaierror',
               'herror',
               'htonl',
               'htons',
               'ntohl',
               'ntohs',
               'inet_aton',
               'inet_ntoa',
               'inet_pton',
               'inet_ntop',
               'timeout',
               'gethostname',
               'getprotobyname',
               'getservbyname',
               'getservbyport',
               'getdefaulttimeout',
               'setdefaulttimeout',
               # Windows:
               'errorTab']

is_windows = sys.platform == 'win32'

if is_windows:
    # no such thing as WSAEPERM or error code 10001 according to winsock.h or MSDN
    from errno import WSAEINVAL as EINVAL
    from errno import WSAEWOULDBLOCK as EWOULDBLOCK
    from errno import WSAEINPROGRESS as EINPROGRESS
    from errno import WSAEALREADY as EALREADY
    from errno import WSAEISCONN as EISCONN
    from gevent.win32util import formatError as strerror
    EAGAIN = EWOULDBLOCK
else:
    from errno import EINVAL
    from errno import EWOULDBLOCK
    from errno import EINPROGRESS
    from errno import EALREADY
    from errno import EAGAIN
    from errno import EISCONN
    from os import strerror

try:
    from errno import EBADF
except ImportError:
    EBADF = 9

for name in __imports__[:]:
    try:
        value = getattr(__socket__, name)
        globals()[name] = value
    except AttributeError:
        __imports__.remove(name)

for name in __socket__.__all__:
    value = getattr(__socket__, name)
    if isinstance(value, (int, bytes, str)):
        globals()[name] = value
        __imports__.append(name)

del name, value

sock_timeout = __socket__.timeout

class socket(__socket__.socket):
    def __init__(self, *args, **kwargs):
        super(socket, self).__init__(*args, **kwargs)
        self._faketimeout = super(socket, self).gettimeout()
        super(socket, self).setblocking(False)
        fileno = self.fileno()
        self.hub = get_hub()
        io = self.hub.loop.io
        self._read_event = io(fileno, 1)
        self._write_event = io(fileno, 2)

    @property
    def timeout(self):
        return self._faketimeout

    @timeout.setter
    def timeout(self, timeout):
        self._faketimeout = timeout

    def setblocking(self, flag):
        if flag:
            self._faketimeout = None
        else:
            self._faketimeout = 0.0

    def settimeout(self, howlong):
        if howlong is not None:
            try:
                f = howlong.__float__
            except AttributeError:
                raise TypeError('a float is required')
            howlong = f()
            if howlong < 0.0:
                raise ValueError('Timeout value out of range')
        self._faketimeout = howlong

    def gettimeout(self):
        return self._faketimeout

    def _wait(self, watcher, timeout_exc=sock_timeout('timed out')):
        """Block the current greenlet until *watcher* has pending events.

        If *timeout* is non-negative, then *timeout_exc* is raised after *timeout* second has passed.
        By default *timeout_exc* is ``socket.timeout('timed out')``.

        If :func:`cancel_wait` is called, raise ``socket.error(EBADF, 'File descriptor was closed in another greenlet')``.
        """
        assert watcher.callback is None, 'This socket is already used by another greenlet: %r' % (watcher.callback, )
        if self._faketimeout is not None:
            print("TIMEOUT: ", self._faketimeout)
            timeout = Timeout.start_new(self._faketimeout, timeout_exc)

        else:
            timeout = None
        try:
            self.hub.wait(watcher)
        finally:
            if timeout is not None:
                timeout.cancel()

    def accept(self):
        while True:
            try:
                fd, addr = self._accept()
                sock = socket(self.family, self.type, self.proto, fileno=fd)
                break
            except error as e:
                if e.args[0] != EWOULDBLOCK or self._faketimeout == 0.0:
                    raise
            self._wait(self._read_event)
        return sock, addr

    def recv(self, *args):
        while True:
            try:
                return super(socket, self).recv(*args)
            except error as e:
                if e.args[0] == EBADF:
                    return ''
                if e.args[0] != EWOULDBLOCK or self._faketimeout == 0.0:
                    raise
            try:
                self._wait(self._read_event)
            except error as e:
                if e.args[0] == EBADF:
                    return ''
                raise
del sock_timeout

__all__ = __implements__ + __extensions__ + __imports__

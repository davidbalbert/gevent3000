import sys
import socket as __socket__
from gevent.hub import get_hub
from gevent.timeout import Timeout
from gevent.zodiac import rebase

# standard functions and classes that this module re-implements in a gevent-aware way:
__implements__ = ['socket',
                'SocketType']

__rebase__ = ['create_connection',
              'fromfd',
              'socketpair',
              'getfqdn']

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

timeout_default = object()

class socket(__socket__.socket):
    def __init__(self, *args, **kwargs):
        super(socket, self).__init__(*args, **kwargs)
        self.timeout = super(socket, self).gettimeout()
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
            self.timeout = None
        else:
            self.timeout = 0.0

    def settimeout(self, howlong):
        if howlong is not None:
            try:
                f = howlong.__float__
            except AttributeError:
                raise TypeError('a float is required')
            howlong = f()
            if howlong < 0.0:
                raise ValueError('Timeout value out of range')
        self.timeout = howlong

    def gettimeout(self):
        return self.timeout

    def _wait(self, watcher, timeout_exc=sock_timeout('timed out')):
        """Block the current greenlet until *watcher* has pending events.

        If *timeout* is non-negative, then *timeout_exc* is raised after *timeout* second has passed.
        By default *timeout_exc* is ``socket.timeout('timed out')``.

        If :func:`cancel_wait` is called, raise ``socket.error(EBADF, 'File descriptor was closed in another greenlet')``.
        """
        assert watcher.callback is None, 'This socket is already used by another greenlet: %r' % (watcher.callback, )
        if self.timeout is not None:
            timeout = Timeout.start_new(self.timeout, timeout_exc)

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
                if e.args[0] != EWOULDBLOCK or self.timeout == 0.0:
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
                if e.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
            try:
                self._wait(self._read_event)
            except error as e:
                if e.args[0] == EBADF:
                    return ''
                raise

    def recvfrom(self, *args):
        while True:
            try:
                return super(socket, self).recvfrom(*args)
            except error as e:
                if e.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
            self._wait(self._read_event)

    def recvfrom_into(self, *args):
        while True:
            try:
                return super(socket, self).recvfrom_into(*args)
            except error as e:
                if e.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
            self._wait(self._read_event)

    def recv_into(self, *args):
        while True:
            try:
                return super(socket, self).recv_into(*args)
            except error as e:
                if e.args[0] == EBADF:
                    return 0
                if e.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
            try:
                self._wait(self._read_event)
            except error as e:
                if e.args[0] == EBADF:
                    return 0
                raise

    def send(self, data, flags=0, timeout=timeout_default):
        if timeout is timeout_default:
            timeout = self.timeout
        try:
            return super(socket, self).send(data, flags)
        except error as e:
            if e.args[0] != EWOULDBLOCK or timeout == 0.0:
                raise
            try:
                self._wait(self._write_event)
            except error as e:
                if e.args[0] == EBADF:
                    return 0
                raise
            try:
                return super(socket, self).send(data, flags)
            except error as e:
                if e.args[0] == EWOULDBLOCK:
                    return 0
                raise

    def sendall(self, data, flags=0):
        while True:
            try:
                return super(socket, self).sendall(data, flags)
            except error as e:
                if e.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
                try:
                    self._wait(self._write_event)
                except error as e2:
                    if e2.args[0] == EBADF:
                        return 0
                    raise

    def sendto(self, *args):
        try:
            return super(socket, self).sendto(*args)
        except error as e:
            if e.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                raise
            self._wait(self._write_event)
            try:
                return super(socket, self).sendto(*args)
            except error as e2:
                if e2.args[0] == EWOULDBLOCK:
                    return 0
                raise

    def close(self, *args, **kwargs):
        self.hub.cancel_wait(self._read_event, cancel_wait_ex)
        self.hub.cancel_wait(self._write_event, cancel_wait_ex)
        return super(socket, self).close(*args, **kwargs)

    def shutdown(self, how):
        if how == 0:  # SHUT_RD
            self.hub.cancel_wait(self._read_event, cancel_wait_ex)
        elif how == 1:  # SHUT_WR
            self.hub.cancel_wait(self._write_event, cancel_wait_ex)
        else:
            self.hub.cancel_wait(self._read_event, cancel_wait_ex)
            self.hub.cancel_wait(self._write_event, cancel_wait_ex)
        super(socket, self).shutdown(how)

    def connect(self, address):
        if self.timeout == 0.0:
            return super(socket, self).connect(address)
        if isinstance(address, tuple):
            r = getaddrinfo(address[0], address[1], self.family, self.type, self.proto)
            address = r[0][-1]
        if self.timeout is not None:
            timer = Timeout.start_new(self.timeout, timeout('timed out'))
        else:
            timer = None
        try:
            while True:
                err = self.getsockopt(SOL_SOCKET, SO_ERROR)
                if err:
                    raise error(err, strerror(err))
                result = self.connect_ex(address)
                if not result or result == EISCONN:
                    break
                elif (result in (EWOULDBLOCK, EINPROGRESS, EALREADY)) or (result == EINVAL and is_windows):
                    self._wait(self._write_event)
                else:
                    raise error(result, strerror(result))
        finally:
            if timer is not None:
                timer.cancel()


del sock_timeout

for name in __rebase__:
    value = getattr(__socket__, name)
    rebase(value, globals(), name, globals())

class BlockingResolver(object):

    def __init__(self, hub=None):
        pass

    def close(self):
        pass

    for method in ['gethostbyname',
                   'gethostbyname_ex',
                   'getaddrinfo',
                   'gethostbyaddr',
                   'getnameinfo']:
        locals()[method] = staticmethod(getattr(__socket__, method))


def gethostbyname(hostname):
    return get_hub().resolver.gethostbyname(hostname)


def gethostbyname_ex(hostname):
    return get_hub().resolver.gethostbyname_ex(hostname)


def getaddrinfo(host, port, family=0, socktype=0, proto=0, flags=0):
    return get_hub().resolver.getaddrinfo(host, port, family, socktype, proto, flags)


def gethostbyaddr(ip_address):
    return get_hub().resolver.gethostbyaddr(ip_address)


def getnameinfo(sockaddr, flags):
    return get_hub().resolver.getnameinfo(sockaddr, flags)

__all__ = __implements__ + __extensions__ + __imports__

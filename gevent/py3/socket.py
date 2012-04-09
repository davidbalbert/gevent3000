# Copyright (c) 2005-2006, Bob Ippolito
# Copyright (c) 2007, Linden Research, Inc.
# Copyright (c) 2009-2012 Denis Bilenko
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""Cooperative socket module.

This module provides socket operations and some related functions.
The API of the functions and classes matches the API of the corresponding
items in standard :mod:`socket` module exactly, but the synchronous functions
in this module only block the current greenlet and let the others run.

For convenience, exceptions (like :class:`error <socket.error>` and :class:`timeout <socket.timeout>`)
as well as the constants from :mod:`socket` module are imported into this module.
"""

import sys
import time
from gevent.hub import get_hub, basestring, exc_clear
from gevent.six import integer_types, text_type, PY3
from gevent.timeout import Timeout

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

import _socket
__socket__ = __import__('socket')
_real_socket = __socket__.socket

def wait(io, timeout=None, timeout_exc=timeout('timed out')):
    """Block the current greenlet until *io* is ready.

    If *timeout* is non-negative, then *timeout_exc* is raised after *timeout* second has passed.
    By default *timeout_exc* is ``socket.timeout('timed out')``.

    If :func:`cancel_wait` is called, raise ``socket.error(EBADF, 'File descriptor was closed in another greenlet')``.
    """
    assert io.callback is None, 'This socket is already used by another greenlet: %r' % (io.callback, )
    if timeout is not None:
        timeout = Timeout.start_new(timeout, timeout_exc)
    try:
        return get_hub().wait(io)
    finally:
        if timeout is not None:
            timeout.cancel()
    # rename "io" to "watcher" because wait() works with any watcher


def wait_read(fileno, timeout=None, timeout_exc=timeout('timed out')):
    """Block the current greenlet until *fileno* is ready to read.

    If *timeout* is non-negative, then *timeout_exc* is raised after *timeout* second has passed.
    By default *timeout_exc* is ``socket.timeout('timed out')``.

    If :func:`cancel_wait` is called, raise ``socket.error(EBADF, 'File descriptor was closed in another greenlet')``.
    """
    io = get_hub().loop.io(fileno, 1)
    return wait(io, timeout, timeout_exc)


def wait_write(fileno, timeout=None, timeout_exc=timeout('timed out'), event=None):
    """Block the current greenlet until *fileno* is ready to write.

    If *timeout* is non-negative, then *timeout_exc* is raised after *timeout* second has passed.
    By default *timeout_exc* is ``socket.timeout('timed out')``.

    If :func:`cancel_wait` is called, raise ``socket.error(EBADF, 'File descriptor was closed in another greenlet')``.
    """
    io = get_hub().loop.io(fileno, 2)
    return wait(io, timeout, timeout_exc)


def wait_readwrite(fileno, timeout=None, timeout_exc=timeout('timed out'), event=None):
    """Block the current greenlet until *fileno* is ready to read or write.

    If *timeout* is non-negative, then *timeout_exc* is raised after *timeout* second has passed.
    By default *timeout_exc* is ``socket.timeout('timed out')``.

    If :func:`cancel_wait` is called, raise ``socket.error(EBADF, 'File descriptor was closed in another greenlet')``.
    """
    io = get_hub().loop.io(fileno, 3)
    return wait(io, timeout, timeout_exc)


cancel_wait_ex = error(EBADF, 'File descriptor was closed in another greenlet')


def cancel_wait(watcher):
    get_hub().cancel_wait(watcher, cancel_wait_ex)


if sys.version_info[:2] < (2, 7):
    _get_memory = buffer
elif sys.version_info[:2] < (3, 0):
    def _get_memory(string, offset):
        try:
            return memoryview(string)[offset:]
        except TypeError:
            return buffer(string, offset)
else:
    def _get_memory(string, offset):
        return memoryview(string)[offset:]

timeout_default = object()

class socket(_real_socket):

    def __init__(self, *args, **kwargs):
		_real_socket.__init__(self, *args, **kwargs)

        self.timeout = getattr(self, 'timeout', False)
        if self.timeout is False:
            self.timeout = _socket.getdefaulttimeout()

        self.setblocking(0)
        self.hub = get_hub()
        io = self.hub.loop.io
        self._read_event = io(fileno, 1)
        self._write_event = io(fileno, 2)
        
    def _wait(self, watcher, timeout_exc=timeout('timed out')):
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
                if PY3:
                    fd, address = self._accept()
                    client_socket = socket(self.family, self.type, self.proto, fd)
                else:
                    sock, address = self._sock.accept(self)
                    client_socket = socket(_sock=sock)
                break
            except error:
                ex = sys.exc_info()[1]
                if ex.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
                exc_clear()
            self._wait(self._read_event)
        return client_socket, address

    def close(self, *args, **kwargs):
		_real_socket.close(selfi, *args, **kwargs)

        self.hub.cancel_wait(self._read_event, cancel_wait_ex)
        self.hub.cancel_wait(self._write_event, cancel_wait_ex)

    def connect(self, address):
        if self.timeout == 0.0:
            return _real_socket.connect(self, address)
        if isinstance(address, tuple):
            r = getaddrinfo(address[0], address[1], self.family, self.type, self.proto)
            address = r[0][-1]
        if self.timeout is not None:
            timer = Timeout.start_new(self.timeout, timeout('timed out'))
        else:
            timer = None
        try:
            while True:
                err = sock.getsockopt(SOL_SOCKET, SO_ERROR)
                if err:
                    raise error(err, strerror(err))
                result = self.connect_ex(self, address)
                if not result or result == EISCONN:
                    break
                elif (result in (EWOULDBLOCK, EINPROGRESS, EALREADY)) or (result == EINVAL and is_windows):
                    self._wait(self._write_event)
                else:
                    raise error(result, strerror(result))
        finally:
            if timer is not None:
                timer.cancel()

    def connect_ex(self, address):
        try:
            return _real_socket.connect(self, address) or 0
        except timeout:
            return EAGAIN
        except error:
            ex = sys.exc_info()[1]
            if type(ex) is error:
                return ex.args[0]
            else:
                raise  # gaierror is not silented by connect_ex

    def dup(self):
        if PY3:
            return _real_socket.dup(self)
        else:
            return socket(_sock=sock)
        return socket(_sock=self._sock)

    def recv(self, *args):
        while True:
            try:
                return _real_socket.recv(self, *args)
            except error:
                ex = sys.exc_info()[1]
                if ex.args[0] == EBADF:
                    return ''
                if ex.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
                # QQQ without clearing exc_info test__refcount.test_clean_exit fails
                exc_clear()
            try:
                self._wait(self._read_event)
            except error:
                ex = sys.exc_info()[1]
                if ex.args[0] == EBADF:
                    return ''
                raise

    def recvfrom(self, *args):
        while True:
            try:
                return _real_socket.recvfrom(self, *args)
            except error:
                ex = sys.exc_info()[1]
                if ex.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
                exc_clear()
            self._wait(self._read_event)

    def recvfrom_into(self, *args):
        while True:
            try:
                return _real_socket.recvfrom_into(self, *args)
            except error:
                ex = sys.exc_info()[1]
                if ex.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
                exc_clear()
            self._wait(self._read_event)

    def recv_into(self, *args):
        while True:
            try:
                return _real_socket.recv_into(self, *args)
            except error:
                ex = sys.exc_info()[1]
                if ex.args[0] == EBADF:
                    return 0
                if ex.args[0] != EWOULDBLOCK or self.timeout == 0.0:
                    raise
                exc_clear()
            try:
                self._wait(self._read_event)
            except error:
                ex = sys.exc_info()[1]
                if ex.args[0] == EBADF:
                    return 0
                raise

    def send(self, data, flags=0, timeout=timeout_default):
        if timeout is timeout_default:
            timeout = self.timeout
        try:
            return _real_socket.send(self, data, flags)
        except error:
            ex = sys.exc_info()[1]
            if ex.args[0] != EWOULDBLOCK or timeout == 0.0:
                raise
            exc_clear()
            try:
                self._wait(self._write_event)
            except error:
                ex = sys.exc_info()[1]
                if ex.args[0] == EBADF:
                    return 0
                raise
            try:
                return _real_socket.send(self, data, flags)
            except error:
                ex2 = sys.exc_info()[1]
                if ex2.args[0] == EWOULDBLOCK:
                    return 0
                raise

    def sendall(self, data, flags=0):
        if isinstance(data, text_type):
            data = data.encode()
        # this sendall is also reused by gevent.ssl.SSLSocket subclass,
        # so it should not call self._sock methods directly
        if self.timeout is None:
            data_sent = 0
            while data_sent < len(data):
                data_sent += self.send(_get_memory(data, data_sent), flags)
        else:
            timeleft = self.timeout
            end = time.time() + timeleft
            data_sent = 0
            while True:
                data_sent += self.send(_get_memory(data, data_sent), flags, timeout=timeleft)
                if data_sent >= len(data):
                    break
                timeleft = end - time.time()
                if timeleft <= 0:
                    raise timeout('timed out')

    def sendto(self, *args):
        try:
            return _real_socket.sendto(self, *args)
        except error:
            ex = sys.exc_info()[1]
            if ex.args[0] != EWOULDBLOCK or timeout == 0.0:
                raise
            exc_clear()
            self._wait(self._write_event)
            try:
                return _real_socket.sendto(self, *args)
            except error:
                ex2 = sys.exc_info()[1]
                if ex2.args[0] == EWOULDBLOCK:
                    return 0
                raise

    def shutdown(self, how):
        if how == 0:  # SHUT_RD
            self.hub.cancel_wait(self._read_event, cancel_wait_ex)
        elif how == 1:  # SHUT_WR
            self.hub.cancel_wait(self._write_event, cancel_wait_ex)
        else:
            self.hub.cancel_wait(self._read_event, cancel_wait_ex)
            self.hub.cancel_wait(self._write_event, cancel_wait_ex)
        _real_socket.shutdown(self, how)

SocketType = socket

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
        locals()[method] = staticmethod(getattr(_socket, method))


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

#TODO move this into init.py so that the patch can be built first
#if not PY3:
#	try:
#		from gevent.ssl import sslwrap_simple as ssl, SSLError as sslerror, SSLSocket as SSLType
#		_have_ssl = True
#	except ImportError:
#		_have_ssl = False

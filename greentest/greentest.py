# Copyright (c) 2008-2009 AG Projects
# Author: Denis Bilenko
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

# package is named greentest, not test, so it won't be confused with test in stdlib
from __future__ import with_statement
import sys
import unittest
from unittest import TestCase as BaseTestCase
import time
import os
from os.path import basename, splitext
import gevent
from patched_tests_setup import get_switch_expected
from gevent.hub import _get_hub, PY3

from functools import wraps

VERBOSE = sys.argv.count('-v') > 1

if '--debug-greentest' in sys.argv:
    sys.argv.remove('--debug-greentest')
    DEBUG = True
else:
    DEBUG = False

gettotalrefcount = getattr(sys, 'gettotalrefcount', None)


def wrap_timeout(timeout, method):
    if timeout is None:
        return method
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with gevent.Timeout(timeout, 'test timed out'):
            return method(self, *args, **kwargs)
    return wrapped


def wrap_refcount(method):
    if gettotalrefcount is None:
        return method
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        import gc
        gc.disable()
        gc.collect()
        deltas = []
        d = None
        try:
            while True:
                d = gettotalrefcount()
                method(self, *args, **kwargs)
                if hasattr(self, 'cleanup'):
                    self.cleanup()
                if 'urlparse' in sys.modules:
                    sys.modules['urlparse'].clear_cache()
                d = gettotalrefcount() - d
                deltas.append(d)
                if 2 <= len(deltas) <= 3 and deltas[-2:] == [0, 0]:
                    break
                if 3 <= len(deltas) and deltas[-3:] == [0, 0, 0]:
                    break
                if len(deltas) >= 6:
                    raise AssertionError('refcount increased by %r' % (deltas, ))
        finally:
            gc.collect()
            gc.enable()
    return wrapped


def wrap_error_fatal(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        SYSTEM_ERROR = gevent.get_hub().SYSTEM_ERROR
        gevent.get_hub().SYSTEM_ERROR = object
        try:
            return method(self, *args, **kwargs)
        finally:
            gevent.get_hub().SYSTEM_ERROR = SYSTEM_ERROR
    return wrapped


def wrap_restore_handle_error(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        old = gevent.get_hub().handle_error
        try:
            return method(self, *args, **kwargs)
        finally:
            gevent.get_hub().handle_error = old
        if self.peek_error()[0] is not None:
            gevent.getcurrent().throw(*self.peek_error()[1:])
    return wrapped


def _get_class_attr(classDict, bases, attr, default=AttributeError):
    NONE = object()
    value = classDict.get(attr, NONE)
    if value is not NONE:
        return value
    for base in bases:
        value = getattr(bases[0], attr, NONE)
        if value is not NONE:
            return value
    if default is AttributeError:
        raise AttributeError('Attribute %r not found\n%s\n%s\n' % (attr, classDict, bases))
    return default


class TestCaseMetaClass(type):
    # wrap each test method with
    # a) timeout check
    # b) totalrefcount check
    def __new__(meta, classname, bases, classDict):
        timeout = classDict.get('__timeout__', 'NONE')
        if timeout == 'NONE':
            timeout = getattr(bases[0], '__timeout__', None)
            if gettotalrefcount is not None and timeout is not None:
                timeout *= 6
        check_totalrefcount = _get_class_attr(classDict, bases, 'check_totalrefcount', True)
        error_fatal = _get_class_attr(classDict, bases, 'error_fatal', True)
        for key, value in classDict.items():
            if key.startswith('test') and callable(value):
                classDict.pop(key)
                value = wrap_timeout(timeout, value)
                my_error_fatal = getattr(value, 'error_fatal', None)
                if my_error_fatal is None:
                    my_error_fatal = error_fatal
                if my_error_fatal:
                    value = wrap_error_fatal(value)
                value = wrap_restore_handle_error(value)
                if check_totalrefcount:
                    value = wrap_refcount(value)
                classDict[key] = value
        return type.__new__(meta, classname, bases, classDict)


class TestCase(BaseTestCase):

    __metaclass__ = TestCaseMetaClass
    __timeout__ = 1
    switch_expected = 'default'
    error_fatal = True

    def run(self, *args, **kwargs):
        if self.switch_expected == 'default':
            self.switch_expected = get_switch_expected(self.fullname)
        return BaseTestCase.run(self, *args, **kwargs)

    def setUp(self):
        self.initial_switch_count = getattr(_get_hub(), 'switch_count', None)

    def tearDown(self):
        if hasattr(self, 'cleanup'):
            self.cleanup()
        if self.switch_count is not None:
            if self.switch_count < 0:
                raise AssertionError('hub.switch_count decreased???')
            if self.switch_expected is None:
                pass
            elif self.switch_expected is True:
                if self.switch_count <= 0:
                    raise AssertionError('%s did not switch' % self.testcasename)
            elif self.switch_expected is False:
                if self.switch_count:
                    raise AssertionError('%s switched but not expected to' % self.testcasename)
            else:
                raise AssertionError('Invalid value for switch_expected: %r' % (self.switch_expected, ))

    @property
    def switch_count(self):
        if self.switch_expected is None:
            return
        if not hasattr(self, 'initial_switch_count'):
            raise AssertionError('Cannot check switch_count (setUp() was not called)')
        if self.initial_switch_count is None:
            return
        current = getattr(_get_hub(), 'switch_count', 0)
        return current - self.initial_switch_count

    @property
    def testname(self):
        return getattr(self, '_testMethodName', '') or getattr(self, '_TestCase__testMethodName')

    @property
    def testcasename(self):
        return self.__class__.__name__ + '.' + self.testname

    @property
    def modulename(self):
        return os.path.basename(sys.modules[self.__class__.__module__].__file__).rsplit('.', 1)[0]

    @property
    def fullname(self):
        return splitext(basename(self.modulename))[0] + '.' + self.testcasename

    _none = (None, None, None)
    _error = _none

    def expect_one_error(self):
        assert self._error == self._none, self._error
        self._old_handle_error = gevent.get_hub().handle_error
        gevent.get_hub().handle_error = self._store_error

    def _store_error(self, where, type, value, tb):
        del tb
        if self._error != self._none:
            gevent.get_hub().parent.throw(type, value)
        else:
            self._error = (where, type, value)

    def peek_error(self):
        return self._error

    def get_error(self):
        try:
            return self._error
        finally:
            self._error = self._none

    def assert_error(self, type=None, value=None, error=None):
        if error is None:
            error = self.get_error()
        if type is not None:
           assert error[1] is type, error
        if value is not None:
            if isinstance(value, str):
                assert str(error[2]) == value, error
            else:
                assert error[2] is value, error
        return error


main = unittest.main
_original_Hub = gevent.hub.Hub


class CountingHub(_original_Hub):

    switch_count = 0

    def switch(self, *args):
        self.switch_count += 1
        return _original_Hub.switch(self, *args)

if gettotalrefcount is None:
    gevent.hub.Hub = CountingHub


def test_outer_timeout_is_not_lost(self):
    timeout = gevent.Timeout.start_new(0.001)
    try:
        try:
            result = self.wait(timeout=1)
        except gevent.Timeout:
            ex = sys.exc_info()[1]
            assert ex is timeout, (ex, timeout)
        else:
            raise AssertionError('must raise Timeout (returned %r)' % (result, ))
    finally:
        timeout.cancel()


class GenericWaitTestCase(TestCase):

    def wait(self, timeout):
        raise NotImplementedError('override me in subclass')

    test_outer_timeout_is_not_lost = test_outer_timeout_is_not_lost

    def test_returns_none_after_timeout(self):
        start = time.time()
        result = self.wait(timeout=0.02)
        # join and wait simply returns after timeout expires
        delay = time.time() - start
        assert 0.02 - 0.002 <= delay < 0.02 + 0.02, delay
        assert result is None, repr(result)


class GenericGetTestCase(TestCase):

    Timeout = gevent.Timeout

    def wait(self, timeout):
        raise NotImplementedError('override me in subclass')

    def cleanup(self):
        pass

    test_outer_timeout_is_not_lost = test_outer_timeout_is_not_lost

    def test_raises_timeout_number(self):
        start = time.time()
        self.assertRaises(self.Timeout, self.wait, timeout=0.01)
        # get raises Timeout after timeout expired
        delay = time.time() - start
        assert 0.01 - 0.001 <= delay < 0.01 + 0.01 + 0.1, delay
        self.cleanup()

    def test_raises_timeout_Timeout(self):
        start = time.time()
        timeout = gevent.Timeout(0.01)
        try:
            self.wait(timeout=timeout)
        except gevent.Timeout:
            ex = sys.exc_info()[1]
            assert ex is timeout, (ex, timeout)
        delay = time.time() - start
        assert 0.01 - 0.001 <= delay < 0.01 + 0.01 + 0.1, delay
        self.cleanup()

    def test_raises_timeout_Timeout_exc_customized(self):
        start = time.time()
        error = RuntimeError('expected error')
        timeout = gevent.Timeout(0.01, exception=error)
        try:
            self.wait(timeout=timeout)
        except RuntimeError:
            ex = sys.exc_info()[1]
            assert ex is error, (ex, error)
        delay = time.time() - start
        assert 0.01 - 0.001 <= delay < 0.01 + 0.01 + 0.1, delay
        self.cleanup()


class ExpectedException(Exception):
    """An exception whose traceback should be ignored"""


def walk_modules(basedir=None, modpath=None, include_so=False):
    if basedir is None:
        basedir = os.path.dirname(gevent.__file__)
        if modpath is None:
            modpath = 'gevent.'
    else:
        if modpath is None:
            modpath = ''
    for fn in sorted(os.listdir(basedir)):
        if (fn in ['py2', 'py3']):
            continue

        path = os.path.join(basedir, fn)
        if os.path.isdir(path):
            pkg_init = os.path.join(path, '__init__.py')
            if os.path.exists(pkg_init):
                yield pkg_init, modpath + fn
                for p, m in walk_modules(path, modpath + fn + "."):
                    yield p, m
            continue
        if fn.endswith('.py') and fn not in ['__init__.py', 'core.py', 'ares.py']:
            yield path, modpath + fn[:-3]
        elif include_so and fn.endswith('.so'):
            if fn.endswith('_d.so'):
                yield path, modpath + fn[:-5]
            else:
                yield path, modpath + fn[:-3]


def bind_and_listen(sock, address=('', 0), backlog=50, reuse_addr=True):
    from socket import SOL_SOCKET, SO_REUSEADDR, error
    if reuse_addr:
        try:
            sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, sock.getsockopt(SOL_SOCKET, SO_REUSEADDR) | 1)
        except error:
            pass
    sock.bind(address)
    sock.listen(backlog)


def tcp_listener(address, backlog=50, reuse_addr=True):
    """A shortcut to create a TCP socket, bind it and put it into listening state."""
    from gevent import socket
    sock = socket.socket()
    bind_and_listen(sock)
    return sock

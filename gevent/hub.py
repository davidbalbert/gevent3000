# Copyright (c) 2009 Denis Bilenko. See LICENSE for details.

import sys
import os
import traceback
from gevent import core


__all__ = ['getcurrent',
           'GreenletExit',
           'spawn_raw',
           'sleep',
           'kill',
           'signal',
           'fork',
           'shutdown']


try:
    from py.magic import greenlet
except ImportError:
    greenlet = __import__('greenlet').greenlet

getcurrent = greenlet.getcurrent
GreenletExit = greenlet.GreenletExit
MAIN = greenlet.getcurrent()

thread = __import__('thread')
threadlocal = thread._local
_threadlocal = threadlocal()
_threadlocal.Hub = None
try:
    _original_fork = os.fork
except AttributeError:
    _original_fork = None
    __all__.remove('fork')


def _switch_helper(function, args, kwargs):
    # work around the fact that greenlet.switch does not support keyword args
    return function(*args, **kwargs)


def spawn_raw(function, *args, **kwargs):
    if kwargs:
        g = greenlet(_switch_helper, get_hub())
        core.active_event(g.switch, function, args, kwargs)
        return g
    else:
        g = greenlet(function, get_hub())
        core.active_event(g.switch, *args)
        return g


def sleep(seconds=0):
    """Yield control to another eligible coroutine until at least *seconds* have
    elapsed.

    *seconds* may be specified as an integer, or a float if fractional seconds
    are desired. Calling sleep with *seconds* of 0 is the canonical way of
    expressing a cooperative yield. For example, if one is looping over a
    large list performing an expensive calculation without calling any socket
    methods, it's a good idea to call ``sleep(0)`` occasionally; otherwise
    nothing else will run.
    """
    unique_mark = object()
    t = core.timer(seconds, getcurrent().switch, unique_mark)
    try:
        switch_result = get_hub().switch()
        assert switch_result is unique_mark, 'Invalid switch into sleep(): %r' % (switch_result, )
    except:
        t.cancel()
        raise


def kill(greenlet, exception=GreenletExit):
    """Kill greenlet asynchronously. The current greenlet is not unscheduled.

    Note, that Greenlet's kill() method does the same and more. However, MAIN
    greenlet does not have kill() method so you have to use this function.
    """
    if not greenlet.dead:
        core.active_event(greenlet.throw, exception)


def signal(signalnum, handler, *args, **kwargs):
    def deliver_exception_to_MAIN():
        try:
            handler(*args, **kwargs)
        except:
            MAIN.throw(*sys.exc_info())
    return core.signal(signalnum, deliver_exception_to_MAIN)


if _original_fork is not None:

    def fork():
        result = _original_fork()
        core.reinit()
        return result


def shutdown():
    """Cancel our CTRL-C handler and wait for core.dispatch() to return."""
    global _threadlocal
    hub = _threadlocal.__dict__.get('hub')
    if hub is not None and not hub.dead:
        hub.shutdown()


def get_hub():
    global _threadlocal
    try:
        return _threadlocal.hub
    except AttributeError:
        try:
            hubtype = _threadlocal.Hub
        except AttributeError:
            # do not pretend to support multiple threads because it's not implemented properly by core.pyx
            # this may change in the future, although currently I don't have a strong need for this
            raise NotImplementedError('gevent is only usable from a single thread')
        if hubtype is None:
            hubtype = Hub
        hub = _threadlocal.hub = hubtype()
        return hub


class Hub(greenlet):

    def __init__(self):
        self.keyboard_interrupt_signal = None

    def switch(self):
        cur = getcurrent()
        assert cur is not self, 'Cannot switch to MAINLOOP from MAINLOOP'
        switch_out = getattr(cur, 'switch_out', None)
        if switch_out is not None:
            try:
                switch_out()
            except:
                traceback.print_exc()
        return greenlet.switch(self)

    def run(self):
        global _threadlocal
        assert self is getcurrent(), 'Do not call run() directly'
        self.keyboard_interrupt_signal = signal(2, MAIN.throw, KeyboardInterrupt)
        try:
            loop_count = 0
            while True:
                try:
                    result = core.dispatch()
                except IOError, ex:
                    loop_count += 1
                    if loop_count > 15:
                        raise
                    sys.stderr.write('Restarting gevent.core.dispatch() after an error [%s]: %s\n' % (loop_count, ex))
                    continue
                raise DispatchExit(result)
        finally:
            if self.keyboard_interrupt_signal is not None:
                self.keyboard_interrupt_signal.cancel()
                self.keyboard_interrupt_signal = None
            if _threadlocal.__dict__.get('hub') is self:
                _threadlocal.__dict__.pop('hub')

    def shutdown(self):
        assert getcurrent() is MAIN, "Shutting down is only possible from MAIN greenlet"
        if self.keyboard_interrupt_signal is not None:
            self.keyboard_interrupt_signal.cancel()
            self.keyboard_interrupt_signal = None
        core.dns_shutdown()
        try:
            self.switch()
        except DispatchExit, ex:
            if ex.code == 1:
                return
            raise


class DispatchExit(Exception):
    
    def __init__(self, code):
        self.code = code
        Exception.__init__(self, code)


class Waiter(object):
    """A low level synchronization class.

    Wrapper around switch() and throw() calls that makes them safe:
    a) switching will occur only if the waiting greenlet is executing wait()
       method currently. Otherwise, switch() and throw() are no-ops.
    b) any error raised in the greenlet is handled inside switch() and throw()

    switch and throw methods must only be called from the mainloop greenlet.
    wait must be called from a greenlet other than mainloop.
    """
    __slots__ = ['greenlet']

    def __init__(self):
        self.greenlet = None

    def __repr__(self):
        if self.waiting:
            waiting = ' waiting'
        else:
            waiting = ''
        return '<%s at %s%s greenlet=%r>' % (type(self).__name__, hex(id(self)), waiting, self.greenlet)

    def __str__(self):
        """
        >>> print Waiter()
        <Waiter greenlet=None>
        """
        if self.waiting:
            waiting = ' waiting'
        else:
            waiting = ''
        return '<%s%s greenlet=%s>' % (type(self).__name__, waiting, self.greenlet)

    def __nonzero__(self):
        return self.greenlet is not None

    @property
    def waiting(self):
        return self.greenlet is not None

    def switch(self, value=None):
        """Wake up the greenlet that is calling wait() currently (if there is one).
        Can only be called from Hub's greenlet.
        """
        assert greenlet.getcurrent() is get_hub(), "Can only use Waiter.switch method from the mainloop"
        if self.greenlet is not None:
            try:
                self.greenlet.switch(value)
            except:
                traceback.print_exc()

    def throw(self, *throw_args):
        """Make greenlet calling wait() wake up (if there is a wait()).
        Can only be called from Hub's greenlet.
        """
        assert greenlet.getcurrent() is get_hub(), "Can only use Waiter.switch method from the mainloop"
        if self.greenlet is not None:
            try:
                self.greenlet.throw(*throw_args)
            except:
                traceback.print_exc()

    # QQQ should be renamed to get() ? and the whole class is called Receiver?
    def wait(self):
        """Wait until switch() or throw() is called.
        """
        assert self.greenlet is None, 'This Waiter is already used by %r' % (self.greenlet, )
        self.greenlet = greenlet.getcurrent()
        try:
            return get_hub().switch()
        finally:
            self.greenlet = None


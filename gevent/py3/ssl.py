import ssl as __ssl__
from gevent.zodiac import rebase
from gevent.socket import socket, timeout_default

__implements__ = ['SSLSocket']

__rebase__ = ['SSLContext',
              'wrap_socket',
              'get_server_certificate']

__implements__ = __implements__ + __rebase__

__imports__ = ['SSLError',
               'CertificateError',
               'match_hostname',
               'RAND_status',
               'RAND_egd',
               'RAND_add',
               'cert_time_to_seconds',
               'get_protocol_name',
               'DER_cert_to_PEM_cert',
               'PEM_cert_to_DER_cert']

for name in __imports__[:]:
    value = getattr(__ssl__, name)
    globals()[name] = value

for name in dir(__ssl__):
    if not name.startswith('_'):
        value = getattr(__ssl__, name)
        if isinstance(value, (int, bytes, str, tuple)):
            globals()[name] = value
            __imports__.append(name)

rebase(__ssl__.SSLSocket, globals(), '_SSLSocket', globals())

class SSLSocket(_SSLSocket):

    def _handle_wait_exc(self, e, timeout):
        errno = e.args[0]
        if errno in [SSL_ERROR_WANT_READ, SSL_ERROR_WANT_WRITE] and self.timeout != 0.0:
            try:
                event = self._read_event if errno == SSL_ERROR_WANT_READ else self._write_event
                self._wait(event, timeout_exc=_SSLErrorReadTimeout)
            except socket_error as ex:
                if ex.args[0] == EBADF:
                    return ''
        else:
            raise

    def read(self, len=0, buffer=None):
        """Read up to LEN bytes and return them.
        Return zero-length string on EOF."""
        while True:
            try:
                return super(SSLSocket, self).read(len, buffer, flags)
            except SSLError as e:
                self._handle_wait_exc(e, self.timeout)
                
    def write(self, data):
        """Read up to LEN bytes and return them.
        Return zero-length string on EOF."""
        while True:
            try:
                return super(SSLSocket, self).write(data)
            except SSLError as e:
                self._handle_wait_exc(e, self.timeout)

    def send(self, data, flags=0, timeout=timeout_default):
        if timeout is timeout_default:
            timeout = self.timeout
        if self._sslobj:
            if flags != 0:
                raise ValueError(
                    "non-zero flags not allowed in calls to send() on %s" %
                    self.__class__)
            while True:
                try:
                    v = self._sslobj.write(data)
                except SSLError as e:
                    errno = e.args[0]
                    if errno in [SSL_ERROR_WANT_READ, SSL_ERROR_WANT_WRITE] and timeout == 0.0:
                        return 0
                    self._handle_wait_exc(e, timeout)
                else:
                    return v
        else:
            return socket.send(self, data, flags, timeout)

    def _sslobj_shutdown(self):
        while True:
            try:
                return self._sslobj.shutdown()
            except SSLError as e:
                if e.args[0] == SSL_ERROR_EOF and self.suppress_ragged_eofs:
                    return ''
                self._handle_wait_exc(e, self.timeout)

    #TODO: make sure that returning s is okay here; 
    # that is, make sure shutdown returns a gevent socket
    def unwrap(self):
        if self._sslobj:
            s = self._sslobj_shutdown()
            self._sslobj = None
            return s
        else:
            raise ValueError("No SSL wrapper around " + str(self))

for name in __rebase__:
    value = getattr(__ssl__, name)
    rebase(value, globals(), name, globals())

del name, value

__all__ = __implements__ + __imports__

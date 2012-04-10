import ssl as __ssl__
from gevent.zodiac import rebase

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
    try:
        value = getattr(__ssl__, name)
        globals()[name] = value
    except AttributeError:
        __imports__.remove(name)

for name in dir(__ssl__):
    if not name.startswith('_'):
        value = getattr(__ssl__, name)
        if isinstance(value, (int, bytes, str, tuple)):
            globals()[name] = value
            __imports__.append(name)

rebase(__socket__.SSLSocket, globals(), '_SSLSocket', globals())

class SSLSocket(_SSLSocket):

    def read(self, len=1024):
        """Read up to LEN bytes and return them.
        Return zero-length string on EOF."""
        while True:
            try:
                return super(SSLSocket, self).read(len)
            except SSLError as e:
				errno = ex.args[0]
                if errno in [SSL_ERROR_WANT_READ, SSL_ERROR_WANT_WRITE] and self.timeout != 0.0:
                    try:
						event = self._read_event if errno == SSL_ERROR_WANT_READ else self._write_event
                        self._wait(event, timeout_exc=_SSLErrorReadTimeout)
                    except socket_error as ex:
                        if ex.args[0] == EBADF:
                            return ''
                else:
                    raise
				
    def write(self, data):
        """Read up to LEN bytes and return them.
        Return zero-length string on EOF."""
        while True:
            try:
                return super(SSLSocket, self).write(data)
            except SSLError as e:
				errno = ex.args[0]
                if errno in [SSL_ERROR_WANT_READ, SSL_ERROR_WANT_WRITE] and self.timeout != 0.0:
                    try:
						event = self._read_event if errno == SSL_ERROR_WANT_READ else self._write_event
                        self._wait(event, timeout_exc=_SSLErrorWriteTimeout)
                    except socket_error as ex:
                        if ex.args[0] == EBADF:
                            return ''
                else:
                    raise

    #etc

for name in __rebase__:
    value = getattr(__ssl__, name)
    rebase(value, globals(), name, globals())

del name, value

__all__ = __implements__ + __imports__

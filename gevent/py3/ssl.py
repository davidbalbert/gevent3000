import ssl as __ssl__
from gevent.zodiac import rebase

__implements__ = ['SSLSocket',
                  'wrap_socket',
                  'get_server_certificate']

__imports__ = ['SSLContext',
               'SSLError',
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

for name in __implements__:
    value = getattr(__ssl__, name)
    rebase(value, globals(), name, globals())

del name, value

__all__ = __implements__ + __imports__

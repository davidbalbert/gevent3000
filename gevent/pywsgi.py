# Copyright (c) 2005-2009, eventlet contributors
# Copyright (c) 2009-2011, gevent contributors

import errno
import sys
import time
import traceback
try:
    import mimetools as mime
except ImportError:
    import email.message as mime
from datetime import datetime
try:
    from urllib import unquote
except ImportError:
    from urllib.parse import unquote

from gevent import socket
import gevent
from gevent.server import StreamServer
from gevent.hub import GreenletExit, exc_clear


__all__ = ['WSGIHandler', 'WSGIServer']


MAX_REQUEST_LINE = 8192
# Weekday and month names for HTTP date/time formatting; always English!
_WEEKDAYNAME = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHNAME = [None,  # Dummy so we can use 1-based month numbers
              "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_INTERNAL_ERROR_STATUS = '500 Internal Server Error'
_INTERNAL_ERROR_BODY = 'Internal Server Error'
_INTERNAL_ERROR_HEADERS = [('Content-Type', 'text/plain'),
                           ('Connection', 'close'),
                           ('Content-Length', str(len(_INTERNAL_ERROR_BODY)))]
_REQUEST_TOO_LONG_RESPONSE = "HTTP/1.0 414 Request URI Too Long\r\nConnection: close\r\nContent-length: 0\r\n\r\n"
_BAD_REQUEST_RESPONSE = "HTTP/1.0 400 Bad Request\r\nConnection: close\r\nContent-length: 0\r\n\r\n"
_CONTINUE_RESPONSE = "HTTP/1.1 100 Continue\r\n\r\n"


def format_date_time(timestamp):
    year, month, day, hh, mm, ss, wd, _y, _z = time.gmtime(timestamp)
    return "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (_WEEKDAYNAME[wd], day, _MONTHNAME[month], year, hh, mm, ss)


class Input(object):

    def __init__(self, rfile, content_length, socket=None, chunked_input=False):
        self.rfile = rfile
        self.content_length = content_length
        self.socket = socket
        self.position = 0
        self.chunked_input = chunked_input
        self.chunk_length = -1

    def _discard(self):
        if self.socket is None and (self.position < (self.content_length or 0) or self.chunked_input):
            # ## Read and discard body
            while 1:
                d = self.read(16384)
                if not d:
                    break

    def _send_100_continue(self):
        if self.socket is not None:
            self.socket.sendall(_CONTINUE_RESPONSE)
            self.socket = None

    def _do_read(self, length=None, use_readline=False):
        if use_readline:
            reader = self.rfile.readline
        else:
            reader = self.rfile.read
        content_length = self.content_length
        if content_length is None:
            # Either Content-Length or "Transfer-Encoding: chunked" must be present in a request with a body
            # if it was chunked, then this function would have not been called
            return ''
        self._send_100_continue()
        left = content_length - self.position
        if length is None:
            length = left
        elif length > left:
            length = left
        if not length:
            return ''
        read = reader(length)
        self.position += len(read)
        if len(read) < length:
            if (use_readline and not read.endswith("\n")) or not use_readline:
                raise IOError("unexpected end of file while reading request at position %s" % (self.position,))

        return read

    def _chunked_read(self, length=None, use_readline=False):
        rfile = self.rfile
        self._send_100_continue()

        if length == 0:
            return ""

        if length < 0:
            length = None

        if use_readline:
            reader = self.rfile.readline
        else:
            reader = self.rfile.read

        response = []
        while self.chunk_length != 0:
            maxreadlen = self.chunk_length - self.position
            if length is not None and length < maxreadlen:
                maxreadlen = length

            if maxreadlen > 0:
                data = reader(maxreadlen)
                if not data:
                    self.chunk_length = 0
                    raise IOError("unexpected end of file while parsing chunked data")

                datalen = len(data)
                response.append(data)

                self.position += datalen
                if self.chunk_length == self.position:
                    rfile.readline()

                if length is not None:
                    length -= datalen
                    if length == 0:
                        break
                if use_readline and data[-1] == "\n":
                    break
            else:
                line = rfile.readline()
                if not line.endswith("\n"):
                    self.chunk_length = 0
                    raise IOError("unexpected end of file while reading chunked data header")
                self.chunk_length = int(line.split(";", 1)[0], 16)
                self.position = 0
                if self.chunk_length == 0:
                    rfile.readline()
        return ''.join(response)

    def read(self, length=None):
        if self.chunked_input:
            return self._chunked_read(length)
        return self._do_read(length)

    def readline(self, size=None):
        if self.chunked_input:
            return self._chunked_read(size, True)
        else:
            return self._do_read(size, use_readline=True)

    def readlines(self, hint=None):
        return list(self)

    def __iter__(self):
        return self

    def next(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class WSGIHandler(object):
    protocol_version = 'HTTP/1.1'
    MessageClass = mime.Message

    def __init__(self, socket, address, server, rfile=None):
        self.socket = socket
        self.client_address = address
        self.server = server
        if rfile is None:
            self.rfile = socket.makefile('rb', -1)
        else:
            self.rfile = rfile

    def handle(self):
        try:
            while self.socket is not None:
                self.time_start = time.time()
                self.time_finish = 0
                result = self.handle_one_request()
                if result is None:
                    break
                if result is True:
                    continue
                self.status, response_body = result
                self.socket.sendall(response_body)
                if self.time_finish == 0:
                    self.time_finish = time.time()
                self.log_request()
                break
        finally:
            if self.socket is not None:
                try:
                    if hasattr(self.socket, '_sock'):
                        self.socket._sock.close()  # do not rely on garbage collection
                    self.socket.close()
                except socket.error:
                    pass
            self.__dict__.pop('socket', None)
            self.__dict__.pop('rfile', None)

    def _check_http_version(self):
        version = self.request_version
        if not version.startswith("HTTP/"):
            return False
        version = tuple(int(x) for x in version[5:].split("."))  # "HTTP/"
        if version[1] < 0 or version < (0, 9) or version >= (2, 0):
            return False
        return True

    def read_request(self, raw_requestline):
        self.requestline = raw_requestline.rstrip()
        words = self.requestline.split()
        if len(words) == 3:
            self.command, self.path, self.request_version = words
            if not self._check_http_version():
                self.log_error('Invalid http version: %r', raw_requestline)
                return
        elif len(words) == 2:
            self.command, self.path = words
            if self.command != "GET":
                self.log_error('Expected GET method: %r', raw_requestline)
                return
            self.request_version = "HTTP/0.9"
            # QQQ I'm pretty sure we can drop support for HTTP/0.9
        else:
            self.log_error('Invalid HTTP method: %r', raw_requestline)
            return

        self.headers = self.MessageClass(self.rfile, 0)
        if self.headers.status:
            self.log_error('Invalid headers status: %r', self.headers.status)
            return

        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            try:
                del self.headers["content-length"]
            except KeyError:
                pass

        content_length = self.headers.get("content-length")
        if content_length is not None:
            content_length = int(content_length)
            if content_length < 0:
                self.log_error('Invalid Content-Length: %r', content_length)
                return
            if content_length and self.command in ('GET', 'HEAD'):
                self.log_error('Unexpected Content-Length')
                return

        self.content_length = content_length

        if self.request_version == "HTTP/1.1":
            conntype = self.headers.get("Connection", "").lower()
            if conntype == "close":
                self.close_connection = True
            else:
                self.close_connection = False
        else:
            self.close_connection = True

        return True

    def log_error(self, msg, *args):
        try:
            message = msg % args
        except Exception:
            traceback.print_exc()
            message = '%r %r' % (msg, args)
        try:
            message = '%s: %s' % (self.socket, message)
        except Exception:
            pass
        try:
            sys.stderr.write(message + '\n')
        except Exception:
            traceback.print_exc()

    def read_requestline(self):
        return self.rfile.readline(MAX_REQUEST_LINE)

    def handle_one_request(self):
        if self.rfile.closed:
            return

        try:
            raw_requestline = self.read_requestline()
        except socket.error:
            # "Connection reset by peer" or other socket errors aren't interesting here
            return

        if not raw_requestline:
            return

        self.response_length = 0

        if len(raw_requestline) >= MAX_REQUEST_LINE:
            return ('414', _REQUEST_TOO_LONG_RESPONSE)

        try:
            if not self.read_request(raw_requestline):
                return ('400', _BAD_REQUEST_RESPONSE)
        except Exception:
            ex = sys.exc_info()[1]
            if not isinstance(ex, ValueError):
                traceback.print_exc()
            self.log_error('Invalid request: %s', str(ex) or ex.__class__.__name__)
            return ('400', _BAD_REQUEST_RESPONSE)

        self.environ = self.get_environ()
        self.application = self.server.application
        try:
            self.handle_one_response()
        except socket.error:
            ex = sys.exc_info()[1]
            # Broken pipe, connection reset by peer
            if ex.args[0] in (errno.EPIPE, errno.ECONNRESET):
                exc_clear()
                return
            else:
                raise

        if self.close_connection:
            return

        if self.rfile.closed:
            return

        return True  # read more requests

    def finalize_headers(self):
        response_headers_list = [x[0] for x in self.response_headers]
        if 'Date' not in response_headers_list:
            self.response_headers.append(('Date', format_date_time(time.time())))

        if self.request_version == 'HTTP/1.0' and 'Connection' not in response_headers_list:
            self.response_headers.append(('Connection', 'close'))
            self.close_connection = True
        elif ('Connection', 'close') in self.response_headers:
            self.close_connection = True

        if self.code not in [204, 304]:
            # the reply will include message-body; make sure we have either Content-Length or chunked
            if 'Content-Length' not in response_headers_list:
                if hasattr(self.result, '__len__'):
                    self.response_headers.append(('Content-Length', str(sum(len(chunk) for chunk in self.result))))
                else:
                    if self.request_version != 'HTTP/1.0':
                        self.response_use_chunked = True
                        self.response_headers.append(('Transfer-Encoding', 'chunked'))

    def write(self, data):
        towrite = []
        if not self.status:
            raise AssertionError("The application did not call start_response()")
        if not self.headers_sent:
            self.headers_sent = True
            self.finalize_headers()

            towrite.append('%s %s\r\n' % (self.request_version, self.status))
            for header in self.response_headers:
                towrite.append('%s: %s\r\n' % header)

            towrite.append('\r\n')

        if data:
            if self.response_use_chunked:
                ## Write the chunked encoding
                towrite.append("%x\r\n%s\r\n" % (len(data), data))
            else:
                towrite.append(data)

        msg = ''.join(towrite)
        try:
            self.socket.sendall(msg)
        except socket.error:
            _, ex, _ = sys.exc_info()
            self.status = 'socket error: %s' % ex
            if self.code > 0:
                self.code = -self.code
            raise
        self.response_length += len(msg)

    def start_response(self, status, headers, exc_info=None):
        if exc_info:
            try:
                if self.headers_sent:
                    # Re-raise original exception if headers sent
                    raise
            finally:
                # Avoid dangling circular ref
                exc_info = None
        self.code = int(status.split(' ', 1)[0])
        self.status = status
        self.response_headers = [('-'.join([x.capitalize() for x in key.split('-')]), value) for key, value in headers]
        return self.write

    def log_request(self):
        log = self.server.log
        if log:
            log.write(self.format_request() + '\n')

    def format_request(self):
        now = datetime.now().replace(microsecond=0)
        if self.time_finish:
            delta = '%.6f' % (self.time_finish - self.time_start)
            length = self.response_length
        else:
            delta = '-'
            if not self.response_length:
                length = '-'
        return '%s - - [%s] "%s" %s %s %s' % (
            self.client_address[0],
            now,
            self.requestline,
            (getattr(self, 'status', None) or '000').split()[0],
            length,
            delta)

    def process_result(self):
        for data in self.result:
            if data:
                self.write(data)
        if self.status and not self.headers_sent:
            self.write('')
        if self.response_use_chunked:
            self.socket.sendall('0\r\n\r\n')
            self.response_length += 5

    def run_application(self):
        self.result = self.application(self.environ, self.start_response)
        self.process_result()

    def handle_one_response(self):
        self.time_start = time.time()
        self.status = None
        self.headers_sent = False

        self.result = None
        self.response_use_chunked = False
        self.response_length = 0

        try:
            try:
                self.run_application()
            finally:
                close = getattr(self.result, 'close', None)
                if close is not None:
                    close()
                self.wsgi_input._discard()
        except:
            self.handle_error(*sys.exc_info())
        finally:
            self.time_finish = time.time()
            self.log_request()

    def handle_error(self, type, value, tb):
        if not issubclass(type, GreenletExit):
            self.server.loop.handle_error(self.environ, type, value, tb)
        del tb
        if self.response_length:
            self.close_connection = True
        else:
            self.start_response(_INTERNAL_ERROR_STATUS, _INTERNAL_ERROR_HEADERS)
            self.write(_INTERNAL_ERROR_BODY)

    def get_environ(self):
        env = self.server.get_environ()
        env['REQUEST_METHOD'] = self.command
        env['SCRIPT_NAME'] = ''

        if '?' in self.path:
            path, query = self.path.split('?', 1)
        else:
            path, query = self.path, ''
        env['PATH_INFO'] = unquote(path)
        env['QUERY_STRING'] = query

        if self.headers.typeheader is not None:
            env['CONTENT_TYPE'] = self.headers.typeheader

        length = self.headers.getheader('content-length')
        if length:
            env['CONTENT_LENGTH'] = length
        env['SERVER_PROTOCOL'] = 'HTTP/1.0'

        client_address = self.client_address
        if isinstance(client_address, tuple):
            env['REMOTE_ADDR'] = str(client_address[0])
            env['REMOTE_PORT'] = str(client_address[1])

        for header in self.headers.headers:
            key, value = header.split(':', 1)
            key = key.replace('-', '_').upper()
            if key not in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
                value = value.strip()
                key = 'HTTP_' + key
                if key in env:
                    if 'COOKIE' in key:
                        env[key] += '; ' + value
                    else:
                        env[key] += ',' + value
                else:
                    env[key] = value

        if env.get('HTTP_EXPECT') == '100-continue':
            socket = self.socket
        else:
            socket = None
        chunked = env.get('HTTP_TRANSFER_ENCODING', '').lower() == 'chunked'
        self.wsgi_input = Input(self.rfile, self.content_length, socket=socket, chunked_input=chunked)
        env['wsgi.input'] = self.wsgi_input
        return env


class WSGIServer(StreamServer):
    """A WSGI server based on :class:`StreamServer` that supports HTTPS."""

    handler_class = WSGIHandler
    base_env = {'GATEWAY_INTERFACE': 'CGI/1.1',
                'SERVER_SOFTWARE': 'gevent/%d.%d Python/%d.%d' % (gevent.version_info[:2] + sys.version_info[:2]),
                'SCRIPT_NAME': '',
                'wsgi.version': (1, 0),
                'wsgi.multithread': False,
                'wsgi.multiprocess': False,
                'wsgi.run_once': False}

    def __init__(self, listener, application=None, backlog=None, spawn='default', log='default', handler_class=None,
                 environ=None, **ssl_args):
        StreamServer.__init__(self, listener, backlog=backlog, spawn=spawn, **ssl_args)
        if application is not None:
            self.application = application
        if handler_class is not None:
            self.handler_class = handler_class
        if log == 'default':
            self.log = sys.stderr
        else:
            self.log = log
        self.set_environ(environ)
        self.set_max_accept()

    def set_environ(self, environ=None):
        if environ is not None:
            self.environ = environ
        environ_update = getattr(self, 'environ', None)
        self.environ = self.base_env.copy()
        if self.ssl_enabled:
            self.environ['wsgi.url_scheme'] = 'https'
        else:
            self.environ['wsgi.url_scheme'] = 'http'
        if environ_update is not None:
            self.environ.update(environ_update)
        if self.environ.get('wsgi.errors') is None:
            self.environ['wsgi.errors'] = sys.stderr

    def set_max_accept(self):
        if self.environ.get('wsgi.multiprocess'):
            self.max_accept = 1

    def get_environ(self):
        return self.environ.copy()

    def init_socket(self):
        StreamServer.init_socket(self)
        self.update_environ()

    def update_environ(self):
        address = self.address
        if isinstance(address, tuple):
            if 'SERVER_NAME' not in self.environ:
                try:
                    name = socket.getfqdn(address[0])
                except socket.error:
                    name = str(address[0])
                self.environ['SERVER_NAME'] = name
            self.environ.setdefault('SERVER_PORT', str(address[1]))
        else:
            self.environ.setdefault('SERVER_NAME', '')
            self.environ.setdefault('SERVER_PORT', '')

    def handle(self, socket, address):
        handler = self.handler_class(socket, address, self)
        handler.handle()

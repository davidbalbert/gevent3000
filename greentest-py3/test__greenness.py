# Copyright (c) 2008 AG Projects
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

"""Test than modules in gevent.green package are indeed green.
To do that spawn a green server and then access it using a green socket.
If either operation blocked the whole script would block and timeout.
"""
import greentest
from gevent import monkey
monkey.patch_all()
import sys
try:
    import urllib.request, urllib.error, urllib.parse
except ImportError:
    from urllib import request as urllib2
try:
    import http.server
except ImportError:
    from http import server as BaseHTTPServer
import gevent


class TestGreenness(greentest.TestCase):
    check_totalrefcount = False

    def serve(self):
        self.httpd.handle_request()
        self.httpd.request_count += 1

    def test_urllib2(self):
        server_address = ('', 0)
        http.server.BaseHTTPRequestHandler.protocol_version = "HTTP/1.0"
        self.httpd = http.server.HTTPServer(server_address, http.server.BaseHTTPRequestHandler)
        self.httpd.request_count = 0
        server = gevent.spawn(self.serve)

        port = self.httpd.socket.getsockname()[1]
        try:
            urllib.request.urlopen('http://127.0.0.1:%s' % port)
            assert False, 'should not get there'
        except urllib.error.HTTPError:
            ex = sys.exc_info()[1]
            assert ex.code == 501, repr(ex)
        server.get(0.01)
        self.assertEqual(self.httpd.request_count, 1)
        self.httpd.server_close()
        self.httpd = None


if __name__ == '__main__':
    greentest.main()

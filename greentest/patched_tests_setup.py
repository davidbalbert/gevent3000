import sys
import re

# By default, test cases are expected to switch and emit warnings if there was none
# If a test is found in this list, it's expected not to switch.
no_switch_tests = '''test_patched_select.SelectTestCase.test_error_conditions
test_patched_ftplib.TestFTPClass.test_all_errors
test_patched_ftplib.TestFTPClass.test_getwelcome
test_patched_ftplib.TestFTPClass.test_sanitize
test_patched_ftplib.TestFTPClass.test_set_pasv
test_patched_ftplib.TestIPv6Environment.test_af
test_patched_socket.TestExceptions.testExceptionTree
test_patched_socket.Urllib2FileobjectTest.testClose
test_patched_socket.TestLinuxAbstractNamespace.testLinuxAbstractNamespace
test_patched_socket.TestLinuxAbstractNamespace.testMaxName
test_patched_socket.TestLinuxAbstractNamespace.testNameOverflow
test_patched_socket.FileObjectInterruptedTestCase.*
test_patched_urllib.*
test_patched_asyncore.HelperFunctionTests.*
test_patched_httplib.BasicTest.*
test_patched_httplib.HTTPSTimeoutTest.test_attributes
test_patched_httplib.HeaderTests.*
test_patched_httplib.OfflineTest.*
test_patched_select.SelectTestCase.test_error_conditions
test_patched_smtplib.NonConnectingTests.*
test_patched_urllib2net.OtherNetworkTests.*
test_patched_wsgiref.*
'''

ignore_switch_tests = '''
test_patched_socket.GeneralModuleTests.*
test_patched_httpservers.BaseHTTPRequestHandlerTestCase.*
test_patched_queue.*
test_patched_signal.SiginterruptTest.*
test_patched_urllib2.*
test_patched_ssl.*
test_patched_signal.BasicSignalTests.*
test_patched_threading_local.*
test_patched_threading.*
'''


def make_re(tests):
    tests = [x.strip().replace('\.', '\\.').replace('*', '.*?') for x in  tests.split('\n') if x.strip()]
    tests = re.compile('^%s$' % '|'.join(tests))
    return tests


no_switch_tests = make_re(no_switch_tests)
ignore_switch_tests = make_re(ignore_switch_tests)


def get_switch_expected(fullname):
    """
    >>> get_switch_expected('test_patched_select.SelectTestCase.test_error_conditions')
    False
    >>> get_switch_expected('test_patched_socket.GeneralModuleTests.testCrucialConstants')
    False
    >>> get_switch_expected('test_patched_socket.SomeOtherTest.testHello')
    True
    >>> get_switch_expected("test_patched_httplib.BasicTest.test_bad_status_repr")
    False
    """
    if ignore_switch_tests.match(fullname) is not None:
        return None
    if no_switch_tests.match(fullname) is not None:
        return False
    return True


disabled_tests = \
    [ 'test_threading.ThreadTests.test_PyThreadState_SetAsyncExc'
    # uses some internal C API of threads not available when threads are emulated with greenlets

    , 'test_threading.ThreadTests.test_join_nondaemon_on_shutdown'
    # asserts that repr(sleep) is '<built-in function sleep>'

    , 'test_urllib2net.TimeoutTest.test_ftp_no_timeout'
    , 'test_urllib2net.TimeoutTest.test_ftp_timeout'
    , 'test_urllib2net.TimeoutTest.test_http_no_timeout'
    , 'test_urllib2net.TimeoutTest.test_http_timeout'
    # accesses _sock.gettimeout() which is always in non-blocking mode

    , 'test_socket.UDPTimeoutTest.testUDPTimeout'
    # has a bug which makes it fail with error: (107, 'Transport endpoint is not connected')
    # (it creates a TCP socket, not UDP)

    , 'test_socket.GeneralModuleTests.testRefCountGetNameInfo'
    # fails with "socket.getnameinfo loses a reference" while the reference is only "lost"
    # because it is referenced by the traceback - any Python function would lose a reference like that.
    # the original getnameinfo does not "lose" it because it's in C.

    , 'test_socket.NetworkConnectionNoServer.test_create_connection_timeout'
    # replaces socket.socket with MockSocket and then calls create_connection.
    # this unfortunately does not work with monkey patching, because gevent.socket.create_connection
    # is bound to gevent.socket.socket and updating socket.socket does not affect it.
    # this issues also manifests itself when not monkey patching DNS: http://code.google.com/p/gevent/issues/detail?id=54
    # create_connection still uses gevent.socket.getaddrinfo while it should be using socket.getaddrinfo

    , 'test_asyncore.BaseTestAPI.test_handle_expt'
    # sends some OOB data and expect it to be detected as such; gevent.select.select does not support that

    , 'test_signal.WakeupSignalTests.test_wakeup_fd_early'
    # expects time.sleep() to return prematurely in case of a signal;
    # gevent.sleep() is better than that and does not get interrupted (unless signal handler raises an error)

    , 'test_signal.WakeupSignalTests.test_wakeup_fd_during'
    # expects select.select() to raise select.error(EINTR, 'interrupted system call')
    # gevent.select.select() does not get interrupted (unless signal handler raises an error)
    # maybe it should?
]


def disable_tests_in_source(source, name):
    my_disabled_tests = [x for x in disabled_tests if x.startswith(name + '.')]
    if not my_disabled_tests:
        return source
    for test in my_disabled_tests:
        # XXX ignoring TestCase class name
        testcase = test.split('.')[-1]
        source, n = re.subn(testcase, 'XXX' + testcase, source)
        print >> sys.stderr, 'Removed %s (%d)' % (testcase, n)
    return source

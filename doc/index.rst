gevent
======

gevent is a coroutine_-based Python_ networking library that uses greenlet_ to provide
a high-level synchronous API on top of libevent_ event loop.

Features include:

* `convenient API around greenlets`__
* familiar synchronization primitives (:mod:`gevent.event`, :mod:`gevent.queue`)
* :doc:`socket module that cooperates <gevent.socket>`
* :doc:`WSGI server on top of libevent-http <gevent.wsgi>`
* DNS requests done through libevent-dns
* :ref:`monkey patching utility to get pure Python modules to cooperate <monkey-patching>`

__ gevent.html
.. _coroutine: http://en.wikipedia.org/wiki/Coroutine
.. _Python: http://www.python.org
.. _greenlet: http://codespeak.net/py/0.9.2/greenlet.html
.. _libevent: http://monkey.org/~provos/libevent/


examples
--------

Browse ``examples/`` folder at bitbucket_ or `google code`_.

.. _bitbucket: http://bitbucket.org/denis/gevent/src/tip/examples/
.. _google code: http://code.google.com/p/gevent/source/browse/#hg/examples


documentation
-------------

INSERT-contentstable.html


get gevent
----------

The latest release `0.11.2`_ is available on the `Python Package Index.`_

.. _0.11.2: changelog.html
.. _Python Package Index.: http://pypi.python.org/pypi/gevent

The current development version is available in a Mercurial repository:

* at bitbucket: http://bitbucket.org/denis/gevent/
* on google code: http://code.google.com/p/gevent/


installation
------------

Install the dependencies:

* greenlet: http://pypi.python.org/pypi/greenlet (it can be installed with ``easy_install greenlet``)
* libevent 1.4.x: http://monkey.org/~provos/libevent/

gevent runs on Python 2.4 and higher.


similar projects
----------------

* `Eventlet <http://eventlet.net/>`_
* `Concurrence <http://opensource.hyves.org/concurrence/>`_
* `StacklessSocket <http://code.google.com/p/stacklessexamples/wiki/StacklessNetworking>`_


feedback
--------

Use `Issue Tracker on Google Code`__ for the bug reports / feature requests.

Comment on the `blog`_.

Send your questions and suggestions to the `mailing list`_.

Contact me directly at denis.bilenko@gmail.com.

__ http://code.google.com/p/gevent/issues/list
.. _blog: http://blog.gevent.org
.. _mailing list: http://groups.google.com/group/gevent


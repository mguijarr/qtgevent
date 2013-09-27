qtgevent
========

PyQt backend for gevent


Using it
========

In order to use qtgevent add the following lines at the beginning
of your project, before importing anything from gevent:

::

    import qtgevent
    qtgevent.install()

Another way of doing this without modifying your code is by exporting environment variables before
running your program:

::

    export GEVENT_LOOP=qtgevent.loop.QtLoop


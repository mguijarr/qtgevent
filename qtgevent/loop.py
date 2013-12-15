# coding=utf8

__all__ = ['QtLoop']

import atexit
import functools
import os
import traceback
from PyQt4 import QtCore, Qt
import socket
import signal
import sys
import gevent

QtCore.pyqtRemoveInputHook()

_signal_rfd, _signal_wfd = socket.socketpair()
_signal_rfd.setblocking(False); _signal_wfd.setblocking(False)
atexit.register(_signal_rfd.close)
atexit.register(_signal_wfd.close)
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.set_wakeup_fd(_signal_wfd.fileno())

class QtLoop(object):
    MINPRI = -2
    MAXPRI = 2

    def __init__(self, flags=None, default=True):
        assert(not QtCore.QCoreApplication.startingUp())
        self._loop = QtCore.QEventLoop()
        self._loop.default = default
        self.__callback_timers = {}
        self._signal_watchers = {}
        self._raised_signal = None 
        self._child_watchers = {}
        self._loop.excepthook = functools.partial(self.handle_error, None)
        self._signal_notifier = QtCore.QSocketNotifier(_signal_rfd.fileno(), QtCore.QSocketNotifier.Read, self._loop)
        self._signal_notifier.activated.connect(self._handle_signal_in_loop)
        self._signal_notifier.setEnabled(True)
        self._watchers = set()
        self._sigchld_handle = None

    def destroy(self):
        self._watchers.clear()
        self._child_watchers = {}
        self._raised_signals = []
        self._sigchld_handle = None
        self._loop = None

    def _handle_syserr(self, message, errno):
        self.handle_error(None, SystemError, SystemError(message + ': ' + os.strerror(errno)), None)

    def handle_error(self, context, type, value, tb):
        error_handler = self.error_handler
        if error_handler is not None:
            # we do want to do getattr every time so that setting Hub.handle_error property just works
            handle_error = getattr(error_handler, 'handle_error', error_handler)
            handle_error(context, type, value, tb)
        else:
            self._default_handle_error(context, type, value, tb)

    def _default_handle_error(self, context, type, value, tb):
        traceback.print_exception(type, value, tb)
        self._loop.quit()

    def _handle_signal_in_loop(self):
        _signal_rfd.recv(1)
        signum = self._raised_signal
        watchers = self._signal_watchers.get(signum)
        if watchers:
            for watcher in watchers.copy():
                watcher._run_callback()
        
    def _handle_signal(self, signum, stack_frame):
        self._raised_signal = signum 

    def run(self, nowait=False, once=False):
        flags = QtCore.QEventLoop.AllEvents #QtCore.QEventLoop.ExcludeUserInputEvents
        if nowait or once:
          if nowait:  #getattr(self._loop, "hasPendingEvents", lambda: False)():
              return
          self._loop.processEvents(flags)
        else: 
          self._loop.exec_(flags)
          gevent.get_hub().throw()
          
    def reinit(self):
        pass

    def ref(self):
        raise NotImplementedError

    def unref(self):
        raise NotImplementedError

    def break_(self, how):
        raise NotImplementedError

    def verify(self):
        pass

    def now(self): 
        raise NotImplementedError

    def update(self):
        self._loop.wakeUp()

    @property
    def default(self):
        return self._loop.default

    @property
    def iteration(self):
        raise NotImplementedError

    @property
    def depth(self):
        raise NotImplementedError

    @property
    def backend(self):
        raise NotImplementedError

    @property
    def backend_int(self):
        raise NotImplementedError

    @property
    def pendingcnt(self):
        raise NotImplementedError

    @property
    def activecnt(self):
        raise NotImplementedError

    @property
    def origflags(self):
        raise NotImplementedError

    @property
    def origflags_int(self):
        raise NotImplementedError

    def io(self, fd, events, ref=True, priority=None):
        return Io(self, fd, events, ref)

    def timer(self, after, repeat=0.0, ref=True, priority=None):
        return Timer(self, after, repeat, ref)

    def prepare(self, ref=True, priority=None):
        return NoOp(self, ref)

    def idle(self, ref=True, priority=None):
        return Idle(self, ref)

    def check(self, ref=True, priority=None):
        return NoOp(self, ref)

    def async(self, ref=True, priority=None):
        return Async(self, ref)

    def stat(self, path, interval=0.0, ref=True, priority=None):
        return NoOp(self, ref)

    def fork(self, ref=True, priority=None):
        return NoOp(self, ref)

    def child(self, pid, trace=False, ref=True):
        if sys.platform == 'win32':
            raise NotImplementedError
        return Child(self, pid, ref)

    def install_sigchld(self):
        if sys.platform == 'win32':
            raise NotImplementedError
        if self._loop.default and self._sigchld_handle is None:
            self._sigchld_handle = Signal(self._loop, signal.SIGCHLD)
            self._sigchld_handle.start(self._handle_SIGCHLD)
            self._sigchld_handle.unref()

    def signal(self, signum, ref=True, priority=None):
        signal.signal(signum, self._handle_signal)
        return Signal(self, signum, ref)

    def _execute_callback(self, cb, timer_id):
        if None in (cb.callback, cb.args):
            return
        try:
            cb.callback(*cb.args)
        finally:
            self.__callback_timers[timer_id].deleteLater()
            del self.__callback_timers[timer_id] 
            cb.stop()

    def run_callback(self, func, *args):
        cb = Callback(func, args)
        callback_timer = QtCore.QTimer()
        callback_timer.setSingleShot(True)
        self.__callback_timers[id(callback_timer)]=callback_timer
        callback_timer.timeout.connect(functools.partial(self._execute_callback, cb, id(callback_timer))) 
        callback_timer.start(0)
        return cb

    def fileno(self):
        raise NotImplementedError

    def _handle_SIGCHLD(self):
        pid, status, usage = os.wait3(os.WNOHANG)
        child = self._child_watchers.get(pid, None) or self._child_watchers.get(0, None)
        if child is not None:
            child._set_status(status)

    def _format(self):
        msg = ''
        if self.default:
            msg += ' default'
        return msg

    def __repr__(self):
        return '<%s at 0x%x%s>' % (self.__class__.__name__, id(self), self._format())


class Callback(object):
    def __init__(self, callback, args):
        self.callback = callback
        self.args = args

    @property
    def pending(self):
        return self.callback is not None

    def stop(self):
        self.callback = None
        self.args = None

    def _format(self):
        return ''

    def __repr__(self):
        format = self._format()
        result = "<%s at 0x%x%s" % (self.__class__.__name__, id(self), format)
        if self.pending:
            result += " pending"
        if self.callback is not None:
            result += " callback=%r" % (self.callback, )
        if self.args is not None:
            result += " args=%r" % (self.args, )
        if self.callback is None and self.args is None:
            result += " stopped"
        return result + ">"

    # Note, that __nonzero__ and pending are different
    # nonzero is used in contexts where we need to know whether to schedule another callback,
    # so it's true if it's pending or currently running
    # 'pending' has the same meaning as libev watchers: it is cleared before entering callback
    def __nonzero__(self):
        # it's nonzero if it's pending or currently executing
        return self.args is not None


class Watcher(object):
    def __init__(self, loop, ref=True):
        self.loop = loop
        self._ref = ref
        self._callback = None

    @property
    def callback(self):
        return self._callback

    @property
    def active(self):
        return self._handle and self._handle.active

    @property
    def pending(self):
        return False

    def _get_ref(self):
        return self._ref
    def _set_ref(self, value):
        self._ref = value
        if self._handle:
            op = self._handle.ref if value else self._handle.unref
            op()
    ref = property(_get_ref, _set_ref)
    del _get_ref, _set_ref

    def start(self, callback, *args):
        self.loop._watchers.add(self)
        self._callback = functools.partial(callback, *args)

    def stop(self):
        self.loop._watchers.discard(self)
        self._handle.deleteLater()
        self._callback = None

    def feed(self, revents, callback, *args):
        raise NotImplementedError

    def _run_callback(self):
        if self._callback:
            try:
                self._callback()
            except:
                self.loop.handle_error(self, *sys.exc_info())
            finally:
                if not self.active:
                    self.stop()

    def _format(self):
        return ''

    def __repr__(self):
        result = '<%s at 0x%x%s' % (self.__class__.__name__, id(self), self._format())
        if self.active:
            result += ' active'
        if self.pending:
            result += ' pending'
        if self.callback is not None:
            result += ' callback=%r' % self.callback
        return result + '>'


class NoOp(Watcher):
    def __init__(self, loop, ref=True):
        super(NoOp, self).__init__(loop, ref)
        self._handle = None

    def start(self, *args, **kw):
        pass

    def stop(self):
        pass


class Timer(Watcher):
    def __init__(self, loop, after=0.0, repeat=0.0, ref=True):
        if repeat < 0.0:
            raise ValueError("repeat must be positive or zero: %r" % repeat)
        super(Timer, self).__init__(loop, ref)
        self._after = after
        self._repeat = repeat
        self._should_repeat = False
        self._handle = QtCore.QTimer(self.loop._loop)
        self._handle.timeout.connect(self._run_callback)

    @property
    def active(self):
        return self._handle.isActive()

    def start(self, callback, *args, **kw):
        super(Timer, self).start(callback, *args)
        if self._handle.isActive():
            return
        if kw.get('update', True):
            self.loop.update()
        if self._repeat:
            self._should_repeat = True
        self._handle.setSingleShot(True)
        self._handle.start(self._after*1000)

    def _run_callback(self, *args, **kwargs):
        super(Timer, self)._run_callback(*args, **kwargs)
        if self._should_repeat:
          self._handle.stop()
          self._handle.setSingleShot(False)
          self._handle.setInterval(self._repeat * 1000)
          self._should_repeat = False
          self._handle.start()

    def stop(self):
        self._handle.stop()
        super(Timer, self).stop()

    def again(self, callback, *args, **kw):
        raise NotImplementedError

    @property
    def at(self):
        raise NotImplementedError


class Idle(Watcher):
    def __init__(self, loop, ref=True):
        super(Idle, self).__init__(loop, ref)
        self._handle = QtCore.QTimer(self.loop._loop)
        self._handle.setInterval(0)

    def _idle_cb(self, handle):
        self._run_callback()

    def start(self, callback, *args):
        super(Idle, self).start(callback, *args)
        self._handle.timeout.connect(self._idle_cb)
        self._handle.start() 

    def stop(self):
        self._handle.stop()
        super(Idle, self).stop()


class Io(Watcher):
    def __init__(self, loop, fd, events, ref=True):
        super(Io, self).__init__(loop, ref)
        self._fd = fd
        self._events = self._ev2qt(events)
        self._handle = QtCore.QSocketNotifier(self._fd, self._events, self.loop._loop)
        self._handle.setEnabled(False)

    @classmethod
    def _ev2qt(cls, events):
        qt_events = 0
        if events & 1:
            qt_events |= QtCore.QSocketNotifier.Read
        if events & 2:
            qt_events |= QtCore.QSocketNotifier.Write
        return qt_events

    @property
    def active(self):
        return self._handle and self._handle.isEnabled()

    def _poll_cb(self):
        if self._callback is None:
            return
        try:
            self._callback()
        except:
            self.loop.handle_error(self, *sys.exc_info())
            self.stop()
        finally:
            if not self.active:
                self.stop()

    def start(self, callback, *args, **kw):
        super(Io, self).start(callback, *args)
        self._handle.activated.connect(self._poll_cb)
        self._handle.setEnabled(True)

    def stop(self):
        self._handle.setEnabled(False)
        super(Io, self).stop()

    @property
    def fd(self):
        # TODO: changing the fd is not currently supported
        return self._fd

    def _get_events(self):
        return self._events
    def _set_events(self, value):
        self._events = self._ev2qt(value)
        already_started = self._handle.isEnabled()
        self._handle = QtCore.QSocketNotifier(self._fd, self._events, self.loop._loop)
        self._handle.setEnabled(False)
        if already_started:
          self._handle.activated.connect(self._poll_cb)
          self._handle.setEnabled(True) 
    events = property(_get_events, _set_events)
    del _get_events, _set_events

    @property
    def events_str(self):
        r = []
        if self._events & QtCore.QSocketNotifier.Read:
            r.append('READABLE')
        if self._events & QtCore.QSocketNotifier.Write:
            r.append('WRITABLE')
        return '|'.join(r)

    def _format(self):
        return ' fd=%s events=%s' % (self.fd, self.events_str)


class Async(Watcher):
    def __init__(self, loop, ref=True):
        super(Async, self).__init__(loop, ref)
        self._handle = QtCore.QObject(self.loop._loop)
        QtCore.QObject.connect(self._handle, Qt.SIGNAL("notification"), self._async_cb)

    @property
    def active(self):
        return False

    def _async_cb(self, handle):
        # this is to be called by event loop
        self._run_callback()

    def start(self, callback, *args, **kw):
        super(Async, self).start(callback, *args)

    def stop(self):
        super(Async, self).stop()

    def send(self):
        # this is called from another thread
        self._handle.emit(Qt.SIGNAL("notification"), ())


class Child(Watcher):
    def __init__(self, loop, pid, ref=True):
        #if not loop.default:
        #    raise TypeError("child watchers are only allowed in the default loop")
        super(Child, self).__init__(loop, ref)
        loop.install_sigchld()
        self._active = False
        self._pid = pid
        self.rpid = None
        self.rstatus = None
        #self._handle = pyuv.Async(self.loop._loop, self._async_cb)

    @property
    def active(self):
        return self._active

    @property
    def pid(self):
        return self._pid

    def _async_cb(self, handle):
        self._run_callback()

    def start(self, callback, *args, **kw):
        super(Child, self).start(callback, *args)
        if not self._ref:
            self._handle.unref()
        self._active = True
        # TODO: should someone be able to register 2 child watchers for the same PID?
        self.loop._child_watchers[self._pid] = self

    def stop(self):
        self._active = False
        self.loop._child_watchers.pop(self._pid, None)
        super(Child, self).stop()

    def _set_status(self, status):
        self.rstatus = status
        self.rpid = os.getpid()
        self._handle.send()

    def _format(self):
        return ' pid=%r rstatus=%r' % (self.pid, self.rstatus)


class Signal(Watcher):
    def __init__(self, loop, signum, ref):
        super(Signal, self).__init__(loop, ref)
        self._signum = signum
        self._handle = None
        self._active = False

    @property
    def active(self):
        return self._active

    def start(self, callback, *args):
        super(Signal, self).start(callback, *args)
        self._active = True
        self.loop._signal_watchers.setdefault(self._signum, set()).add(self)

    def stop(self):
        self._active = False
        super(Signal, self).stop()
        self.loop._signal_watchers[self._signum].discard(self)


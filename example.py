from PyQt4 import Qt, QtCore, QtGui
import qtgevent
qtgevent.install()
import gevent
from gevent import monkey; monkey.patch_all()
import functools
import time

def test_greenlet(name):
  i = 1
  while True:
    print name, i
    i += 1
    time.sleep(1)

def btn_clicked():
  btn.setEnabled(False)
  gevent.spawn(test_greenlet, "C")

if __name__ == '__main__':
  app = QtGui.QApplication([])
  mainwin = QtGui.QMainWindow()
  btn = QtGui.QPushButton('Start greenlet', mainwin) 
  btn.clicked.connect(btn_clicked)
  gevent.spawn(test_greenlet, 'A')
  gevent.spawn(test_greenlet, 'B')
  
  mainwin.show()
  app.exec_()

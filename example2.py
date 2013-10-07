from PyQt4 import Qt, QtCore, QtGui
import qtgevent
qtgevent.install()
import gevent
from gevent import monkey; monkey.patch_all()
import functools
import time
import greenlet

def btn_clicked():
  print 'before sleep'
  gevent.sleep(3)
  print 'after sleep'

if __name__ == '__main__':
  app = QtGui.QApplication([])
  mainwin = QtGui.QMainWindow()
  btn = QtGui.QPushButton('Start greenlet', mainwin) 
  btn.clicked.connect(btn_clicked)
  mainwin.show()
  app.exec_()

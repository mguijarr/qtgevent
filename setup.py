from distutils.core import setup
import sys

setup(name = "qtgevent",version = "0.1",
      description = "PyQt4 backend for gevent", 
      author="Matias Guijarro",
      package_dir={"qtgevent": "qtgevent"},
      packages = ["qtgevent"])


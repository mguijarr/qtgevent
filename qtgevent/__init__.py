# coding=utf8

# Copyright (C) 2012 Saúl Ibarra Corretgé <saghul@gmail.com>
#

__all__ = ['install']
__version__ = '0.1.0'


# Patchers

def patch_loop():
    from .loop import QtLoop
    from gevent.hub import Hub
    Hub.loop_class = QtLoop


def install():
    patch_loop()


import sys

def g():
    frame = sys._getframe()
    print(f"current func is: {frame.f_code.co_name}")
    caller = frame.f_back
    print(caller.f_globals.keys())

def f():
    g()

f()
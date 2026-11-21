"""Static standard-library imports for the frozen operational helper build.

Operational source modules are admitted and compiled from external bundle data
by the frozen entrypoint. Keep those modules out of this static import graph.
"""

import collections
import ctypes
import dataclasses
import enum
import errno
import fcntl
import hashlib
import hmac
import importlib
import json
import math
import numbers
import os
import pathlib
import platform
import re
import select
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
import typing
import uuid


__all__ = ()

"""Every test runs offline: a connection or a name lookup that leaves this machine raises."""
import socket

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "[::1]", "", None}


class NetworkBlocked(AssertionError):
    pass


def _host_of(address):
    return address[0] if isinstance(address, tuple) else None


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _connect(self, address):
    if isinstance(address, tuple) and _host_of(address) not in _LOOPBACK:
        raise NetworkBlocked("a test tried to connect beyond loopback")
    return _real_connect(self, address)


def _connect_ex(self, address):
    if isinstance(address, tuple) and _host_of(address) not in _LOOPBACK:
        raise NetworkBlocked("a test tried to connect beyond loopback")
    return _real_connect_ex(self, address)


def _getaddrinfo(host, *args, **kwargs):
    if host not in _LOOPBACK:
        raise NetworkBlocked("a test tried to look up a name beyond loopback")
    return _real_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo

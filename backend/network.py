"""LAN addresses for printed QR labels; never encode a loopback address."""
import ipaddress
import socket
from urllib.parse import urlsplit


def lan_ip(value):
    try:
        address = ipaddress.IPv4Address(value)
        return any(address in ipaddress.IPv4Network(net) for net in
                   ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    except ipaddress.AddressValueError:
        return False


def validate_base(value):
    message = '请填写主机的局域网地址，例如 http://192.168.1.20:8765；不能填写 127.0.0.1 或 localhost'
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError(message)
    value = value.strip().rstrip('/')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not lan_ip(parsed.hostname)
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or any(c.isspace() or ord(c) < 32 for c in value)
                or parsed.port == 0):
            raise ValueError(message)
        return f'{parsed.scheme}://{parsed.hostname}' + (f':{parsed.port}' if parsed.port else '')
    except (ValueError, TypeError):
        raise ValueError(message) from None


def addresses():
    found = set()
    try:
        found.update(item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET))
    except OSError:
        pass
    # UDP connect selects the default interface without sending a packet or using the internet.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(('192.0.2.1', 9))
            found.add(connection.getsockname()[0])
    except OSError:
        pass
    return sorted(address for address in found if lan_ip(address))

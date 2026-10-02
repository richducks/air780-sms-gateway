#!/usr/bin/env python3
"""Small host-side switch for the Air780 data interface.

The SMS container talks to this Unix socket. Only the exact AirM2M USB device
is reconfigured; the host's primary interface and DNS are never changed.
"""
import json
import grp
import os
import re
import socketserver
import subprocess
import tempfile
from pathlib import Path

SOCKET = Path('/run/air780-4g/control.sock')
NETWORK = Path('/etc/systemd/network/05-air780-rndis.network')
NM_PREFIX = 'air780-4g-'


def air780_parent(device):
    while device != device.parent:
        try:
            if ((device / 'idVendor').read_text().strip().lower() == '19d1'
                    and (device / 'idProduct').read_text().strip().lower() == '0001'):
                return device
        except OSError:
            pass
        device = device.parent
    return None


def interfaces():
    found = []
    for link in Path('/sys/class/net').iterdir():
        device = (link / 'device').resolve()
        while device != device.parent:
            try:
                if ((device / 'idVendor').read_text().strip().lower() == '19d1'
                        and (device / 'idProduct').read_text().strip().lower() == '0001'):
                    driver = (link / 'device' / 'driver').resolve().name
                    if driver == 'rndis_host':
                        found.append(link.name)
                    break
            except OSError:
                pass
            device = device.parent
    return found


def command_ok(command):
    return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          check=False).returncode == 0


def network_backend():
    if command_ok(['systemctl', 'is-active', '--quiet', 'NetworkManager']):
        return 'NetworkManager'
    if Path('/run/systemd/netif').exists():
        return 'systemd-networkd'
    return None


def nm_connection(link):
    return NM_PREFIX + link


def nm_link_enabled(link):
    result = subprocess.run(['nmcli', '-t', '-f', 'GENERAL.CONNECTION',
                             'device', 'show', link], capture_output=True,
                            text=True, check=False)
    return result.returncode == 0 and result.stdout.strip().endswith(nm_connection(link))


def enabled(links=None):
    links = interfaces() if links is None else links
    if network_backend() == 'NetworkManager':
        return bool(links) and all(nm_link_enabled(link) for link in links)
    try:
        return 'DHCP=ipv4' in NETWORK.read_text()
    except OSError:
        return False


def addresses(interface):
    result = subprocess.run(['ip', '-4', '-o', 'addr', 'show', 'dev', interface],
                            capture_output=True, text=True, check=True)
    return re.findall(r'\binet (\S+)', result.stdout)


def interface_ports(link):
    """Serial ports sharing the same physical Air780 USB device as a data link."""
    parent = air780_parent((Path('/sys/class/net') / link / 'device').resolve())
    if parent is None:
        return []
    return sorted('/dev/' + tty.name for tty in Path('/sys/class/tty').glob('ttyACM*')
                  if air780_parent((tty / 'device').resolve()) == parent)


def state():
    links = interfaces()
    return {'available': bool(links), 'enabled': enabled(links),
            'interfaces': [{'name': link, 'enabled': (nm_link_enabled(link)
                            if network_backend() == 'NetworkManager' else enabled(links)),
                            'addresses': addresses(link),
                            'serial_ports': interface_ports(link)} for link in links],
            'network_backend': network_backend(),
            'route_policy': '4G 路由优先级低于主网络，不接管 DNS',
            # Signal strength is reported by the SMS bridge itself. The host-side
            # 4G switch must never open ttyACM ports, otherwise it races the SMS
            # gateway and can make devices flap or appear offline.
            'signal': None, 'signal_supported': False}


def set_networkmanager(links, value):
    for link in links:
        name = nm_connection(link)
        if value:
            subprocess.run(['nmcli', 'device', 'set', link, 'managed', 'yes'],
                           check=True, timeout=15)
            if not command_ok(['nmcli', 'connection', 'show', name]):
                subprocess.run(['nmcli', 'connection', 'add', 'type', 'ethernet',
                                'ifname', link, 'con-name', name], check=True, timeout=15)
            subprocess.run([
                'nmcli', 'connection', 'modify', name,
                'connection.interface-name', link, 'connection.autoconnect', 'no',
                'ipv4.method', 'auto', 'ipv4.route-metric', '5000',
                'ipv4.ignore-auto-dns', 'yes', 'ipv4.never-default', 'no',
                'ipv6.method', 'disabled'
            ], check=True, timeout=15)
            subprocess.run(['nmcli', 'device', 'set', link, 'managed', 'yes'],
                           check=True, timeout=15)
            subprocess.run(['nmcli', 'connection', 'up', name, 'ifname', link],
                           check=True, timeout=45)
        else:
            subprocess.run(['nmcli', 'connection', 'down', name],
                           capture_output=True, check=False, timeout=20)
            subprocess.run(['nmcli', 'device', 'disconnect', link],
                           capture_output=True, check=False, timeout=20)
            subprocess.run(['nmcli', 'device', 'set', link, 'managed', 'no'],
                           check=True, timeout=15)
            subprocess.run(['ip', 'route', 'del', 'default', 'dev', link],
                           capture_output=True, check=False)
            subprocess.run(['resolvectl', 'revert', link],
                           capture_output=True, check=False)


def set_networkd(links, value):
    config = ('[Match]\nDriver=rndis_host\n\n[Network]\n'
              f'DHCP={"ipv4" if value else "no"}\n'
              'IPv6AcceptRA=no\nLinkLocalAddressing=no\n'
              'ConfigureWithoutCarrier=yes\n'
              '\n[DHCPv4]\nRouteMetric=5000\nUseDNS=no\nUseNTP=no\nUseDomains=no\n')
    previous = NETWORK.read_text()
    fd, temp_name = tempfile.mkstemp(prefix='.air780-rndis-', dir=NETWORK.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(config)
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, NETWORK)
        subprocess.run(['networkctl', 'reload'], check=True, timeout=15)
        for link in links:
            subprocess.run(['networkctl', 'reconfigure', link], check=True, timeout=20)
            if not value:
                subprocess.run(['ip', 'route', 'del', 'default', 'dev', link],
                               capture_output=True, check=False)
    except Exception:
        NETWORK.write_text(previous)
        subprocess.run(['networkctl', 'reload'], check=False)
        for link in links:
            subprocess.run(['networkctl', 'reconfigure', link], check=False)
        raise


def set_enabled(value, requested_link=None):
    links = interfaces()
    if not links:
        raise ValueError('未检测到 Air780 4G 数据网卡')
    if requested_link is not None:
        if requested_link not in links:
            raise ValueError('指定的 4G 网卡不存在')
        links = [requested_link]
    backend = network_backend()
    if backend == 'NetworkManager':
        set_networkmanager(links, value)
    elif backend == 'systemd-networkd':
        set_networkd(links, value)
    else:
        raise ValueError('未检测到受支持的网络管理器')
    return state()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            raw = self.rfile.readline(1025)
            if len(raw) > 1024:
                raise ValueError('request too large')
            request = json.loads(raw)
            if request == {'action': 'status'}:
                result = state()
            elif request.get('action') == 'set' and type(request.get('enabled')) is bool:
                result = set_enabled(request['enabled'], request.get('interface'))
            else:
                raise ValueError('invalid request')
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            result = {'error': str(exc)}
        self.wfile.write((json.dumps(result, ensure_ascii=False) + '\n').encode())


if __name__ == '__main__':
    SOCKET.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with socketserver.ThreadingUnixStreamServer(str(SOCKET), Handler) as server:
        os.chown(SOCKET, 0, grp.getgrnam('dialout').gr_gid)
        os.chmod(SOCKET, 0o660)
        server.serve_forever()

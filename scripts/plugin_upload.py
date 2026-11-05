"""Explicit maintainer upload command; never invoked by the plugin or CI build."""

import argparse
import getpass
from pathlib import Path
import sys
from urllib.parse import quote, urlsplit, urlunsplit
import xmlrpc.client

SERVER = "plugins.qgis.org"
ENDPOINT = "/plugins/RPC2/"


def hide_password(url, start=None):
    """Remove all userinfo from a diagnostic URL, including the username."""
    parts = urlsplit(url)
    authority = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, authority, parts.path, "", ""))


def upload(archive, username, password, server=SERVER, port=443, proxy_factory=None):
    """Upload explicitly supplied credentials without logging them."""
    if not server or any(c in server for c in "/:@?#\\"):
        raise ValueError("Server must be a hostname without a URL or credentials")
    if not 1 <= int(port) <= 65535:
        raise ValueError("Invalid server port")
    archive = Path(archive)
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise ValueError("Supply an existing plugin ZIP archive")
    if archive.stat().st_size > 25_000_000:
        raise ValueError("Plugin archive exceeds the repository size limit")
    address = (
        f"https://{quote(username, safe='')}:{quote(password, safe='')}"
        f"@{server}:{int(port)}{ENDPOINT}"
    )
    proxy_factory = proxy_factory or xmlrpc.client.ServerProxy
    print(f"Connecting to: {hide_password(address)}")
    with proxy_factory(address, verbose=False) as proxy:
        return proxy.plugin.upload(xmlrpc.client.Binary(archive.read_bytes()))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Publish a prepared QGIS plugin ZIP")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--username", "-u")
    parser.add_argument("--server", default=SERVER)
    parser.add_argument("--port", type=int, default=443)
    options = parser.parse_args(argv)
    username = options.username or input(f"Username [{getpass.getuser()}]: ").strip() \
        or getpass.getuser()
    password = getpass.getpass("QGIS repository password: ")
    try:
        plugin_id, version_id = upload(
            options.archive, username, password, options.server, options.port,
        )
    except xmlrpc.client.ProtocolError as exc:
        print(f"Upload failed: HTTP status {exc.errcode}", file=sys.stderr)
        return 1
    except xmlrpc.client.Fault as exc:
        print(f"Upload rejected: XML-RPC fault {exc.faultCode}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"Upload failed: {exc}", file=sys.stderr)
        return 1
    print(f"Plugin ID: {plugin_id}; version ID: {version_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

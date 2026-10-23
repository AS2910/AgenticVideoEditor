"""Launch item 5: link imports cannot reach private, loopback, link-local or
metadata addresses, after redirects too, and a DNS answer cannot change
between the check and the connect. DNS and HTTP are fakes; nothing leaves
the machine."""
import socket

import httpcore
import httpx
import pytest

from app import linkimport as li

MP4_HEAD = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
OK_VIDEO = dict(content=MP4_HEAD + b"x" * 100, headers={"content-type": "video/mp4"})


def resolved(url="https://www.dropbox.com/s/abc/ad.mp4?dl=1"):
    return li.Resolved("dropbox", "Dropbox", url, "ad.mp4")


@pytest.mark.parametrize("ip", [
    "10.0.0.1", "172.16.5.4", "192.168.1.1",          # RFC1918
    "100.64.0.1", "100.127.255.254",                  # CGNAT
    "127.0.0.1", "127.8.8.8", "::1",                  # loopback
    "169.254.169.254", "169.254.1.1", "fe80::1",      # link-local, cloud metadata
    "fc00::1", "fd12:3456::1",                        # unique-local
    "::ffff:127.0.0.1", "::ffff:169.254.169.254", "::ffff:10.0.0.1",  # IPv4-mapped
    "::127.0.0.1", "64:ff9b::a9fe:a9fe", "2002:7f00:1::1", "2002:a9fe:a9fe::1",  # compatible, NAT64, 6to4
    "0.0.0.0", "::", "0.1.2.3",                       # unspecified / this network
    "224.0.0.1", "239.255.255.250", "ff02::1",        # multicast
    "240.0.0.1", "255.255.255.255", "198.18.0.1", "192.0.2.1", "2001:db8::1",  # reserved, benchmarking, docs
    "fec0::1",                                        # site-local
])
def test_addresses_that_are_not_public_are_refused(ip):
    with pytest.raises(li.ImportRefused, match="public addresses"):
        li.check_ip(ip)


@pytest.mark.parametrize("ip", ["142.250.72.14", "162.125.1.18", "2607:f8b0:4005:80b::200e", "::ffff:142.250.72.14"])
def test_public_addresses_pass(ip):
    li.check_ip(ip)


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://[::ffff:169.254.169.254]/",
    "http://[::1]/", "http://127.0.0.1/", "http://10.1.2.3/x.mp4", "http://0.0.0.0/",
    "http://2130706433/",                    # 127.0.0.1 as one number
    "http://0x7f000001/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://metadata/", "http://localhost/a.mp4", "http://foo.localhost/", "http://printer.local/",
    "https://www.dropbox.com:8443/s/abc/ad.mp4",  # odd port
    "https://user:pw@www.dropbox.com/s/abc",      # credentials
    "file:///etc/passwd", "gopher://example.com/", "ftp://example.com/a.mp4",
])
def test_bad_download_addresses_are_refused_before_any_connection(url):
    with pytest.raises(li.ImportRefused):
        li.check_url(url)


def test_a_redirect_to_metadata_is_refused_and_never_requested(tmp_path):
    asked = []

    def handler(r):
        asked.append(str(r.url))
        if r.url.host == "www.dropbox.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/iam/"})
        return httpx.Response(200, **OK_VIDEO)
    with pytest.raises(li.ImportRefused, match="public addresses"):
        li.download(resolved(), tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert asked == ["https://www.dropbox.com/s/abc/ad.mp4?dl=1"]


@pytest.mark.parametrize("location", ["http://localhost:8000/admin", "http://[::ffff:127.0.0.1]/", "//10.0.0.5/x",
                                      "http://metadata.google.internal/", "file:///etc/passwd"])
def test_every_redirect_hop_is_checked(tmp_path, location):
    hops = iter([httpx.Response(301, headers={"location": "https://uc123.dl.dropboxusercontent.com/cd/0/get/x"}),
                 httpx.Response(307, headers={"location": location})])
    client = httpx.Client(transport=httpx.MockTransport(lambda r: next(hops)))
    with pytest.raises(li.ImportRefused):
        li.download(resolved(), tmp_path, client=client)


def test_a_public_redirect_chain_still_downloads(tmp_path):
    def handler(r):
        if r.url.host == "www.dropbox.com":
            return httpx.Response(302, headers={"location": "https://uc123.dl.dropboxusercontent.com/cd/0/get/x"})
        return httpx.Response(200, **OK_VIDEO)
    out = li.download(resolved(), tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out.read_bytes().startswith(MP4_HEAD)


def test_too_many_redirects_are_refused(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"location": f"https://www.dropbox.com/s/{len(str(r.url))}"})))
    with pytest.raises(li.ImportRefused, match="redirects too many times"):
        li.download(resolved(), tmp_path, client=client)


# --- connect time: the real client resolves once, checks, connects to that address

def fake_dns(monkeypatch, answers):
    """answers: host -> list of IPs, or a callable returning one per call."""
    calls = []

    def getaddrinfo(host, port, *a, **k):
        calls.append(host)
        got = answers[host]() if callable(answers[host]) else answers[host]
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in got]
    monkeypatch.setattr(li, "resolver", getaddrinfo)
    return calls


def capture_connects(monkeypatch):
    """Record every TCP connect and refuse it (nothing leaves the machine).
    The suite's network guard refuses every non-local request at the
    transport; here the request goes on to the guarded pool instead, whose
    sockets are the fake below."""
    from httpx._transports.default import map_httpcore_exceptions
    seen = []

    def handle(self, request):
        assert isinstance(self._pool._network_backend, li._GuardedBackend)
        req = httpcore.Request(method=request.method,
                               url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                                                port=request.url.port, target=request.url.raw_path),
                               headers=request.headers.raw, content=request.stream, extensions=request.extensions)
        with map_httpcore_exceptions():
            got = self._pool.handle_request(req)
        return httpx.Response(status_code=got.status, headers=got.headers, content=got.read())
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)

    def connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        seen.append((host, port))
        raise httpcore.ConnectError("test: no network")
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    return seen


def test_the_real_client_connects_to_the_address_it_checked(monkeypatch):
    fake_dns(monkeypatch, {"www.dropbox.com": ["162.125.1.18"]})
    seen = capture_connects(monkeypatch)
    with li.safe_client() as client, pytest.raises(httpx.ConnectError):
        client.get("https://www.dropbox.com/s/abc")
    assert seen == [("162.125.1.18", 443)]


@pytest.mark.parametrize("answer", [["127.0.0.1"], ["169.254.169.254"], ["162.125.1.18", "10.0.0.7"], ["::ffff:192.168.0.1"],
                                    ["100.100.100.200"]])
def test_a_name_that_resolves_to_a_private_address_never_connects(monkeypatch, tmp_path, answer):
    fake_dns(monkeypatch, {"www.dropbox.com": answer})
    seen = capture_connects(monkeypatch)
    with li.safe_client() as client, pytest.raises(li.ImportRefused, match="public addresses"):
        li.download(resolved(), tmp_path, client=client)
    assert seen == []


def test_dns_rebinding_cannot_swap_the_address_after_the_check(monkeypatch):
    """First answer public, every later answer loopback: the one connection
    made uses the first (checked) answer; nothing resolves the name again."""
    answers = iter([["162.125.1.18"]] + [["127.0.0.1"]] * 10)
    calls = fake_dns(monkeypatch, {"www.dropbox.com": lambda: next(answers)})
    seen = capture_connects(monkeypatch)
    with li.safe_client() as client, pytest.raises(httpx.ConnectError):
        client.get("https://www.dropbox.com/s/abc")
    assert calls == ["www.dropbox.com"] and seen == [("162.125.1.18", 443)]
    with li.safe_client() as client, pytest.raises(li.ImportRefused):
        client.get("https://www.dropbox.com/s/abc")   # the next connect re-checks and refuses
    assert seen == [("162.125.1.18", 443)]


def test_the_real_client_ignores_proxy_settings_and_does_not_follow_redirects(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:3128")
    client = li.safe_client()
    assert client.trust_env is False and client.follow_redirects is False
    assert isinstance(client._transport._pool._network_backend, li._GuardedBackend)


def test_the_import_route_uses_the_guarded_client():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "app" / "api" / "main.py").read_text()
    assert "_link_http or linkimport.safe_client()" in src and "httpx.Client()\n" not in src.split("def _run_import", 1)[1][:1500]

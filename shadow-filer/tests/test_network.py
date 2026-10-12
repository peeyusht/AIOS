"""Network: tidying what Windows reports and the findings. A made-up answer stands in for PowerShell."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dashboard  # noqa: E402
import network  # noqa: E402

WIN = "C:\\Windows\\System32\\svchost.exe"


def raw(**over):
    r = {
        "computer": "DEMO-PC",
        "adapters": [
            {"index": 5, "name": "Ethernet", "description": "Intel(R) Ethernet", "status": "Up", "speed": 1_000_000_000,
             "mac": "AA-BB-CC-00-11-22", "virtual": False, "media": "802.3", "kind": "802.3"},
            {"index": 9, "name": "WiFi", "description": "Wireless-AC 802.11", "status": "Disconnected", "speed": 0,
             "mac": "AA-BB-CC-00-11-33", "virtual": False, "media": "Native 802.11", "kind": "Native 802.11"},
            {"index": 12, "name": "vEthernet (Lab)", "description": "Hyper-V Virtual Ethernet Adapter", "status": "Up",
             "speed": 10_000_000_000, "mac": "00-15-5D-00-00-01", "virtual": True, "media": "", "kind": ""},
        ],
        "ips": [{"index": 5, "address": "192.168.2.101", "prefix": 24, "family": "IPv4", "origin": "Dhcp"},
                {"index": 5, "address": "fe80::1%5", "prefix": 64, "family": "IPv6", "origin": "WellKnown"},
                {"index": 12, "address": "172.20.0.1", "prefix": 20, "family": "IPv4", "origin": "Manual"}],
        "ifaces": [{"index": 5, "family": "IPv4", "dhcp": "Enabled", "metric": 25, "mtu": 1500},
                   {"index": 12, "family": "IPv4", "dhcp": "Disabled", "metric": 5000, "mtu": 1500}],
        "dns": [{"index": 5, "family": 2, "servers": ["192.168.2.1"]}, {"index": 12, "family": 2, "servers": []}],
        "profiles": [{"index": 5, "name": "Home", "category": "Private", "ipv4": "Internet", "ipv6": "NoTraffic"}],
        "routes": [{"index": 5, "destination": "0.0.0.0/0", "next": "192.168.2.1", "metric": 0, "family": "IPv4", "protocol": "NetMgmt"},
                   {"index": 5, "destination": "192.168.2.0/24", "next": "0.0.0.0", "metric": 256, "family": "IPv4", "protocol": "Local"},
                   {"index": 5, "destination": "192.168.2.101/32", "next": "0.0.0.0", "metric": 256, "family": "IPv4", "protocol": "Local"},
                   {"index": 5, "destination": "224.0.0.0/4", "next": "0.0.0.0", "metric": 256, "family": "IPv4", "protocol": "Local"},
                   {"index": 1, "destination": "127.0.0.0/8", "next": "0.0.0.0", "metric": 256, "family": "IPv4", "protocol": "Local"}],
        "firewall": [{"name": "Domain", "enabled": True, "inbound": "Block", "outbound": "Allow"},
                     {"name": "Private", "enabled": True, "inbound": "Block", "outbound": "Allow"},
                     {"name": "Public", "enabled": True, "inbound": "Block", "outbound": "Allow"}],
        "shares": [{"name": "C$", "path": "C:\\", "type": 2147483648, "description": "Default share"},
                   {"name": "IPC$", "path": "", "type": 2147483651, "description": "Remote IPC"}],
        "listen": [{"proto": "TCP", "address": "0.0.0.0", "port": 27017, "pid": 100, "process": "tessd", "path": "C:\\Tess\\tessd.exe"},
                   {"proto": "TCP", "address": "::", "port": 27017, "pid": 100, "process": "tessd", "path": "C:\\Tess\\tessd.exe"},
                   {"proto": "TCP", "address": "127.0.0.1", "port": 8765, "pid": 200, "process": "pythonw", "path": "D:\\a\\pythonw.exe"},
                   {"proto": "TCP", "address": "0.0.0.0", "port": 135, "pid": 300, "process": "svchost", "path": WIN},
                   {"proto": "UDP", "address": "0.0.0.0", "port": 5353, "pid": 300, "process": "svchost", "path": WIN}],
        "conns": [{"local": "192.168.2.101", "lport": 50001, "remote": "93.184.216.34", "rport": 443, "pid": 400, "process": "browser"},
                  {"local": "192.168.2.101", "lport": 50002, "remote": "93.184.216.34", "rport": 443, "pid": 400, "process": "browser"},
                  {"local": "192.168.2.101", "lport": 50003, "remote": "192.168.2.50", "rport": 445, "pid": 4, "process": "System"},
                  {"local": "127.0.0.1", "lport": 50004, "remote": "127.0.0.1", "rport": 8765, "pid": 400, "process": "browser"}],
        "neigh": [{"index": 5, "address": "192.168.2.1", "mac": "11-22-33-44-55-66", "state": "Reachable", "family": "IPv4"},
                  {"index": 5, "address": "192.168.2.50", "mac": "11-22-33-44-55-77", "state": "Stale", "family": "IPv4"},
                  {"index": 5, "address": "192.168.2.255", "mac": "FF-FF-FF-FF-FF-FF", "state": "Permanent", "family": "IPv4"},
                  {"index": 5, "address": "224.0.0.22", "mac": "01-00-5E-00-00-16", "state": "Permanent", "family": "IPv4"},
                  {"index": 5, "address": "192.168.2.77", "mac": "00-00-00-00-00-00", "state": "Unreachable", "family": "IPv4"}],
        "proxy": {"enabled": False, "server": "", "script": "", "bypass": ""},
        "hosts": [], "wifi": [], "suffixes": [], "other_firewalls": [],
    }
    r.update(over)
    return r


class TidyTest(unittest.TestCase):
    def test_interfaces_routes_ports_connections_devices(self):
        v = network.tidy(raw())
        eth, lab, wifi = v["adapters"]                      # connected and real first, not connected last
        self.assertEqual((eth["name"], eth["kind"], eth["up"], eth["gateways"], eth["dns"], eth["dhcp"], eth["category"], eth["internet"]),
                         ("Ethernet", "ethernet", True, ["192.168.2.1"], ["192.168.2.1"], True, "private", True))
        self.assertEqual([(a["address"], a["scope"]) for a in eth["addresses"]],
                         [("192.168.2.101", "local network"), ("fe80::1", "local network")])
        self.assertEqual((lab["kind"], wifi["kind"], wifi["up"]), ("virtual", "wifi", False))
        self.assertEqual([(r["destination"], r["kind"], r["on_link"], r["interface"]) for r in v["routes"]][:3],
                         [("0.0.0.0/0", "default", False, "Ethernet"), ("192.168.2.0/24", "network", True, "Ethernet"),
                          ("192.168.2.101/32", "host", True, "Ethernet")])
        # the same port on IPv4 and IPv6 is one entry; what only this PC can reach is told apart
        self.assertEqual([(e["proto"], e["port"], e["process"], e["reach"], e["windows"]) for e in v["listening"]],
                         [("TCP", 27017, "tessd", "network", False), ("TCP", 135, "svchost", "network", True),
                          ("UDP", 5353, "svchost", "network", True), ("TCP", 8765, "pythonw", "this PC", False)])
        self.assertEqual([(g["process"], g["count"], g["internet"], g["local"]) for g in v["connections"]],
                         [("browser", 2, 2, 0), ("System", 1, 0, 1)])       # a connection to this PC itself is not one
        self.assertEqual(v["connections"][0]["remotes"], [{"address": "93.184.216.34", "port": 443, "count": 2, "scope": "internet"}])
        self.assertEqual([(d["address"], d["gateway"], d["state"]) for d in v["devices"]],
                         [("192.168.2.1", True, "reachable"), ("192.168.2.50", False, "stale")])   # no broadcast, multicast, dead entries
        self.assertEqual(v["counts"], {"adapters_up": 2, "adapters": 3, "routes": 5, "listening": 4, "listening_network": 3,
                                       "listening_network_other": 1, "connections": 3, "programs_connected": 2, "devices": 2,
                                       "shares": 0, "hosts": 0, "rules": None, "rule_programs": 0})

    def test_a_setting_nobody_changed_shows_what_windows_then_does(self):
        untouched = [{"name": "Public", "enabled": True, "inbound": "NotConfigured", "outbound": "NotConfigured"},
                     {"name": "Private", "enabled": True, "inbound": "Allow", "outbound": "Block"}]
        pub, priv = network.tidy(raw(firewall=untouched))["firewall"]
        self.assertEqual((pub["inbound"], pub["outbound"], pub["inbound_default"]), ("Block", "Allow", True))
        self.assertEqual((priv["inbound"], priv["outbound"], priv["inbound_default"]), ("Allow", "Block", False))

    def test_scope(self):
        for a, want in (("127.0.0.1", "this PC"), ("::1", "this PC"), ("0.0.0.0", "all"), ("::", "all"),
                        ("192.168.1.5", "local network"), ("10.0.0.1", "local network"), ("fe80::1%12", "local network"),
                        ("93.184.216.34", "internet"), ("nonsense", "unknown")):
            self.assertEqual(network.scope(a), want, a)

    def test_findings(self):
        texts = lambda **o: [(f["level"], f["tab"], f["text"]) for f in network.tidy(raw(**o))["findings"]]
        quiet = texts()
        self.assertEqual([(lv, tab) for lv, tab, _ in quiet], [("info", "exposure"), ("info", "exposure")])
        self.assertIn("1 TCP port opened by programs that are not part of Windows accept connections from the network (tessd)", quiet[0][2])
        self.assertIn("marked Private", quiet[1][2])
        off = [{"name": n, "enabled": False, "inbound": "NotConfigured", "outbound": "NotConfigured"} for n in ("Domain", "Private", "Public")]
        got = texts(firewall=off)
        self.assertEqual(got[0][:2], ("danger", "exposure"))
        self.assertIn("off for all profiles, and no other firewall is registered", got[0][2])
        got = texts(firewall=off, other_firewalls=["Contoso Endpoint Firewall"])       # another product has the job
        self.assertEqual((got[0][0], "Contoso Endpoint Firewall is registered as the firewall instead" in got[0][2]), ("warning", True))
        one = [dict(f, enabled=f["name"] != "Public") for f in raw()["firewall"]]        # off, but not for this network
        self.assertEqual(texts(firewall=one)[0][0], "warning")
        got = texts(shares=[{"name": "Scans", "path": "D:\\Scans", "type": 0, "description": ""}],
                    proxy={"enabled": True, "server": "proxy.example:8080", "script": "", "bypass": ""},
                    hosts=["10.0.0.5 intranet.example  # note", "bad line"])
        self.assertIn(("warning", "exposure", "1 folder is shared from this PC: Scans."), got)
        self.assertEqual([t[1] for t in got if t[0] == "info"][-2:], ["dns", "dns"])
        got = texts(ips=[{"index": 5, "address": "169.254.10.20", "prefix": 16, "family": "IPv4", "origin": "WellKnown"}],
                    routes=[])
        self.assertIn("has no address from the network", " ".join(t[2] for t in got))

    def test_kept_in_memory_only_and_fails_quietly(self):
        network._cache.update(at=0.0, value=None)
        calls = []

        def read():
            calls.append(1)
            return raw()
        a = network.view(read=read)
        b = network.view(read=read)                          # within the cache time: Windows is not asked again
        self.assertEqual((len(calls), a is b, network.peek() is a), (1, True, True))
        network.view(force=True, read=read)
        self.assertEqual(len(calls), 2)
        network._cache.update(at=0.0, value=None)
        v = network.view(read=lambda: None)
        self.assertEqual((v["read_at"], v["adapters"], bool(v["error"]), network.peek()), (None, [], True, None))
        src = Path(network.__file__).read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", src)                     # nothing here is written to a database or a file
        self.assertNotIn("write_text", src)

    def test_firewall_rules(self):
        base = "v2.31|Action=Allow|Active=TRUE|Dir=In|"
        lines = [
            base + "Protocol=6|Profile=Public|LPort=7070|App=C:\\Apps\\harbor.exe|Name=Harbor|",
            base + "Protocol=17|Profile=Private|LPort=7070|LPort=7071|App=C:\\Apps\\harbor.exe|Name=Harbor UDP|RA4=LocalSubnet|",
            base + "App=C:\\Old\\v1\\gone.exe|Name=Gone|",
            base + "App=C:\\Old\\v2\\gone.exe|Name=Gone|",                     # the same leftover in another old folder
            base + "Name=Let everything in|",                                        # no program, no port
            base + "Protocol=6|LPort=3389|Name=Remote desktop by hand|",             # a port without a program
            base + "App=%SystemRoot%\\system32\\svchost.exe|Svc=x|Name=@FirewallAPI.dll,-28502|",
            "v2.31|Action=Block|Active=TRUE|Dir=In|App=C:\\Apps\\blocked.exe|Name=Blocked|",
            "v2.31|Action=Allow|Active=FALSE|Dir=In|App=C:\\Apps\\off.exe|Name=Off|",
            "v2.31|Action=Allow|Active=TRUE|Dir=Out|App=C:\\Apps\\out.exe|Name=Out|",
        ]
        self.assertEqual(network.parse_rule(lines[1])["LPort"], ["7070", "7071"])
        v = network.rules_view(lines, exists=lambda p: "Old" not in p)
        self.assertEqual((v["total"], v["windows"], v["missing"], [w["name"] for w in v["wide_open"]]), (7, 1, 1, ["Let everything in"]))
        got = {g["program"]: g for g in v["programs"]}
        self.assertEqual(sorted(got), ["Remote desktop by hand", "gone.exe", "harbor.exe"])
        h = got["harbor.exe"]
        self.assertEqual((h["rules"], h["ports"], h["profiles"], h["any_address"], h["public"], h["missing"]),
                         (2, ["7070", "7071"], ["Private", "Public"], True, True, False))
        self.assertEqual((got["gone.exe"]["rules"], got["gone.exe"]["missing"], got["gone.exe"]["any_port"]), (2, True, True))
        self.assertEqual(v["programs"][0]["program"], "gone.exe")                    # leftovers first
        self.assertIsNone(network.rules_view(None))
        n = network.tidy(raw(rules=lines))
        self.assertIn("1 firewall rule lets any program accept connections on any port (Let everything in).",
                      [f["text"] for f in n["findings"] if f["level"] == "warning"])
        self.assertEqual((n["counts"]["rules"], n["counts"]["rule_programs"]), (7, 3))

    def test_dashboard_gets_the_serious_findings_only(self):
        off = [{"name": n, "enabled": False, "inbound": "", "outbound": ""} for n in ("Domain", "Private", "Public")]
        net = {"findings": [f for f in network.tidy(raw(firewall=off))["findings"] if f["level"] != "info"]}
        got = dashboard.attention({"network": net})
        self.assertEqual([(a["level"], a["to"]) for a in got], [("danger", "/network")])


if __name__ == "__main__":
    unittest.main()

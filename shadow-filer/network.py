"""
Network: how this PC is connected and what it exposes. Interfaces and their addresses, the routing table,
DNS servers, proxy and hosts file, Windows Firewall and the network's Public/Private mark, folders shared
from this PC, every listening port with the program behind it, the connections open right now, and the
other devices on the local network that Windows already knows about.

READ-ONLY and passive. One fixed PowerShell call with no arguments asks Windows for what it already holds.
Nothing is changed, nothing is sent, and the network is NOT scanned: "devices" is Windows' own neighbour
table (who this PC has talked to), not a sweep of addresses. No lookup of the public address, since that
would go online.

Kept in memory only (for `CACHE_SECONDS`), like origin.py: addresses of the sites you are connected to and
of the devices around you are not written to the database, the report files or the log. The log gets counts.

Measured on the user's PC (12 Oct 2026): see CLAUDE.md.
"""
import ipaddress
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime

CREATE_NO_WINDOW = 0x08000000
CACHE_SECONDS = 30
_lock = threading.Lock()
_cache = {"at": 0.0, "value": None}

NETWORK_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$procs = @{}
foreach ($p in Get-Process) { $procs[[int]$p.Id] = @{ name = "$($p.ProcessName)"; path = "$($p.Path)" } }
function Proc($id) { $e = $procs[[int]$id]; if ($e) { $e } else { @{ name = ''; path = '' } } }
$adapters = foreach ($a in Get-NetAdapter -IncludeHidden:$false) {
  [pscustomobject]@{ index = [int]$a.ifIndex; name = "$($a.Name)"; description = "$($a.InterfaceDescription)";
    status = "$($a.Status)"; speed = [long]$a.Speed; mac = "$($a.MacAddress)"; virtual = [bool]$a.Virtual;
    media = "$($a.PhysicalMediaType)"; kind = "$($a.MediaType)" }
}
$ips = foreach ($i in Get-NetIPAddress) {
  [pscustomobject]@{ index = [int]$i.InterfaceIndex; address = "$($i.IPAddress)"; prefix = [int]$i.PrefixLength;
    family = "$($i.AddressFamily)"; origin = "$($i.PrefixOrigin)" }
}
$ifaces = foreach ($i in Get-NetIPInterface) {
  [pscustomobject]@{ index = [int]$i.ifIndex; family = "$($i.AddressFamily)"; dhcp = "$($i.Dhcp)";
    metric = [int]$i.InterfaceMetric; mtu = [long]$i.NlMtu; alias = "$($i.InterfaceAlias)"; connected = "$($i.ConnectionState)" }
}
$dns = foreach ($d in Get-DnsClientServerAddress) {
  [pscustomobject]@{ index = [int]$d.InterfaceIndex; family = [int]$d.AddressFamily; servers = @($d.ServerAddresses) }
}
$profiles = foreach ($p in Get-NetConnectionProfile) {
  [pscustomobject]@{ index = [int]$p.InterfaceIndex; name = "$($p.Name)"; category = "$($p.NetworkCategory)";
    ipv4 = "$($p.IPv4Connectivity)"; ipv6 = "$($p.IPv6Connectivity)" }
}
$routes = foreach ($r in Get-NetRoute) {
  [pscustomobject]@{ index = [int]$r.ifIndex; destination = "$($r.DestinationPrefix)"; next = "$($r.NextHop)";
    metric = [int]$r.RouteMetric; family = "$($r.AddressFamily)"; protocol = "$($r.Protocol)"; alias = "$($r.InterfaceAlias)" }
}
$firewall = foreach ($f in Get-NetFirewallProfile) {
  [pscustomobject]@{ name = "$($f.Name)"; enabled = "$($f.Enabled)" -eq 'True'; inbound = "$($f.DefaultInboundAction)";
    outbound = "$($f.DefaultOutboundAction)" }
}
$shares = foreach ($s in Get-CimInstance Win32_Share) {
  [pscustomobject]@{ name = "$($s.Name)"; path = "$($s.Path)"; type = [long]$s.Type; description = "$($s.Description)" }
}
$listen = @()
foreach ($l in Get-NetTCPConnection -State Listen) {
  $p = Proc $l.OwningProcess
  $listen += [pscustomobject]@{ proto = 'TCP'; address = "$($l.LocalAddress)"; port = [int]$l.LocalPort;
    pid = [int]$l.OwningProcess; process = $p.name; path = $p.path }
}
foreach ($l in Get-NetUDPEndpoint) {
  $p = Proc $l.OwningProcess
  $listen += [pscustomobject]@{ proto = 'UDP'; address = "$($l.LocalAddress)"; port = [int]$l.LocalPort;
    pid = [int]$l.OwningProcess; process = $p.name; path = $p.path }
}
$conns = foreach ($c in Get-NetTCPConnection -State Established) {
  $p = Proc $c.OwningProcess
  [pscustomobject]@{ local = "$($c.LocalAddress)"; lport = [int]$c.LocalPort; remote = "$($c.RemoteAddress)";
    rport = [int]$c.RemotePort; pid = [int]$c.OwningProcess; process = $p.name }
}
$neigh = foreach ($n in Get-NetNeighbor) {
  [pscustomobject]@{ index = [int]$n.ifIndex; address = "$($n.IPAddress)"; mac = "$($n.LinkLayerAddress)";
    state = "$($n.State)"; family = "$($n.AddressFamily)" }
}
$inet = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$proxy = [pscustomobject]@{ enabled = [int]$inet.ProxyEnable -eq 1; server = "$($inet.ProxyServer)";
  script = "$($inet.AutoConfigURL)"; bypass = "$($inet.ProxyOverride)" }
$hosts = @(Get-Content -LiteralPath "$env:SystemRoot\System32\drivers\etc\hosts" | Where-Object { $_ -match '^\s*[0-9a-fA-F:.]+\s+\S' } | ForEach-Object { "$_" })
$wifi = @(netsh wlan show interfaces | ForEach-Object { "$_" })
$global = Get-DnsClientGlobalSetting
$others = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct | ForEach-Object { "$($_.displayName)" })
$out = [pscustomobject]@{ computer = "$env:COMPUTERNAME"; adapters = @($adapters); ips = @($ips); ifaces = @($ifaces);
  dns = @($dns); profiles = @($profiles); routes = @($routes); firewall = @($firewall); shares = @($shares);
  listen = @($listen); conns = @($conns); neigh = @($neigh); proxy = $proxy; hosts = $hosts; wifi = $wifi;
  suffixes = @($global.SuffixSearchList); other_firewalls = $others }
$json = ConvertTo-Json -InputObject $out -Compress -Depth 6
'JSON:' + [regex]::Replace($json, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
"""


def read_network() -> dict | None:
    """Everything Windows knows, raw. None when it could not be asked."""
    if os.name != "nt":
        return None
    root = os.environ.get("SystemRoot", r"C:\Windows")
    ps = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    try:
        r = subprocess.run([ps if os.path.exists(ps) else "powershell.exe", "-NoProfile", "-NonInteractive",
                            "-Command", NETWORK_PS], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, creationflags=CREATE_NO_WINDOW)
        line = next((x for x in r.stdout.splitlines() if x.startswith("JSON:")), None)
        raw = json.loads(line[5:]) if line else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(raw, dict):
        return None
    raw["rules"] = read_rules()
    return raw


RULE_KEYS = (r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules",
             r"SOFTWARE\Policies\Microsoft\WindowsFirewall\FirewallRules")


def read_rules() -> list | None:
    """Windows Firewall's rules as Windows stores them (one text line each), straight from the registry:
    asking the firewall cmdlets for each rule's program and ports takes tens of seconds. None if unreadable."""
    try:
        import winreg
    except ImportError:
        return None
    out, opened = [], 0
    for path in RULE_KEYS:
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except OSError:
            continue
        opened += 1
        with k:
            for i in range(winreg.QueryInfoKey(k)[1]):
                try:
                    _, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    continue
                if isinstance(value, str):
                    out.append(value)
    return out if opened else None


def parse_rule(line: str) -> dict:
    """'v2.31|Action=Allow|Active=TRUE|Dir=In|Protocol=6|Profile=Public|LPort=7070|App=C:\\x.exe|Name=X|' -> a dict;
    a field that can repeat (Profile, LPort) becomes a list."""
    d = {}
    for part in (line or "").split("|"):
        k, sep, v = part.partition("=")
        if sep:
            d.setdefault(k, []).append(v)
    return d


def rules_view(lines: list | None, exists=os.path.exists) -> dict | None:
    """The enabled rules that let connections IN, grouped by program, with the ones that deserve a look:
    a rule that lets any program in on any port, and rules for programs that are no longer there."""
    if lines is None:
        return None
    win = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows")) + os.sep
    total = windows = 0
    progs, wide = {}, []
    for line in lines:
        r = parse_rule(line)
        one = lambda k: (r.get(k) or [""])[0]
        if one("Action").lower() != "allow" or one("Active").upper() != "TRUE" or one("Dir").lower() != "in":
            continue
        total += 1
        app = os.path.expandvars(one("App"))
        name = one("Name")
        if name.startswith("@") or one("EmbedCtxt").startswith("@") or os.path.normcase(app).startswith(win) \
                or app.lower() == "system" or (not app and one("Svc")) or one("AppPkgId") or one("LUOwn") and not app:
            windows += 1
            continue
        ports = [p for p in r.get("LPort", []) + r.get("LPort2_10", []) if p]
        profiles = sorted({p for p in r.get("Profile", []) if p}) or ["all"]
        anywhere = not (r.get("RA4") or r.get("RA6"))
        if not app:
            if not ports:                    # no program and no port: everything, from the stated addresses
                wide.append({"name": name or "(unnamed rule)", "profiles": profiles, "any_address": anywhere})
                continue
            app = ""
        gone = bool(app) and not exists(app)
        # leftovers of one program in several old folders (each update of a browser part leaves one) are one entry
        key = ("gone:" + os.path.basename(app).lower()) if gone else (os.path.normcase(app) or "port:" + name)
        g = progs.setdefault(key, {"program": os.path.basename(app) or name or "(no program)", "path": app, "rules": 0,
                                   "ports": set(), "any_port": False, "profiles": set(), "any_address": False,
                                   "missing": gone})
        g["rules"] += 1
        g["ports"].update(ports)
        g["any_port"] = g["any_port"] or not ports
        g["profiles"].update(profiles)
        g["any_address"] = g["any_address"] or anywhere
    out = []
    for g in progs.values():
        nums = sorted(g["ports"], key=lambda p: (not p.isdigit(), int(p) if p.isdigit() else 0, p))
        out.append({**g, "ports": nums[:12], "more_ports": max(0, len(nums) - 12), "profiles": sorted(g["profiles"]),
                    "public": "all" in g["profiles"] or "Public" in g["profiles"]})
    out.sort(key=lambda g: (not g["missing"], not (g["public"] and g["any_address"]), g["program"].lower()))
    return {"total": total, "windows": windows, "programs": out, "wide_open": wide,
            "missing": sum(1 for g in out if g["missing"])}


# --------------------------------------------------------------------------- tidying
def _ip(s: str):
    try:
        return ipaddress.ip_address((s or "").split("%")[0])
    except ValueError:
        return None


def scope(address: str) -> str:
    """'this PC' (loopback), 'local network' (private or link-local), 'internet', or 'all' for 0.0.0.0 / ::."""
    ip = _ip(address)
    if ip is None:
        return "unknown"
    if ip.is_unspecified:
        return "all"
    if ip.is_loopback:
        return "this PC"
    if ip.is_private or ip.is_link_local or ip.is_multicast:
        return "local network"
    return "internet"


def _list(v) -> list:
    return v if isinstance(v, list) else [] if v is None else [v]


def _kind(a: dict) -> str:
    d, m = (a.get("description") or "").lower(), (a.get("media") or "").lower()
    if "802.11" in m or "wi-fi" in d or "wireless" in d or "wlan" in d:
        return "wifi"
    if "bluetooth" in d or "bluetooth" in m:
        return "bluetooth"
    if any(w in d for w in ("vpn", "fortinet", "wireguard", "tap-", "openvpn", "wintun", "anyconnect", "zerotier", "tailscale")):
        return "vpn"
    if a.get("virtual") or any(w in d for w in ("hyper-v", "vmware", "virtualbox", "vethernet", "wsl", "loopback", "docker")):
        return "virtual"
    return "ethernet"


def _wifi(lines: list) -> dict:
    """SSID, signal and security from `netsh wlan show interfaces` (English labels; empty elsewhere)."""
    out = {}
    for ln in _list(lines):
        m = re.match(r"\s*([A-Za-z ()]+?)\s*:\s*(.+?)\s*$", ln or "")
        if m:
            k = m.group(1).strip().lower()
            if k in ("ssid", "signal", "authentication", "radio type", "channel", "band") and k not in out:
                out[k.replace(" ", "_")] = m.group(2)
    return out


def _profile(f: dict) -> dict:
    """A firewall profile with what it actually does. Windows answers 'NotConfigured' when nobody changed the
    setting, which means its default applies: incoming connections blocked, outgoing allowed."""
    def effective(v, default):
        v = str(v or "")
        return (default, True) if v.lower() in ("notconfigured", "") else (v, False)
    inbound, in_def = effective(f.get("inbound"), "Block")
    outbound, out_def = effective(f.get("outbound"), "Allow")
    return {**f, "inbound": inbound, "outbound": outbound, "inbound_default": in_def, "outbound_default": out_def}


def tidy(raw: dict) -> dict:
    """The raw answer as the page shows it, plus the findings worth a look."""
    by = lambda rows, key="index": {k: [r for r in _list(rows) if r.get(key) == k] for k in {r.get(key) for r in _list(rows)}}
    ips, ifs, dns, prof = by(raw.get("ips")), by(raw.get("ifaces")), by(raw.get("dns")), by(raw.get("profiles"))
    routes = [r for r in _list(raw.get("routes")) if r.get("destination")]
    gateways = {}
    for r in routes:
        if r["destination"] in ("0.0.0.0/0", "::/0") and r.get("next") not in ("0.0.0.0", "::", ""):
            gateways.setdefault(r["index"], []).append(r["next"])
    wifi = _wifi(raw.get("wifi"))
    adapters = []
    for a in _list(raw.get("adapters")):
        i, kind = a.get("index"), _kind(a)
        addrs = [{"address": x["address"].split("%")[0], "prefix": x.get("prefix"), "family": x.get("family"),
                  "origin": (x.get("origin") or "").lower(), "scope": scope(x["address"])}
                 for x in ips.get(i, []) if x.get("address")]
        v4 = next((f for f in ifs.get(i, []) if f.get("family") == "IPv4"), {})
        p = (prof.get(i) or [{}])[0]
        up = (a.get("status") or "").lower() == "up"
        adapters.append({
            "index": i, "name": a.get("name") or "", "description": a.get("description") or "", "kind": kind,
            "up": up, "status": a.get("status") or "", "speed": a.get("speed") or 0, "mac": a.get("mac") or "",
            "addresses": sorted(addrs, key=lambda x: (x["family"] != "IPv4", x["address"])),
            "gateways": sorted(set(gateways.get(i, []))),
            "dns": [s for d in dns.get(i, []) for s in _list(d.get("servers"))],
            "dhcp": (v4.get("dhcp") or "").lower() == "enabled", "metric": v4.get("metric"), "mtu": v4.get("mtu"),
            "network": p.get("name") or None, "category": (p.get("category") or "").lower() or None,
            "internet": (p.get("ipv4") or "").lower() == "internet" or (p.get("ipv6") or "").lower() == "internet",
            "wifi": wifi if kind == "wifi" and up else None})
    adapters.sort(key=lambda a: (not a["up"], a["kind"] in ("virtual", "bluetooth"), a["metric"] if a["metric"] is not None else 9999, a["name"]))
    names = {a["index"]: a["name"] for a in adapters}

    def route(r):
        dest = r["destination"]
        net = None
        try:
            net = ipaddress.ip_network(dest, strict=False)
        except ValueError:
            pass
        kind = ("default" if dest in ("0.0.0.0/0", "::/0") else "loopback" if net and net.is_loopback
                else "multicast" if net and net.is_multicast else "link" if net and net.is_link_local
                else "host" if net and net.prefixlen == net.max_prefixlen else "network")
        return {"destination": dest, "next": r.get("next") or "", "on_link": r.get("next") in ("0.0.0.0", "::", ""),
                "interface": names.get(r.get("index")) or r.get("alias") or "", "metric": r.get("metric"),
                "family": r.get("family"), "protocol": r.get("protocol") or "", "kind": kind}
    rt = sorted((route(r) for r in routes), key=lambda r: (r["family"] != "IPv4", r["kind"] != "default", r["kind"] in ("multicast", "loopback", "link"), r["destination"], r["metric"] or 0))

    win = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows")) + os.sep
    ports = {}
    for l in _list(raw.get("listen")):
        key = (l.get("proto"), l.get("port"), l.get("pid"))
        e = ports.setdefault(key, {"proto": l.get("proto"), "port": l.get("port"), "process": l.get("process") or "",
                                   "path": l.get("path") or "", "pid": l.get("pid"), "addresses": [], "reach": "this PC"})
        e["addresses"].append((l.get("address") or "").split("%")[0])
        s = scope(l.get("address") or "")
        if s in ("all", "local network", "internet"):
            e["reach"] = "network"
    listening = []
    for e in ports.values():
        e["addresses"] = sorted(set(e["addresses"]))
        e["windows"] = (not e["path"] and e["pid"] in (0, 4)) or os.path.normcase(e["path"]).startswith(win) or e["process"].lower() in ("system", "svchost", "lsass", "wininit", "services", "spoolsv")
        listening.append(e)
    listening.sort(key=lambda e: (e["reach"] != "network", e["windows"], e["proto"], e["port"]))

    groups = {}
    for c in _list(raw.get("conns")):
        s = scope(c.get("remote") or "")
        if s in ("this PC", "unknown", "all"):
            continue
        g = groups.setdefault(c.get("process") or "?", {"process": c.get("process") or "?", "count": 0, "internet": 0,
                                                        "local": 0, "remotes": {}})
        g["count"] += 1
        g["internet" if s == "internet" else "local"] += 1
        k = (c.get("remote"), c.get("rport"))
        g["remotes"][k] = g["remotes"].get(k, 0) + 1
    connections = [{**g, "remotes": [{"address": a, "port": p, "count": n, "scope": scope(a)}
                                     for (a, p), n in sorted(g["remotes"].items(), key=lambda x: -x[1])[:25]]}
                   for g in groups.values()]
    connections.sort(key=lambda g: (-g["count"], g["process"].lower()))

    gw_all = {g for v in gateways.values() for g in v}
    devices = []
    for n in _list(raw.get("neigh")):
        ip, mac = _ip(n.get("address") or ""), (n.get("mac") or "").upper()
        if (ip is None or ip.is_multicast or ip.is_unspecified or ip.is_loopback or not mac
                or set(mac.replace("-", "").replace(":", "")) <= {"0"} or mac.replace("-", "") == "F" * 12
                or (n.get("state") or "").lower() in ("unreachable", "incomplete")
                or str(ip).endswith(".255") or (ip.version == 6 and ip.is_link_local)):
            continue
        devices.append({"address": str(ip), "mac": mac, "state": (n.get("state") or "").lower(),
                        "interface": names.get(n.get("index")) or "", "gateway": str(ip) in gw_all, "family": n.get("family")})
    devices.sort(key=lambda d: (not d["gateway"], d["interface"], _ip(d["address"]).version, int(_ip(d["address"]))))

    shares = [{"name": s.get("name") or "", "path": s.get("path") or "", "description": s.get("description") or "",
               "builtin": (s.get("name") or "").endswith("$") or int(s.get("type") or 0) >= 2 ** 31 or int(s.get("type") or 0) == 3,
               "printer": int(s.get("type") or 0) & 0xFF == 1}
              for s in _list(raw.get("shares")) if s.get("name")]
    hosts = []
    for ln in _list(raw.get("hosts")):
        parts = (ln or "").split("#")[0].split()
        if len(parts) >= 2:
            hosts.append({"address": parts[0], "names": parts[1:]})
    px = raw.get("proxy") or {}
    out = {"read_at": datetime.now().isoformat(timespec="seconds"), "computer": raw.get("computer") or "",
           "adapters": adapters, "routes": rt, "firewall": [_profile(f) for f in _list(raw.get("firewall"))],
           "rules": rules_view(raw.get("rules")),
           "other_firewalls": [x for x in _list(raw.get("other_firewalls")) if x],
           "shares": shares, "listening": listening, "connections": connections, "devices": devices,
           "dns": {"suffixes": [s for s in _list(raw.get("suffixes")) if s],
                   "servers": sorted({s for a in adapters if a["up"] for s in a["dns"]})},
           "proxy": {"enabled": bool(px.get("enabled")), "server": px.get("server") or "", "script": px.get("script") or "",
                     "bypass": px.get("bypass") or ""},
           "hosts": hosts}
    out["findings"] = findings(out)
    out["counts"] = {"adapters_up": sum(1 for a in adapters if a["up"]), "adapters": len(adapters), "routes": len(rt),
                     "listening": len(listening), "listening_network": sum(1 for e in listening if e["reach"] == "network"),
                     "listening_network_other": sum(1 for e in listening if e["reach"] == "network" and not e["windows"]),
                     "connections": sum(g["count"] for g in connections), "programs_connected": len(connections),
                     "devices": len(devices), "shares": sum(1 for s in shares if not s["builtin"]),
                     "rules": (out["rules"] or {}).get("total"), "rule_programs": len((out["rules"] or {}).get("programs") or []),
                     "hosts": len(hosts)}
    return out


def findings(n: dict) -> list:
    """What deserves a look, most serious first: {'level': danger | warning | info, 'text', 'tab'}."""
    out = []

    def add(level, text, tab):
        out.append({"level": level, "text": text, "tab": tab})

    off = [f["name"] for f in n["firewall"] if not f.get("enabled")]
    active = sorted({a["category"] for a in n["adapters"] if a["up"] and a["category"]})
    if off:
        hit = [c for c in active if c.capitalize() in off or (c == "domainauthenticated" and "Domain" in off)]
        other = n.get("other_firewalls") or []
        what = ("all profiles" if len(off) == len(n["firewall"]) else
                f"the {', '.join(off)} profile{'s' if len(off) != 1 else ''}")
        if other:       # another product says it is the firewall: worth knowing, not an alarm
            add("warning", f"Windows Firewall is off for {what}; {', '.join(other)} is registered as the firewall instead.", "exposure")
        else:
            add("danger" if hit else "warning",
                f"Windows Firewall is off for {what}" + (", including the one the network you are on uses" if hit and len(off) != len(n["firewall"]) else "")
                + ", and no other firewall is registered with Windows: nothing filters incoming connections.", "exposure")
    for f in n["firewall"]:
        if f.get("enabled") and (f.get("inbound") or "").lower() == "allow":
            add("warning", f"Windows Firewall lets every incoming connection through on the {f['name']} profile.", "exposure")
    ru = n.get("rules") or {}
    if ru.get("wide_open"):
        add("warning", f"{len(ru['wide_open'])} firewall rule{'s let' if len(ru['wide_open']) != 1 else ' lets'} any program accept "
                       f"connections on any port ({', '.join(w['name'] for w in ru['wide_open'][:3])}).", "exposure")
    if ru.get("missing"):
        add("info", f"{ru['missing']} program{'s' if ru['missing'] != 1 else ''} with a firewall rule {'are' if ru['missing'] != 1 else 'is'} "
                    "no longer on this PC; the rules are left over.", "exposure")
    user_shares = [s for s in n["shares"] if not s["builtin"] and not s["printer"]]
    if user_shares:
        add("warning", f"{len(user_shares)} folder{'s are' if len(user_shares) != 1 else ' is'} shared from this PC: "
            + ", ".join(s["name"] for s in user_shares[:4]) + ("…" if len(user_shares) > 4 else "") + ".", "exposure")
    for a in n["adapters"]:
        if a["up"] and any(x["address"].startswith("169.254.") for x in a["addresses"]) and not a["gateways"]:
            add("warning", f"{a['name']} has no address from the network (169.254…): it is connected but cannot reach anything.", "interfaces")
    defaults = [r for r in n["routes"] if r["kind"] == "default" and r["family"] == "IPv4"]
    if len({r["interface"] for r in defaults}) > 1:
        best = min(defaults, key=lambda r: r["metric"] if r["metric"] is not None else 9999)
        add("info", f"{len({r['interface'] for r in defaults})} interfaces offer a way to the internet; "
                    f"{best['interface']} is one of them. The lowest total metric wins.", "routes")
    other = [e for e in n["listening"] if e["reach"] == "network" and not e["windows"] and e["proto"] == "TCP"]
    if other:
        names = sorted({e["process"] for e in other if e["process"]})
        add("info", f"{len(other)} TCP port{'s' if len(other) != 1 else ''} opened by programs that are not part of Windows "
                    f"accept connections from the network ({', '.join(names[:5])}{'…' if len(names) > 5 else ''}).", "exposure")
    if "private" in active:
        add("info", "The network you are on is marked Private: this PC can be found by other devices on it. "
                    "Right at home or in the office, not on a network you do not trust.", "exposure")
    if n["proxy"]["enabled"] or n["proxy"]["script"]:
        add("info", "A proxy is set: web traffic of programs that follow the Windows setting goes through it.", "dns")
    if n["hosts"]:
        add("info", f"The hosts file overrides {len(n['hosts'])} name{'s' if len(n['hosts']) != 1 else ''}.", "dns")
    return out


def view(force: bool = False, read=read_network, log=None) -> dict:
    """The current picture, at most CACHE_SECONDS old. Never stored anywhere but here."""
    with _lock:
        if not force and _cache["value"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["value"]
        t0 = time.time()
        raw = read()
        if raw is None:
            return {"read_at": None, "error": "Windows could not be asked about the network.", "adapters": [], "routes": [],
                    "firewall": [], "shares": [], "listening": [], "connections": [], "devices": [],
                    "dns": {"suffixes": [], "servers": []}, "proxy": {"enabled": False, "server": "", "script": "", "bypass": ""},
                    "hosts": [], "findings": [], "counts": {}}
        v = tidy(raw)
        v["seconds"] = round(time.time() - t0, 1)
        _cache.update(at=time.time(), value=v)
        if log:      # counts only: no addresses in the log
            c = v["counts"]
            log.info("network: %d of %d interfaces up, %d routes, %d listening (%d from the network), %d connections, "
                     "%d devices, %d finding(s), %.1fs", c["adapters_up"], c["adapters"], c["routes"], c["listening"],
                     c["listening_network"], c["connections"], c["devices"], len(v["findings"]), v["seconds"])
        return v


def peek() -> dict | None:
    """The last picture, however old, without asking Windows. None before the first read."""
    return _cache["value"]


def refresh_soon(max_age: int = 900, log=None) -> None:
    """Read in the background unless the last picture is younger than `max_age` seconds. For the dashboard,
    which must not wait five seconds for PowerShell every minute."""
    if _cache["value"] is not None and time.time() - _cache["at"] < max_age:
        return
    if _lock.locked():
        return
    threading.Thread(target=lambda: view(force=True, log=log), daemon=True, name="network-read").start()


def as_text(v: dict) -> str:
    if not v.get("read_at"):
        return (v.get("error") or "Nothing read.") + "\n"
    c = v["counts"]
    lines = [f"Network on {v['computer']} ({v['read_at'].replace('T', ' ')}, {v.get('seconds', 0)} s)", ""]
    for f in v["findings"]:
        lines.append(f"  [{f['level']}] {f['text']}")
    lines += ["", "Interfaces:"]
    for a in v["adapters"]:
        if not a["up"]:
            continue
        v4 = ", ".join(f"{x['address']}/{x['prefix']}" for x in a["addresses"] if x["family"] == "IPv4")
        lines.append(f"  {a['name']} ({a['kind']}, {a['speed'] // 1_000_000} Mbit/s) {v4 or '-'}  gateway {', '.join(a['gateways']) or '-'}"
                     f"  dns {', '.join(a['dns'][:3]) or '-'}" + (f"  network {a['category']}" if a["category"] else ""))
    lines += [f"  ({c['adapters'] - c['adapters_up']} more are not connected)", "", "Routes (IPv4, without multicast and loopback):"]
    for r in v["routes"]:
        if r["family"] == "IPv4" and r["kind"] not in ("multicast", "loopback"):
            lines.append(f"  {r['destination']:<20} via {('on-link' if r['on_link'] else r['next']):<16} {r['interface']:<28} metric {r['metric']}")
    lines += ["", f"Firewall: " + ", ".join(f"{f['name']} {'on' if f.get('enabled') else 'OFF'}" for f in v["firewall"]),
              f"Listening: {c['listening']} ports, {c['listening_network']} reachable from the network "
              f"({c['listening_network_other']} by programs that are not part of Windows)",
              f"Connections now: {c['connections']} by {c['programs_connected']} programs",
              f"Devices Windows knows on the local network: {c['devices']}",
              f"Shared folders: {c['shares']}   hosts entries: {c['hosts']}   proxy: {'on' if v['proxy']['enabled'] else 'off'}"]
    return "\n".join(lines) + "\n"

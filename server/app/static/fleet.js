// Fleet page, phase 1: the list of devices of one organisation. The console key lives in sessionStorage,
// so it is gone when the tab closes. Everything is built with textContent: nothing a device reports is ever
// treated as HTML.
(function () {
  const $ = (id) => document.getElementById(id);
  const KEY = "sf-fleet-key";
  let timer = null;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function ago(seconds) {
    if (seconds == null) return "never";
    if (seconds < 90) return "just now";
    if (seconds < 3600) return Math.round(seconds / 60) + " min ago";
    if (seconds < 86400 * 2) return Math.round(seconds / 3600) + " h ago";
    return Math.round(seconds / 86400) + " days ago";
  }

  function badge(text, tone) { return el("span", "badge" + (tone ? " " + tone : ""), text); }

  function yesNo(v, yes, no) {
    if (v === true) return badge(yes, "ok");
    if (v === false) return badge(no, "bad");
    return badge("Unknown");
  }

  function tile(label, value, sub) {
    const t = el("div", "tile");
    t.append(el("div", "label", label), el("div", "value", String(value)));
    if (sub) t.append(el("div", "sub", sub));
    return t;
  }

  function show(data) {
    $("org").textContent = data.organisation ? data.organisation + ": devices that report to this server." : "Devices that report to this server.";
    $("updated").textContent = "Updated " + new Date(data.generated_at).toLocaleTimeString();
    const devices = data.devices;
    const late = (d) => d.silent_seconds == null || d.silent_seconds > data.checkin_seconds * 4;
    const tiles = $("tiles");
    tiles.replaceChildren(
      tile("Devices", devices.length, devices.filter(late).length + " not reporting"),
      tile("Firewall off", devices.filter((d) => d.summary.firewall && d.summary.firewall !== "on").length, "off or partly off"),
      tile("Not encrypted", devices.filter((d) => d.summary.encrypted === false).length, "a drive without BitLocker"),
      tile("Updates pending", devices.reduce((n, d) => n + (d.summary.updates || 0), 0), "across all devices"),
    );
    $("empty").hidden = devices.length > 0;
    $("devices").hidden = devices.length === 0;
    const body = $("devices").querySelector("tbody");
    body.replaceChildren(...devices.map((d) => {
      const s = d.summary || {};
      const tr = el("tr");
      const name = el("td");
      name.append(el("div", "name", d.name), el("div", "small", s.model || ""));
      const seen = el("td");
      seen.append(late(d) ? badge(ago(d.silent_seconds), "warn") : el("span", null, ago(d.silent_seconds)), el("div", "small", "agent " + (d.agent_version || "?")));
      const fw = el("td");
      fw.append(s.firewall == null ? badge("Unknown") : badge(s.firewall === "on" ? "On" : s.firewall === "off" ? "Off" : "Partly off", s.firewall === "on" ? "ok" : "bad"));
      const av = el("td"); av.append(yesNo(s.antivirus, "On", "Off"));
      const enc = el("td"); enc.append(yesNo(s.encrypted, "Yes", "No"));
      tr.append(name, el("td", null, s.windows || "—"), seen, el("td", "num", s.programs != null ? String(s.programs) : "—"),
        el("td", "num", s.updates != null ? String(s.updates) : "—"), fw, av, enc, el("td", "num", s.ports_open != null ? String(s.ports_open) : "—"));
      return tr;
    }));
  }

  async function load() {
    const key = sessionStorage.getItem(KEY);
    if (!key) return signedOut();
    let r;
    try { r = await fetch("/api/v1/devices", { headers: { Authorization: "Bearer " + key } }); }
    catch { $("updated").textContent = "The server is not answering."; return; }
    if (r.status === 401) { sessionStorage.removeItem(KEY); return signedOut("That key was not accepted."); }
    if (!r.ok) { $("updated").textContent = "The server answered " + r.status + "."; return; }
    $("signin").hidden = true; $("fleet").hidden = false; $("refresh").hidden = false; $("signout").hidden = false;
    show(await r.json());
  }

  function signedOut(message) {
    clearInterval(timer); timer = null;
    $("fleet").hidden = true; $("refresh").hidden = true; $("signout").hidden = true; $("signin").hidden = false;
    $("signin-error").textContent = message || "";
    $("updated").textContent = "";
  }

  $("signin").addEventListener("submit", (e) => {
    e.preventDefault();
    sessionStorage.setItem(KEY, $("key").value.trim());
    $("key").value = "";
    load().then(() => { if (!timer && sessionStorage.getItem(KEY)) timer = setInterval(load, 60000); });
  });
  $("refresh").addEventListener("click", load);
  $("signout").addEventListener("click", () => { sessionStorage.removeItem(KEY); signedOut(); });

  load().then(() => { if (sessionStorage.getItem(KEY)) timer = setInterval(load, 60000); });
})();

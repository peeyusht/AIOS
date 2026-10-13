"""
Builds the device agent's installer, in a Linux container (see Dockerfile and ../docker-compose.yml):

    /out/ShadowFilerAgent-<version>.msi      Python's own embeddable build for Windows, the `cryptography`
                                             package, and the nine source files named below. Nothing else.
    /out/ShadowFilerAgent-<version>.json     the release manifest
    /out/ShadowFilerAgent-<version>.sig      its signature, made with /keys/release-key.private.pem

Without the release key the installer is still built, but no agent will take it as an update. With
/keys/codesign.pfx (and CODESIGN_PASSWORD) the .msi is also signed for Windows (Authenticode), before the
manifest is made, because signing changes the file.

WHAT GOES IN is the two tuples below, and tests/test_agent.py checks that nothing able to change a PC is
among them. Adding a file here puts it on customers' PCs.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from xml.sax.saxutils import quoteattr

SHARED = ("fleet.py", "apps.py", "services.py", "network.py", "compliance.py")       # from shadow-filer/
OWN = ("agent.py", "winsvc.py", "selfupdate.py", "release.py")                       # from device-agent/
NEVER = {"remedy.py", "mover.py", "cleanup.py", "autofile.py", "web_ui.py", "shadow_agent.py", "library.py", "cve.py"}

PRODUCT = "ShadowFiler Agent"
SERVICE = "ShadowFilerAgent"
UPGRADE_CODE = "6d328991-4229-450b-8fd9-8b739011feb2"       # the same for every version: how Windows knows it is an upgrade
NAMESPACE = uuid.UUID("1f280d02-117f-44da-bef4-32a504f6a8b3")
PTH = "python312.zip\n.\n..\\app\n..\\lib\n"        # all Python may import from; no user folders, no environment variables
CMD = '@"%~dp0python\\python.exe" -B "%~dp0app\\agent.py" %*\r\n'


def ident(prefix: str, rel: str) -> str:
    return prefix + hashlib.md5(rel.encode("utf-8")).hexdigest()[:20]


def stage(src: Path, work: Path, version: str | None) -> str:
    """Lay out the folder the installer will copy to Program Files. Returns the version being built."""
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src / "python", work / "python")
    shutil.copytree(src / "lib", work / "lib")
    (work / "app").mkdir()
    assert not (set(SHARED) | set(OWN)) & NEVER
    for name in SHARED:
        shutil.copy2(src / "shared" / name, work / "app" / name)
    for name in OWN:
        shutil.copy2(src / "own" / name, work / "app" / name)
    agent = work / "app" / "agent.py"
    text = agent.read_text(encoding="utf-8")
    found = re.search(r'^VERSION = "(\d+\.\d+\.\d+)"$', text, re.M)
    if not found:
        sys.exit("agent.py has no VERSION = \"x.y.z\" line.")
    if version and version != found.group(1):          # for trying an upgrade; a real release changes agent.py
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            sys.exit("AGENT_VERSION must be three numbers, like 0.4.1.")
        agent.write_text(text.replace(found.group(0), f'VERSION = "{version}"'), encoding="utf-8", newline="\n")
    pth = next((work / "python").glob("python*._pth"))
    pth.write_text(PTH, encoding="ascii", newline="\r\n")
    (work / "sfagent.cmd").write_bytes(CMD.encode("ascii"))
    for junk in list(work.rglob("__pycache__")):
        shutil.rmtree(junk)
    return version or found.group(1)


def wxs(work: Path, version: str) -> str:
    """The installer's description: every file, the service, and the two values a silent install may leave."""
    files = sorted(p for p in work.rglob("*") if p.is_file())
    tree: dict = {}
    for f in files:
        node = tree
        for part in f.relative_to(work).parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault("", []).append(f)
    components = []

    def folder(node: dict, rel: str, depth: int) -> list:
        pad, out = "  " * depth, []
        for f in node.get("", []):
            r = f.relative_to(work).as_posix()
            cid = ident("c", r)
            components.append(cid)
            out.append(f'{pad}<Component Id="{cid}" Guid="{uuid.uuid5(NAMESPACE, r)}" Win64="yes">')
            out.append(f'{pad}  <File Id="{ident("f", r)}" Name={quoteattr(f.name)} Source={quoteattr(str(f))} KeyPath="yes"/>')
            if r == "python/python.exe":
                out.append(f'{pad}  <ServiceInstall Id="svc" Name="{SERVICE}" DisplayName="{PRODUCT}" Type="ownProcess" Start="auto" '
                           f'ErrorControl="normal" Account="LocalSystem" Arguments=\'-B "[INSTALLDIR]app\\agent.py" service\' '
                           f'Description="Reports this PC\'s installed programs and security settings to your organisation\'s fleet server. Reads only; changes nothing on the PC."/>')
                out.append(f'{pad}  <ServiceControl Id="svcctl" Name="{SERVICE}" Start="install" Stop="both" Remove="uninstall" Wait="yes"/>')
            out.append(f"{pad}</Component>")
        for name in sorted(k for k in node if k):
            sub = f"{rel}/{name}" if rel else name
            out.append(f'{pad}<Directory Id="{ident("d", sub)}" Name={quoteattr(name)}>')
            out += folder(node[name], sub, depth + 1)
            out.append(f"{pad}</Directory>")
        return out
    body = folder(tree, "", 5)
    components.append("cEnrol")
    refs = "\n".join(f'      <ComponentRef Id="{c}"/>' for c in components)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="{PRODUCT}" Language="1033" Version="{version}" Manufacturer="Shadow Filer" UpgradeCode="{UPGRADE_CODE}">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine"
             Description="{PRODUCT} {version}: reports this PC to your organisation's fleet server"/>
    <MajorUpgrade DowngradeErrorMessage="A newer version of {PRODUCT} is already installed."/>
    <Media Id="1" Cabinet="agent.cab" EmbedCab="yes"/>
    <Property Id="ARPNOMODIFY" Value="1"/>
    <Property Id="MsiHiddenProperties" Value="TOKEN"/>      <!-- keeps the token out of an installer log -->
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFiles64Folder">
        <Directory Id="INSTALLDIR" Name="{PRODUCT}">
{chr(10).join(body)}
          <!-- msiexec /i ... SERVER=https://... TOKEN=sfe_... : left for the service, which enrols and removes them -->
          <Component Id="cEnrol" Guid="{uuid.uuid5(NAMESPACE, 'enrol')}" Win64="yes">
            <Condition>SERVER AND TOKEN</Condition>
            <RegistryValue Root="HKLM" Key="SOFTWARE\\{PRODUCT}" Name="Server" Type="string" Value="[SERVER]" KeyPath="yes"/>
            <RegistryValue Root="HKLM" Key="SOFTWARE\\{PRODUCT}" Name="Token" Type="string" Value="[TOKEN]"/>
          </Component>
        </Directory>
      </Directory>
    </Directory>
    <Feature Id="Agent" Title="{PRODUCT}" Level="1">
{refs}
    </Feature>
  </Product>
</Wix>
"""


def remove_old_version_last(msi: Path) -> None:
    """An upgrade must take the old version away AFTER the new one is in place. wixl schedules it first, and
    Windows Installer has by then already decided that python.exe and every DLL "are there, same version,
    need no copying": it then removes them with the old version, and the service with them. That is what the
    first self-update did on 13 Oct 2026 (0.4.0 to 0.4.1: installed "successfully", no python.exe, no service).
    Removed last, the old version only gives up what the new one does not share."""
    table = Path("/tmp/InstallExecuteSequence.idt")
    text = subprocess.run(["msiinfo", "export", str(msi), "InstallExecuteSequence"], check=True, capture_output=True, text=True).stdout
    lines = text.splitlines()
    final = next(int(x.split("\t")[2]) for x in lines if x.startswith("InstallFinalize\t"))
    moved = f"RemoveExistingProducts\t\t{final + 100}"
    fixed = [moved if x.startswith("RemoveExistingProducts\t") else x for x in lines]
    if fixed == lines:
        sys.exit("The installer has no RemoveExistingProducts step to move: upgrades would not work.")
    table.write_bytes(("\r\n".join(fixed) + "\r\n").encode("ascii"))
    subprocess.run(["msibuild", str(msi), "-i", str(table)], check=True)
    after = subprocess.run(["msiinfo", "export", str(msi), "InstallExecuteSequence"], check=True, capture_output=True, text=True).stdout
    if moved not in after.splitlines():
        sys.exit("The upgrade step could not be moved to the end of the installer.")



def main() -> None:
    src, out, keys = Path("/src"), Path("/out"), Path("/keys")
    work = Path("/tmp/stage")
    version = stage(src, work, os.environ.get("AGENT_VERSION") or None)
    desc = Path("/tmp/agent.wxs")
    desc.write_text(wxs(work, version), encoding="utf-8")
    msi = out / f"ShadowFilerAgent-{version}.msi"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["wixl", "-a", "x64", "-o", str(msi), str(desc)], check=True)
    remove_old_version_last(msi)
    n = sum(1 for p in work.rglob("*") if p.is_file())
    print(f"{msi.name}: {msi.stat().st_size / 1e6:.1f} MB, {n} files, version {version}")

    pfx = keys / "codesign.pfx"
    if pfx.is_file():
        signed = msi.with_suffix(".signed")
        subprocess.run(["osslsigncode", "sign", "-pkcs12", str(pfx), "-pass", os.environ.get("CODESIGN_PASSWORD", ""),
                        "-n", PRODUCT, "-h", "sha256", *(["-ts", os.environ["CODESIGN_TIMESTAMP"]] if os.environ.get("CODESIGN_TIMESTAMP") else []),
                        "-in", str(msi), "-out", str(signed)], check=True)
        signed.replace(msi)
        print("signed for Windows with the certificate in keys/codesign.pfx")
    else:
        print("NOT signed for Windows (no keys/codesign.pfx): Windows will say the publisher is unknown")

    sys.path.insert(0, str(src / "own"))
    import release
    pem = keys / "release-key.private.pem"
    for old in (msi.with_suffix(".json"), msi.with_suffix(".sig")):
        old.unlink(missing_ok=True)
    if not pem.is_file():
        print("NO release signature (no keys/release-key.private.pem): agents will not take this as an update")
        return
    if release.public_of(pem.read_bytes()) not in release.RELEASE_KEYS:
        sys.exit("keys/release-key.private.pem is not the key whose public half is in release.py: agents would refuse this release.")
    text = release.manifest(version, msi.name, msi.read_bytes())
    msi.with_suffix(".json").write_text(text, encoding="utf-8")
    msi.with_suffix(".sig").write_text(release.sign(text, pem.read_bytes()), encoding="ascii")
    release.verify(text, msi.with_suffix(".sig").read_text(encoding="ascii"))
    print(f"release manifest and signature written; SHA-256 {hashlib.sha256(msi.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()

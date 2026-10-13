# Device agent (phase 4)

What is installed on a customer's PC: a small Windows service that reads the PC's programs, services,
firewall and security settings and reports them to the organisation's fleet server (`../server`) every 15
minutes. The file-organising agent in `../shadow-filer` is a personal tool and is not part of it.

| | |
|---|---|
| Sends | exactly what `fleet.payload()` lists (`../shadow-filer/fleet.py`, SENT / NEVER SENT) |
| Changes on the PC | nothing. The code that moves files, updates programs, stops services or switches the firewall is not in the installer, and nothing can send the agent a command |
| Listens | on no port. Outgoing HTTPS to its own fleet server only |
| Installs | only a newer version of itself, signed with the release key (`selfupdate.py`, `release.py`) |
| Runs as | SYSTEM, as the service `ShadowFilerAgent`. Its folder `C:\ProgramData\ShadowFiler Agent` (key, state, log) is closed to everyone but SYSTEM and administrators |

## Files

| File | Role |
|---|---|
| `agent.py` | the service's loop, enrolment, the commands, and the reading of a PC from the SYSTEM account |
| `winsvc.py` | the little that makes a Python program a Windows service (ctypes, no wrapper of someone else's) |
| `selfupdate.py` | fetch a newer release, check it, hand it to Windows Installer |
| `release.py` | what a release is and how its signature is checked. Also used by the server and the build |
| `build/` | builds the installer in a Linux container: `Dockerfile`, `make_msi.py`, `requirements.txt` |
| `keys/` | never committed: `release-key.private.pem`, and optionally `codesign.pfx` |

The installer holds Python's own embeddable build for Windows, the `cryptography` package, the four files
above and five modules shared with the other agent (`fleet.py`, `apps.py`, `services.py`, `network.py`,
`compliance.py`). The two tuples at the top of `build/make_msi.py` are the whole list; a test checks that
`remedy.py`, `mover.py` and the like are not on it and are not loaded.

## Build

```
docker compose run --rm --build build        # -> dist/ShadowFilerAgent-<version>.msi, .json, .sig
```
No build tools are needed on the PC. The version is `VERSION` in `agent.py` (three numbers). The build
downloads two things while the image is made, both pinned by hash: Python's embeddable zip from python.org
and three Windows wheels from PyPI.

**Signing, two different things:**
- *The release signature* (`.json` + `.sig`, Ed25519, made with `keys/release-key.private.pem`). This is
  what an agent checks before it installs an update. The public half is in `release.py`. Keep the private
  half off every server; whoever has it can update every agent. It was made on 13 Oct 2026 and is not
  protected by a password: move it somewhere safe before there is a real customer.
- *Windows' own signature* (Authenticode). Needs a code-signing certificate, which we do not have. Put it at
  `keys/codesign.pfx` and set `CODESIGN_PASSWORD` (and `CODESIGN_TIMESTAMP` to a timestamp server's address,
  which makes the build go online); until then Windows says "unknown publisher" when the installer is run by
  hand.

## Install and enrol

Make an enrolment token in the console (Access), then on the PC, from an administrator's prompt:
```
msiexec /i ShadowFilerAgent-0.4.0.msi /qn SERVER=https://fleet.example.com TOKEN=sfe_...
```
or install first and enrol later:
```
"C:\Program Files\ShadowFiler Agent\sfagent.cmd" enrol https://fleet.example.com sfe_...
"C:\Program Files\ShadowFiler Agent\sfagent.cmd" status
"C:\Program Files\ShadowFiler Agent\sfagent.cmd" show          # the last report, exactly as sent
"C:\Program Files\ShadowFiler Agent\sfagent.cmd" updates off   # no self-update on this PC
"C:\Program Files\ShadowFiler Agent\sfagent.cmd" leave
```
Either way the server and token are left in the registry (`HKLM\SOFTWARE\ShadowFiler Agent`) and the service
enrols within a minute and removes them; for that minute a person signed in to the PC could read the token.
The PC makes its own key pair when it enrols; the server gets the public half only. Uninstalling removes the
program and the service and leaves the folder in ProgramData: run `leave` first to forget the key.

## Publish an update

```
docker compose run --rm --build build                                           # after raising VERSION
cd ..\server
docker compose run --rm -v "<path>\device-agent\dist:/in:ro" manage release add /in --version 0.4.1
docker compose run --rm manage release list
docker compose run --rm manage release withdraw 0.4.1
```
`release add` refuses anything not signed with the release key. Each device sees the new version at its next
report and installs it; an agent never goes back to an older version, tries a version at most three times,
and reports its version with every check-in (the console's device list shows it).

## Try it without installing

```
msiexec /a dist\ShadowFilerAgent-0.4.0.msi /qn TARGETDIR=%TEMP%\sfagent        # unpacks only
"%TEMP%\sfagent\ShadowFiler Agent\sfagent.cmd" --data %TEMP%\sfagent-data enrol http://127.0.0.1:8770 <token>
"%TEMP%\sfagent\ShadowFiler Agent\sfagent.cmd" --data %TEMP%\sfagent-data run --once
```
With `--data` the agent runs as you, keeps its state in that folder and never installs an update.

## Tests

```
..\shadow-filer\.venv\Scripts\python -m unittest discover -s tests
```
13 tests: what a release must be, every way an update is refused, enrolment from what the installer left,
a person's settings and programs outlasting their signing out, the folder that somebody else made, and what
the installer holds. The server's side (signed requests, replay, releases) is in `../server/tests`.

## Known limits

- As a service the agent cannot ask winget, so it does not report which programs have a newer version.
- A person's settings (screen lock, AutoPlay) are those of the account that signed in last; "the everyday
  account is an administrator" looks at direct membership of the Administrators group only.
- Programs a person installed for themselves are seen only once that person has signed in while the agent
  was running.
- The PC's private key is sealed by Windows for SYSTEM (DPAPI), not held in the TPM.
- Everybody gets a release at once: no rings, no per-organisation choice.

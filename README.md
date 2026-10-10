# AIOS

Local AI utilities for a Windows workstation. Everything runs on the PC; nothing is sent to the cloud.

| Folder | What it is |
|---|---|
| [`shadow-filer/`](shadow-filer/) | Watches Downloads and predicts where each file belongs in a PARA tree (rules first, a local Ollama model second), measures its own accuracy, recommends cleanup (content duplicates, extracted archives, old installers) with Recycle Bin delete on confirmation, and offers semantic + keyword search over your folders. Web console at http://127.0.0.1:8765. |

See [`shadow-filer/README.md`](shadow-filer/README.md) for setup.

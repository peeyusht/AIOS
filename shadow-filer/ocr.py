"""
OCR with the engine built into Windows 10/11 (Windows.Media.Ocr). Nothing to install.

Python hands a batch of files to a small Windows PowerShell 5.1 script (WinRT is reachable from
powershell.exe, not from pwsh 7), which:
  - images (png, jpg, bmp, tif, gif): decodes and recognizes them;
  - PDFs: renders each page with Windows' own PDF engine (Windows.Data.Pdf) and recognizes it;
and returns the text as JSON. Images embedded in .docx files are pulled out in Python first.

SAFETY: read-only. File paths travel in a JSON file, never on a command line, so a file name can't
inject commands. No console window is shown. Password-protected PDFs are reported as locked, never
opened with a guessed password. Text stays on this PC.
"""
import json
import os
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path

DEFAULTS = {
    "enabled": True,
    "max_pdf_pages": 10,      # pages read per scanned PDF
    "min_image_kb": 15,       # smaller images (icons, logos) are skipped
    "max_file_mb": 40,
    "batch": 12,              # files per PowerShell run
    "timeout_seconds": 300,   # per batch
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif"}
OCR_EXT = IMAGE_EXT | {".pdf", ".docx"}
CREATE_NO_WINDOW = 0x08000000

PS_SCRIPT = r'''
param([string]$InFile, [string]$OutFile, [int]$MaxPages)
$ErrorActionPreference = "Stop"
$out = @{ engine = $null; files = @{} }
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    $asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
    function Await($op, [Type]$type) {
        $t = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
    function AwaitAction($op) { $t = $asTaskAction.Invoke($null, @($op)); $t.Wait(-1) | Out-Null }
    [void][Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
    [void][Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
    [void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
    [void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    [void][Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) { throw "No OCR language installed (Settings > Time & language > Language)" }
    $out.engine = $engine.RecognizerLanguage.LanguageTag
    $maxDim = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension

    $fmt = [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8
    $alpha = [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied
    function Recognize($stream) {
        $stream.Seek(0)
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        if ($dec.PixelWidth -gt $maxDim -or $dec.PixelHeight -gt $maxDim) {
            $scale = [Math]::Min($maxDim / $dec.PixelWidth, $maxDim / $dec.PixelHeight)
            $tr = [Windows.Graphics.Imaging.BitmapTransform]::new()
            $tr.ScaledWidth = [uint32]($dec.PixelWidth * $scale); $tr.ScaledHeight = [uint32]($dec.PixelHeight * $scale)
            $bmp = Await ($dec.GetSoftwareBitmapAsync($fmt, $alpha, $tr,
                [Windows.Graphics.Imaging.ExifOrientationMode]::RespectExifOrientation,
                [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
        } else {
            $bmp = Await ($dec.GetSoftwareBitmapAsync($fmt, $alpha)) ([Windows.Graphics.Imaging.SoftwareBitmap])
        }
        $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
        ($res.Lines | ForEach-Object { $_.Text }) -join "`n"
    }

    $paths = Get-Content -Raw -Encoding UTF8 $InFile | ConvertFrom-Json
    foreach ($p in $paths) {
        $r = @{ text = ""; pages = 0; error = $null; locked = $false }
        try {
            $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
            if ($p.ToLower().EndsWith(".pdf")) {
                try {
                    $doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
                } catch {
                    if ($_.Exception.ToString() -match "password|0x8007052B|0x80070056") { $r.locked = $true; throw "password-protected" }
                    throw
                }
                $n = [Math]::Min([int]$doc.PageCount, $MaxPages)
                $texts = @()
                for ($i = 0; $i -lt $n; $i++) {
                    $page = $doc.GetPage([uint32]$i)
                    $opts = [Windows.Data.Pdf.PdfPageRenderOptions]::new()
                    # ~200 dpi: page size is in DIPs (1/96 in)
                    $opts.DestinationWidth = [uint32][Math]::Min($maxDim, $page.Size.Width * 200 / 96)
                    $ms = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
                    AwaitAction ($page.RenderToStreamAsync($ms, $opts))
                    $texts += (Recognize $ms)
                    $page.Dispose(); $ms.Dispose()
                }
                $r.pages = $n
                $r.text = $texts -join "`n`n"
            } else {
                $st = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
                $r.text = Recognize $st
                $r.pages = 1
                $st.Dispose()
            }
        } catch {
            if (-not $r.error) { $r.error = ($_.Exception.Message -split "`n")[0] }
        }
        $out.files[$p] = $r
    }
} catch {
    $out.fatal = ($_.Exception.Message -split "`n")[0]
}
$out | ConvertTo-Json -Depth 5 -Compress | Set-Content -Encoding UTF8 $OutFile
'''


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("ocr") or {})}


class Unavailable(RuntimeError):
    pass


_state = {"available": None, "engine": None, "error": None, "files": 0, "seconds": 0.0}
_lock = threading.Lock()


def status() -> dict:
    return dict(_state)


def available() -> bool:
    return os.name == "nt" and _state["available"] is not False


def _powershell() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    p = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return p if os.path.exists(p) else "powershell.exe"


def _run_batch(paths: list[str], cfg: dict) -> dict:
    """{path: {text, pages, error, locked}} for files Windows can read directly (images, PDFs)."""
    s = settings(cfg)
    with tempfile.TemporaryDirectory(prefix="shadow-ocr-") as td:
        script = os.path.join(td, "ocr.ps1")
        inp, outp = os.path.join(td, "in.json"), os.path.join(td, "out.json")
        Path(script).write_text(PS_SCRIPT, encoding="utf-8-sig")  # BOM: PS 5.1 reads it as UTF-8
        Path(inp).write_text(json.dumps(paths), encoding="utf-8")
        t0 = time.time()
        try:
            subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", script, "-InFile", inp, "-OutFile", outp, "-MaxPages", str(s["max_pdf_pages"])],
                           capture_output=True, timeout=s["timeout_seconds"],
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            raise Unavailable("OCR timed out")
        except OSError as e:
            raise Unavailable(f"can't start PowerShell: {e}")
        try:
            raw = Path(outp).read_text(encoding="utf-8-sig")
            data = json.loads(raw)
        except (OSError, ValueError):
            raise Unavailable("OCR produced no result")
        with _lock:
            _state["seconds"] += time.time() - t0
        if data.get("fatal"):
            _state.update(available=False, error=data["fatal"])
            raise Unavailable(data["fatal"])
        _state.update(available=True, engine=data.get("engine"), error=None)
        files = data.get("files") or {}
        return {p: files.get(p) or {"text": "", "error": "no result"} for p in paths}


def _docx_images(path: str, td: str, min_kb: int, limit: int = 12) -> list[str]:
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            for info in sorted(z.infolist(), key=lambda i: i.filename):
                ext = os.path.splitext(info.filename)[1].lower()
                if not info.filename.startswith("word/media/") or ext not in IMAGE_EXT:
                    continue
                if info.file_size < min_kb * 1024 or info.file_size > 30 * 1024 * 1024:
                    continue
                dest = os.path.join(td, f"{len(out):03d}{ext}")
                with z.open(info) as src, open(dest, "wb") as dst:
                    dst.write(src.read())
                out.append(dest)
                if len(out) >= limit:
                    break
    except (zipfile.BadZipFile, OSError):
        pass
    return out


def wanted(path: str, size: int, cfg: dict) -> bool:
    s = settings(cfg)
    ext = os.path.splitext(path)[1].lower()
    if not s["enabled"] or ext not in OCR_EXT or size > s["max_file_mb"] * 1024 * 1024:
        return False
    if ext in IMAGE_EXT and size < s["min_image_kb"] * 1024:
        return False
    return True


def ocr_files(paths: list[str], cfg: dict) -> dict:
    """OCR several files. Returns {path: {"text": str, "locked": bool, "error": str|None}}.
    Raises Unavailable if Windows OCR can't run at all on this PC."""
    if os.name != "nt":
        raise Unavailable("OCR needs Windows")
    if _state["available"] is False:
        raise Unavailable(_state["error"] or "OCR unavailable")
    s = settings(cfg)
    results: dict = {}
    direct = [p for p in paths if not p.lower().endswith(".docx")]
    for i in range(0, len(direct), s["batch"]):
        results.update(_run_batch(direct[i:i + s["batch"]], cfg))
    for p in paths:
        if not p.lower().endswith(".docx"):
            continue
        with tempfile.TemporaryDirectory(prefix="shadow-ocr-docx-") as td:
            imgs = _docx_images(p, td, s["min_image_kb"])
            if not imgs:
                results[p] = {"text": "", "error": None}
                continue
            r = _run_batch(imgs, cfg)
            results[p] = {"text": "\n\n".join((r[x] or {}).get("text") or "" for x in imgs).strip(), "error": None}
    with _lock:
        _state["files"] += len(paths)
    for p, r in results.items():
        r["text"] = (r.get("text") or "").strip()
        r.setdefault("locked", False)
    return results


def ocr_text(path: str, cfg: dict) -> str:
    """Convenience for a single file; '' if nothing could be read."""
    try:
        return ocr_files([path], cfg).get(path, {}).get("text", "")
    except Unavailable:
        return ""


def selftest(cfg: dict) -> dict:
    """Render a known sentence into a PNG and an image-only PDF, OCR both, and compare."""
    from PIL import Image, ImageDraw, ImageFont
    words = "Shadow Filer OCR test 4821 invoice"
    img = Image.new("RGB", (1400, 240), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    d.text((40, 80), words, fill="black", font=font)
    with tempfile.TemporaryDirectory(prefix="shadow-ocr-test-") as td:
        png, pdf = os.path.join(td, "test.png"), os.path.join(td, "test.pdf")
        img.save(png)
        img.save(pdf, "PDF", resolution=150)
        t0 = time.time()
        try:
            r = ocr_files([png, pdf], cfg)
        except Unavailable as e:
            return {"ok": False, "message": f"OCR is not available: {e}"}
        secs = round(time.time() - t0, 1)
    got_png, got_pdf = r[png]["text"], r[pdf]["text"]
    norm = lambda t: " ".join(t.lower().split())
    ok_png, ok_pdf = norm(words) in norm(got_png), norm(words) in norm(got_pdf)
    return {"ok": ok_png and ok_pdf, "engine": _state["engine"], "seconds": secs,
            "image": {"ok": ok_png, "text": got_png, "error": r[png].get("error")},
            "pdf": {"ok": ok_pdf, "text": got_pdf, "error": r[pdf].get("error")},
            "message": (f"OCR works ({_state['engine']}): read the test image and the scanned-PDF test in {secs}s."
                        if ok_png and ok_pdf else "OCR ran but didn't read the test text correctly.")}

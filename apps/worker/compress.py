"""Streaming archive compression and bounded PDF optimization."""
import gzip
import copy
import lzma
import os
import shutil
import subprocess
import zipfile
from apps.api.app.compression import OFFICE_FORMATS


def compress_file(source, target, options, media_command):
    fmt = options["output_format"]
    level = options.get("level", 6)
    if fmt in OFFICE_FORMATS:
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
            infos = src.infolist()
            limit = int(os.environ.get("MAX_UPLOAD_BYTES", 2147483648))
            if len(infos) > 10000 or sum(info.file_size for info in infos) > limit:
                raise ValueError("Dokument überschreitet das Entpacklimit.")
            # Preserve entry order, attributes, and content; never extract paths to disk.
            total = 0
            for info in infos:
                output_info = copy.copy(info)
                output_info.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
                output_info._compresslevel = level
                with src.open(info) as reader, dst.open(output_info, "w") as writer:
                    while chunk := reader.read(1024 * 1024):
                        total += len(chunk)
                        if total > limit:
                            raise ValueError("Dokument überschreitet das Entpacklimit.")
                        writer.write(chunk)
    elif fmt == "zip":
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as archive:
            name = options["original_filename"].replace("\\", "/").split("/")[-1]
            archive.write(source, arcname=name)
    elif fmt in {"gz", "xz"}:
        opener = gzip.open if fmt == "gz" else lzma.open
        settings = {"compresslevel": level} if fmt == "gz" else {"preset": level}
        with open(source, "rb") as src, opener(target, "wb", **settings) as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
    elif fmt == "pdf":
        gs = shutil.which("gs") or shutil.which("gswin64c")
        if not gs:
            raise RuntimeError("PDF-Komprimierung benötigt Ghostscript im Worker.")
        quality = options["quality_preset"]
        dpi = options.get("pdf_dpi", {"high": 300, "balanced": 150, "small": 72}[quality])
        subprocess.run([
            gs, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.6", "-dDetectDuplicateImages=true",
            "-dDownsampleColorImages=true", "-dDownsampleGrayImages=true",
            f"-dColorImageResolution={dpi}", f"-dGrayImageResolution={dpi}",
            f"-sOutputFile={target}", "-f", source,
        ], check=True, capture_output=True, timeout=120)
    else:
        media_command()
    if not os.path.isfile(target) or os.path.getsize(target) == 0:
        raise RuntimeError("Komprimierung hat keine gültige Ausgabedatei erzeugt.")

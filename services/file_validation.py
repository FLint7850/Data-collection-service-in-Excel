"""Size and archive-safety checks for uploaded and downloaded files."""

import io
import zipfile
from pathlib import Path
from typing import BinaryIO, Union

from config import MAX_ARCHIVE_MEMBERS, MAX_ARCHIVE_UNCOMPRESSED_BYTES, MAX_DOWNLOAD_BYTES


def _declared_size(response) -> int:
    try:
        return int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0


def read_limited_response(response, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
    declared = _declared_size(response)
    if declared > limit:
        raise ValueError(f"Файл превышает допустимый размер {limit // (1024 * 1024)} МБ")
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise ValueError(f"Файл превышает допустимый размер {limit // (1024 * 1024)} МБ")
        chunks.append(chunk)
    return b"".join(chunks)


def write_limited_response(response, target: Path, limit: int = MAX_DOWNLOAD_BYTES) -> int:
    declared = _declared_size(response)
    if declared > limit:
        raise ValueError(f"Файл превышает допустимый размер {limit // (1024 * 1024)} МБ")
    total = 0
    with target.open("wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise ValueError(f"Файл превышает допустимый размер {limit // (1024 * 1024)} МБ")
            output.write(chunk)
    return total


def validate_xlsx_archive(source: Union[Path, bytes, BinaryIO]) -> None:
    archive_source = io.BytesIO(source) if isinstance(source, bytes) else source
    try:
        with zipfile.ZipFile(archive_source) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise ValueError("XLSX содержит слишком много файлов")
            total_uncompressed = sum(max(0, member.file_size) for member in members)
            if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError("Распакованный XLSX превышает допустимый размер")
            for member in members:
                if member.compress_size > 0 and member.file_size / member.compress_size > 500:
                    raise ValueError("XLSX имеет подозрительно высокий коэффициент сжатия")
    except zipfile.BadZipFile as error:
        raise ValueError("Некорректный XLSX-файл") from error

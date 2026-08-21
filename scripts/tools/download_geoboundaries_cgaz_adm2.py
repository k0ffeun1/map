"""Resumable downloader for geoBoundaries CGAZ Admin-2 source data."""
from __future__ import annotations

import urllib.request
from pathlib import Path


URL = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/CGAZ/geoBoundariesCGAZ_ADM2.zip"
EXPECTED_BYTES = 155_911_064
CHUNK_BYTES = 8 * 1024 * 1024
OUT = Path(__file__).resolve().parent / "_work" / "geoBoundariesCGAZ_ADM2.zip"


def main() -> None:
	OUT.parent.mkdir(parents=True, exist_ok=True)
	start = OUT.stat().st_size if OUT.exists() else 0
	# A prior interrupted non-range download is unusable; safely restart this
	# generated cache file.
	if start > EXPECTED_BYTES:
		start = 0
		OUT.write_bytes(b"")
	while start < EXPECTED_BYTES:
		end = min(start + CHUNK_BYTES - 1, EXPECTED_BYTES - 1)
		request = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}"})
		with urllib.request.urlopen(request, timeout=90) as response:
			data = response.read()
		if len(data) != end - start + 1:
			raise RuntimeError(f"Unexpected range response: requested {start}-{end}, got {len(data)} bytes")
		with OUT.open("ab" if start else "wb") as handle:
			handle.write(data)
		start += len(data)
		print(f"Downloaded {start:,}/{EXPECTED_BYTES:,} bytes")
	print(f"Complete: {OUT}")


if __name__ == "__main__":
	main()

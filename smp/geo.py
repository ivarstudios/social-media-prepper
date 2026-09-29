"""Offline reverse geocoding: GPS -> nearest place, region and country, from GeoNames data.

The GeoNames files (about 10 MB) are downloaded once into the data folder; after that no coordinates leave
this PC. Without them, places simply stay empty."""

from __future__ import annotations

import io
import logging
import math
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from smp.config import data_dir

log = logging.getLogger(__name__)
BASE = "https://download.geonames.org/export/dump/"
FILES = {"cities": "cities1000.zip", "admin1": "admin1CodesASCII.txt", "countries": "countryInfo.txt"}
NEAR_KM = 25.0           # further than this from any town: only region and country are given


@dataclass
class Place:
    city: str
    region: str
    country: str
    country_code: str
    km: float

    def label(self) -> str:
        parts = [self.city if self.km <= NEAR_KM else "", self.region, self.country]
        text = ", ".join(p for p in parts if p)
        return f"{text} (nearest town {self.city}, {self.km:.0f} km)" if self.km > NEAR_KM else text


class Geocoder:
    def __init__(self, folder: Path | None = None):
        self.folder = folder or data_dir() / "geonames"
        self._grid: dict[tuple[int, int], list[tuple[float, float, str, str, str]]] | None = None
        self._admin1: dict[str, str] = {}
        self._countries: dict[str, str] = {}
        self._lock = threading.Lock()

    def available(self) -> bool:
        return all((self.folder / n).exists() for n in FILES.values())

    def download(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=120, follow_redirects=True) as http:
            for name in FILES.values():
                target = self.folder / name
                if not target.exists():
                    r = http.get(BASE + name)
                    r.raise_for_status()
                    target.write_bytes(r.content)

    def _load(self) -> None:
        with self._lock:
            if self._grid is not None:
                return
            grid: dict = {}
            with zipfile.ZipFile(self.folder / FILES["cities"]) as z:
                with z.open(z.namelist()[0]) as f:
                    for line in io.TextIOWrapper(f, encoding="utf-8"):
                        c = line.rstrip("\n").split("\t")
                        lat, lon = float(c[4]), float(c[5])
                        grid.setdefault((math.floor(lat), math.floor(lon)), []).append(
                            (lat, lon, c[1], c[8], f"{c[8]}.{c[10]}"))
            for line in (self.folder / FILES["admin1"]).read_text(encoding="utf-8").splitlines():
                c = line.split("\t")
                if len(c) > 1:
                    self._admin1[c[0]] = c[1]
            for line in (self.folder / FILES["countries"]).read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#"):
                    c = line.split("\t")
                    self._countries[c[0]] = c[4]
            self._grid = grid

    def lookup(self, lat: float, lon: float) -> Place | None:
        if not self.available():
            return None
        self._load()
        best, best_km = None, 1e9
        for ring in (1, 2, 3):
            for dy in range(-ring, ring + 1):
                for dx in range(-ring, ring + 1):
                    for row in self._grid.get((math.floor(lat) + dy, math.floor(lon) + dx), ()):
                        km = _haversine(lat, lon, row[0], row[1])
                        if km < best_km:
                            best, best_km = row, km
            if best is not None and best_km < ring * 60:
                break
        if best is None:
            return None
        _, _, name, cc, admin_key = best
        return Place(name, self._admin1.get(admin_key, ""), self._countries.get(cc, cc), cc, best_km)


def _haversine(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


_default: Geocoder | None = None


def geocoder() -> Geocoder:
    global _default
    if _default is None:
        _default = Geocoder()
    return _default

import io
import zipfile

from smp.geo import Geocoder


def geonames(folder):
    folder.mkdir()
    rows = [  # geonameid, name, ascii, alt, lat, lon, fclass, fcode, cc, cc2, admin1
        "1\tKiruna\tKiruna\t\t67.8557\t20.2253\tP\tPPL\tSE\t\t14",
        "2\tAbisko\tAbisko\t\t68.3495\t18.8312\tP\tPPL\tSE\t\t14",
        "3\tTromsø\tTromso\t\t69.6496\t18.9560\tP\tPPL\tNO\t\t54",
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cities1000.txt", "\n".join(r + "\t" * 8 for r in rows) + "\n")
    (folder / "cities1000.zip").write_bytes(buf.getvalue())
    (folder / "admin1CodesASCII.txt").write_text("SE.14\tNorrbotten\tNorrbotten\t1\nNO.54\tTroms\tTroms\t2\n",
                                                 encoding="utf-8")
    (folder / "countryInfo.txt").write_text("#header\nSE\tSWE\t752\tSW\tSweden\nNO\tNOR\t578\tNO\tNorway\n",
                                            encoding="utf-8")


def test_nearest_town_region_country(tmp_path):
    geonames(tmp_path / "g")
    g = Geocoder(tmp_path / "g")
    p = g.lookup(68.35, 18.80)
    assert (p.city, p.region, p.country, p.country_code) == ("Abisko", "Norrbotten", "Sweden", "SE")
    assert p.km < 3 and p.label() == "Abisko, Norrbotten, Sweden"
    far = g.lookup(67.90, 18.50)                     # in the mountains, far from any listed town
    assert far.km > 25 and "nearest town" in far.label()


def test_unavailable_without_files(tmp_path):
    assert Geocoder(tmp_path / "none").lookup(60, 18) is None

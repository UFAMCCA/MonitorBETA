"""Gera docs/data/limites.geojson com os municípios da área de monitoramento.

Rodar só uma vez (ou quando mudar a lista em config.py):
    python scripts/limites.py [caminho_opcional_geojson_AM]

Fonte: malha municipal do IBGE (via github.com/tbrugz/geodata-br).
"""
import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_DIR, MUNICIPIOS  # noqa: E402

URL = "https://raw.githubusercontent.com/tbrugz/geodata-br/master/geojson/geojs-13-mun.json"


def norm(s):
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()
    return s.lower().strip()


def main():
    if len(sys.argv) > 1:
        src = json.load(open(sys.argv[1], encoding="utf-8"))
    else:
        with urllib.request.urlopen(URL, timeout=60) as r:
            src = json.load(r)

    wanted = {norm(m): m for m in MUNICIPIOS}
    feats, geoms = [], []
    for f in src["features"]:
        nome = f["properties"]["name"]
        if norm(nome) in wanted:
            # A malha de origem tem anéis marcados como buracos de forma errada;
            # make_valid reconstrói o polígono sem descartar partes.
            g = make_valid(shape(f["geometry"]))
            g = unary_union([p for p in getattr(g, "geoms", [g]) if p.geom_type in ("Polygon", "MultiPolygon")])
            geoms.append(g)
            feats.append({
                "type": "Feature",
                "properties": {"nome": nome, "cod_ibge": f["properties"]["id"]},
                "geometry": mapping(g.simplify(0.001, preserve_topology=True)),
            })

    faltando = set(wanted) - {norm(f["properties"]["nome"]) for f in feats}
    if faltando:
        sys.exit(f"Municípios não encontrados na malha: {faltando}")

    area = unary_union(geoms)
    minx, miny, maxx, maxy = area.bounds
    out = {
        "type": "FeatureCollection",
        "bbox": [round(minx, 4), round(miny, 4), round(maxx, 4), round(maxy, 4)],
        "features": sorted(feats, key=lambda f: f["properties"]["nome"]),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "limites.geojson").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{len(feats)} municípios, bbox {out['bbox']}")


if __name__ == "__main__":
    main()

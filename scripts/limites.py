"""Gera os limites municipais de cada região definida em config.REGIOES.

Saídas:
    docs/data/<regiao>/limites.geojson   municípios da região (sede marcada)
    docs/data/regioes.json               lista de regiões para o seletor do site

Rodar quando mudar a lista de municípios:
    python scripts/limites.py                # baixa as malhas
    python scripts/limites.py --fontes pasta # usa arquivos já baixados

Fontes:
    Brasil   IBGE, via github.com/tbrugz/geodata-br (AM, PA, AC, RO)
    Colômbia DANE MGN 2018, via github.com/caticoa3/colombia_mapa (municípios)
    Peru     INEI, via github.com/juaneladio/peru-geojson (distritos)
"""
import argparse
import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

from shapely.geometry import Point, mapping, shape
from shapely.ops import polylabel, unary_union
from shapely.validation import make_valid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

TBRUGZ = "https://raw.githubusercontent.com/tbrugz/geodata-br/master/geojson/geojs-{}-mun.json"
FONTES = {
    "AM": ("br-13.json", TBRUGZ.format(13)),
    "PA": ("br-15.json", TBRUGZ.format(15)),
    "AC": ("br-12.json", TBRUGZ.format(12)),
    "RO": ("br-11.json", TBRUGZ.format(11)),
    "CO": ("col-mpio.geojson", "https://raw.githubusercontent.com/caticoa3/colombia_mapa/master/co_2018_MGN_MPIO_POLITICO.geojson"),
    "PE": ("per-dist.geojson", "https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_distrital_simple.geojson"),
}
PAIS = {"CO": "Colômbia", "PE": "Peru"}
# As malhas estrangeiras vêm em maiúsculas e sem acento
GRAFIA = {"leticia": "Letícia"}
# Departamento de cada nome estrangeiro, para não confundir homônimos
FILTRO_ESTRANGEIRO = {"CO": ("DPTO_CNMBR", "AMAZONAS"), "PE": ("NOMBDEP", "LORETO")}

# Ajustes manuais do ponto do rótulo para evitar nomes sobrepostos (lon, lat).
# Só são usados se o ponto cair dentro do município.
ROTULO_MANUAL = {
    "manaus": (-60.45, -2.40),
    "rio preto da eva": (-59.62, -2.30),
    "careiro da varzea": (-59.70, -3.33),
}


def norm(s):
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("-", " ").split())


def separar(item):
    """'Oriximiná/PA' -> ('oriximina', 'PA');  'Tefé' -> ('tefe', 'AM')."""
    if "/" in item:
        nome, uf = item.rsplit("/", 1)
        return norm(nome), uf.strip().upper()
    return norm(item), "AM"


def carregar_fontes(pasta):
    dados = {}
    for uf, (arq, url) in FONTES.items():
        p = Path(pasta) / arq if pasta else None
        if p and p.exists():
            dados[uf] = json.loads(p.read_text(encoding="utf-8"))
        else:
            with urllib.request.urlopen(url, timeout=120) as r:
                dados[uf] = json.load(r)
    return dados


def indexar(dados):
    """{(nome_normalizado, uf): (nome_original, codigo, geometria)}"""
    idx = {}
    for uf, fc in dados.items():
        for f in fc["features"]:
            p = f["properties"]
            if uf in ("CO", "PE"):
                campo, valor = FILTRO_ESTRANGEIRO[uf]
                if norm(str(p.get(campo, ""))) != norm(valor):
                    continue
                nome = p["MPIO_CNMBR"] if uf == "CO" else p["NOMBDIST"]
                cod = p.get("MPIO_CCNCT") or p.get("IDDIST")
                nome = GRAFIA.get(norm(nome), nome.title())
            else:
                nome, cod = p["name"], p["id"]
            idx[(norm(nome), uf)] = (nome, cod, f["geometry"])
    return idx


def geometria(g):
    # Algumas malhas têm anéis marcados como buracos de forma errada;
    # make_valid reconstrói o polígono sem descartar partes.
    g = make_valid(shape(g))
    return unary_union([p for p in getattr(g, "geoms", [g]) if p.geom_type in ("Polygon", "MultiPolygon")])


def rotulo(nome_norm, g):
    maior = max(getattr(g, "geoms", [g]), key=lambda x: x.area)
    pt = polylabel(maior, tolerance=0.005)
    if nome_norm in ROTULO_MANUAL:
        cand = Point(*ROTULO_MANUAL[nome_norm])
        if g.contains(cand):
            pt = cand
    return [round(pt.x, 4), round(pt.y, 4)]


def nome_exibicao(nome, uf):
    if uf == "AM":
        return nome
    return f"{nome} ({PAIS.get(uf, uf)})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fontes", help="pasta com as malhas já baixadas")
    a = ap.parse_args()
    idx = indexar(carregar_fontes(a.fontes))

    lista = []
    erros = []
    for rid, reg in C.REGIOES.items():
        itens = [reg["sede"], *reg["entorno"]]
        vistos, feats, geoms = set(), [], []
        for i, item in enumerate(itens):
            chave = separar(item)
            if chave in vistos:
                continue  # nome repetido na lista
            vistos.add(chave)
            if chave not in idx:
                erros.append(f"{rid}: '{item}' não encontrado na malha")
                continue
            nome, cod, geo = idx[chave]
            g = geometria(geo)
            geoms.append(g)
            feats.append({
                "type": "Feature",
                "properties": {
                    "nome": nome_exibicao(nome, chave[1]), "nome_curto": nome, "uf": chave[1],
                    "cod": cod, "sede": i == 0, "rotulo": rotulo(chave[0], g),
                },
                "geometry": mapping(g.simplify(0.001, preserve_topology=True)),
            })
        area = unary_union(geoms)
        o, s, l, n = area.bounds
        fc = {"type": "FeatureCollection", "bbox": [round(o, 4), round(s, 4), round(l, 4), round(n, 4)],
              "features": sorted(feats, key=lambda f: (not f["properties"]["sede"], f["properties"]["nome"]))}
        pasta = C.DATA_DIR / rid
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "limites.geojson").write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        lista.append({"id": rid, "nome": reg["nome"], "sede": reg["sede"], "sensor": reg.get("sensor"),
                      "bbox": fc["bbox"], "n_municipios": len(feats)})
        print(f"{rid:18s} {len(feats):2d} municípios  bbox {fc['bbox']}")

    (C.DATA_DIR / "regioes.json").write_text(
        json.dumps({"padrao": C.REGIAO_PADRAO, "regioes": lista}, ensure_ascii=False, indent=1), encoding="utf-8")
    if erros:
        sys.exit("\n".join(erros))


if __name__ == "__main__":
    main()

"""Temperatura de superfície terrestre (LST) quinzenal a partir do Landsat 8/9 (TIRS).

Busca as cenas Landsat Coleção 2 Nível 2 (banda ST_B10) dos últimos 16 dias no
Microsoft Planetary Computer (gratuito, sem cadastro), remove nuvens e sombras
pela banda QA_PIXEL e monta um mosaico com o pixel limpo MAIS RECENTE.
Cada pixel guarda de qual cena veio, para o site mostrar satélite, data e hora.

Roda para cada região de config.REGIOES. Saídas em docs/data/<regiao>/:
lst.png (camada colorida), lst_grade.npz (valores em °C e índice da cena de
origem) e lst.json (metadados). Regiões grandes usam pixel maior para que a
grade não passe de config.LST_MAX_PIXELS de lado.

Uso:  python scripts/lst.py [--regiao humaita] [--fim 2026-09-30]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

TZ = ZoneInfo(C.FUSO)
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
ESCALA, DESLOC = 0.00341802, 149.0          # ST_B10 -> Kelvin (Coleção 2)
BITS_NUVEM = (1, 2, 3, 4)                    # nuvem dilatada, cirrus, nuvem, sombra
SEM_CENA = 65535
FAIXA_C = (20.0, 46.0)                       # faixa fixa da legenda, comparável entre quinzenas

# Paleta (azul -> amarelo -> vermelho escuro)
PALETA = np.array([
    [49, 54, 149], [69, 117, 180], [116, 173, 209], [171, 217, 233], [224, 243, 248],
    [255, 255, 191], [254, 224, 144], [253, 174, 97], [244, 109, 67], [215, 48, 39], [165, 0, 38],
], dtype=np.float32)


def buscar_cenas(bbox, inicio, fim):
    import planetary_computer
    import pystac_client
    cat = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    busca = cat.search(
        collections=["landsat-c2-l2"], bbox=bbox,
        datetime=f"{inicio:%Y-%m-%d}/{fim:%Y-%m-%d}",
        query={"platform": {"in": ["landsat-8", "landsat-9"]}, "eo:cloud_cover": {"lt": C.LST_NUVEM_MAX}},
    )
    return sorted(busca.items(), key=lambda it: it.datetime)


def resolucao(bbox):
    lado = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    return max(C.LST_RES_GRAUS, lado / C.LST_MAX_PIXELS)


def compor(itens, bbox, res):
    """Mosaico do pixel sem nuvem mais recente, carregando uma cena por vez
    (mais antiga -> mais recente; a mais recente sobrescreve).
    Devolve (lst °C, índice da cena de origem, affine, ny, nx)."""
    from odc.geo.geobox import GeoBox
    from odc.stac import load
    gbox = GeoBox.from_bbox(bbox, crs="EPSG:4326", resolution=res)
    ny, nx = gbox.shape
    lst = np.full((ny, nx), np.nan, np.float32)
    origem = np.full((ny, nx), SEM_CENA, np.uint16)
    for k, it in enumerate(itens):
        try:
            ds = load([it], bands=["lwir11", "qa_pixel"], geobox=gbox, groupby=None,
                      resampling={"lwir11": "average", "qa_pixel": "nearest"})
        except Exception as e:
            print(f"  aviso: cena {it.id} ignorada ({e})")
            continue
        st = ds["lwir11"].values[0].astype(np.float32)
        qa = ds["qa_pixel"].values[0].astype(np.uint16)
        ruim = (st == 0) | (qa == 1)  # 0 = sem dado; QA=1 = fill
        for b in BITS_NUVEM:
            ruim |= ((qa >> b) & 1).astype(bool)
        v = ~ruim
        lst[v] = st[v] * ESCALA + DESLOC - 273.15
        origem[v] = k
    return lst, origem, gbox.affine, ny, nx


def mascara_area(forma, transform, geoms):
    from rasterio.features import rasterize
    return rasterize([(g, 1) for g in geoms], out_shape=forma, transform=transform, fill=0, dtype="uint8").astype(bool)


def colorir(lst):
    from PIL import Image
    t = np.clip((lst - FAIXA_C[0]) / (FAIXA_C[1] - FAIXA_C[0]), 0, 1) * (len(PALETA) - 1)
    t0 = np.floor(np.nan_to_num(t)).astype(int)
    t1 = np.minimum(t0 + 1, len(PALETA) - 1)
    f = (np.nan_to_num(t) - t0)[..., None]
    rgb = PALETA[t0] * (1 - f) + PALETA[t1] * f
    alfa = np.where(np.isnan(lst), 0, 215).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb.astype(np.uint8), alfa]), "RGBA")


def metadados_cena(it):
    p = it.properties
    t = it.datetime.astimezone(timezone.utc)
    return {
        "id": it.id,
        "satelite": {"landsat-8": "Landsat 8", "landsat-9": "Landsat 9"}.get(p.get("platform"), p.get("platform")),
        "sensor": "TIRS",
        "data_hora_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hora_local": t.astimezone(TZ).strftime("%d/%m/%Y %H:%M"),
        "orbita_ponto": f"{p.get('landsat:wrs_path')}/{p.get('landsat:wrs_row')}",
        "nuvem_pct": p.get("eo:cloud_cover"),
    }


def salvar(pasta, lst, origem, cenas, bbox_saida, inicio, fim, cobertura, res):
    pasta.mkdir(parents=True, exist_ok=True)
    colorir(lst).save(pasta / "lst.png", optimize=True)
    np.savez_compressed(pasta / "lst_grade.npz", lst=lst.astype(np.float16), origem=origem)
    validos = lst[~np.isnan(lst)]
    usadas = sorted(set(int(x) for x in np.unique(origem) if x != SEM_CENA))
    meta = {
        "produto": "Temperatura da superfície terrestre (LST) — Landsat Coleção 2 Nível 2, banda ST_B10",
        "observacao": "Temperatura da superfície (pele), não do solo em profundidade. Passagem ~10h local.",
        "periodo_inicio": f"{inicio:%Y-%m-%d}", "periodo_fim": f"{fim:%Y-%m-%d}",
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resolucao_nativa_m": 100, "resolucao_produto_m": 30,
        "resolucao_exibicao_m": round(res * 111320),
        "composicao": "pixel sem nuvem mais recente do período",
        "cobertura_pct": round(cobertura, 1),
        "bbox": [round(v, 5) for v in bbox_saida],
        "legenda_c": list(FAIXA_C),
        "estatisticas_c": ({"min": round(float(validos.min()), 1), "mediana": round(float(np.median(validos)), 1),
                            "max": round(float(validos.max()), 1)} if validos.size else None),
        "cenas": cenas,
        "cenas_usadas": [cenas[i] for i in usadas],
        "proxima_atualizacao": "dias 1 e 16 de cada mês",
    }
    (pasta / "lst.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def processar(rid, inicio, fim):
    from shapely.geometry import shape
    pasta = C.DATA_DIR / rid
    lim = json.loads((pasta / "limites.geojson").read_text(encoding="utf-8"))
    bbox = lim["bbox"]
    geoms = [shape(f["geometry"]) for f in lim["features"]]
    res = resolucao(bbox)
    itens = buscar_cenas(bbox, inicio, fim)
    if not itens:
        print(f"{rid}: nenhuma cena Landsat no período; camada anterior mantida.")
        return False
    print(f"{rid}: {len(itens)} cenas, pixel de ~{round(res * 111320)} m")
    lst, origem, transform, ny, nx = compor(itens, bbox, res)
    dentro = mascara_area((ny, nx), transform, geoms)
    lst[~dentro] = np.nan
    origem[~dentro] = SEM_CENA
    cobertura = 100 * np.count_nonzero(~np.isnan(lst)) / max(1, np.count_nonzero(dentro))
    oeste, norte = transform.c, transform.f
    bbox_saida = (oeste, norte + transform.e * ny, oeste + transform.a * nx, norte)
    meta = salvar(pasta, lst, origem, [metadados_cena(it) for it in itens], bbox_saida, inicio, fim, cobertura, res)
    print(f"{rid}: cobertura sem nuvem {meta['cobertura_pct']}% | {meta['estatisticas_c']}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regiao", action="append", help="região (pode repetir); padrão: todas")
    ap.add_argument("--fim", help="data final (AAAA-MM-DD); padrão: hoje")
    a = ap.parse_args()
    fim = datetime.strptime(a.fim, "%Y-%m-%d") if a.fim else datetime.now(timezone.utc)
    inicio = fim - timedelta(days=C.LST_DIAS)
    falhas = []
    for rid in (a.regiao or list(C.REGIOES)):
        try:
            processar(rid, inicio, fim)
        except Exception as e:
            print(f"{rid}: erro: {e}")
            falhas.append(rid)
    # arquivos da versão de região única
    for antigo in ("lst.json", "lst.png", "lst_grade.npz"):
        (C.DATA_DIR / antigo).unlink(missing_ok=True)
    if falhas:
        sys.exit("Falhou em: " + ", ".join(falhas))


if __name__ == "__main__":
    main()

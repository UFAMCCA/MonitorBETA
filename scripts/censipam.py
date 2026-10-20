"""Cópia de reserva dos dados do Painel do Fogo (Censipam) para cada região.

O site busca os dados direto do GeoServer do Censipam no navegador de quem acessa
(sempre atualizados). Esta cópia, gravada a cada coleta em docs/data/<regiao>/censipam.json,
só é usada se a consulta ao vivo falhar. Se o servidor não responder ao GitHub
(ele pode bloquear acessos de fora do Brasil), o script avisa e segue sem erro.

    python scripts/censipam.py
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

WFS = "https://panorama.sipam.gov.br/geoserver/painel_do_fogo/wfs"
# Mesma lista usada no navegador (docs/censipam.js)
CAMADAS = [
    "mv_evento_filtro",
    "mv_alertas_goes_novos_eventos",
    "mv_alertas_goes_atividade_eventos",
    "mv_alertas_estradas",
    "mv_alertas_areas_urbanizadas",
    "tb_brigada_pto",
]
LIMITE = 5000


def baixar(camada, bbox):
    q = {"service": "WFS", "version": "1.0.0", "request": "GetFeature", "outputFormat": "application/json",
         "typeName": f"painel_do_fogo:{camada}", "maxFeatures": LIMITE,
         "bbox": ",".join(f"{v:.4f}" for v in bbox)}
    req = urllib.request.Request(f"{WFS}?{urllib.parse.urlencode(q)}", headers={"User-Agent": "monitor-queimadas-am/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    falhas = 0
    for rid in C.REGIOES:
        pasta = C.DATA_DIR / rid
        bbox = json.loads((pasta / "limites.geojson").read_text(encoding="utf-8"))["bbox"]
        saida = {"gerado_em": agora, "fonte": WFS, "camadas": {}, "status": {}}
        for camada in CAMADAS:
            try:
                fc = baixar(camada, bbox)
                saida["camadas"][camada] = {"type": "FeatureCollection", "features": fc.get("features", [])}
                saida["status"][camada] = f"ok ({len(fc.get('features', []))})"
            except Exception as e:
                saida["status"][camada] = f"erro: {str(e)[:120]}"
                falhas += 1
        ok = sum(1 for s in saida["status"].values() if s.startswith("ok"))
        if ok:
            (pasta / "censipam.json").write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{rid:18s} {ok}/{len(CAMADAS)} camadas: {saida['status']}")
    if falhas:
        print("aviso: o servidor do Censipam não respondeu a todas as consultas; o site tenta ao vivo no navegador.")


if __name__ == "__main__":
    main()

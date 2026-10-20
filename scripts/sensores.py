"""Busca a coordenada exata dos sensores PurpleAir usados como centro das regiões.

Precisa de uma chave de leitura da API do PurpleAir (gratuita, develop.purpleair.com)
no ambiente, em PURPLEAIR_API_KEY. Só consulta a API para sensores que ainda não têm
coordenada em docs/data/sensores.json, então gasta pouquíssimos pontos da conta.

Coordenadas fixadas à mão em config.SENSORES_MANUAL sempre têm prioridade.

    PURPLEAIR_API_KEY=xxxx python scripts/sensores.py [--forcar]
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

API = "https://api.purpleair.com/v1/sensors"
ARQ = C.DATA_DIR / "sensores.json"
# Caixa que cobre o Amazonas e o entorno das regiões
CAIXA = {"nwlng": -76.0, "nwlat": 4.0, "selng": -50.0, "selat": -12.0}


def agora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def consultar(chave):
    params = {"fields": "name,latitude,longitude,last_seen,location_type", **CAIXA}
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}",
                                 headers={"X-API-Key": chave, "User-Agent": "monitor-queimadas-am/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    campos = d["fields"]
    return [dict(zip(campos, linha)) for linha in d["data"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true", help="consulta a API mesmo se já houver coordenadas")
    a = ap.parse_args()

    atual = json.loads(ARQ.read_text(encoding="utf-8")) if ARQ.exists() else {}
    nomes = sorted({r["sensor"] for r in C.REGIOES.values() if r.get("sensor")})

    for nome, (lat, lon) in C.SENSORES_MANUAL.items():
        atual[nome] = {"lat": lat, "lon": lon, "fonte": "manual (config.py)", "atualizado_em": agora()}

    faltando = [n for n in nomes if a.forcar or n not in atual or atual[n].get("lat") is None]
    faltando = [n for n in faltando if n not in C.SENSORES_MANUAL]
    chave = os.environ.get("PURPLEAIR_API_KEY", "").strip()
    if faltando and chave:
        try:
            achados = {s["name"].strip().upper(): s for s in consultar(chave) if s.get("name")}
            for n in faltando:
                s = achados.get(n.upper())
                if s and s.get("latitude") is not None:
                    atual[n] = {"lat": s["latitude"], "lon": s["longitude"], "sensor_index": s.get("sensor_index"),
                                "ultimo_sinal": s.get("last_seen"), "fonte": "API PurpleAir", "atualizado_em": agora()}
                    print(f"{n}: {s['latitude']}, {s['longitude']} (índice {s.get('sensor_index')})")
                else:
                    print(f"{n}: não encontrado na API do PurpleAir (o nome pode estar diferente ou o sensor ser privado)")
        except Exception as e:
            print(f"aviso: falha ao consultar o PurpleAir: {e}")
    elif faltando:
        print("aviso: sem PURPLEAIR_API_KEY; sensores sem coordenada: " + ", ".join(faltando))

    for n in nomes:
        atual.setdefault(n, {"lat": None, "lon": None, "fonte": "pendente"})
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    ARQ.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

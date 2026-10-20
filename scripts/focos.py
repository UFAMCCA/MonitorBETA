"""Coleta focos de calor (INPE BDQueimadas + NASA FIRMS) uma vez e processa cada
região de config.REGIOES: agrupa em eventos, estima o status (ativo / extinto
estimado) e grava os arquivos do site em docs/data/<regiao>/.

Uso normal (GitHub Actions, 04h, 12h e 18h de Manaus):
    FIRMS_MAP_KEY=xxxx python scripts/focos.py

Teste offline com CSVs locais:
    python scripts/focos.py --inpe-local pasta_inpe --firms-local pasta_firms --agora 2026-09-25T22:00:00Z
"""
import argparse
import shutil
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from shapely.geometry import box, mapping, shape, Point
from shapely.ops import unary_union
from shapely.prepared import prep

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402
import nuvens as nuvens_mod  # noqa: E402

TZ = ZoneInfo(C.FUSO)
UTC = timezone.utc
INPE_BASE = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv"
FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
MARGEM_PASSAGEM_GRAUS = 1.0  # área ampla usada para saber se um satélite passou

INPE_PARA_CHAVE = {n: k for k, v in C.SATELITES.items() for n in v["inpe"]}


# ----------------------------------------------------------------- utilidades
def http_get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "monitor-queimadas-am/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fnum(x):
    try:
        v = float(str(x).replace(",", "."))
        return None if math.isnan(v) or v <= -999 else v
    except (TypeError, ValueError):
        return None


def parse_dt(s):
    s = str(s).strip().replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def km_entre(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def conf_classe(valor, sensor):
    """Normaliza a confiança para baixa / nominal / alta."""
    if valor is None or valor == "":
        return None
    v = str(valor).strip().lower()
    if v in ("l", "low", "baixa"):
        return "baixa"
    if v in ("n", "nominal"):
        return "nominal"
    if v in ("h", "high", "alta"):
        return "alta"
    n = fnum(v)
    if n is None:
        return None
    return "baixa" if n < 30 else ("nominal" if n < 80 else "alta")


# ------------------------------------------------------------------- leitura
def ler_csv_inpe(texto, fonte):
    out = []
    rd = csv.DictReader(io.StringIO(texto))
    for row in rd:
        r = {k.strip().lower(): v for k, v in row.items() if k}
        sat_nome = (r.get("satelite") or r.get("satellite") or "").strip()
        chave = INPE_PARA_CHAVE.get(sat_nome)
        if not chave:
            continue
        lat = fnum(r.get("lat") or r.get("latitude"))
        lon = fnum(r.get("lon") or r.get("longitude"))
        t = parse_dt(r.get("data_hora_gmt") or r.get("datahora") or r.get("data") or "")
        if lat is None or lon is None or t is None:
            continue
        out.append({
            "sat": chave, "sat_nome": sat_nome, "sensor": C.SATELITES[chave]["sensor"],
            "lat": lat, "lon": lon, "t": t, "fontes": {"INPE"},
            "scan_km": None, "track_km": None,
            "confianca": None, "confianca_bruta": None,
            "frp": fnum(r.get("frp")), "brilho_k": None, "brilho2_k": None, "periodo": None,
            "id_inpe": r.get("id") or r.get("foco_id"),
            "municipio_inpe": r.get("municipio"),
            "risco_fogo": fnum(r.get("risco_fogo") or r.get("riscofogo")),
            "dias_sem_chuva": fnum(r.get("numero_dias_sem_chuva") or r.get("diasemchuva")),
            "precipitacao": fnum(r.get("precipitacao")),
            "bioma": r.get("bioma"), "arquivo": fonte,
        })
    return out


def ler_csv_firms(texto, fonte_firms):
    out = []
    for r in csv.DictReader(io.StringIO(texto)):
        lat, lon = fnum(r.get("latitude")), fnum(r.get("longitude"))
        d, h = r.get("acq_date"), (r.get("acq_time") or "").zfill(4)
        if lat is None or lon is None or not d:
            continue
        t = datetime.strptime(f"{d} {h}", "%Y-%m-%d %H%M").replace(tzinfo=UTC)
        if fonte_firms.startswith("MODIS"):
            hora_local = t.astimezone(TZ).hour
            sat_letra = (r.get("satellite") or "").strip().upper()[:1]
            if sat_letra == "T" and 5 <= hora_local < 13:
                chave, nome = "TERRA", "TERRA_M-M"
            elif sat_letra == "A" and 12 <= hora_local < 19:
                chave, nome = "AQUA", "AQUA_M-T"
            else:
                continue
            brilho, brilho2 = fnum(r.get("brightness")), fnum(r.get("bright_t31"))
        else:
            chave = "NOAA-20" if "NOAA20" in fonte_firms else "NOAA-21"
            nome = chave
            brilho, brilho2 = fnum(r.get("bright_ti4")), fnum(r.get("bright_ti5"))
        sensor = C.SATELITES[chave]["sensor"]
        out.append({
            "sat": chave, "sat_nome": nome, "sensor": sensor,
            "lat": lat, "lon": lon, "t": t, "fontes": {"FIRMS"},
            "scan_km": fnum(r.get("scan")), "track_km": fnum(r.get("track")),
            "confianca": conf_classe(r.get("confidence"), sensor),
            "confianca_bruta": r.get("confidence"),
            "frp": fnum(r.get("frp")), "brilho_k": brilho, "brilho2_k": brilho2,
            "periodo": {"D": "dia", "N": "noite"}.get((r.get("daynight") or "").upper()),
            "id_inpe": None, "municipio_inpe": None, "risco_fogo": None,
            "dias_sem_chuva": None, "precipitacao": None, "bioma": None,
            "arquivo": fonte_firms,
        })
    return out


def coletar_inpe(agora, local_dir, status):
    textos = []
    if local_dir:
        for p in sorted(Path(local_dir).glob("*.csv")):
            textos.append((p.read_text(encoding="utf-8", errors="replace"), p.name))
    else:
        inicio = agora - timedelta(hours=C.HORAS_HISTORICO + 3)
        # Arquivos de 10 minutos (tempo quase real)
        try:
            idx = http_get(f"{INPE_BASE}/10min/")
            nomes = sorted(set(re.findall(r'href="(focos_10min_(\d{8})_(\d{4})\.csv)"', idx)))
            for nome, d, hm in nomes:
                t = datetime.strptime(d + hm, "%Y%m%d%H%M").replace(tzinfo=UTC)
                if inicio <= t <= agora + timedelta(minutes=10):
                    try:
                        textos.append((http_get(f"{INPE_BASE}/10min/{nome}"), nome))
                    except Exception as e:  # arquivo isolado com erro não derruba a coleta
                        print(f"aviso: {nome}: {e}", file=sys.stderr)
            status["INPE_10min"] = f"ok ({len(textos)} arquivos)"
        except Exception as e:
            status["INPE_10min"] = f"erro: {e}"
        # Arquivos diários (trazem risco de fogo, dias sem chuva, precipitação)
        n = 0
        for dias in range(0, 3):
            d = (agora - timedelta(days=dias)).strftime("%Y%m%d")
            nome = f"focos_diario_br_{d}.csv"
            try:
                textos.append((http_get(f"{INPE_BASE}/diario/Brasil/{nome}"), nome))
                n += 1
            except Exception:
                pass
        status["INPE_diario"] = f"ok ({n} arquivos)" if n else "sem arquivos diários disponíveis"
    regs = []
    for texto, nome in textos:
        regs.extend(ler_csv_inpe(texto, nome))
    return regs


def coletar_firms(caixas, local_dir, status):
    """Consulta o FIRMS para cada caixa (uma por região) e junta tudo."""
    fontes = sorted({v["firms"] for v in C.SATELITES.values() if v["firms"]})
    regs = []
    if local_dir:
        for p in sorted(Path(local_dir).glob("*.csv")):
            fonte = next((f for f in fontes if f in p.name), None)
            if fonte:
                regs.extend(ler_csv_firms(p.read_text(encoding="utf-8"), fonte))
        return regs
    chave = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not chave:
        status["FIRMS"] = "sem FIRMS_MAP_KEY: usando só INPE (sem tamanho real do pixel e confiança)"
        return regs
    for fonte in fontes:
        n, erros = 0, []
        for caixa in caixas:
            area = ",".join(f"{v:.3f}" for v in caixa)
            try:
                txt = http_get(f"{FIRMS_BASE}/{chave}/{fonte}/{area}/3")
                if txt.lstrip().lower().startswith(("invalid", "error")):
                    raise RuntimeError(txt.strip()[:120])
                r = ler_csv_firms(txt, fonte)
                regs.extend(r)
                n += len(r)
            except Exception as e:
                erros.append(str(e)[:120])
        status[f"FIRMS {fonte}"] = (f"ok ({n} detecções)" if not erros
                                    else f"erro em {len(erros)} de {len(caixas)} consultas: {erros[0]}")
    return regs


# --------------------------------------------------------------- processamento
def deduplicar(regs):
    """Remove repetições (10min x diário) e funde INPE com FIRMS da mesma detecção."""
    unicos = {}
    for r in regs:
        k = (r["sat"], round(r["lat"], 4), round(r["lon"], 4), r["t"].strftime("%Y%m%d%H%M"), next(iter(r["fontes"])))
        if k in unicos:
            base = unicos[k]
            for campo, v in r.items():
                if base.get(campo) in (None, "") and v not in (None, ""):
                    base[campo] = v
        else:
            unicos[k] = dict(r)
    regs = list(unicos.values())

    firms = [r for r in regs if "FIRMS" in r["fontes"]]
    inpe = [r for r in regs if r["fontes"] == {"INPE"}]
    grade = defaultdict(list)  # (satélite, célula de 0,05°) -> detecções FIRMS
    for f in firms:
        grade[(f["sat"], int(f["lat"] // 0.05), int(f["lon"] // 0.05))].append(f)
    restantes = []
    for i in inpe:
        tol_km = max(0.5, C.SATELITES[i["sat"]]["pixel_km"] * 1.2)
        par = None
        ci, cj = int(i["lat"] // 0.05), int(i["lon"] // 0.05)
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                for f in grade.get((i["sat"], ci + a, cj + b), []):
                    if abs((f["t"] - i["t"]).total_seconds()) <= 20 * 60 and km_entre(i["lat"], i["lon"], f["lat"], f["lon"]) <= tol_km:
                        par = f
                        break
                if par:
                    break
            if par:
                break
        if par:
            par["fontes"] = par["fontes"] | {"INPE"}
            for campo in ("id_inpe", "municipio_inpe", "risco_fogo", "dias_sem_chuva", "precipitacao", "bioma"):
                if par.get(campo) in (None, "") and i.get(campo) not in (None, ""):
                    par[campo] = i[campo]
            if par.get("frp") is None:
                par["frp"] = i.get("frp")
        else:
            restantes.append(i)
    return firms + restantes


def completar_pixel(r):
    if r["scan_km"] and r["track_km"]:
        r["pixel_real"] = True
    else:
        n = C.SATELITES[r["sat"]]["pixel_km"]
        r["scan_km"] = r["track_km"] = n
        r["pixel_real"] = False
    if r["periodo"] is None:
        h = r["t"].astimezone(TZ).hour
        r["periodo"] = "dia" if 6 <= h < 18 else "noite"
    return r


def pegada(r):
    """Retângulo aproximado do pixel (scan ~ leste-oeste, track ~ norte-sul)."""
    dlat = r["track_km"] / 111.32 / 2
    dlon = r["scan_km"] / (111.32 * math.cos(math.radians(r["lat"]))) / 2
    return box(r["lon"] - dlon, r["lat"] - dlat, r["lon"] + dlon, r["lat"] + dlat)


def passagens(regs_amplos):
    """Horários de passagem por satélite polar, inferidos das detecções na área ampla."""
    por_sat = defaultdict(list)
    for r in regs_amplos:
        if C.SATELITES[r["sat"]]["tipo"] == "polar":
            por_sat[r["sat"]].append(r["t"])
    out = []
    for sat, ts in por_sat.items():
        ts.sort()
        grupo = [ts[0]]
        for t in ts[1:]:
            if (t - grupo[-1]).total_seconds() > 40 * 60:
                out.append((sat, grupo[0], grupo[-1], len(grupo)))
                grupo = [t]
            else:
                grupo.append(t)
        out.append((sat, grupo[0], grupo[-1], len(grupo)))
    return sorted(out, key=lambda x: x[1])


def agrupar(dets):
    n = len(dets)
    pai = list(range(n))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    diag = [math.hypot(d["scan_km"], d["track_km"]) / 2 for d in dets]
    # grade grosseira para não comparar todos com todos
    cel = defaultdict(list)
    for i, d in enumerate(dets):
        cel[(int(d["lat"] / 0.05), int(d["lon"] / 0.05))].append(i)
    for i, d in enumerate(dets):
        ci, cj = int(d["lat"] / 0.05), int(d["lon"] / 0.05)
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                for j in cel.get((ci + a, cj + b), []):
                    if j <= i:
                        continue
                    e = dets[j]
                    if abs((d["t"] - e["t"]).total_seconds()) > C.AGRUP_JANELA_H * 3600:
                        continue
                    if km_entre(d["lat"], d["lon"], e["lat"], e["lon"]) <= diag[i] + diag[j] + C.AGRUP_TOLERANCIA_KM:
                        pai[raiz(i)] = raiz(j)
    grupos = defaultdict(list)
    for i in range(n):
        grupos[raiz(i)].append(dets[i])
    return list(grupos.values())


def municipio_de(lat, lon, municipios):
    p = Point(lon, lat)
    for nome, g in municipios:
        if g.contains(p):
            return nome
    return None


def status_evento(ev, agora, lista_passagens, goes_ultimo):
    t_ult = max(d["t"] for d in ev)
    tem_goes = any(d["sat"] == "GOES-19" for d in ev)
    info = {"status": "ativo", "extincao_apos": None, "extincao_ate": None, "criterio": None,
            "passagens_sem_deteccao": []}
    if (agora - t_ult).total_seconds() < C.ATIVO_HORAS_MIN * 3600:
        info["criterio"] = f"detectado há menos de {C.ATIVO_HORAS_MIN} h"
        return info
    falhas = [(s, t0) for s, t0, _t1, _n in lista_passagens if t0 > t_ult + timedelta(minutes=15)]
    info["passagens_sem_deteccao"] = [{"satelite": s, "hora": iso(t)} for s, t in falhas]
    fim_goes = None
    if tem_goes and goes_ultimo and (goes_ultimo - t_ult).total_seconds() >= C.EXT_HORAS_GOES * 3600:
        fim_goes = t_ult + timedelta(minutes=10)
    fim_polar = falhas[0][1] if len(falhas) >= C.EXT_PASSAGENS_POLARES else None
    candidatos = [t for t in (fim_goes, fim_polar) if t]
    if candidatos:
        info["status"] = "extinto_estimado"
        info["extincao_apos"] = iso(t_ult)
        info["extincao_ate"] = iso(min(candidatos))
        partes = []
        if fim_goes:
            partes.append(f"GOES-19 sem detecção por ≥{C.EXT_HORAS_GOES} h")
        if fim_polar:
            partes.append(f"{len(falhas)} passagens polares sem detecção")
        info["criterio"] = "; ".join(partes)
    else:
        info["criterio"] = "ainda sem observação posterior suficiente para indicar extinção"
    return info


def amostrar_lst(lat, lon, lst):
    if not lst:
        return None
    oeste, sul, leste, norte = lst["bbox"]
    grade = lst["grade"]
    if not (oeste <= lon <= leste and sul <= lat <= norte):
        return None
    ny, nx = grade.shape
    i = min(ny - 1, int((norte - lat) / (norte - sul) * ny))
    j = min(nx - 1, int((lon - oeste) / (leste - oeste) * nx))
    v = float(grade[i, j])
    if math.isnan(v):
        return None
    k = int(lst["origem"][i, j])
    cenas = lst["meta"].get("cenas", [])
    return {"valor_c": round(v, 1), "cena": cenas[k] if k < len(cenas) else None}


def carregar_lst(pasta):
    meta_p, grade_p = pasta / "lst.json", pasta / "lst_grade.npz"
    if not (meta_p.exists() and grade_p.exists()):
        return None
    try:
        import numpy as np
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        z = np.load(grade_p)
        return {"bbox": meta["bbox"], "grade": z["lst"].astype("float32"), "origem": z["origem"], "meta": meta}
    except Exception as e:
        print(f"aviso: LST não carregada: {e}", file=sys.stderr)
        return None


def janela_da_hora(agora):
    h = agora.astimezone(TZ).hour + agora.astimezone(TZ).minute / 60
    return min(C.ATUALIZACOES, key=lambda k: min(abs(h - int(k[:2])), 24 - abs(h - int(k[:2]))))


def carregar_sensores():
    p = C.DATA_DIR / "sensores.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def limpar(d):
    """Remove campos vazios para deixar o JSON das detecções menor."""
    return {k: v for k, v in d.items() if v not in (None, "")}


HIST_CAMPOS = ["hora_utc", "satelite", "lat", "lon", "municipio", "frp_mw", "confianca",
               "scan_km", "track_km", "periodo", "fontes"]


def gravar_historico(rid, dets):
    """Acrescenta as detecções da região ao arquivo mensal (docs/data/historico/<regiao>/AAAA-MM.csv)."""
    pasta = C.DATA_DIR / "historico" / rid
    pasta.mkdir(parents=True, exist_ok=True)
    por_mes = defaultdict(list)
    for d in dets:
        por_mes[d["t"].strftime("%Y-%m")].append(d)
    for mes, lista in por_mes.items():
        arq = pasta / f"{mes}.csv"
        chaves, linhas = set(), []
        if arq.exists():
            with open(arq, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    chaves.add((row["satelite"], row["hora_utc"], row["lat"], row["lon"]))
                    linhas.append(row)
        novos = 0
        for d in lista:
            row = {"hora_utc": iso(d["t"]), "satelite": d["sat"], "lat": f"{d['lat']:.4f}", "lon": f"{d['lon']:.4f}",
                   "municipio": d["municipio"] or "", "frp_mw": "" if d["frp"] is None else d["frp"],
                   "confianca": d["confianca"] or "", "scan_km": round(d["scan_km"], 3), "track_km": round(d["track_km"], 3),
                   "periodo": d["periodo"] or "", "fontes": "+".join(sorted(d["fontes"]))}
            k = (row["satelite"], row["hora_utc"], row["lat"], row["lon"])
            if k not in chaves:
                chaves.add(k)
                linhas.append(row)
                novos += 1
        if novos:
            linhas.sort(key=lambda r: (r["hora_utc"], r["satelite"]))
            with open(arq, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=HIST_CAMPOS)
                w.writeheader()
                w.writerows(linhas)


def migrar_lst_antiga():
    """A camada de temperatura ficava em docs/data/; agora fica na pasta da região padrão."""
    destino = C.DATA_DIR / C.REGIAO_PADRAO
    for nome in ("lst.json", "lst.png", "lst_grade.npz"):
        antigo, novo = C.DATA_DIR / nome, destino / nome
        if antigo.exists() and not novo.exists():
            destino.mkdir(parents=True, exist_ok=True)
            shutil.copy2(antigo, novo)


def checar_nuvens(nuv, rid, st, ev, c_lat, c_lon, serie):
    """Para focos dados como extintos: o local estava sob nuvens nas observações
    que deveriam tê-lo visto? Se sim, a extinção é incerta."""
    out = {"extincao_incerta": False, "nuvem_nas_passagens": None}
    if st["status"] != "extinto_estimado":
        return out
    t_ult = max(d["t"] for d in ev)
    marcas = []
    for p in st["passagens_sem_deteccao"]:
        t = datetime.fromisoformat(p["hora"].replace("Z", "+00:00"))
        p["nuvem"] = nuv.nublado(rid, t, c_lat, c_lon)
    usadas = st["passagens_sem_deteccao"][:max(C.EXT_PASSAGENS_POLARES, 1)]
    marcas = [p["nuvem"] for p in usadas if p.get("nuvem") is not None]
    # extinção decidida pelo GOES: olha a série de 3 em 3 h logo depois do último registro
    if not marcas:
        janela = [t for t in serie if t_ult < t <= t_ult + timedelta(hours=6)]
        marcas = [x for x in (nuv.nublado(rid, t, c_lat, c_lon) for t in janela) if x is not None]
    if marcas:
        nubladas = sum(1 for x in marcas if x)
        out["nuvem_nas_passagens"] = {"nubladas": nubladas, "observadas": len(marcas)}
        if nubladas:
            out["extincao_incerta"] = True
            st["criterio"] = (st["criterio"] or "") + f"; ATENÇÃO: havia nuvem sobre o local em {nubladas} de {len(marcas)} observações seguintes, o fogo pode ter continuado escondido"
    return out


def resumo_nuvens(nuv, rid, ctx, eventos, agora, pasta):
    """Cobertura de nuvens da região: série de 48 h, passagens do VIIRS, área cega."""
    viirs = ctx["viirs"]
    serie = []
    for t in sorted(ctx["serie"]):
        f = nuv.fracao(rid, t)
        if f:
            serie.append({"hora": iso(f["imagem"]), "pct": f["pct"]})
    passagens_v = []
    for t in viirs:
        f = nuv.fracao(rid, t)
        if f:
            h_local = t.astimezone(TZ).hour
            passagens_v.append({"passagem": iso(t), "imagem": iso(f["imagem"]), "pct": f["pct"],
                                "periodo": "dia" if 6 <= h_local < 18 else "noite"})
    if not passagens_v and not serie:
        return {"disponivel": False, "motivo": "; ".join(nuv.erros[:3]) or "sem imagens do GOES-19 para a região"}
    cego = nuv.fracao_cega(rid, viirs)
    camada = None
    if viirs:
        bbox = nuv.png(rid, viirs[0], viirs, pasta / "nuvens.png")
        if bbox:
            camada = {"arquivo": "nuvens.png", "bbox": bbox, "passagem": iso(viirs[0])}
    ultimas = passagens_v[:2]
    ref = max((p["pct"] for p in ultimas), default=None)
    nivel = None if ref is None else ("alto" if ref >= 60 or (cego or 0) >= 30 else "moderado" if ref >= 30 or (cego or 0) >= 10 else "baixo")
    extintos = [e for e in eventos if e["properties"]["status"] == "extinto_estimado"]
    return {
        "disponivel": True,
        "fonte": "GOES-19 ABI, máscara de nuvens (ABI-L2-ACMF), pixel de 2 km",
        "nivel": nivel,
        "passagens_viirs": passagens_v,
        "serie": serie,
        "media_48h": round(sum(x["pct"] for x in serie) / len(serie), 1) if serie else None,
        "cego_48h_pct": cego,
        "extintos": len(extintos),
        "extintos_incertos": sum(1 for e in extintos if e["properties"].get("extincao_incerta")),
        "camada": camada,
    }


def contexto_regiao(rid, regs, inicio):
    """Limites, detecções da área ampla e passagens inferidas de uma região."""
    pasta = C.DATA_DIR / rid
    lim = json.loads((pasta / "limites.geojson").read_text(encoding="utf-8"))
    geom = unary_union([shape(f["geometry"]) for f in lim["features"]])
    o, s, l, n = lim["bbox"]
    m = MARGEM_PASSAGEM_GRAUS
    bbox_amplo = (o - m, s - m, l + m, n + m)
    amplos = [r for r in regs if bbox_amplo[0] <= r["lon"] <= bbox_amplo[2] and bbox_amplo[1] <= r["lat"] <= bbox_amplo[3]]
    goes = [r["t"] for r in amplos if r["sat"] == "GOES-19"]
    return {"pasta": pasta, "lim": lim, "geom": geom, "amplos": amplos,
            "lista_pass": passagens([r for r in amplos if r["t"] >= inicio]),
            "goes_ultimo": max(goes) if goes else None}


def tempos_viirs(agora, lon):
    """Passagens nominais do VIIRS nas últimas 48 h (≈13h30 e ≈01h30 hora solar)."""
    out = []
    for d in range(0, 3):
        for hs in (13.5, 1.5):
            t = nuvens_mod.hora_solar_utc(agora - timedelta(days=d), hs, lon).replace(second=0, microsecond=0)
            if agora - timedelta(hours=C.HORAS_HISTORICO) <= t <= agora - timedelta(minutes=20):
                out.append(t)
    return sorted(out, reverse=True)


def tempos_serie(agora):
    base = agora.replace(minute=0, second=0, microsecond=0)
    base -= timedelta(hours=base.hour % 3)
    return [base - timedelta(hours=3 * k) for k in range(0, C.HORAS_HISTORICO // 3 + 1)]


def processar_regiao(rid, reg, ctx, agora, inicio, janela, status, sensores, teste, historico, nuv=None):
    pasta, lim, amplos = ctx["pasta"], ctx["lim"], ctx["amplos"]
    lista_pass, goes_ultimo = ctx["lista_pass"], ctx["goes_ultimo"]
    municipios = [(f["properties"]["nome"], prep(shape(f["geometry"]))) for f in lim["features"]]
    area = prep(ctx["geom"])
    o, s, l, n = lim["bbox"]

    dets = []
    for r in amplos:
        if r["t"] >= inicio and o <= r["lon"] <= l and s <= r["lat"] <= n and area.contains(Point(r["lon"], r["lat"])):
            d = dict(r)
            d["municipio"] = municipio_de(d["lat"], d["lon"], municipios) or d.get("municipio_inpe")
            dets.append(d)

    sensor_nome = reg.get("sensor")
    sensor = None
    if sensor_nome:
        info = sensores.get(sensor_nome) or {}
        sensor = {"nome": sensor_nome, "lat": info.get("lat"), "lon": info.get("lon"),
                  "sensor_index": info.get("sensor_index"), "fonte": info.get("fonte", "pendente")}
    tem_coord = bool(sensor and sensor["lat"] is not None)

    lst = carregar_lst(pasta)
    eventos, detalhes = [], {}
    for ev in agrupar(dets):
        ev.sort(key=lambda d: d["t"])
        prim, ult = ev[0], ev[-1]
        eid = "E" + hashlib.sha1(f"{prim['sat']}{prim['t'].isoformat()}{prim['lat']:.4f}{prim['lon']:.4f}".encode()).hexdigest()[:10]
        # Área desenhada = pixels do sensor mais fino que viu o foco (ex.: VIIRS 375 m).
        # O GOES (2 km) só define a área quando foi o único a detectar.
        menor = min(C.SATELITES[d["sat"]]["pixel_km"] for d in ev)
        finos = [d for d in ev if C.SATELITES[d["sat"]]["pixel_km"] <= menor * 1.5]
        geom = unary_union([pegada(d) for d in finos]).simplify(0.0003)
        c = geom.centroid
        por_passagem = Counter((d["sat"], d["t"].strftime("%Y%m%d%H") + str(d["t"].minute // 20)) for d in ev)
        confs = [d["confianca"] for d in ev if d["confianca"]]
        ordem = {"baixa": 0, "nominal": 1, "alta": 2}
        st = status_evento(ev, agora, lista_pass, goes_ultimo)
        if nuv is not None:
            st.update(checar_nuvens(nuv, rid, st, ev, c_lat=sum(d["lat"] for d in ev) / len(ev),
                                    c_lon=sum(d["lon"] for d in ev) / len(ev), serie=ctx.get("serie", [])))
        frps = [d["frp"] for d in ev if d["frp"] is not None]
        mun = Counter(d["municipio"] for d in ev if d["municipio"]).most_common(1)
        props = {
            "id": eid,
            "municipio": mun[0][0] if mun else None,
            "primeira_deteccao": iso(prim["t"]),
            "ultima_deteccao": iso(ult["t"]),
            "duracao_h": round((ult["t"] - prim["t"]).total_seconds() / 3600, 2),
            "satelites": sorted({d["sat"] for d in ev}),
            "satelite_primeira": prim["sat"],
            "n_deteccoes": len(ev),
            "n_pixels": max(por_passagem.values()),
            "area_pelo_sensor": C.SATELITES[finos[0]["sat"]]["sensor"],
            "confianca": max(confs, key=ordem.get) if confs else None,
            "frp_max": max(frps) if frps else None,
            "lat": round(c.y, 5), "lon": round(c.x, 5),
            "dist_sensor_km": round(km_entre(c.y, c.x, sensor["lat"], sensor["lon"]), 1) if tem_coord else None,
            "temp_superficie": amostrar_lst(c.y, c.x, lst),
            **st,
        }
        eventos.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
        detalhes[eid] = [limpar({
            "satelite": d["sat"], "nome_fonte": d["sat_nome"], "sensor": d["sensor"],
            "hora": iso(d["t"]), "lat": round(d["lat"], 5), "lon": round(d["lon"], 5),
            "fontes": sorted(d["fontes"]), "municipio": d["municipio"],
            "confianca": d["confianca"], "confianca_bruta": d["confianca_bruta"],
            "frp_mw": d["frp"], "brilho_k": d["brilho_k"], "brilho2_k": d["brilho2_k"],
            "scan_km": round(d["scan_km"], 3), "track_km": round(d["track_km"], 3),
            "pixel_real": d["pixel_real"], "periodo": d["periodo"],
            "risco_fogo": d["risco_fogo"], "dias_sem_chuva": d["dias_sem_chuva"],
            "precipitacao_mm": d["precipitacao"], "bioma": d["bioma"], "id_inpe": d["id_inpe"],
        }) for d in ev]

    eventos.sort(key=lambda f: f["properties"]["ultima_deteccao"], reverse=True)
    ativos = [e for e in eventos if e["properties"]["status"] == "ativo"]
    perto = {}
    if tem_coord:
        for raio in (25, 50, 100):
            perto[str(raio)] = sum(1 for e in ativos if e["properties"]["dist_sensor_km"] <= raio)

    nuvens_info = resumo_nuvens(nuv, rid, ctx, eventos, agora, pasta) if nuv is not None else {
        "disponivel": False, "motivo": "máscara de nuvens do GOES-19 não obtida nesta coleta"}

    resumo = {
        "nuvens": nuvens_info,
        "regiao": {"id": rid, "nome": reg["nome"], "sede": reg["sede"], "n_municipios": len(municipios)},
        "sensor": sensor,
        "ativos_perto_do_sensor": perto,
        "gerado_em": iso(agora),
        "dados_de_teste": teste,
        "atualizacao": janela,
        "atualizacao_descricao": C.ATUALIZACOES[janela],
        "proximas_atualizacoes": list(C.ATUALIZACOES),
        "atualizacoes": C.ATUALIZACOES,
        "janela_inicio": iso(inicio),
        "eventos_ativos": len(ativos),
        "eventos_extintos": len(eventos) - len(ativos),
        "eventos_total": len(eventos),
        "deteccoes_total": len(dets),
        "deteccoes_ativas": sum(e["properties"]["n_deteccoes"] for e in ativos),
        "por_municipio": dict(Counter(e["properties"]["municipio"] or "—" for e in eventos).most_common()),
        "ativos_por_municipio": dict(Counter(e["properties"]["municipio"] or "—" for e in ativos).most_common()),
        "por_satelite": dict(Counter(d["sat"] for d in dets).most_common()),
        "passagens": [{
            "satelite": s_, "sensor": C.SATELITES[s_]["sensor"], "inicio": iso(t0), "fim": iso(t1),
            "resolucao_km": C.SATELITES[s_]["pixel_km"],
            "deteccoes_na_area": sum(1 for d in dets if d["sat"] == s_ and t0 - timedelta(minutes=5) <= d["t"] <= t1 + timedelta(minutes=5)),
        } for s_, t0, t1, _ in lista_pass],
        "goes_ultima_deteccao_regional": iso(goes_ultimo),
        "satelites": C.SATELITES,
        "fontes_status": status,
        "temperatura_superficie": lst["meta"] if lst else None,
    }
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "focos.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": eventos}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (pasta / "deteccoes.json").write_text(json.dumps(detalhes, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    if historico:
        gravar_historico(rid, dets)
    print(f"  {rid:18s} {len(dets):6d} detecções -> {len(eventos):5d} focos ({len(ativos)} ativos)")


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inpe-local")
    ap.add_argument("--firms-local")
    ap.add_argument("--agora", help="instante de referência em UTC (testes)")
    ap.add_argument("--janela", choices=list(C.ATUALIZACOES))
    ap.add_argument("--regiao", action="append", help="processar só esta região (pode repetir)")
    ap.add_argument("--sem-historico", action="store_true")
    ap.add_argument("--sem-nuvens", action="store_true", help="não baixar a máscara de nuvens do GOES-19")
    ap.add_argument("--goes-local", help="pasta com máscaras ACM do GOES (testes)")
    a = ap.parse_args()

    agora = datetime.fromisoformat(a.agora.replace("Z", "+00:00")) if a.agora else datetime.now(UTC)
    janela = a.janela or janela_da_hora(agora)
    inicio = agora - timedelta(hours=C.HORAS_HISTORICO)
    teste = bool(a.inpe_local or a.firms_local)
    regioes = {k: v for k, v in C.REGIOES.items() if not a.regiao or k in a.regiao}

    m = MARGEM_PASSAGEM_GRAUS
    caixas = []
    for rid in regioes:
        o, s, l, n = json.loads((C.DATA_DIR / rid / "limites.geojson").read_text(encoding="utf-8"))["bbox"]
        caixas.append((o - m, s - m, l + m, n + m))

    def dentro(r):
        return any(c[0] <= r["lon"] <= c[2] and c[1] <= r["lat"] <= c[3] for c in caixas)

    status = {}
    brutos = [r for r in coletar_inpe(agora, a.inpe_local, status) if dentro(r)]
    brutos += [r for r in coletar_firms(caixas, a.firms_local, status) if dentro(r)]
    regs = [completar_pixel(r) for r in deduplicar(brutos) if inicio - timedelta(hours=24) <= r["t"] <= agora]
    print(f"[{janela}] {len(regs)} detecções na área das regiões. Fontes: {status}")

    migrar_lst_antiga()
    sensores = carregar_sensores()
    contextos = {rid: contexto_regiao(rid, regs, inicio) for rid in regioes}

    # Nuvens (GOES-19): passagens polares inferidas + passagens nominais do VIIRS + série de 3 h
    nuv = None
    if not a.sem_nuvens:
        try:
            serie = tempos_serie(agora)
            instantes = set(serie)
            for rid, ctx in contextos.items():
                o, s_, l, n = ctx["lim"]["bbox"]
                ctx["viirs"] = tempos_viirs(agora, (o + l) / 2)
                ctx["serie"] = serie
                instantes.update(ctx["viirs"])
                instantes.update(t0 for _s, t0, _t1, _n in ctx["lista_pass"])
            nuv = nuvens_mod.Nuvens({rid: {"bbox": ctx["lim"]["bbox"], "geom": ctx["geom"]} for rid, ctx in contextos.items()},
                                    local_dir=a.goes_local)
            n_arq = nuv.preparar(sorted(instantes))
            status["GOES-19 nuvens"] = f"ok ({n_arq} imagens)" if n_arq else "erro: nenhuma imagem obtida"
            if not n_arq:
                nuv = None
        except Exception as e:
            status["GOES-19 nuvens"] = f"erro: {str(e)[:150]}"
            nuv = None

    for rid, reg in regioes.items():
        processar_regiao(rid, reg, contextos[rid], agora, inicio, janela, status, sensores, teste,
                         historico=not (teste or a.sem_historico), nuv=nuv)

    # arquivos da versão de região única, que não são mais usados
    for antigo in ("focos.geojson", "deteccoes.json", "resumo.json", "limites.geojson"):
        (C.DATA_DIR / antigo).unlink(missing_ok=True)


if __name__ == "__main__":
    main()

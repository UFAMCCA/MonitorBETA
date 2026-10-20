"""Cobertura de nuvens observada pelo GOES-19 (máscara de nuvens ABI-L2-ACMF).

Os satélites não enxergam fogo sob nuvens. Este módulo baixa a máscara de nuvens
do GOES-19 (disco completo, a cada 10 min, pixel de 2 km, dados públicos da NOAA
no AWS) para os instantes que importam:
  - as passagens dos satélites polares (para saber se um foco "sumiu" porque apagou
    ou porque estava sob nuvens);
  - a última passagem diurna e noturna do VIIRS;
  - uma série a cada 3 h nas últimas 48 h.

Para cada região gera uma grade de 0,02° (≈2 km) com 0 = céu limpo, 1 = nuvem,
255 = sem dado. É usado por focos.py; não roda sozinho.
"""
import io
import math
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

BUCKET = "https://noaa-goes19.s3.amazonaws.com"
PRODUTO = "ABI-L2-ACMF"
RES = 0.02
SEM_DADO = 255
PADRAO_NOME = re.compile(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})\d_")
MAX_ARQUIVOS = 70


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "monitor-queimadas-am/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def inicio_do_arquivo(nome):
    m = PADRAO_NOME.search(nome)
    if not m:
        return None
    a, doy, h, mi, s = (int(x) for x in m.groups())
    return datetime(a, 1, 1, h, mi, s, tzinfo=timezone.utc) + timedelta(days=doy - 1)


class Nuvens:
    def __init__(self, regioes, local_dir=None):
        """regioes: {rid: {"bbox": [o, s, l, n], "geom": geometria shapely da região}}"""
        import shapely
        self.local_dir = Path(local_dir) if local_dir else None
        self.listas = {}
        self.regioes = {}
        for rid, r in regioes.items():
            o, s, l, n = r["bbox"]
            lons = np.arange(o + RES / 2, l, RES)
            lats = np.arange(n - RES / 2, s, -RES)
            glon, glat = np.meshgrid(lons, lats)
            dentro = shapely.contains_xy(r["geom"], glon, glat)
            self.regioes[rid] = {"bbox": (o, s, l, n), "lons": lons, "lats": lats, "dentro": dentro,
                                 "grades": {}, "indices": None}
        self.arquivos = {}   # instante pedido -> (nome, início da varredura) ou None
        self.erros = []

    # ------------------------------------------------------------ arquivos
    def _listar(self, hora):
        chave = hora.strftime("%Y%j%H")
        if chave in self.listas:
            return self.listas[chave]
        nomes = []
        try:
            if self.local_dir:
                nomes = [p.name for p in self.local_dir.glob("*.nc")]
            else:
                prefixo = f"{PRODUTO}/{hora:%Y}/{hora:%j}/{hora:%H}/"
                xml = _get(f"{BUCKET}/?list-type=2&prefix={prefixo}", timeout=60).decode()
                nomes = re.findall(r"<Key>([^<]+)</Key>", xml)
        except Exception as e:
            self.erros.append(f"listagem {chave}: {e}")
        self.listas[chave] = [(n, inicio_do_arquivo(n)) for n in nomes if inicio_do_arquivo(n)]
        return self.listas[chave]

    def _escolher(self, t):
        """Varredura que começou até 20 min antes de t (ou, na falta, até 20 min depois)."""
        cands = self._listar(t) + self._listar(t - timedelta(hours=1))
        antes = [(n, s) for n, s in cands if t - timedelta(minutes=20) <= s <= t]
        if antes:
            return max(antes, key=lambda x: x[1])
        depois = self._listar(t + timedelta(hours=1)) + cands
        perto = [(n, s) for n, s in depois if abs((s - t).total_seconds()) <= 20 * 60]
        return min(perto, key=lambda x: abs((x[1] - t).total_seconds())) if perto else None

    def _bytes(self, nome):
        if self.local_dir:
            return (self.local_dir / Path(nome).name).read_bytes()
        return _get(f"{BUCKET}/{nome}")

    @staticmethod
    def _ler(dados):
        # A biblioteca netCDF/HDF5 não é segura entre threads: a leitura é sempre
        # feita na thread principal (só o download é paralelo).
        import netCDF4
        ds = netCDF4.Dataset("acm", memory=dados)
        try:
            bcm = ds.variables["BCM"][:]
            bcm = np.ma.filled(bcm.astype(np.int16), SEM_DADO).astype(np.uint8)
            x = np.asarray(ds.variables["x"][:], dtype=np.float64)
            y = np.asarray(ds.variables["y"][:], dtype=np.float64)
            pj = ds.variables["goes_imager_projection"]
            proj = {k: float(getattr(pj, k)) for k in ("perspective_point_height", "semi_major_axis",
                                                        "semi_minor_axis", "longitude_of_projection_origin")}
            proj["sweep"] = str(getattr(pj, "sweep_angle_axis", "x"))
        finally:
            ds.close()
        return bcm, x, y, proj

    def _indices(self, reg, x, y, proj):
        """Linha/coluna da imagem GOES para cada célula da grade da região."""
        from pyproj import CRS, Transformer
        chave = (round(x[0], 9), round(x[1] - x[0], 12), round(y[0], 9), round(y[1] - y[0], 12), len(x), len(y),
                 proj["longitude_of_projection_origin"])
        if reg["indices"] and reg["indices"][0] == chave:
            return reg["indices"][1], reg["indices"][2]
        h = proj["perspective_point_height"]
        geos = CRS.from_proj4(
            f"+proj=geos +h={h} +lon_0={proj['longitude_of_projection_origin']} +sweep={proj['sweep']} "
            f"+a={proj['semi_major_axis']} +b={proj['semi_minor_axis']} +units=m +no_defs")
        tr = Transformer.from_crs("EPSG:4326", geos, always_xy=True)
        glon, glat = np.meshgrid(reg["lons"], reg["lats"])
        xm, ym = tr.transform(glon, glat)
        xr, yr = np.asarray(xm) / h, np.asarray(ym) / h
        with np.errstate(invalid="ignore"):
            ix = np.rint((xr - x[0]) / (x[1] - x[0]))
            iy = np.rint((yr - y[0]) / (y[1] - y[0]))
        ok = np.isfinite(ix) & np.isfinite(iy) & (ix >= 0) & (ix < len(x)) & (iy >= 0) & (iy < len(y))
        ix = np.where(ok, ix, -1).astype(np.int32)
        iy = np.where(ok, iy, -1).astype(np.int32)
        reg["indices"] = (chave, iy, ix)
        return iy, ix

    def preparar(self, instantes):
        """Baixa a máscara mais próxima de cada instante e recorta para cada região."""
        pedidos = {}
        for t in sorted(set(instantes)):
            esc = self._escolher(t)
            self.arquivos[t] = esc
            if esc:
                pedidos.setdefault(esc[0], esc[1])
        nomes = sorted(pedidos, key=lambda n: pedidos[n], reverse=True)[:MAX_ARQUIVOS]

        def baixar(nome):
            try:
                return nome, self._bytes(nome)
            except Exception as e:
                self.erros.append(f"{Path(nome).name}: {e}")
                return nome, None

        with ThreadPoolExecutor(max_workers=6) as ex:
            for nome, dados in ex.map(baixar, nomes):
                if dados is None:
                    continue
                try:
                    bcm, x, y, proj = self._ler(dados)
                except Exception as e:
                    self.erros.append(f"{Path(nome).name}: leitura: {e}")
                    continue
                del dados
                for reg in self.regioes.values():
                    iy, ix = self._indices(reg, x, y, proj)
                    g = np.full(iy.shape, SEM_DADO, np.uint8)
                    ok = ix >= 0
                    g[ok] = bcm[iy[ok], ix[ok]]
                    g[(g != 0) & (g != 1)] = SEM_DADO
                    reg["grades"][nome] = g
        return len(nomes)

    # ------------------------------------------------------------ consultas
    def _grade(self, rid, t):
        esc = self.arquivos.get(t)
        if not esc:
            return None, None
        g = self.regioes[rid]["grades"].get(esc[0])
        return (g, esc[1]) if g is not None else (None, None)

    def fracao(self, rid, t):
        """% da região coberta por nuvens no instante t, e o horário real da imagem."""
        g, quando = self._grade(rid, t)
        if g is None:
            return None
        d = self.regioes[rid]["dentro"]
        validos = d & (g != SEM_DADO)
        if validos.sum() < 0.5 * d.sum():
            return None
        return {"pct": round(100 * float((g[validos] == 1).mean()), 1), "imagem": quando}

    def nublado(self, rid, t, lat, lon):
        """True se havia nuvem no local (ou num pixel vizinho), False se limpo, None se sem dado."""
        g, _ = self._grade(rid, t)
        if g is None:
            return None
        r = self.regioes[rid]
        o, s, l, n = r["bbox"]
        i = int((n - lat) / RES)
        j = int((lon - o) / RES)
        bloco = g[max(0, i - 1):i + 2, max(0, j - 1):j + 2]
        if bloco.size == 0 or (bloco == SEM_DADO).all():
            return None
        return bool((bloco == 1).any())

    def png(self, rid, t_ultima, tempos_cegos, caminho):
        """Camada do mapa. Branco mais forte: nuvem em todas as passagens de tempos_cegos
        (área que nenhum satélite viu); branco suave: nuvem só na passagem t_ultima."""
        from PIL import Image
        g, _ = self._grade(rid, t_ultima)
        if g is None:
            return None
        r = self.regioes[rid]
        cegas = self.cego(rid, tempos_cegos)
        rgba = np.zeros(g.shape + (4,), np.uint8)
        rgba[(g == 1) & r["dentro"]] = (240, 244, 250, 120)
        if cegas is not None:
            rgba[cegas] = (250, 252, 255, 215)
        Image.fromarray(rgba, "RGBA").save(caminho, optimize=True)
        o, s, l, n = r["bbox"]
        ny, nx = g.shape
        return [round(o, 5), round(n - ny * RES, 5), round(o + nx * RES, 5), round(n, 5)]

    def cego(self, rid, tempos):
        """Células da região com nuvem em TODOS os instantes dados (com dado em todos)."""
        grades = [self._grade(rid, t)[0] for t in tempos]
        grades = [g for g in grades if g is not None]
        if len(grades) < 2:
            return None
        pilha = np.stack(grades)
        return (pilha == 1).all(axis=0) & self.regioes[rid]["dentro"]

    def fracao_cega(self, rid, tempos):
        m = self.cego(rid, tempos)
        if m is None:
            return None
        d = self.regioes[rid]["dentro"]
        return round(100 * float(m.sum()) / max(1, int(d.sum())), 1)


def hora_solar_utc(dia_utc, hora_solar, lon):
    """Instante UTC em que o relógio solar local marca hora_solar, no dia dado."""
    base = datetime(dia_utc.year, dia_utc.month, dia_utc.day, tzinfo=timezone.utc)
    return base + timedelta(hours=hora_solar - lon / 15.0)


def ultima_passagem_viirs(agora, lon, hora_solar):
    """Horário nominal da última passagem do VIIRS (NOAA-20/21 cruzam o equador ~13h30 e ~01h30 solar)."""
    for d in range(0, 3):
        t = hora_solar_utc(agora - timedelta(days=d), hora_solar, lon)
        if t <= agora - timedelta(minutes=20):
            return t.replace(second=0, microsecond=0)
    return None


if __name__ == "__main__":
    sys.exit("Este módulo é usado por focos.py.")

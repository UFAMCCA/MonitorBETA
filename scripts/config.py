"""Configuração central do monitoramento de focos e temperatura de superfície."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "docs" / "data"

FUSO = "America/Manaus"  # UTC-4, sem horário de verão

# ------------------------------------------------------------------ regiões
# Cada região tem um município-sede, os municípios do entorno e, quando houver,
# o sensor de qualidade do ar (PurpleAir) em que o mapa é centralizado.
# Municípios são escritos como "Nome" (Amazonas) ou "Nome/UF" (outro estado)
# ou "Nome/CO" (Colômbia) e "Nome/PE" (Peru). Acentos e maiúsculas não importam.
REGIAO_PADRAO = "manaus"
REGIOES = {
    "manaus": {
        "nome": "Manaus",
        "sensor": None,
        "sede": "Manaus",
        "entorno": ["Iranduba", "Careiro", "Careiro da Várzea", "Manacapuru", "Novo Airão",
                    "Anori", "Beruri", "Rio Preto da Eva", "Presidente Figueiredo",
                    "Itacoatiara", "Manaquiri", "Autazes"],
    },
    "itacoatiara": {
        "nome": "Itacoatiara",
        "sensor": "SEMA_DCAM_38",
        "sede": "Itacoatiara",
        "entorno": ["Autazes", "Nova Olinda do Norte", "Silves", "Urucará", "Barreirinha",
                    "Parintins", "Urucurituba", "Maués", "Itapiranga",
                    "São Sebastião do Uatumã", "Boa Vista do Ramos",
                    "Presidente Figueiredo", "Rio Preto da Eva"],
    },
    "parintins": {
        "nome": "Parintins",
        "sensor": "SEMA_DCAM_47",
        "sede": "Parintins",
        "entorno": ["Nhamundá", "Oriximiná/PA", "Boa Vista do Ramos", "Maués", "Urucurituba",
                    "Barreirinha", "Urucará", "Itaituba/PA", "Santarém/PA", "Itapiranga",
                    "Presidente Figueiredo", "Rio Preto da Eva", "São Sebastião do Uatumã",
                    "Itacoatiara"],
    },
    "humaita": {
        "nome": "Humaitá",
        "sensor": "SEMA_DCAM_65",
        "sede": "Humaitá",
        "entorno": ["Lábrea", "Porto Velho/RO", "Apuí", "Canutama", "Cruzeiro do Sul/AC",
                    "Manicoré", "Novo Aripuanã", "Tapauá", "Autazes", "Manaquiri"],
    },
    "coari": {
        "nome": "Coari",
        "sensor": "SEMA_DCAM_27",
        "sede": "Coari",
        "entorno": ["Tefé", "Canutama", "Lábrea", "Tapauá", "Beruri", "Anori", "Manacapuru",
                    "Manaus", "Novo Airão", "Anamã", "Barcelos", "Manicoré"],
    },
    "benjamin-constant": {
        "nome": "Benjamin Constant",
        "sensor": "SEMA_DCAM_19",
        "sede": "Benjamin Constant",
        "entorno": ["Atalaia do Norte", "Letícia/CO", "Tabatinga", "Santo Antônio do Içá",
                    "Amaturá", "São Gabriel da Cachoeira", "Eirunepé", "Carauari", "Envira",
                    "Iquitos/PE", "Cruzeiro do Sul/AC", "Mâncio Lima/AC"],
    },
}

# Coordenadas dos sensores. Ficam em docs/data/sensores.json, preenchido
# automaticamente pela API do PurpleAir (segredo PURPLEAIR_API_KEY).
# Para fixar uma coordenada à mão, preencha aqui: "SEMA_DCAM_38": (-3.14, -58.44)
SENSORES_MANUAL = {
}

# Compatibilidade: lista de municípios da região padrão
MUNICIPIOS = [REGIOES[REGIAO_PADRAO]["sede"], *REGIOES[REGIAO_PADRAO]["entorno"]]

# Horários de atualização (hora local de Manaus). A das 08h foi retirada
# porque nenhum satélite polar passa entre 04h e 08h.
ATUALIZACOES = {
    "04h": "Passagem noturna do VIIRS (~01h30) + GOES-19",
    "12h": "Terra manhã (~9h) e MetOp-B/C (~9h30) + GOES-19",
    "18h": "Passagem da tarde do VIIRS (~13h30) + GOES-19 + Aqua (referência INPE)",
}

# Satélites usados. 'inpe' = nome no BDQueimadas; 'firms' = fonte na API do FIRMS.
# 'pixel_km' = tamanho nominal do pixel no nadir, usado quando a fonte não
# informa o tamanho real (scan x track).
SATELITES = {
    "NOAA-20": {
        "inpe": ["NOAA-20"], "firms": "VIIRS_NOAA20_NRT", "sensor": "VIIRS",
        "pixel_km": 0.375, "tipo": "polar", "papel": "principal",
        "horario": "~01h30 e ~13h30",
    },
    "NOAA-21": {
        "inpe": ["NOAA-21"], "firms": "VIIRS_NOAA21_NRT", "sensor": "VIIRS",
        "pixel_km": 0.375, "tipo": "polar", "papel": "principal",
        "horario": "~01h30 e ~13h30",
    },
    "GOES-19": {
        "inpe": ["GOES-19"], "firms": None, "sensor": "ABI",
        "pixel_km": 2.2, "tipo": "geoestacionario", "papel": "principal",
        "horario": "a cada 10 min",
    },
    "TERRA": {
        "inpe": ["TERRA_M-M"], "firms": "MODIS_NRT", "sensor": "MODIS",
        "pixel_km": 1.0, "tipo": "polar", "papel": "apoio (12h)",
        "horario": "~9h (órbita em deriva)",
    },
    "METOP-B": {
        "inpe": ["METOP-B"], "firms": None, "sensor": "AVHRR",
        "pixel_km": 1.1, "tipo": "polar", "papel": "apoio (12h)",
        "horario": "~9h30",
    },
    "METOP-C": {
        "inpe": ["METOP-C"], "firms": None, "sensor": "AVHRR",
        "pixel_km": 1.1, "tipo": "polar", "papel": "apoio (12h)",
        "horario": "~9h30",
    },
    "AQUA": {
        "inpe": ["AQUA_M-T"], "firms": "MODIS_NRT", "sensor": "MODIS",
        "pixel_km": 1.0, "tipo": "polar", "papel": "referência INPE",
        "horario": "~15h30 (órbita em deriva; fim de missão)",
    },
}

# Janela de dados exibida no mapa
HORAS_HISTORICO = 48

# Agrupamento de detecções num mesmo evento de fogo
AGRUP_TOLERANCIA_KM = 0.5    # folga além do contato entre os pixels
AGRUP_JANELA_H = 12          # detecções separadas por mais que isso não se ligam

# Extinção estimada (o satélite NÃO observa a extinção; isto é inferência)
EXT_PASSAGENS_POLARES = 2    # passagens polares seguidas sem detecção
EXT_HORAS_GOES = 3           # horas de GOES sem detecção
ATIVO_HORAS_MIN = 3          # detectado há menos que isso = sempre ativo

# Temperatura de superfície (quinzenal)
LST_DIAS = 16
LST_RES_GRAUS = 0.0027       # ~300 m para exibição na web (nativo: 100 m)
LST_NUVEM_MAX = 80           # % de nuvem máxima por cena na busca
LST_MAX_PIXELS = 2600        # lado máximo da grade; regiões grandes usam pixel maior

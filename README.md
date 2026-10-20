# Focos de calor · Amazonas

Site estático com os focos de calor ativos e das últimas 48 horas em seis regiões do Amazonas. Cada região tem um município-sede e o seu entorno. Nas regiões com sensor de qualidade do ar (PurpleAir, rede SEMA-AM), o mapa é centralizado na coordenada exata do sensor e mostra a distância de cada foco até ele. O site também mostra a temperatura da superfície, atualizada a cada quinzena.

| Região | Sensor | Entorno |
|---|---|---|
| Manaus | — | Iranduba, Careiro, Careiro da Várzea, Manacapuru, Manaquiri, Autazes, Novo Airão, Anori, Beruri, Rio Preto da Eva, Presidente Figueiredo, Itacoatiara |
| Itacoatiara | SEMA_DCAM_38 | Autazes, Nova Olinda do Norte, Silves, Urucará, Barreirinha, Parintins, Urucurituba, Maués, Itapiranga, São Sebastião do Uatumã, Boa Vista do Ramos, Presidente Figueiredo, Rio Preto da Eva |
| Parintins | SEMA_DCAM_47 | Nhamundá, Oriximiná (PA), Boa Vista do Ramos, Maués, Urucurituba, Barreirinha, Urucará, Itaituba (PA), Santarém (PA), Itapiranga, Presidente Figueiredo, Rio Preto da Eva, São Sebastião do Uatumã, Itacoatiara |
| Humaitá | SEMA_DCAM_65 | Lábrea, Porto Velho (RO), Apuí, Canutama, Cruzeiro do Sul (AC), Manicoré, Novo Aripuanã, Tapauá, Autazes, Manaquiri |
| Coari | SEMA_DCAM_27 | Tefé, Canutama, Lábrea, Tapauá, Beruri, Anori, Manacapuru, Manaus, Novo Airão, Anamã, Barcelos, Manicoré |
| Benjamin Constant | SEMA_DCAM_19 | Atalaia do Norte, Letícia (Colômbia), Tabatinga, Santo Antônio do Içá, Amaturá, São Gabriel da Cachoeira, Eirunepé, Carauari, Envira, Iquitos (Peru, distrito), Cruzeiro do Sul (AC), Mâncio Lima (AC) |

Para mudar regiões ou municípios, edite `REGIOES` em `scripts/config.py` e rode `python scripts/limites.py`. Depois envie a pasta `docs/data` gerada.

## Painel do Fogo (Censipam)

O site também mostra, em lilás, os dados do [Painel do Fogo](https://panorama.sipam.gov.br/painel-do-fogo/) do Censipam, lidos do GeoServer público (`painel_do_fogo`, WFS):

| Camada | Conteúdo |
|---|---|
| `mv_evento_filtro` | eventos de fogo (área, persistência, detecções, potência, situação) |
| `mv_alertas_goes_novos_eventos` | alertas GOES de novo evento |
| `mv_alertas_goes_atividade_eventos` | alertas GOES de evento em atividade |
| `mv_alertas_estradas` | fogo perto de estrada (rodovia e km) |
| `mv_alertas_areas_urbanizadas` | fogo perto de área urbana |
| `tb_brigada_pto` | brigadas de incêndio |

A consulta é feita ao vivo no navegador de quem abre o site. Se falhar, o site usa a cópia gravada na última coleta (`scripts/censipam.py`). O servidor do Censipam pode recusar acessos de fora do Brasil, e os servidores do GitHub ficam nos EUA. Nesse caso a cópia não é gerada e vale só a consulta ao vivo.

## O que roda e quando

| Tarefa | Quando (Manaus) | Fonte |
|---|---|---|
| Focos das seis regiões | 04h, 12h e 18h, disparados pelo Google Apps Script | INPE BDQueimadas + NASA FIRMS |
| Temperatura da superfície | dias 1 e 16, disparada pelo Google Apps Script | Landsat 8/9 TIRS (Microsoft Planetary Computer) |

A coleta de focos publica o site direto no GitHub Pages, e os arquivos de 48 h não vão para o repositório. Assim ele não cresce a cada atualização. No repositório ficam só:
- o histórico compacto, em `docs/data/historico/<regiao>/AAAA-MM.csv`, uma linha por detecção, útil para balanços mensais;
- as coordenadas dos sensores;
- as camadas de temperatura.

## Configuração (uma vez)

1. **Segredos** (Settings → Secrets and variables → Actions):
   - `FIRMS_MAP_KEY`: chave gratuita do FIRMS, já cadastrada.
   - `PURPLEAIR_API_KEY`: chave de leitura gratuita do PurpleAir (develop.purpleair.com). É usada só para buscar a coordenada exata dos sensores, uma única vez. Os sensores não mudam de lugar, então o gasto de pontos é mínimo.
   - Também é possível fixar a coordenada à mão em `SENSORES_MANUAL`, em `scripts/config.py`.
2. **Pages** (Settings → Pages → Build and deployment → Source): escolha **GitHub Actions**.
3. **Apps Script**: continua igual, disparando `focos.yml` e `lst.yml`.

## Como os dados são tratados

- **Coleta única para todas as regiões.** INPE e FIRMS são consultados uma vez, só na área das regiões, e cada região é processada em separado. Um mesmo município pode estar em mais de uma região.
- **Agrupamento.** Detecções cujos pixels se tocam (com 500 m de folga) e que estão a até 12 h uma da outra formam um único foco.
- **Área desenhada.** É a união dos pixels reais do sensor mais fino que viu o foco. A cor indica a idade, a opacidade indica a confiança e o contorno tracejado indica extinção estimada.
- **Extinção estimada.** O foco é marcado como extinto quando uma destas condições se cumpre:
  - duas passagens polares seguidas não o registram;
  - ele tinha detecções do GOES-19 e o GOES passa 3 h sem registrá-lo.

  Nuvem e fumaça podem produzir falsas extinções.
- **Distância ao sensor.** É medida do centro do foco até o sensor. O painel conta os focos ativos a até 25, 50 e 100 km.
- **Temperatura da superfície.** É o pixel Landsat sem nuvem mais recente da quinzena. Regiões grandes usam pixel maior na exibição: de ~300 m em Manaus a ~660 m em Humaitá.

## Rodar localmente

```bash
pip install -r requirements.txt
python scripts/limites.py
PURPLEAIR_API_KEY=... python scripts/sensores.py
FIRMS_MAP_KEY=... python scripts/focos.py
pip install -r requirements-lst.txt && python scripts/lst.py --regiao manaus
cd docs && python -m http.server 8000
```

## Fontes dos limites

- **Brasil:** IBGE, via github.com/tbrugz/geodata-br.
- **Colômbia:** DANE, MGN 2018.
- **Peru:** INEI, distritos.

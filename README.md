# Monitor de Focos de calor · Manaus e entorno

Site estático que mostra focos de calor ativos e das últimas 48 horas em 11 municípios do Amazonas: Manaus, Iranduba, Careiro, Careiro da Várzea, Manacapuru, Novo Airão, Anori, Beruri, Rio Preto da Eva, Presidente Figueiredo e Itacoatiara. Também mostra a temperatura da superfície, atualizada a cada quinzena.

## O que roda e quando

| Tarefa | Horário (Manaus) | Fonte | Satélites |
|---|---|---|---|
| Focos | 04h | INPE BDQueimadas + NASA FIRMS | NOAA-20 e NOAA-21 (VIIRS noturno, ~01h30), GOES-19 |
| Focos | 12h | idem | Terra (~9h), MetOp-B/C (~9h30), GOES-19 |
| Focos | 18h | idem | NOAA-20 e NOAA-21 (VIIRS, ~13h30), GOES-19, Aqua (referência INPE, enquanto operar) |
| Temperatura da superfície | dias 1 e 16 | Landsat 8/9 TIRS via Microsoft Planetary Computer | Landsat 8 e 9 (~10h, 100 m) |


## Publicar no GitHub Pages (uma vez)

1. Crie um repositório no GitHub e envie esta pasta para ele (branch `main`).
2. Peça uma chave gratuita do FIRMS em https://firms.modaps.eosdis.nasa.gov/api/map_key/ e cadastre-a em **Settings → Secrets and variables → Actions → New repository secret** com o nome `FIRMS_MAP_KEY`. Sem a chave o site funciona só com o INPE, sem o tamanho real do pixel e sem a confiança da detecção.
3. Em **Settings → Pages**, escolha *Deploy from a branch*, branch `main`, pasta `/docs`.
4. Em **Actions**, rode manualmente *Focos de calor* e *Temperatura da superfície* (botão *Run workflow*) para gerar os primeiros dados. Depois disso, os horários acima rodam sozinhos.


## Como os dados são tratados

- **Agrupamento.** Detecções cujos pixels se tocam (com 500 m de folga) e que estão a até 12 h uma da outra formam um único foco.
- **Área desenhada (buffer C).** É a união dos pixels reais do sensor mais fino que viu o foco, com o tamanho *scan × track* informado pelo FIRMS. Quando só o INPE tem a detecção, usa-se o tamanho nominal do sensor. A cor indica a idade da última detecção, a opacidade indica a confiança e o contorno tracejado indica extinção estimada. O círculo cresce com o número de pixels.
- **Extinção estimada.** O satélite não observa a extinção. O foco é marcado como extinto quando uma destas condições se cumpre:
  - duas passagens polares seguidas não o registram;
  - ele tinha detecções do GOES-19 e o GOES passa 3 h sem registrá-lo.

  O site mostra o intervalo entre a última detecção e a primeira observação sem registro. Nuvem e fumaça podem produzir falsas extinções.
- **Horário das passagens.** É inferido pelas próprias detecções numa faixa de 3° ao redor da área.
- **Temperatura da superfície.** Cada pixel vem da imagem Landsat sem nuvem mais recente da quinzena (nuvem, sombra e cirrus removidos pela banda QA_PIXEL). O arquivo guarda de qual cena veio cada pixel, e o popup técnico mostra satélite, data e hora. É temperatura da superfície, não do solo em profundidade.

Todos os limiares ficam em `scripts/config.py`.

## Rodar localmente

```bash
pip install -r requirements.txt
python scripts/focos.py                 # usa FIRMS_MAP_KEY do ambiente, se existir
pip install -r requirements-lst.txt
python scripts/lst.py
cd docs && python -m http.server 8000   # abrir http://localhost:8000
```

É possível realizar teste offline com CSVs próprios: `python scripts/focos.py --inpe-local pasta --firms-local pasta --agora 2026-09-25T22:00:00Z`. Nesse modo o site exibe o aviso de dados de teste.

## Limitações conhecidas

- O Aqua e o Terra estão no fim da missão. Quando pararem, as linhas deles somem sem quebrar nada. O Suomi-NPP não foi incluído porque a NASA encerra seus dados em 1º/11/2026.
- A reserva com VIIRS para a temperatura da superfície, para quando a quinzena estiver muito nublada, é o próximo passo de implementação: exige conta no NASA Earthdata. Na versão beta atual as áreas cobertas por nuvem durante toda a quinzena ficam sem cor, e a porcentagem de cobertura aparece no painel.
- O formato dos CSVs do INPE pode mudar. O leitor aceita as variações de nome de coluna conhecidas, e o status de cada fonte aparece em `docs/data/resumo.json` e no aviso do topo do site.
- Os limites municipais vêm da malha do IBGE, via github.com/tbrugz/geodata-br. A malha tem anéis de polígono mal marcados, que o script corrige. Para trocar os municípios, edite `MUNICIPIOS` em `scripts/config.py` e rode `python scripts/limites.py`.

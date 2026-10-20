/* Mapa principal: seletor de região, focos agrupados, linha do tempo de 48 h,
   passagens dos satélites, sensor de qualidade do ar e temperatura de superfície. */
(async function () {
  const estado = { regiao: null, filtro: "todos", eventos: [], agora: null, inicio: null, mostrarTodos: false, carga: 0 };
  const LIMITE_LISTA = 150;
  const RAIOS_KM = [25, 50, 100];
  const $ = id => document.getElementById(id);

  let regioes, sensores = {};
  try {
    regioes = await carregarJSON("data/regioes.json");
  } catch (e) {
    $("atualiz").textContent = "Não foi possível carregar a lista de regiões (data/regioes.json).";
    console.error(e);
    return;
  }
  try { sensores = await carregarJSON("data/sensores.json"); } catch (e) { sensores = {}; }

  /* ---------- mapa (criado uma vez) ---------- */
  const mapa = L.map("mapa", { zoomControl: true, minZoom: 4 });
  const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" });
  const img = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 18, attribution: "Imagem © Esri" });
  img.addTo(mapa);
  const telaCanvas = L.canvas({ padding: 0.5 });

  const mascara = L.layerGroup().addTo(mapa);
  const limCamada = L.layerGroup().addTo(mapa);
  const nomesCamada = L.layerGroup().addTo(mapa);
  const raiosCamada = L.layerGroup().addTo(mapa);
  const grupoEventos = L.layerGroup().addTo(mapa);
  const sensorCamada = L.layerGroup().addTo(mapa);
  let lstCamada = null, controleCamadas = null;
  let censCamadas = {};  // camadas do Painel do Fogo (Censipam) da região atual
  let nuvensCamada = null;
  const faixaNuvens = L.control({ position: "topright" });
  faixaNuvens.onAdd = () => { const d = L.DomUtil.create("div", "faixa-nuvens"); d.hidden = true; L.DomEvent.disableClickPropagation(d); return d; };
  faixaNuvens.addTo(mapa);

  /* Rótulos: em zoom afastado ficam menores e os que se sobrepõem são escondidos,
     mantendo a sede, os municípios maiores e o sensor sempre visíveis. */
  let rotulos = [];  // [{marcador, prioridade}]
  function ajustarNomes() {
    $("mapa").classList.toggle("nomes-pequenos", mapa.getZoom() < 8);
    const ocupados = [];
    const sobrepoe = r => ocupados.some(o => !(r.right + 3 < o.left || r.left - 3 > o.right || r.bottom + 2 < o.top || r.top - 2 > o.bottom));
    sensorCamada.eachLayer(m => { const el = m.getElement && m.getElement(); if (el) ocupados.push(el.getBoundingClientRect()); });
    for (const { marcador, prioridade } of rotulos) {
      const el = marcador.getElement && marcador.getElement();
      if (!el) continue;
      el.classList.remove("oculto");
      const r = el.firstElementChild.getBoundingClientRect();
      if (prioridade !== Infinity && sobrepoe(r)) el.classList.add("oculto"); else ocupados.push(r);  // a sede nunca some
    }
  }
  mapa.on("zoomend", ajustarNomes);
  mapa.on("overlayadd", () => setTimeout(ajustarNomes, 0));

  function montarControleCamadas() {
    if (controleCamadas) controleCamadas.remove();
    const extras = { "Limites municipais": limCamada, "Nomes dos municípios": nomesCamada, "Focos": grupoEventos };
    if (sensorCamada.getLayers().length) {
      extras["Sensor de qualidade do ar"] = sensorCamada;
      extras["Raios de 25, 50 e 100 km"] = raiosCamada;
    }
    if (nuvensCamada) extras["Nuvens na última passagem do VIIRS (GOES-19)"] = nuvensCamada;
    if (lstCamada) extras["Temperatura da superfície"] = lstCamada;
    for (const { grupo, cfg } of Object.values(censCamadas)) extras[`Censipam · ${cfg.nome}`] = grupo;
    controleCamadas = L.control.layers({ "Imagem de satélite": img, "Mapa de ruas": osm }, extras, { collapsed: true }).addTo(mapa);
  }

  /* ---------- legenda (fixa) ---------- */
  const legenda = L.control({ position: "bottomright" });
  legenda.onAdd = () => {
    const d = L.DomUtil.create("div", "legenda");
    const aberta = !window.matchMedia("(max-width: 820px)").matches;
    d.innerHTML = `<details${aberta ? " open" : ""}><summary>Legenda</summary>
      <div class="rotulo">Última detecção há</div>
      ${FAIXAS_IDADE.map(f => `<div class="linha"><i style="background:${corVar(f.cor)}"></i>${f.nome}</div>`).join("")}
      <div class="rotulo" style="margin-top:4px">Contorno</div>
      <div class="linha"><i class="borda"></i>ativo</div>
      <div class="linha"><i class="borda tracejada"></i>extinto (estimado)</div>
      <div class="linha"><i class="borda pontilhada"></i>extinção incerta (nuvens)</div>
      <div class="linha"><i class="amostra-nuvem"></i>nuvem na última passagem</div>
      <div class="linha"><i class="amostra-nuvem cega"></i>nuvem em todas as passagens (48 h)</div>
      <div class="rotulo" style="margin-top:4px">Preenchimento</div>
      <div class="linha">mais opaco = maior confiança</div>
      <div class="linha">área = pixels reais do sensor; círculo maior = mais pixels</div>
      <div class="linha legenda-sensor"><span class="icone-sensor"></span>sensor de qualidade do ar</div>
      <div class="linha"><i class="amostra-evento"></i>evento do Painel do Fogo (Censipam)</div>
    </details>`;
    L.DomEvent.disableClickPropagation(d);
    return d;
  };
  legenda.addTo(mapa);

  /* ---------- seletor de região ---------- */
  const sel = $("regiao");
  sel.innerHTML = regioes.regioes.map(r => `<option value="${esc(r.id)}">${esc(r.nome)} e entorno</option>`).join("");
  const pedida = new URLSearchParams(location.search).get("r");
  let guardada = null;
  try { guardada = localStorage.getItem("regiao"); } catch (e) { /* sem armazenamento */ }
  const existe = id => regioes.regioes.some(r => r.id === id);
  const inicial = [pedida, guardada, regioes.padrao].find(existe) || regioes.regioes[0].id;
  sel.value = inicial;
  sel.addEventListener("change", () => trocarRegiao(sel.value));

  /* ---------- funções de desenho ---------- */
  function estilo(p) {
    const cor = corIdade(horasDesde(p.ultima_deteccao, estado.agora));
    return {
      color: cor, fillColor: cor, fillOpacity: opacConf(p.confianca), opacity: 0.95,
      weight: p.status === "ativo" ? 2 : 1.6, dashArray: p.status === "ativo" ? null : p.extincao_incerta ? "1 4" : "5 4",
    };
  }

  function popup(p) {
    const outros = p.satelites.filter(x => x !== p.satelite_primeira).map(nomeSat);
    const dist = p.dist_sensor_km != null ? `<dt>Distância do sensor</dt><dd>${num(p.dist_sensor_km, p.dist_sensor_km < 10 ? 1 : 0)} km</dd>` : "";
    return `<div class="pop">
      <h3>${esc(p.municipio || "Área monitorada")}</h3>
      <span class="estado ${p.status}"><span class="ponto"></span>${textoStatus(p)}</span>
      <dl>
        <dt>Detectado em</dt><dd>${horaLocal(p.primeira_deteccao)}</dd>
        <dt>Última detecção</dt><dd>${horaLocal(p.ultima_deteccao)}</dd>
        <dt>Extinção</dt><dd>${p.status === "ativo" ? "ainda ativo" : textoExtincao(p)}${p.extincao_incerta ? `<br><small class="alerta-nuvem">☁ havia nuvem sobre o local depois do último registro: o fogo pode continuar ativo</small>` : ""}</dd>
        <dt>Duração</dt><dd>${duracao(p.duracao_h)}</dd>
        <dt>Satélite</dt><dd>${esc(nomeSat(p.satelite_primeira))}${outros.length ? `<br><small>também: ${esc(outros.join(", "))}</small>` : ""}</dd>
        ${dist}
      </dl>
      <a class="abrir" href="detalhe.html?r=${encodeURIComponent(estado.regiao)}#${esc(p.id)}" target="_blank" rel="noopener">Detalhes técnicos ↗</a>
    </div>`;
  }

  const porId = {};
  function desenharEventos() {
    grupoEventos.clearLayers();
    for (const k in porId) delete porId[k];
    const muitos = estado.eventos.length > 400;  // muitos focos: canvas é bem mais leve que SVG
    for (const f of estado.eventos) {
      const p = f.properties;
      if (estado.filtro !== "todos" && p.status !== estado.filtro) continue;
      const st = estilo(p);
      const opcoes = muitos ? { renderer: telaCanvas } : {};
      const poli = L.geoJSON(f, { style: st, ...opcoes });
      const idade = horasDesde(p.ultima_deteccao, estado.agora);
      const marcador = L.circleMarker([p.lat, p.lon], {
        ...st, ...opcoes, radius: 5 + 2.2 * Math.sqrt(p.n_pixels), fillOpacity: Math.max(0.35, st.fillOpacity),
        className: !muitos && p.status === "ativo" && idade <= 6 ? "pulso" : "",
      });
      const g = L.featureGroup([poli, marcador]).bindPopup(popup(p), { maxWidth: 300 });
      g.on("popupopen", () => marcarLinha(p.id));
      g.addTo(grupoEventos);
      porId[p.id] = g;
    }
  }

  const pos = iso => Math.max(0, Math.min(100, (new Date(iso) - estado.inicio) / (estado.agora - estado.inicio) * 100));
  const lista = $("eventos");
  function desenharLista() {
    const evs = estado.eventos.filter(f => estado.filtro === "todos" || f.properties.status === estado.filtro);
    if (!evs.length) { lista.innerHTML = `<p class="vazio">Nenhum foco neste filtro.</p>`; return; }
    const mostrar = estado.mostrarTodos ? evs : evs.slice(0, LIMITE_LISTA);
    lista.innerHTML = mostrar.map(f => {
      const p = f.properties;
      const cor = corIdade(horasDesde(p.ultima_deteccao, estado.agora));
      const a = pos(p.primeira_deteccao), b = pos(p.ultima_deteccao);
      let fim;
      if (p.status === "extinto_estimado") {
        const c = pos(p.extincao_ate);
        fim = `<span class="apagou" style="left:${b}%;width:${Math.max(0.6, c - b)}%"></span><span class="fim" style="left:${c}%"></span>`;
      } else {
        fim = `<span class="segue" style="left:${b}%;width:${Math.max(2, 100 - b)}%;background:linear-gradient(90deg, ${cor}, transparent)"></span>`;
      }
      return `<button type="button" class="evento${p.id === estado.sel ? " sel" : ""}" data-id="${p.id}" title="${esc(textoStatus(p))} · ${horaLocal(p.primeira_deteccao)} → ${p.status === "ativo" ? "agora" : horaLocal(p.extincao_ate)}">
        <span class="nome">${esc(p.municipio || "—")}<small>${horaCurta(p.primeira_deteccao)} · ${p.n_pixels} px · ${p.status === "ativo" ? "ativo" : p.extincao_incerta ? "extinto? (nuvens)" : "extinto"}</small></span>
        <span class="trilho"><span class="queima" style="left:${a}%;width:${Math.max(0.8, b - a)}%;background:${cor}"></span>${fim}</span>
      </button>`;
    }).join("") + (evs.length > mostrar.length
      ? `<button type="button" class="mais" id="mostrar-todos">Mostrar todos os ${evs.length} focos</button>` : "");
  }

  function marcarLinha(id) {
    estado.sel = id;
    lista.querySelectorAll(".evento").forEach(el => el.classList.toggle("sel", el.dataset.id === id));
  }
  lista.addEventListener("click", ev => {
    if (ev.target.id === "mostrar-todos") { estado.mostrarTodos = true; desenharLista(); return; }
    const b = ev.target.closest(".evento"); if (!b) return;
    const g = porId[b.dataset.id]; if (!g) return;
    mapa.fitBounds(g.getBounds(), { maxZoom: 13, padding: [40, 40] });
    g.openPopup(); marcarLinha(b.dataset.id);
    if (window.matchMedia("(max-width: 820px)").matches) $("mapa").scrollIntoView({ behavior: "smooth" });
  });
  document.querySelectorAll(".filtros button").forEach(bt => bt.addEventListener("click", () => {
    estado.filtro = bt.dataset.filtro;
    estado.mostrarTodos = false;
    document.querySelectorAll(".filtros button").forEach(x => x.setAttribute("aria-pressed", String(x === bt)));
    desenharEventos(); desenharLista();
  }));

  /* temperatura: controles ligados uma vez, agindo sobre a camada da região atual */
  const chk = $("lst-ligado"), opac = $("lst-opac");
  chk.addEventListener("change", () => { if (!lstCamada) return; chk.checked ? lstCamada.addTo(mapa) : mapa.removeLayer(lstCamada); });
  opac.addEventListener("input", () => lstCamada && lstCamada.setOpacity(Number(opac.value)));
  mapa.on("overlayadd overlayremove", e => { if (lstCamada && e.layer === lstCamada) chk.checked = e.type === "overlayadd"; });

  /* ---------- troca de região ---------- */
  async function trocarRegiao(id) {
    const carga = ++estado.carga;
    const reg = regioes.regioes.find(r => r.id === id);
    document.body.classList.add("carregando");
    let resumo, focos, limites, lst = null;
    try {
      [resumo, focos, limites] = await Promise.all([
        carregarJSON(`data/${id}/resumo.json`), carregarJSON(`data/${id}/focos.geojson`), carregarJSON(`data/${id}/limites.geojson`),
      ]);
    } catch (e) {
      console.error(e);
      if (carga !== estado.carga) return;
      document.body.classList.remove("carregando");
      $("atualiz").innerHTML = `<span>Os dados de ${esc(reg.nome)} ainda não foram gerados. Rode a coleta de focos uma vez.</span>`;
      return;
    }
    try { lst = await carregarJSON(`data/${id}/lst.json`); } catch (e) { lst = null; }
    if (carga !== estado.carga) return;  // outra região foi escolhida no meio do carregamento
    document.body.classList.remove("carregando");

    estado.regiao = id;
    estado.agora = new Date(resumo.gerado_em);
    estado.inicio = new Date(estado.agora - 48 * 3.6e6);
    estado.eventos = focos.features;
    estado.sel = null;
    estado.mostrarTodos = false;
    try { localStorage.setItem("regiao", id); } catch (e) { /* sem armazenamento */ }
    const url = new URL(location.href); url.searchParams.set("r", id); history.replaceState(null, "", url);
    document.title = `Focos de Calor ${reg.nome}`;

    /* cabeçalho */
    const sensorNome = reg.sensor;
    const s = resumo.sensor && resumo.sensor.lat != null ? resumo.sensor
      : (sensorNome && sensores[sensorNome] && sensores[sensorNome].lat != null ? { nome: sensorNome, ...sensores[sensorNome] } : null);
    $("sub-regiao").textContent = `${limites.features.length} municípios` + (sensorNome ? ` · sensor ${sensorNome}` : "");
    const ordem = resumo.proximas_atualizacoes;
    const proxima = ordem[(ordem.indexOf(resumo.atualizacao) + 1) % ordem.length];
    $("atualiz").innerHTML = `<span>Atualizado em <b>${horaLocal(resumo.gerado_em)}</b></span>` +
      ordem.map(h => `<span class="chip${h === resumo.atualizacao ? " atual" : ""}" title="${esc(h === resumo.atualizacao ? resumo.atualizacao_descricao : "")}">${h}</span>`).join("") +
      `<span>próxima: ${proxima}</span>`;

    const avisos = [];
    if (resumo.dados_de_teste) avisos.push("Demonstração com dados sintéticos: os focos exibidos não são reais.");
    if (lst && lst.dados_de_teste) avisos.push("A camada de temperatura também é sintética.");
    if (sensorNome && !s) avisos.push(`Coordenada do sensor ${sensorNome} ainda não disponível: o mapa mostra a região inteira.`);
    for (const [fonte, st] of Object.entries(resumo.fontes_status || {})) {
      if (/^erro|^sem /.test(st)) avisos.push(`${fonte}: ${st}`);
    }
    const av = $("aviso"); av.textContent = avisos.join(" · "); av.hidden = !avisos.length;

    /* contadores */
    $("n-ativos").textContent = resumo.eventos_ativos;
    $("n-det-ativas").textContent = resumo.deteccoes_ativas;
    $("n-extintos").textContent = resumo.eventos_extintos;
    const incertos = (resumo.nuvens && resumo.nuvens.extintos_incertos) || 0;
    $("n-extintos-nota").textContent = incertos ? `${incertos} com extinção incerta por nuvens` : "";
    $("n-det").textContent = resumo.deteccoes_total;
    const perto = resumo.ativos_perto_do_sensor || {};
    $("perto-sensor").hidden = !s || !Object.keys(perto).length;
    $("perto-sensor").innerHTML = RAIOS_KM.map(r => `<div><b class="num">${perto[r] ?? 0}</b><small>até ${r} km</small></div>`).join("");

    const totais = resumo.por_municipio, ativosM = resumo.ativos_por_municipio;
    const maxM = Math.max(1, ...Object.values(totais));
    $("munis").innerHTML = Object.keys(totais).length
      ? Object.entries(totais).map(([m, n]) => {
        const a = ativosM[m] || 0;
        return `<div class="muni"><span>${esc(m)}</span><span class="barra" title="${a} ativos, ${n - a} extintos" style="display:flex">` +
          `<i style="width:${a / maxM * 100}%"></i><i class="ext" style="width:${(n - a) / maxM * 100}%"></i></span><span>${n}</span></div>`;
      }).join("") + `<p class="nota">Focos por município em 48 h. Vermelho: ativos. Cinza: extintos.</p>`
      : `<p class="vazio">Nenhum foco na área nas últimas 48 horas.</p>`;

    /* limites, máscara e nomes */
    mascara.clearLayers(); limCamada.clearLayers(); nomesCamada.clearLayers(); raiosCamada.clearLayers(); sensorCamada.clearLayers();
    const aneis = [];
    limites.features.forEach(f => {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      polys.forEach(p => aneis.push(p[0].map(([x, y]) => [y, x])));
    });
    L.polygon([[[-60, -120], [-60, 0], [30, 0], [30, -120]], ...aneis], {
      stroke: false, fillColor: "#0e1512", fillOpacity: 0.45, interactive: false,
    }).addTo(mascara);
    L.geoJSON(limites, {
      style: f => ({ color: "#ffffff", weight: f.properties.sede ? 2.6 : 1.3, opacity: f.properties.sede ? 1 : 0.8, fill: false }),
      onEachFeature: (f, lyr) => lyr.bindTooltip(f.properties.nome + (f.properties.sede ? " (sede da região)" : ""), { sticky: true }),
    }).addTo(limCamada);
    rotulos = [];
    limites.features.forEach(f => {
      const b = L.geoJSON(f).getBounds();
      const pt = f.properties.rotulo ? [f.properties.rotulo[1], f.properties.rotulo[0]] : b.getCenter();
      const marcador = L.marker(pt, {
        interactive: false, keyboard: false,
        icon: L.divIcon({ className: "nome-municipio" + (f.properties.sede ? " sede" : ""), html: `<span>${esc(f.properties.nome)}</span>`, iconSize: null }),
      }).addTo(nomesCamada);
      const tamanho = (b.getNorth() - b.getSouth()) * (b.getEast() - b.getWest());
      rotulos.push({ marcador, prioridade: f.properties.sede ? Infinity : tamanho });
    });

    /* sensor e raios */
    if (s) {
      RAIOS_KM.forEach(r => {
        L.circle([s.lat, s.lon], { radius: r * 1000, color: "#7fe3ec", weight: 1.2, opacity: 0.85, dashArray: "4 6", fill: false, interactive: false }).addTo(raiosCamada);
        const marcador = L.marker([s.lat + r / 111.32, s.lon], {
          interactive: false, keyboard: false,
          icon: L.divIcon({ className: "rotulo-raio", html: `<span>${r} km</span>`, iconSize: null }),
        }).addTo(raiosCamada);
        rotulos.push({ marcador, prioridade: -r });  // raios cedem lugar aos nomes
      });
      const link = s.sensor_index ? `<a href="https://map.purpleair.com/?select=${encodeURIComponent(s.sensor_index)}#11/${s.lat}/${s.lon}" target="_blank" rel="noopener">Ver no mapa do PurpleAir ↗</a>` : "";
      L.marker([s.lat, s.lon], {
        zIndexOffset: 1000, keyboard: true, title: `Sensor ${s.nome}`,
        icon: L.divIcon({ className: "marcador-sensor", html: `<span class="icone-sensor"></span>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
      }).bindPopup(`<div class="pop">
          <h3>${esc(s.nome)}</h3>
          <dl>
            <dt>Tipo</dt><dd>Sensor de qualidade do ar (PurpleAir)</dd>
            <dt>Coordenada</dt><dd class="mono">${num(s.lat, 5)}, ${num(s.lon, 5)}</dd>
            <dt>Focos ativos</dt><dd>${RAIOS_KM.map(r => `${perto[r] ?? 0} até ${r} km`).join(" · ")}</dd>
            <dt>Origem</dt><dd>${esc(s.fonte || "—")}</dd>
          </dl>${link}</div>`, { maxWidth: 300 }).addTo(sensorCamada);
    }

    /* nuvens */
    desenharNuvens(id, resumo);

    /* temperatura */
    if (lstCamada) mapa.removeLayer(lstCamada);
    lstCamada = null;
    if (lst) {
      const [lo, ls, ll, ln] = lst.bbox;
      lstCamada = L.imageOverlay(`data/${id}/lst.png?v=${encodeURIComponent(lst.gerado_em || "")}`, [[ls, lo], [ln, ll]], { opacity: Number(opac.value), interactive: false });
      if (chk.checked) lstCamada.addTo(mapa);
    }
    montarControleCamadas();

    /* enquadramento: centro exato no sensor, com zoom que mostra a região inteira */
    const [o, sul, l, n] = limites.bbox;
    mapa.setMaxBounds(null);
    if (s) {
      const dlat = Math.max(n - s.lat, s.lat - sul), dlon = Math.max(l - s.lon, s.lon - o);
      const caixa = L.latLngBounds([s.lat - dlat, s.lon - dlon], [s.lat + dlat, s.lon + dlon]);
      mapa.setView([s.lat, s.lon], mapa.getBoundsZoom(caixa, false, L.point(20, 20)), { animate: false });
      mapa.setMaxBounds(caixa.pad(0.4));
    } else {
      mapa.fitBounds([[sul, o], [n, l]], { padding: [10, 10], animate: false });
      mapa.setMaxBounds(L.latLngBounds([sul, o], [n, l]).pad(0.25));
    }
    rotulos.sort((a, b) => b.prioridade - a.prioridade);
    ajustarNomes();

    desenharEventos();

    /* eixo da linha do tempo */
    const marcas = [];
    const t0 = new Date(estado.inicio); t0.setUTCMinutes(0, 0, 0);
    for (let t = new Date(t0); t <= estado.agora; t = new Date(+t + 3.6e6)) {
      const hLocal = Number(fmtHoraCurta.format(t).slice(0, 2));
      if (t > estado.inicio && hLocal % 12 === 0) marcas.push(t);
    }
    $("eixo").innerHTML = marcas.map(t => `<span style="left:${pos(t.toISOString())}%">${fmtDia.format(t)} ${fmtHoraCurta.format(t).slice(0, 2)}h</span>`).join("");
    desenharLista();

    /* passagens */
    const pass = [...resumo.passagens].sort((x, y) => y.inicio.localeCompare(x.inicio));
    $("passagens").innerHTML = pass.length ? pass.map(p => `<tr>
        <td>${horaLocal(p.inicio)}</td><td>${esc(nomeSat(p.satelite))}</td>
        <td>${p.resolucao_km < 1 ? Math.round(p.resolucao_km * 1000) + " m" : num(p.resolucao_km, 1) + " km"}</td>
        <td>${p.deteccoes_na_area}</td></tr>`).join("")
      : `<tr><td colspan="4" class="vazio">Nenhuma passagem registrada.</td></tr>`;
    $("nota-goes").textContent = resumo.goes_ultima_deteccao_regional
      ? `GOES-19 observa a região a cada 10 min (pixel ~2 km). Última detecção regional: ${horaLocal(resumo.goes_ultima_deteccao_regional)}. Horário da passagem polar estimado pelas detecções na região.`
      : "GOES-19 observa a região a cada 10 min, mas não registrou focos no período.";

    /* satélites */
    $("sat-ficha").innerHTML = Object.entries(resumo.satelites).map(([k, v]) =>
      `<dt>${esc(nomeSat(k))}</dt><dd>${esc(v.horario)} · ${v.pixel_km < 1 ? Math.round(v.pixel_km * 1000) + " m" : v.pixel_km + " km"} · ${esc(v.papel)}</dd>`).join("") +
      Object.entries(resumo.atualizacoes || {}).map(([h, d]) => `<dt>Atualização ${h}</dt><dd>${esc(d)}</dd>`).join("");

    /* ficha da temperatura */
    const ficha = $("lst-ficha");
    if (lst) {
      const [a, b] = lst.legenda_c;
      $("lst-escala").innerHTML = `<span>${a} °C</span><span>${(a + b) / 2} °C</span><span>${b} °C</span>`;
      const cenas = lst.cenas_usadas.slice(0, 6).map(c => `${esc(c.satelite)} · ${esc(c.hora_local)} · órbita ${esc(c.orbita_ponto)}`).join("<br>") +
        (lst.cenas_usadas.length > 6 ? `<br><small>e mais ${lst.cenas_usadas.length - 6} cenas</small>` : "");
      ficha.innerHTML = `
        <dt>Período</dt><dd>${lst.periodo_inicio.split("-").reverse().join("/")} a ${lst.periodo_fim.split("-").reverse().join("/")}</dd>
        <dt>Satélites</dt><dd>${cenas || "—"}</dd>
        <dt>Sensor</dt><dd>TIRS, banda termal 10,9 µm</dd>
        <dt>Resolução</dt><dd>${lst.resolucao_nativa_m} m nativa · exibida a ~${lst.resolucao_exibicao_m} m</dd>
        <dt>Sem nuvem</dt><dd>${num(lst.cobertura_pct, 0)}% da área</dd>
        ${lst.estatisticas_c ? `<dt>Faixa</dt><dd>${num(lst.estatisticas_c.min, 1)} a ${num(lst.estatisticas_c.max, 1)} °C (mediana ${num(lst.estatisticas_c.mediana, 1)} °C)</dd>` : ""}
        <dt>Próxima</dt><dd>${esc(lst.proxima_atualizacao)}</dd>`;
      $("lst-nota").textContent = `${lst.observacao} Cada ponto usa a imagem sem nuvem mais recente do período; áreas sem cor ficaram cobertas por nuvem em todas as passagens.`;
      chk.disabled = false; opac.disabled = false;
    } else {
      chk.checked = false; chk.disabled = true; opac.disabled = true;
      ficha.innerHTML = `<dt>Estado</dt><dd>A composição quinzenal desta região ainda não foi gerada.</dd>`;
      $("lst-nota").textContent = "";
    }

    carregarCensipam(id, limites, s, carga);
  }

  /* ---------- nuvens: aviso e camada ---------- */
  function desenharNuvens(id, resumo) {
    const n = resumo.nuvens || { disponivel: false };
    const bloco = $("nuvens"), faixa = faixaNuvens.getContainer();
    if (nuvensCamada) mapa.removeLayer(nuvensCamada);
    nuvensCamada = null;
    bloco.hidden = false;
    bloco.className = "bloco nuvens " + (n.disponivel ? `nivel-${n.nivel || "baixo"}` : "nivel-sem");
    if (!n.disponivel) {
      bloco.innerHTML = `<div class="nuv-cab"><span class="nuv-icone" aria-hidden="true"></span><h2>Nuvens escondem focos</h2></div>
        <p>Não foi possível medir a cobertura de nuvens nesta coleta. Os satélites não enxergam fogo sob nuvens ou fumaça densa: em dias nublados, o número real de focos pode ser bem maior que o mostrado, e focos marcados como extintos podem continuar ativos.</p>`;
      faixa.hidden = true;
      return;
    }
    if (n.camada) {
      const [o, s_, l, nn] = n.camada.bbox;
      nuvensCamada = L.imageOverlay(`data/${id}/${n.camada.arquivo}?v=${encodeURIComponent(resumo.gerado_em)}`, [[s_, o], [nn, l]], { opacity: 1, interactive: false });
      if (n.nivel === "alto") nuvensCamada.addTo(mapa);
    }
    const ult = (n.passagens_viirs || [])[0];
    const pct = ult ? Math.round(ult.pct) : null;
    const titulo = {
      alto: "Céu encoberto: muitos focos podem estar escondidos",
      moderado: "Nuvens parciais: parte dos focos pode não aparecer",
      baixo: "Céu quase limpo na última passagem do VIIRS",
    }[n.nivel] || "Cobertura de nuvens";
    const passagens = (n.passagens_viirs || []).slice(0, 4).map(p =>
      `<li><span>${p.periodo === "dia" ? "Dia" : "Noite"} · ${horaLocal(p.passagem)}</span><b class="num">${Math.round(p.pct)}%</b></li>`).join("");
    const serie = n.serie || [];
    const barras = serie.map(x => `<i style="height:${Math.max(2, x.pct)}%" title="${horaLocal(x.hora)}: ${Math.round(x.pct)}% sob nuvens"></i>`).join("");
    bloco.innerHTML = `
      <div class="nuv-cab"><span class="nuv-icone" aria-hidden="true"></span><h2>${titulo}</h2></div>
      ${pct != null ? `<p class="nuv-destaque"><b class="num">${pct}%</b><span>da região estava sob nuvens na passagem do VIIRS de ${horaLocal(ult.passagem)}. Um foco em qualquer ponto da região tinha <b>${pct}% de chance</b> de estar escondido nessa passagem.</span></p>` : ""}
      ${n.cego_48h_pct != null && n.cego_48h_pct > 0 ? `<p><b>${num(n.cego_48h_pct, 0)}% da área</b> ficou coberta em todas as passagens do VIIRS das últimas 48 h: ali nenhum foco pôde ser visto.</p>` : ""}
      ${n.extintos_incertos ? `<p><b>${n.extintos_incertos} de ${n.extintos}</b> focos marcados como extintos tinham nuvem sobre o local nas passagens seguintes e podem continuar ativos (contorno pontilhado no mapa).</p>` : ""}
      <ul class="nuv-passagens">${passagens}</ul>
      ${serie.length ? `<div class="nuv-serie" role="img" aria-label="Cobertura de nuvens a cada 3 horas nas últimas 48 horas">${barras}</div>
        <div class="nuv-eixo"><span>${horaLocal(serie[0].hora)}</span><span>% da região sob nuvens, a cada 3 h</span><span>${horaLocal(serie[serie.length - 1].hora)}</span></div>` : ""}
      ${nuvensCamada ? `<button type="button" class="mais" id="ver-nuvens">${mapa.hasLayer(nuvensCamada) ? "Esconder" : "Mostrar"} nuvens no mapa</button>` : ""}
      <p class="nota">Máscara de nuvens do GOES-19 (pixel de 2 km). Fogo sob nuvens ou fumaça densa não é detectado por nenhum satélite.</p>`;
    const bt = $("ver-nuvens");
    if (bt) bt.addEventListener("click", () => {
      if (mapa.hasLayer(nuvensCamada)) mapa.removeLayer(nuvensCamada); else nuvensCamada.addTo(mapa);
      bt.textContent = `${mapa.hasLayer(nuvensCamada) ? "Esconder" : "Mostrar"} nuvens no mapa`;
    });
    if (pct != null && (n.nivel === "alto" || n.nivel === "moderado")) {
      faixa.className = `faixa-nuvens nivel-${n.nivel}`;
      faixa.innerHTML = `<span class="nuv-icone" aria-hidden="true"></span><span><b>${pct}% da região sob nuvens</b> na última passagem do VIIRS. Focos podem estar escondidos.</span>`;
      faixa.hidden = false;
    } else {
      faixa.hidden = true;
    }
  }

  /* ---------- Painel do Fogo (Censipam) ---------- */
  async function carregarCensipam(id, limites, sensor, carga) {
    for (const { grupo } of Object.values(censCamadas)) mapa.removeLayer(grupo);
    censCamadas = {};
    montarControleCamadas();
    const caixa = $("cens");
    caixa.innerHTML = `<p class="nota">Consultando o Painel do Fogo do Censipam…</p>`;
    let dados;
    try { dados = await CENSIPAM.carregar(id, limites); } catch (e) { dados = { origem: null, camadas: {}, erros: { geral: String(e) } }; }
    if (carga !== estado.carga) return;
    if (!dados.origem) {
      caixa.innerHTML = `<p class="nota">Não foi possível obter os dados do Censipam agora (o servidor não respondeu e ainda não há cópia da coleta). ` +
        `Veja direto no <a href="${CENSIPAM.PAINEL}" target="_blank" rel="noopener">Painel do Fogo ↗</a>.</p>`;
      return;
    }
    const muitos = Object.values(dados.camadas).reduce((n, l) => n + l.length, 0) > 400;
    censCamadas = CENSIPAM.camadasLeaflet(dados, sensor, muitos ? telaCanvas : undefined);
    for (const { grupo, cfg } of Object.values(censCamadas)) if (cfg.ligada) grupo.addTo(mapa);
    grupoEventos.eachLayer(l => l.bringToFront && l.bringToFront());
    montarControleCamadas();

    const r = CENSIPAM.resumo(dados, sensor);
    const quando = dados.origem === "ao vivo" ? `consultado ao vivo às ${horaCurta(dados.quando)}` : `cópia da coleta de ${horaLocal(dados.quando)}`;
    const linha = (rot, v, sigla, tipo) => `<div class="cens-linha"><span>${sigla ? `<i class="marca-cens ${tipo}"><span>${sigla}</span></i>` : `<i class="amostra-evento"></i>`}${rot}</span><b class="num">${v}</b></div>`;
    caixa.innerHTML = `
      <div class="cens-cont">
        <div><b class="num">${r.ativos}</b><small>eventos ativos</small></div>
        <div><b class="num">${num(r.area_ha, 0)}</b><small>ha em eventos ativos</small></div>
        ${r.perto50 != null ? `<div><b class="num">${r.perto50}</b><small>ativos até 50 km do sensor</small></div>` : `<div><b class="num">${r.eventos}</b><small>eventos no total</small></div>`}
      </div>
      <div class="cens-lista">
        ${linha("Alertas GOES de novo evento", r.goes_novos, "G", "alerta")}
        ${linha("Alertas GOES de evento em atividade", r.goes_ativ, "A", "alerta")}
        ${linha("Fogo perto de estrada", r.estradas, "E", "alerta")}
        ${linha("Fogo perto de área urbana", r.urbanas, "U", "alerta")}
        ${linha("Brigadas na região", r.brigadas, "B", "brigada")}
      </div>
      ${r.maiores.length ? `<div class="rotulo">Maiores eventos ativos</div><div class="cens-maiores">${r.maiores.map((f, i) => {
        const p = f.properties;
        return `<button type="button" class="evento-cens" data-i="${i}"><span>${esc(p.municipio || "—")}<small>${p.persistencia_dias != null ? `${num(p.persistencia_dias)} dias · ` : ""}${p.dt_maxima ? "último " + horaLocal(new Date(p.dt_maxima).toISOString()) : ""}</small></span><b class="num">${num(p.area_total_evento, 0)} ha</b></button>`;
      }).join("")}</div>` : ""}
      <p class="nota">Eventos e alertas do <a href="${CENSIPAM.PAINEL}" target="_blank" rel="noopener">Painel do Fogo</a> (Censipam), ${quando}. São calculados pelo Censipam com regras próprias e aparecem no mapa em lilás, separados dos focos deste site. Ligue ou desligue cada tipo no seletor de camadas.</p>`;
    caixa.querySelectorAll(".evento-cens").forEach(b => b.addEventListener("click", () => {
      const f = r.maiores[Number(b.dataset.i)];
      const grupo = censCamadas.mv_evento_filtro && censCamadas.mv_evento_filtro.grupo;
      if (!grupo) return;
      if (!mapa.hasLayer(grupo)) grupo.addTo(mapa);
      grupo.eachLayer(l => {
        if (l.feature === f) {
          if (l.getBounds) mapa.fitBounds(l.getBounds(), { maxZoom: 13, padding: [40, 40] }); else mapa.setView(l.getLatLng(), 12);
          l.openPopup();
        }
      });
      if (window.matchMedia("(max-width: 820px)").matches) $("mapa").scrollIntoView({ behavior: "smooth" });
    }));
  }

  trocarRegiao(inicial);
})();

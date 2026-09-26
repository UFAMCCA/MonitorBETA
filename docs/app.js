/* Mapa principal: focos agrupados, linha do tempo de 48 h, passagens e temperatura de superfície. */
(async function () {
  const estado = { filtro: "todos", sel: null, camadas: {}, eventos: [], agora: null };

  let resumo, focos, limites, lst = null;
  try {
    [resumo, focos, limites] = await Promise.all([
      carregarJSON("data/resumo.json"), carregarJSON("data/focos.geojson"), carregarJSON("data/limites.geojson"),
    ]);
  } catch (e) {
    document.getElementById("atualiz").textContent = "Não foi possível carregar os dados. Verifique se a coleta já rodou pelo menos uma vez.";
    console.error(e);
    return;
  }
  try { lst = await carregarJSON("data/lst.json"); } catch (e) { lst = null; }

  estado.agora = new Date(resumo.gerado_em);
  estado.eventos = focos.features;
  const inicio = new Date(estado.agora - 48 * 3.6e6);

  /* ---------- cabeçalho ---------- */
  const at = document.getElementById("atualiz");
  const proxima = (() => {
    const ordem = resumo.proximas_atualizacoes;
    return ordem[(ordem.indexOf(resumo.atualizacao) + 1) % ordem.length];
  })();
  at.innerHTML = `<span>Atualizado em <b>${horaLocal(resumo.gerado_em)}</b></span>` +
    resumo.proximas_atualizacoes.map(h => `<span class="chip${h === resumo.atualizacao ? " atual" : ""}" title="${esc(h === resumo.atualizacao ? resumo.atualizacao_descricao : "")}">${h}</span>`).join("") +
    `<span>próxima: ${proxima}</span>`;

  const avisos = [];
  if (resumo.dados_de_teste) avisos.push("Demonstração com dados sintéticos: os focos exibidos não são reais.");
  if (lst && lst.dados_de_teste) avisos.push("A camada de temperatura também é sintética.");
  for (const [fonte, st] of Object.entries(resumo.fontes_status || {})) {
    if (/^erro|^sem /.test(st)) avisos.push(`${fonte}: ${st}`);
  }
  if (avisos.length) { const av = document.getElementById("aviso"); av.textContent = avisos.join(" · "); av.hidden = false; }

  /* ---------- contadores ---------- */
  document.getElementById("n-ativos").textContent = resumo.eventos_ativos;
  document.getElementById("n-det-ativas").textContent = resumo.deteccoes_ativas;
  document.getElementById("n-extintos").textContent = resumo.eventos_extintos;
  document.getElementById("n-det").textContent = resumo.deteccoes_total;

  const munis = document.getElementById("munis");
  const totais = resumo.por_municipio, ativosM = resumo.ativos_por_municipio;
  const maxM = Math.max(1, ...Object.values(totais));
  munis.innerHTML = Object.keys(totais).length
    ? Object.entries(totais).map(([m, n]) => {
      const a = ativosM[m] || 0;
      return `<div class="muni"><span>${esc(m)}</span><span class="barra" title="${a} ativos, ${n - a} extintos" style="display:flex">` +
        `<i style="width:${a / maxM * 100}%"></i><i class="ext" style="width:${(n - a) / maxM * 100}%"></i></span><span>${n}</span></div>`;
    }).join("") + `<p class="nota">Focos por município em 48 h. Vermelho: ativos. Cinza: extintos.</p>`
    : `<p class="vazio">Nenhum foco na área nas últimas 48 horas.</p>`;

  /* ---------- mapa ---------- */
  const [o, s, l, n] = limites.bbox;
  const mapa = L.map("mapa", { zoomControl: true, preferCanvas: false, maxBounds: [[s - 1, o - 1], [n + 1, l + 1]], minZoom: 6 });
  mapa.fitBounds([[s, o], [n, l]], { padding: [10, 10] });

  const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" });
  const img = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 18, attribution: "Imagem © Esri" });
  img.addTo(mapa);

  // máscara fora da área de monitoramento
  const aneis = [];
  limites.features.forEach(f => {
    const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    polys.forEach(p => aneis.push(p[0].map(([x, y]) => [y, x])));
  });
  L.polygon([[[-60, -120], [-60, 0], [30, 0], [30, -120]], ...aneis], {
    stroke: false, fillColor: "#0e1512", fillOpacity: 0.45, interactive: false,
  }).addTo(mapa);
  const limCamada = L.geoJSON(limites, {
    style: { color: "#ffffff", weight: 1.4, opacity: 0.85, fill: false },
    onEachFeature: (f, lyr) => lyr.bindTooltip(f.properties.nome, { sticky: true, className: "" }),
  }).addTo(mapa);

  // nomes dos municípios fixos no mapa
  const nomesCamada = L.layerGroup(limites.features.map(f => {
    const pt = f.properties.rotulo ? [f.properties.rotulo[1], f.properties.rotulo[0]]
      : L.geoJSON(f).getBounds().getCenter();
    return L.marker(pt, {
      interactive: false, keyboard: false,
      icon: L.divIcon({ className: "nome-municipio", html: `<span>${esc(f.properties.nome)}</span>`, iconSize: null }),
    });
  })).addTo(mapa);
  const ajustarNomes = () => document.getElementById("mapa").classList.toggle("nomes-pequenos", mapa.getZoom() < 8);
  mapa.on("zoomend", ajustarNomes); ajustarNomes();

  // temperatura de superfície
  let lstCamada = null;
  if (lst) {
    const [lo, ls, ll, ln] = lst.bbox;
    lstCamada = L.imageOverlay("data/lst.png", [[ls, lo], [ln, ll]], { opacity: 0.75, interactive: false });
  }

  const grupoEventos = L.layerGroup().addTo(mapa);
  L.control.layers({ "Imagem de satélite": img, "Mapa de ruas": osm },
    Object.assign({ "Limites municipais": limCamada, "Nomes dos municípios": nomesCamada, "Focos": grupoEventos }, lstCamada ? { "Temperatura da superfície": lstCamada } : {}),
    { collapsed: true }).addTo(mapa);

  function estilo(p) {
    const idade = horasDesde(p.ultima_deteccao, estado.agora);
    const cor = corIdade(idade);
    return {
      color: cor, fillColor: cor, fillOpacity: opacConf(p.confianca), opacity: 0.95,
      weight: p.status === "ativo" ? 2 : 1.6, dashArray: p.status === "ativo" ? null : "5 4",
    };
  }

  function popup(p) {
    const outros = p.satelites.filter(x => x !== p.satelite_primeira).map(nomeSat);
    return `<div class="pop">
      <h3>${esc(p.municipio || "Área monitorada")}</h3>
      <span class="estado ${p.status}"><span class="ponto"></span>${textoStatus(p)}</span>
      <dl>
        <dt>Detectado em</dt><dd>${horaLocal(p.primeira_deteccao)}</dd>
        <dt>Última detecção</dt><dd>${horaLocal(p.ultima_deteccao)}</dd>
        <dt>Extinção</dt><dd>${p.status === "ativo" ? "ainda ativo" : textoExtincao(p)}</dd>
        <dt>Duração</dt><dd>${duracao(p.duracao_h)}</dd>
        <dt>Satélite</dt><dd>${esc(nomeSat(p.satelite_primeira))}${outros.length ? `<br><small>também: ${esc(outros.join(", "))}</small>` : ""}</dd>
      </dl>
      <a class="abrir" href="detalhe.html#${esc(p.id)}" target="_blank" rel="noopener">Detalhes técnicos ↗</a>
    </div>`;
  }

  const porId = {};
  function desenhar() {
    grupoEventos.clearLayers();
    for (const f of estado.eventos) {
      const p = f.properties;
      if (estado.filtro !== "todos" && p.status !== estado.filtro) continue;
      const st = estilo(p);
      const poli = L.geoJSON(f, { style: st });
      const idade = horasDesde(p.ultima_deteccao, estado.agora);
      const marcador = L.circleMarker([p.lat, p.lon], {
        ...st, radius: 5 + 2.2 * Math.sqrt(p.n_pixels), fillOpacity: Math.max(0.35, st.fillOpacity),
        className: p.status === "ativo" && idade <= 6 ? "pulso" : "",
      });
      const g = L.featureGroup([poli, marcador]).bindPopup(popup(p), { maxWidth: 300 });
      g.on("popupopen", () => marcarLinha(p.id));
      g.addTo(grupoEventos);
      porId[p.id] = g;
    }
  }
  desenhar();

  /* ---------- legenda ---------- */
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
      <div class="rotulo" style="margin-top:4px">Preenchimento</div>
      <div class="linha">mais opaco = maior confiança</div>
      <div class="linha">área = pixels reais do sensor; círculo maior = mais pixels</div>
    </details>`;
    L.DomEvent.disableClickPropagation(d);
    return d;
  };
  legenda.addTo(mapa);

  /* ---------- linha do tempo ---------- */
  const pos = iso => Math.max(0, Math.min(100, (new Date(iso) - inicio) / (estado.agora - inicio) * 100));
  const eixo = document.getElementById("eixo");
  const marcas = [];
  const t0 = new Date(inicio); t0.setUTCMinutes(0, 0, 0);
  for (let t = new Date(t0); t <= estado.agora; t = new Date(+t + 3.6e6)) {
    const hLocal = Number(fmtHoraCurta.format(t).slice(0, 2));
    if (t > inicio && hLocal % 12 === 0) marcas.push(t);
  }
  eixo.innerHTML = marcas.map(t => `<span style="left:${pos(t.toISOString())}%">${fmtDia.format(t)} ${fmtHoraCurta.format(t).slice(0, 2)}h</span>`).join("");

  const lista = document.getElementById("eventos");
  function desenharLista() {
    const evs = estado.eventos.filter(f => estado.filtro === "todos" || f.properties.status === estado.filtro);
    if (!evs.length) { lista.innerHTML = `<p class="vazio">Nenhum foco neste filtro.</p>`; return; }
    lista.innerHTML = evs.map(f => {
      const p = f.properties;
      const cor = corIdade(horasDesde(p.ultima_deteccao, estado.agora));
      const a = pos(p.primeira_deteccao), b = pos(p.ultima_deteccao);
      let fim = "";
      if (p.status === "extinto_estimado") {
        const c = pos(p.extincao_ate);
        fim = `<span class="apagou" style="left:${b}%;width:${Math.max(0.6, c - b)}%"></span><span class="fim" style="left:${c}%"></span>`;
      } else {
        fim = `<span class="segue" style="left:${b}%;width:${Math.max(2, 100 - b)}%;background:linear-gradient(90deg, ${cor}, transparent)"></span>`;
      }
      return `<button type="button" class="evento" data-id="${p.id}" title="${esc(textoStatus(p))} · ${horaLocal(p.primeira_deteccao)} → ${p.status === "ativo" ? "agora" : horaLocal(p.extincao_ate)}">
        <span class="nome">${esc(p.municipio || "—")}<small>${horaCurta(p.primeira_deteccao)} · ${p.n_pixels} px · ${p.status === "ativo" ? "ativo" : "extinto"}</small></span>
        <span class="trilho"><span class="queima" style="left:${a}%;width:${Math.max(0.8, b - a)}%;background:${cor}"></span>${fim}</span>
      </button>`;
    }).join("");
  }
  desenharLista();

  function marcarLinha(id) {
    estado.sel = id;
    lista.querySelectorAll(".evento").forEach(el => el.classList.toggle("sel", el.dataset.id === id));
  }
  lista.addEventListener("click", ev => {
    const b = ev.target.closest(".evento"); if (!b) return;
    const g = porId[b.dataset.id]; if (!g) return;
    mapa.fitBounds(g.getBounds(), { maxZoom: 13, padding: [40, 40] });
    g.openPopup(); marcarLinha(b.dataset.id);
    if (window.matchMedia("(max-width: 820px)").matches) document.getElementById("mapa").scrollIntoView({ behavior: "smooth" });
  });

  document.querySelectorAll(".filtros button").forEach(bt => bt.addEventListener("click", () => {
    estado.filtro = bt.dataset.filtro;
    document.querySelectorAll(".filtros button").forEach(x => x.setAttribute("aria-pressed", String(x === bt)));
    desenhar(); desenharLista();
  }));

  /* ---------- passagens ---------- */
  const tb = document.getElementById("passagens");
  const pass = [...resumo.passagens].sort((x, y) => y.inicio.localeCompare(x.inicio));
  tb.innerHTML = pass.length ? pass.map(p => `<tr>
      <td>${horaLocal(p.inicio)}</td><td>${esc(nomeSat(p.satelite))}</td>
      <td>${p.resolucao_km < 1 ? Math.round(p.resolucao_km * 1000) + " m" : num(p.resolucao_km, 1) + " km"}</td>
      <td>${p.deteccoes_na_area}</td></tr>`).join("")
    : `<tr><td colspan="4" class="vazio">Nenhuma passagem registrada.</td></tr>`;
  document.getElementById("nota-goes").textContent = resumo.goes_ultima_deteccao_regional
    ? `GOES-19 observa a região a cada 10 min (pixel ~2 km). Última detecção regional: ${horaLocal(resumo.goes_ultima_deteccao_regional)}. Horário da passagem polar estimado pelas detecções na região.`
    : "GOES-19 observa a região a cada 10 min, mas não registrou focos no período.";

  /* ---------- satélites ---------- */
  document.getElementById("sat-ficha").innerHTML = Object.entries(resumo.satelites).map(([k, v]) =>
    `<dt>${esc(nomeSat(k))}</dt><dd>${esc(v.horario)} · ${v.pixel_km < 1 ? Math.round(v.pixel_km * 1000) + " m" : v.pixel_km + " km"} · ${esc(v.papel)}</dd>`).join("") +
    Object.entries(resumo.atualizacoes || {}).map(([h, d]) => `<dt>Atualização ${h}</dt><dd>${esc(d)}</dd>`).join("");

  /* ---------- temperatura ---------- */
  const ficha = document.getElementById("lst-ficha");
  const chk = document.getElementById("lst-ligado"), opac = document.getElementById("lst-opac");
  if (lst && lstCamada) {
    const [a, b] = lst.legenda_c;
    document.getElementById("lst-escala").innerHTML = `<span>${a} °C</span><span>${(a + b) / 2} °C</span><span>${b} °C</span>`;
    const cenas = lst.cenas_usadas.map(c => `${esc(c.satelite)} · ${esc(c.hora_local)} · órbita ${esc(c.orbita_ponto)}`).join("<br>");
    ficha.innerHTML = `
      <dt>Período</dt><dd>${lst.periodo_inicio.split("-").reverse().join("/")} a ${lst.periodo_fim.split("-").reverse().join("/")}</dd>
      <dt>Satélites</dt><dd>${cenas || "—"}</dd>
      <dt>Sensor</dt><dd>TIRS, banda termal 10,9 µm</dd>
      <dt>Resolução</dt><dd>${lst.resolucao_nativa_m} m nativa · exibida a ~${lst.resolucao_exibicao_m} m</dd>
      <dt>Sem nuvem</dt><dd>${num(lst.cobertura_pct, 0)}% da área</dd>
      ${lst.estatisticas_c ? `<dt>Faixa</dt><dd>${num(lst.estatisticas_c.min, 1)} a ${num(lst.estatisticas_c.max, 1)} °C (mediana ${num(lst.estatisticas_c.mediana, 1)} °C)</dd>` : ""}
      <dt>Próxima</dt><dd>${esc(lst.proxima_atualizacao)}</dd>`;
    ficha.insertAdjacentHTML("afterend", `<p class="nota">${esc(lst.observacao)} Cada ponto usa a imagem sem nuvem mais recente do período; áreas sem cor ficaram cobertas por nuvem em todas as passagens.</p>`);
    chk.addEventListener("change", () => chk.checked ? lstCamada.addTo(mapa) : mapa.removeLayer(lstCamada));
    opac.addEventListener("input", () => lstCamada.setOpacity(Number(opac.value)));
    mapa.on("overlayadd overlayremove", e => { if (e.layer === lstCamada) chk.checked = e.type === "overlayadd"; });
  } else {
    chk.disabled = true; opac.disabled = true;
    ficha.innerHTML = `<dt>Estado</dt><dd>A primeira composição quinzenal ainda não foi gerada.</dd>`;
  }
})();

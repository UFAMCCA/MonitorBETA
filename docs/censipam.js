/* Painel do Fogo (Censipam): eventos de fogo, alertas e brigadas.
   Busca ao vivo no GeoServer do Censipam; se falhar, usa a cópia gravada na
   última coleta (data/<regiao>/censipam.json). */
const CENSIPAM = (() => {
  const WFS = "https://panorama.sipam.gov.br/geoserver/painel_do_fogo/wfs";
  const PAINEL = "https://panorama.sipam.gov.br/painel-do-fogo/";
  const CAMADAS = {
    mv_evento_filtro: { nome: "Eventos de fogo", sigla: "", tipo: "evento", ligada: true },
    mv_alertas_goes_novos_eventos: { nome: "Alerta GOES: novo evento", sigla: "G", tipo: "alerta", ligada: true },
    mv_alertas_goes_atividade_eventos: { nome: "Alerta GOES: evento em atividade", sigla: "A", tipo: "alerta", ligada: false },
    mv_alertas_estradas: { nome: "Alerta: fogo perto de estrada", sigla: "E", tipo: "alerta", ligada: true },
    mv_alertas_areas_urbanizadas: { nome: "Alerta: fogo perto de área urbana", sigla: "U", tipo: "alerta", ligada: true },
    tb_brigada_pto: { nome: "Brigadas de incêndio", sigla: "B", tipo: "brigada", ligada: false },
  };
  /* Rótulos dos campos conhecidos; os demais aparecem em "Todos os campos". */
  const CAMPOS = {
    id_evento: "Evento", municipio: "Município", estado: "UF", id_status_evento: "Situação",
    dt_minima: "Primeira detecção", dt_maxima: "Última detecção", persistencia_dias: "Persistência",
    area_total_evento: "Área total", qtd_deteccoes: "Detecções", total_power: "Potência total (FRP)",
    n_recorrencia: "Recorrências", densidade: "Densidade", nomenclatura_rodovia: "Rodovia",
    km_inicial: "Km inicial", km_final: "Km final", distancia: "Distância",
    id_evento_mais_proximo: "Evento mais próximo", nome: "Nome", nome_brif: "Brigada",
    mun_brif: "Município da brigada", tipo_brif: "Tipo", total_brif: "Brigadistas",
    orgao_responsavel: "Órgão responsável", viaturas: "Viaturas", barco: "Barcos",
  };

  async function buscar(camada, bbox, ms = 25000) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), ms);
    const q = new URLSearchParams({
      service: "WFS", version: "1.0.0", request: "GetFeature", outputFormat: "application/json",
      typeName: `painel_do_fogo:${camada}`, maxFeatures: "5000", bbox: bbox.map(v => v.toFixed(4)).join(","),
    });
    try {
      const r = await fetch(`${WFS}?${q}`, { signal: ctl.signal });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const fc = await r.json();
      return fc.features || [];
    } finally { clearTimeout(t); }
  }

  /* Ponto representativo de uma geometria (para filtrar pela região e medir distância). */
  function ponto(g) {
    if (!g) return null;
    if (g.type === "Point") return g.coordinates;
    if (g.type === "MultiPoint") return g.coordinates[0];
    const anel = g.type === "Polygon" ? g.coordinates[0] : g.type === "MultiPolygon" ? g.coordinates[0][0]
      : g.type === "LineString" ? g.coordinates : g.type === "MultiLineString" ? g.coordinates[0] : null;
    if (!anel || !anel.length) return null;
    let x = 0, y = 0;
    anel.forEach(c => { x += c[0]; y += c[1]; });
    return [x / anel.length, y / anel.length];
  }
  function dentroAnel([x, y], anel) {
    let d = false;
    for (let i = 0, j = anel.length - 1; i < anel.length; j = i++) {
      const [xi, yi] = anel[i], [xj, yj] = anel[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) d = !d;
    }
    return d;
  }

  async function carregar(regiao, limites) {
    const bbox = limites.bbox;
    const aneis = [];
    limites.features.forEach(f => {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      polys.forEach(p => aneis.push(p[0]));
    });
    const naRegiao = f => { const p = ponto(f.geometry); return p && aneis.some(a => dentroAnel(p, a)); };

    const nomes = Object.keys(CAMADAS);
    const vivos = await Promise.allSettled(nomes.map(n => buscar(n, bbox)));
    let camadas = {}, origem = null, quando = new Date().toISOString(), erros = {};
    vivos.forEach((r, i) => {
      if (r.status === "fulfilled") camadas[nomes[i]] = r.value;
      else erros[nomes[i]] = String(r.reason && r.reason.message || r.reason);
    });
    if (Object.keys(camadas).length) {
      origem = "ao vivo";
    } else {
      try {
        const copia = await carregarJSON(`data/${regiao}/censipam.json`);
        for (const [n, fc] of Object.entries(copia.camadas || {})) camadas[n] = fc.features || [];
        if (Object.keys(camadas).length) { origem = "cópia"; quando = copia.gerado_em; }
      } catch (e) { /* sem cópia */ }
    }
    for (const n of Object.keys(camadas)) camadas[n] = camadas[n].filter(naRegiao);
    return { origem, quando, camadas, erros };
  }

  const ativo = p => p.id_status_evento === 1 || p.id_status_evento === "1" || /^ativ/i.test(String(p.status || p.situacao || ""));

  function formatar(k, v) {
    if (v == null || v === "") return "—";
    if (/^dt_|data|hora/i.test(k) && !Number.isNaN(Date.parse(v))) return horaLocal(new Date(v).toISOString());
    if (k === "area_total_evento") return `${num(v, v < 10 ? 1 : 0)} ha`;
    if (k === "persistencia_dias") return `${num(v)} ${Number(v) === 1 ? "dia" : "dias"}`;
    if (k === "total_power") return `${num(v, 1)} MW`;
    if (k === "id_status_evento") return ativo({ id_status_evento: v }) ? "ativo" : `inativo (código ${esc(v)})`;
    if (typeof v === "number") return num(v, Number.isInteger(v) ? 0 : 2);
    return esc(v);
  }

  function popup(camada, f, sensor) {
    const p = f.properties || {};
    const conhecidos = Object.keys(CAMPOS).filter(k => k in p && p[k] != null && p[k] !== "");
    const outros = Object.keys(p).filter(k => !(k in CAMPOS) && !/^(geom|the_geom|bbox)$/i.test(k));
    let dist = "";
    if (sensor) {
      const pt = ponto(f.geometry);
      if (pt) dist = `<dt>Distância do sensor</dt><dd>${num(km(sensor.lat, sensor.lon, pt[1], pt[0]), 0)} km</dd>`;
    }
    const titulo = CAMADAS[camada].tipo === "evento"
      ? `Evento ${esc(p.id_evento ?? "")}` : CAMADAS[camada].nome;
    return `<div class="pop">
      <span class="olho-cens">Painel do Fogo · Censipam</span>
      <h3>${titulo}</h3>
      ${CAMADAS[camada].tipo === "evento" ? `<span class="estado ${ativo(p) ? "ativo" : "extinto_estimado"}"><span class="ponto"></span>${ativo(p) ? "Ativo" : "Inativo"}</span>` : ""}
      <dl>${conhecidos.filter(k => k !== "id_evento" && k !== "id_status_evento").map(k => `<dt>${CAMPOS[k]}</dt><dd>${formatar(k, p[k])}</dd>`).join("")}${dist}</dl>
      ${outros.length ? `<details class="campos"><summary>Todos os campos</summary><dl>${outros.map(k => `<dt class="mono">${esc(k)}</dt><dd>${formatar(k, p[k])}</dd>`).join("")}</dl></details>` : ""}
      <a class="abrir" href="${PAINEL}" target="_blank" rel="noopener">Abrir o Painel do Fogo ↗</a>
    </div>`;
  }

  function km(lat1, lon1, lat2, lon2) {
    const r = 6371, p1 = lat1 * Math.PI / 180, p2 = lat2 * Math.PI / 180;
    const dp = p2 - p1, dl = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * r * Math.asin(Math.sqrt(a));
  }

  /* Cria uma camada Leaflet por tipo de dado. */
  function camadasLeaflet(dados, sensor, renderer) {
    const out = {};
    for (const [n, feats] of Object.entries(dados.camadas)) {
      const cfg = CAMADAS[n];
      if (!cfg) continue;
      const grupo = L.geoJSON({ type: "FeatureCollection", features: feats }, {
        style: f => {
          const a = ativo(f.properties || {});
          return { color: "#c9a7ff", weight: a ? 2 : 1.2, opacity: a ? 1 : 0.6, dashArray: a ? null : "3 4",
                   fillColor: "#a77bff", fillOpacity: a ? 0.18 : 0.06 };
        },
        renderer,
        pointToLayer: (f, ll) => cfg.tipo === "evento"
          ? L.circleMarker(ll, { radius: 6, color: "#c9a7ff", weight: 2, fillColor: "#a77bff", fillOpacity: 0.35, renderer })
          : L.marker(ll, { icon: L.divIcon({ className: `marca-cens ${cfg.tipo}`, html: `<span>${cfg.sigla}</span>`, iconSize: [18, 18], iconAnchor: [9, 9] }), title: cfg.nome }),
        onEachFeature: (f, lyr) => lyr.bindPopup(() => popup(n, f, sensor), { maxWidth: 320 }),
      });
      out[n] = { grupo, cfg };
    }
    return out;
  }

  function resumo(dados, sensor) {
    const ev = dados.camadas.mv_evento_filtro || [];
    const ativos = ev.filter(f => ativo(f.properties || {}));
    const area = ativos.reduce((s, f) => s + (Number(f.properties.area_total_evento) || 0), 0);
    let perto = null;
    if (sensor) perto = ativos.filter(f => { const p = ponto(f.geometry); return p && km(sensor.lat, sensor.lon, p[1], p[0]) <= 50; }).length;
    const conta = n => (dados.camadas[n] || []).length;
    return {
      eventos: ev.length, ativos: ativos.length, area_ha: area, perto50: perto,
      goes_novos: conta("mv_alertas_goes_novos_eventos"), goes_ativ: conta("mv_alertas_goes_atividade_eventos"),
      estradas: conta("mv_alertas_estradas"), urbanas: conta("mv_alertas_areas_urbanizadas"), brigadas: conta("tb_brigada_pto"),
      maiores: [...ativos].sort((a, b) => (b.properties.area_total_evento || 0) - (a.properties.area_total_evento || 0)).slice(0, 5),
    };
  }

  return { CAMADAS, PAINEL, carregar, camadasLeaflet, resumo, ativo, ponto };
})();

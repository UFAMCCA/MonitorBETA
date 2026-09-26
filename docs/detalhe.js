/* Página técnica de um foco: abre em nova aba a partir do popup do mapa (detalhe.html#ID). */
(async function () {
  const pag = document.getElementById("pagina");
  const id = decodeURIComponent((location.hash || "").slice(1)) || new URLSearchParams(location.search).get("id");
  let resumo, focos, dets;
  try {
    [resumo, focos, dets] = await Promise.all([
      carregarJSON("data/resumo.json"), carregarJSON("data/focos.geojson"), carregarJSON("data/deteccoes.json"),
    ]);
  } catch (e) {
    pag.innerHTML = `<p class="vazio">Não foi possível carregar os dados (${esc(e.message)}).</p>`;
    return;
  }
  const f = focos.features.find(x => x.properties.id === id);
  if (!f) {
    pag.innerHTML = `<div class="cabecalho"><h1>Foco não encontrado</h1>
      <p>O foco <span class="mono">${esc(id || "(sem código)")}</span> não está na atualização de ${horaLocal(resumo.gerado_em)}. Os dados cobrem só as últimas 48 horas.</p>
      <p><a href="index.html">Voltar ao mapa</a></p></div>`;
    return;
  }
  const p = f.properties;
  const lista = (dets[id] || []).slice().sort((a, b) => a.hora.localeCompare(b.hora));
  const agora = new Date(resumo.gerado_em);
  document.title = `Foco em ${p.municipio || "área monitorada"}`;

  const max = (campo) => { const v = lista.map(d => d[campo]).filter(x => x != null); return v.length ? Math.max(...v) : null; };
  const min = (campo) => { const v = lista.map(d => d[campo]).filter(x => x != null); return v.length ? Math.min(...v) : null; };
  const biomas = [...new Set(lista.map(d => d.bioma).filter(Boolean))];
  const reais = lista.filter(d => d.pixel_real).length;
  const t = p.temp_superficie;
  const cor = corIdade(horasDesde(p.ultima_deteccao, agora));

  const linhasPass = (p.passagens_sem_deteccao || []).slice(0, 8).map(x =>
    `<dt>${horaLocal(x.hora)}</dt><dd>${esc(nomeSat(x.satelite))}</dd>`).join("");

  pag.innerHTML = `
  <div class="cabecalho">
    <span class="rotulo">Foco <span class="mono">${esc(p.id)}</span> · dados de ${horaLocal(resumo.gerado_em)} (horário de Manaus)</span>
    <h1>${esc(p.municipio || "Área monitorada")}</h1>
    <div><span class="pop"><span class="estado ${p.status}"><span class="ponto"></span>${textoStatus(p)}</span></span>
      <span class="mono">${num(p.lat, 5)}, ${num(p.lon, 5)}</span></div>
    ${resumo.dados_de_teste ? `<p class="aviso" style="border-radius:6px;margin:4px 0 0">Demonstração com dados sintéticos: este foco não é real.</p>` : ""}
  </div>

  <div class="grade-cartoes">
    <section class="cartao">
      <h2>Linha do tempo</h2>
      <dl class="ficha">
        <dt>Primeira detecção</dt><dd>${horaLocal(p.primeira_deteccao)} <span class="mono">(${horaUTC(p.primeira_deteccao)})</span></dd>
        <dt>Última detecção</dt><dd>${horaLocal(p.ultima_deteccao)} <span class="mono">(${horaUTC(p.ultima_deteccao)})</span></dd>
        <dt>Extinção estimada</dt><dd>${p.status === "ativo" ? "ainda ativo" : textoExtincao(p)}</dd>
        <dt>Duração observada</dt><dd>${duracao(p.duracao_h)}</dd>
        <dt>Critério</dt><dd>${esc(p.criterio)}</dd>
      </dl>
    </section>

    <section class="cartao">
      <h2>Detecção</h2>
      <dl class="ficha">
        <dt>Satélites</dt><dd>${esc(p.satelites.map(nomeSat).join(", "))}</dd>
        <dt>Detecções</dt><dd>${p.n_deteccoes}</dd>
        <dt>Pixels (máx. numa passagem)</dt><dd>${p.n_pixels}</dd>
        <dt>Confiança máxima</dt><dd>${esc(NOME_CONF[p.confianca] || "não informada")}</dd>
        <dt>FRP máxima</dt><dd>${num(p.frp_max, 1, " MW")}</dd>
        <dt>Tamanho do pixel</dt><dd>${reais} de ${lista.length} com tamanho real (FIRMS)</dd>
        <dt>Área no mapa</dt><dd>pixels do ${esc(p.area_pelo_sensor || "sensor")}, o mais fino que detectou</dd>
      </dl>
    </section>

    <section class="cartao">
      <h2>Ambiente</h2>
      <dl class="ficha">
        <dt>Temperatura da superfície</dt><dd>${t ? `${num(t.valor_c, 1)} °C` : "sem dado (nuvem ou fora do período)"}</dd>
        ${t && t.cena ? `<dt>Imagem</dt><dd>${esc(t.cena.satelite)} TIRS · ${esc(t.cena.hora_local)} · 100 m</dd>` : ""}
        <dt>Risco de fogo (INPE)</dt><dd>${num(max("risco_fogo"), 2)}</dd>
        <dt>Dias sem chuva</dt><dd>${num(max("dias_sem_chuva"))}</dd>
        <dt>Precipitação</dt><dd>${num(min("precipitacao_mm"), 1, " mm")}</dd>
        <dt>Bioma</dt><dd>${esc(biomas.join(", ") || "—")}</dd>
      </dl>
      <p class="nota">Risco de fogo é um índice meteorológico do INPE (0 a 1) e não a probabilidade de o foco ser uma queimada.</p>
    </section>

    <section class="cartao">
      <h2>Passagens sem detecção depois do último registro</h2>
      ${linhasPass ? `<dl class="ficha">${linhasPass}</dl>` : `<p class="nota">Nenhuma passagem polar posterior no período.</p>`}
      <p class="nota">Nuvem ou fumaça densa também impede a detecção, então uma passagem sem registro não prova que o fogo acabou.</p>
    </section>
  </div>

  <section class="cartao grafico">
    <h2>Detecções por satélite</h2>
    <div id="grafico"></div>
    <p class="nota">Cada marca é uma detecção; tamanho proporcional à FRP (potência radiativa do fogo) quando informada.</p>
  </section>

  <section class="cartao">
    <h2>Todas as detecções (${lista.length})</h2>
    <div class="caixa-rolagem">
      <table class="tabela">
        <thead><tr><th>Hora local</th><th>UTC</th><th>Satélite</th><th>Lat</th><th>Lon</th><th>Confiança</th><th>FRP (MW)</th>
          <th>Brilho (K)</th><th>Pixel (km)</th><th>Período</th><th>Risco</th><th>Dias s/ chuva</th><th>Fonte</th></tr></thead>
        <tbody>${lista.map(d => `<tr>
          <td>${horaLocal(d.hora)}</td><td class="mono">${d.hora.slice(11, 16)}</td><td>${esc(nomeSat(d.satelite))}</td>
          <td class="mono">${num(d.lat, 4)}</td><td class="mono">${num(d.lon, 4)}</td>
          <td>${esc(d.confianca ? `${d.confianca}${d.confianca_bruta && !/^[lnh]$/i.test(d.confianca_bruta) ? ` (${d.confianca_bruta}%)` : ""}` : "—")}</td>
          <td class="n">${num(d.frp_mw, 1)}</td><td class="n">${num(d.brilho_k, 1)}</td>
          <td class="n">${num(d.scan_km, 2)} × ${num(d.track_km, 2)}${d.pixel_real ? "" : " *"}</td>
          <td>${esc(d.periodo || "—")}</td><td class="n">${num(d.risco_fogo, 2)}</td><td class="n">${num(d.dias_sem_chuva)}</td>
          <td>${esc(d.fontes.join(" + "))}</td></tr>`).join("")}</tbody>
      </table>
    </div>
    <p class="nota">* tamanho nominal do sensor (a fonte não informou o tamanho real). Brilho: canal I4 (VIIRS) ou 21/22 (MODIS).</p>
  </section>

  <p class="nota">Ver no <a href="https://firms.modaps.eosdis.nasa.gov/map/#d:48hrs;@${p.lon},${p.lat},13.0z" target="_blank" rel="noopener">mapa do FIRMS</a> ·
    <a href="https://terrabrasilis.dpi.inpe.br/queimadas/bdqueimadas/" target="_blank" rel="noopener">BDQueimadas</a> ·
    <a href="https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=14/${p.lat}/${p.lon}" target="_blank" rel="noopener">OpenStreetMap</a></p>`;

  /* gráfico: detecções no tempo, uma linha por satélite */
  const sats = [...new Set(lista.map(d => d.satelite))];
  const W = 900, lh = 30, topo = 10, esq = 130, dir = 16, H = topo + sats.length * lh + 28;
  const t0 = Math.min(new Date(p.primeira_deteccao), new Date(p.extincao_ate || p.ultima_deteccao)) - 3.6e6;
  const t1 = Math.max(+new Date(p.extincao_ate || 0), +new Date(p.ultima_deteccao)) + 3.6e6;
  const x = tt => esq + (tt - t0) / (t1 - t0) * (W - esq - dir);
  const frpMax = Math.max(1, ...lista.map(d => d.frp_mw || 0));
  const passo = [1, 2, 3, 6, 12, 24].find(h => (t1 - t0) / 3.6e6 / h <= 8) || 24;
  let ticks = "";
  for (let tt = Math.ceil(t0 / (passo * 3.6e6)) * passo * 3.6e6; tt <= t1; tt += passo * 3.6e6) {
    ticks += `<line class="grade-linha" x1="${x(tt)}" x2="${x(tt)}" y1="${topo - 4}" y2="${H - 22}"/>` +
      `<text x="${x(tt)}" y="${H - 6}" text-anchor="middle">${fmtDia.format(new Date(tt))} ${fmtHoraCurta.format(new Date(tt))}</text>`;
  }
  const faixa = p.status === "extinto_estimado"
    ? `<rect x="${x(new Date(p.extincao_apos))}" y="${topo - 4}" width="${Math.max(1, x(new Date(p.extincao_ate)) - x(new Date(p.extincao_apos)))}" height="${H - 18 - topo}" fill="${corVar("--f3")}" fill-opacity="0.16"/>
       <text x="${x(new Date(p.extincao_ate)) - 4}" y="${topo + 8}" text-anchor="end">extinção estimada</text>` : "";
  const linhas = sats.map((s, i) => {
    const y = topo + i * lh + lh / 2;
    const pts = lista.filter(d => d.satelite === s).map(d =>
      `<circle cx="${x(new Date(d.hora)).toFixed(1)}" cy="${y}" r="${(3 + 7 * Math.sqrt((d.frp_mw || frpMax * 0.15) / frpMax)).toFixed(1)}" fill="${cor}" fill-opacity="${opacConf(d.confianca)}" stroke="${cor}"><title>${horaLocal(d.hora)} · FRP ${num(d.frp_mw, 1)} MW</title></circle>`).join("");
    return `<line class="grade-linha" x1="${esq}" x2="${W - dir}" y1="${y}" y2="${y}"/><text x="${esq - 8}" y="${y + 4}" text-anchor="end">${esc(nomeSat(s))}</text>${pts}`;
  }).join("");
  document.getElementById("grafico").innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Detecções por satélite ao longo do tempo">${ticks}${faixa}${linhas}</svg>`;
})();

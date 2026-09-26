/* Funções compartilhadas entre o mapa e a página de detalhes. */
const FUSO = "America/Manaus";

const fmtHora = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const fmtHoraCurta = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit" });
const fmtDia = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, day: "2-digit", month: "2-digit" });

function data(iso) { return iso ? new Date(iso) : null; }
function horaLocal(iso) { return iso ? fmtHora.format(new Date(iso)).replace(",", "") : "—"; }
function horaCurta(iso) { return iso ? fmtHoraCurta.format(new Date(iso)) : "—"; }
function horaUTC(iso) { return iso ? iso.slice(11, 16) + " UTC" : "—"; }

function duracao(h) {
  if (h == null) return "—";
  if (h < 1 / 60) return "uma única passagem";
  if (h < 1) return `${Math.round(h * 60)} min`;
  const hh = Math.floor(h), mm = Math.round((h - hh) * 60);
  return mm ? `${hh} h ${mm} min` : `${hh} h`;
}

function horasDesde(iso, agora) { return (agora - new Date(iso)) / 3.6e6; }

/* Cor pela idade da última detecção */
const FAIXAS_IDADE = [
  { ate: 6, cor: "--f0", nome: "até 6 h" },
  { ate: 12, cor: "--f1", nome: "6 a 12 h" },
  { ate: 24, cor: "--f2", nome: "12 a 24 h" },
  { ate: 999, cor: "--f3", nome: "24 a 48 h" },
];
function corVar(nome) { return getComputedStyle(document.documentElement).getPropertyValue(nome).trim(); }
function faixaIdade(horas) { return FAIXAS_IDADE.find(f => horas <= f.ate); }
function corIdade(horas) { return corVar(faixaIdade(horas).cor); }

/* Opacidade pela confiança */
const OPAC_CONF = { alta: 0.78, nominal: 0.52, baixa: 0.28 };
function opacConf(c) { return OPAC_CONF[c] ?? 0.45; }
const NOME_CONF = { alta: "alta", nominal: "nominal", baixa: "baixa" };

const NOME_SAT = {
  "NOAA-20": "NOAA-20 (VIIRS)", "NOAA-21": "NOAA-21 (VIIRS)", "GOES-19": "GOES-19 (ABI)",
  "TERRA": "Terra (MODIS)", "AQUA": "Aqua (MODIS)", "METOP-B": "MetOp-B (AVHRR)", "METOP-C": "MetOp-C (AVHRR)",
};
function nomeSat(s) { return NOME_SAT[s] || s; }

function textoStatus(p) {
  return p.status === "ativo" ? "Ativo" : "Extinto (estimado)";
}
function textoExtincao(p) {
  if (p.status !== "extinto_estimado") return "—";
  return `entre ${horaCurta(p.extincao_apos)} e ${horaLocal(p.extincao_ate)}`;
}
function num(v, casas = 0, sufixo = "") {
  return v == null || Number.isNaN(v) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }) + sufixo;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
async function carregarJSON(caminho) {
  const r = await fetch(caminho, { cache: "no-store" });
  if (!r.ok) throw new Error(`${caminho}: ${r.status}`);
  return r.json();
}

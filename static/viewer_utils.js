/**
 * viewer_utils.js — pure utility functions shared between viewer.html and tests.
 *
 * No DOM dependencies. Export for Node (tests), attach to window for the browser.
 */

// ── FEN / board ──────────────────────────────────────────────────────────────

/**
 * Parse the piece-placement part of a FEN string into an 8×8 matrix.
 * Each cell is a piece character (e.g. 'P', 'k') or null for empty.
 */
function parseFen(fen) {
  return fen.split(' ')[0].split('/').map(row => {
    const cells = [];
    for (const ch of row) {
      if (/\d/.test(ch)) for (let i = 0; i < +ch; i++) cells.push(null);
      else cells.push(ch);
    }
    return cells;
  });
}

/**
 * Convert a UCI move string to from/to square coordinates.
 * Returns [{col, row}, {col, row}] where col 0=a, row 0=rank-8.
 * Returns [null, null] for invalid input.
 */
function uciToSquares(uci) {
  if (!uci || uci.length < 4) return [null, null];
  const fi = c => c.charCodeAt(0) - 97;
  return [
    { col: fi(uci[0]), row: 8 - +uci[1] },
    { col: fi(uci[2]), row: 8 - +uci[3] },
  ];
}

// ── Material / captures ───────────────────────────────────────────────────────

const STARTING_COUNTS = { p: 8, n: 2, b: 2, r: 2, q: 1 };
const PIECE_VALUES    = { p: 1, n: 3, b: 3, r: 5, q: 9 };
const GV_ORDER        = ['q', 'r', 'b', 'n', 'p'];

/**
 * Compute captured pieces and material imbalance from a FEN string.
 * imbalance > 0 means White is ahead; < 0 means Black is ahead.
 */
function computeCaptures(fen) {
  const counts = { P:0,N:0,B:0,R:0,Q:0, p:0,n:0,b:0,r:0,q:0 };
  for (const ch of fen.split(' ')[0]) {
    if (Object.prototype.hasOwnProperty.call(counts, ch)) counts[ch]++;
  }
  const whiteLost = {}, blackLost = {};
  let whiteValue = 0, blackValue = 0;
  for (const t of GV_ORDER) {
    const T = t.toUpperCase();
    whiteLost[t] = Math.max(0, STARTING_COUNTS[t] - counts[T]);
    blackLost[t] = Math.max(0, STARTING_COUNTS[t] - counts[t]);
    whiteValue  += counts[T] * PIECE_VALUES[t];
    blackValue  += counts[t] * PIECE_VALUES[t];
  }
  return { whiteLost, blackLost, imbalance: whiteValue - blackValue };
}

// ── Model ID display ──────────────────────────────────────────────────────────

/**
 * Strip the namespace prefix and version suffix from a model ID.
 * "google/gemma-3-27b-it" → "gemma-3-27b-it"
 * "qwen3-30b-a3b@q4_k_m"  → "qwen3-30b-a3b"
 * "model:latest"          → "model"
 */
function extractModelName(modelId) {
  const afterSlash = modelId.split('/').pop();
  return afterSlash.split(/[:@]/)[0];
}

// ── ELO sparkline ─────────────────────────────────────────────────────────────

/**
 * Build an inline SVG sparkline from an ELO history array.
 * history: [{elo_after: number}, ...]
 * Returns an SVG string, or '' if fewer than 2 data points.
 */
function buildSparkline(history) {
  if (!history || history.length < 2) return '';
  const W = 58, H = 20, pad = 1;
  const vals = history.map(h => h.elo_after);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const range = hi - lo || 1;
  const px = (i) => pad + (i / (vals.length - 1)) * (W - pad*2);
  const py = (v) => H - pad - ((v - lo) / range) * (H - pad*2);
  const pts = vals.map((v,i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(' ');
  const fill = `${pts} ${(W-pad).toFixed(1)},${H} ${pad},${H}`;
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    <polygon points="${fill}" fill="rgba(200,146,30,.18)" stroke="none"/>
    <polyline points="${pts}" fill="none" stroke="var(--gold)" stroke-width="1.2" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

// ── HTML escaping ─────────────────────────────────────────────────────────────

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Export (Node) / attach to window (browser) ────────────────────────────────

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { parseFen, uciToSquares, computeCaptures, extractModelName, buildSparkline, escHtml };
} else {
  // Browser: functions are already in the global scope; nothing extra needed.
}

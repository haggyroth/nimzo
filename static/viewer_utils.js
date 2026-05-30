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

// ── Model card: shared state ──────────────────────────────────────────────────
// Accessed by renderPortraitBlock / openModelCard and, in viewer.html, by the
// portrait-upload / regen handlers that live in viewer.js.

let _mcCurrentModelId = null;
let _portraitQuotaExhausted = false;

// ── Model card: render helpers ────────────────────────────────────────────────

// Generic value sparkline from a plain array of numbers (used for coherence trend).
function _buildValueSparkline(values, W, H, color) {
  if (!values || values.length < 2) return '';
  const pad = 1;
  const lo = Math.min(...values), hi = Math.max(...values);
  const range = hi - lo || 1;
  const px = i => pad + (i / (values.length - 1)) * (W - pad * 2);
  const py = v => H - pad - ((v - lo) / range) * (H - pad * 2);
  const pts = values.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(' ');
  const fill = `${pts} ${(W - pad).toFixed(1)},${H} ${pad},${H}`;
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    <polygon points="${fill}" fill="rgba(91,161,214,.14)" stroke="none"/>
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.2" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

function renderPortraitBlock(p) {
  const midJs  = (p.model_id || '').replace(/\\/g,'\\\\').replace(/'/g, "\\'");
  // Action buttons only available in viewer.html (where triggerPortraitUpload / regenPortrait live).
  const hasActions = typeof triggerPortraitUpload === 'function';
  const upBtn  = hasActions ? `<button class="mc-portrait-btn" onclick="triggerPortraitUpload('${midJs}')">📷 Upload photo</button>` : '';
  const regenBtn = (!hasActions || p.user_provided_portrait || _portraitQuotaExhausted) ? '' :
    `<button class="mc-portrait-btn" onclick="regenPortrait('${midJs}')">↺ Regenerate AI</button>`;
  const quotaNote = _portraitQuotaExhausted
    ? `<div class="mc-quota-notice">Portrait generation unavailable (API quota)</div>` : '';
  const actions = hasActions ? `<div class="mc-portrait-actions">${upBtn}${regenBtn}</div>${quotaNote}` : '';
  if (p.portrait_url) {
    return `<img class="mc-portrait" src="${escHtml(p.portrait_url)}" alt="${escHtml(p.name || '')} portrait">${actions}`;
  }
  const family = (p.metadata && p.metadata.family) || '';
  const icon = family ? family[0].toUpperCase() : '♟';
  return `<div class="mc-portrait-placeholder">${icon}</div>${actions}`;
}

async function openModelCard(modelId) {
  _mcCurrentModelId = modelId;
  try {
    const [p, effectiveness, coherenceHist, openings] = await Promise.all([
      fetch(`${API}/api/models/${encodeURIComponent(modelId)}/profile`).then(r => r.json()),
      fetch(`${API}/api/models/${encodeURIComponent(modelId)}/lesson-effectiveness`).then(r => r.json()).catch(() => []),
      fetch(`${API}/api/models/${encodeURIComponent(modelId)}/coherence-history`).then(r => r.json()).catch(() => []),
      fetch(`${API}/api/models/${encodeURIComponent(modelId)}/openings`).then(r => r.json()).catch(() => []),
    ]);
    p._effectiveness = effectiveness;
    p._coherenceHist = coherenceHist;
    p._openings = openings;
    renderModelCard(p);
    document.getElementById('modelModal').classList.add('show');
    // If no portrait yet and quota not exhausted, try to generate one
    if (!p.portrait_url && !_portraitQuotaExhausted) {
      const portraitEl = document.getElementById('mcCard').querySelector('.mc-portrait-placeholder, .mc-portrait');
      if (portraitEl) {
        portraitEl.outerHTML = `<div class="mc-portrait-generating"><div class="spinner"></div>Painting…</div>`;
      }
      fetch(`${API}/api/models/${encodeURIComponent(modelId)}/portrait`, { method: 'POST' })
        .then(r => r.json())
        .then(j => {
          if (j.quota_exhausted) _portraitQuotaExhausted = true;
          if (j.portrait_url) {
            p.portrait_url = j.portrait_url;
            const gen = document.getElementById('mcCard').querySelector('.mc-portrait-generating');
            if (gen) {
              const img = document.createElement('img');
              img.className = 'mc-portrait';
              img.src = j.portrait_url;
              img.alt = (p.name || '') + ' portrait';
              gen.replaceWith(img);
            }
          } else {
            const gen = document.getElementById('mcCard').querySelector('.mc-portrait-generating');
            if (gen) gen.outerHTML = `<div class="mc-portrait-placeholder">♟</div>`;
            if (_portraitQuotaExhausted) {
              // Refresh to show quota notice
              renderModelCard(p);
            }
          }
        })
        .catch(() => {
          const gen = document.getElementById('mcCard').querySelector('.mc-portrait-generating');
          if (gen) gen.outerHTML = `<div class="mc-portrait-placeholder">♟</div>`;
        });
    }
  } catch (e) {
    console.error('Model card load failed:', e);
  }
}

function closeModelCard() {
  document.getElementById('modelModal').classList.remove('show');
}

function renderModelCard(p) {
  const m = p.moves || {};
  const c = p.color || {};
  const g = p.games || {};
  const total = m.total_moves || 0;
  const wGames = (c.white_wins||0) + (c.white_draws||0) + (c.white_losses||0);
  const bGames = (c.black_wins||0) + (c.black_draws||0) + (c.black_losses||0);
  const wins   = (c.white_wins||0) + (c.black_wins||0);
  const draws  = (c.white_draws||0) + (c.black_draws||0);
  const losses = (c.white_losses||0) + (c.black_losses||0);

  // Quality bar segments — width proportional to count
  const qkeys = ['q_best','q_excellent','q_good','q_inaccuracy','q_mistake','q_blunder'];
  const qcls  = { q_best:'q-best', q_excellent:'q-excellent', q_good:'q-good',
                  q_inaccuracy:'q-inaccuracy', q_mistake:'q-mistake', q_blunder:'q-blunder' };
  const qSum = qkeys.reduce((s,k) => s + (m[k]||0), 0);
  const qBar = total && qSum
    ? qkeys.map(k => {
        const n = m[k] || 0;
        if (!n) return '';
        const pct = (n / qSum * 100).toFixed(2);
        return `<span class="${qcls[k]}" style="width:${pct}%" title="${k.slice(2)}: ${n}"></span>`;
      }).join('')
    : '<span style="width:100%;background:var(--border)"></span>';

  const traits = (p.traits && p.traits.length)
    ? p.traits.map(t =>
        `<div class="mc-trait">
           <span class="mc-trait-label">${escHtml(t.label)}</span>
           <span class="mc-trait-detail">${escHtml(t.detail)}</span>
         </div>`).join('')
    : `<div class="mc-no-traits">No personality signal yet — play more games.</div>`;

  // Build effectiveness lookup: lesson text → {delta, games_measured}
  const effMap = {};
  for (const e of (p._effectiveness || [])) {
    effMap[e.lesson] = e;
  }

  const lessons = (p.recent_lessons || []).map(l => {
    const tag = l.lesson_type === 'strength' ? 'strength' : 'improve';
    const eff = effMap[l.lesson];
    let effChip = '';
    if (eff) {
      const pct = Math.round(Math.abs(eff.delta) * 100);
      if (eff.delta < -0.02) {
        effChip = `<span class="eff better" title="Bad-move rate dropped ${pct}pp over ${eff.games_measured} game(s)">↑ ${pct}pp</span>`;
      } else if (eff.delta > 0.02) {
        effChip = `<span class="eff worse" title="Bad-move rate rose ${pct}pp over ${eff.games_measured} game(s)">↓ ${pct}pp</span>`;
      } else {
        effChip = `<span class="eff same" title="No significant change over ${eff.games_measured} game(s)">→ same</span>`;
      }
    }
    return `<div class="mc-lesson">
              ${effChip}<span class="tag ${tag}">${tag}</span>${escHtml(l.lesson)}
            </div>`;
  }).join('') || `<div class="mc-no-traits">No lessons yet.</div>`;

  // Strategic profile — rendered as formatted text if present
  const profileHtml = p.strategic_profile
    ? `<div class="mc-profile">${escHtml(p.strategic_profile).replace(/\n/g,'<br>')}</div>`
    : null;

  // Coherence trend sparkline
  const cohHist = (p._coherenceHist || []);
  const cohVals = cohHist.map(h => h.avg_coherence).filter(v => v != null);
  const cohAvg  = cohVals.length ? (cohVals.reduce((s,v) => s+v, 0) / cohVals.length).toFixed(1) : null;
  const cohSparkHtml = cohVals.length >= 2
    ? _buildValueSparkline(cohVals, 90, 20, 'var(--accent)')
    : '';
  const cohSection = cohVals.length
    ? `<div class="mc-section-head">Reasoning coherence${cohAvg ? ' · avg ' + cohAvg + '/10' : ''}</div>
       <div class="mc-coherence-row">${cohSparkHtml}
         <span class="mc-coherence-note">${cohHist.length} game${cohHist.length!==1?'s':''}</span>
       </div>`
    : '';

  // Opening repertoire table
  const openings = p._openings || [];
  const openingRows = openings.map(o => {
    const total = o.games || 0;
    const wpct  = total ? Math.round(o.wins / total * 100) : 0;
    return `<tr>
      <td class="op-eco">${escHtml(o.eco_code || '?')}</td>
      <td class="op-name">${escHtml(o.opening_name || 'Unknown')}</td>
      <td class="op-games">${total}</td>
      <td class="op-score" title="${o.wins}W ${o.draws}D ${o.losses}L">${wpct}%</td>
    </tr>`;
  }).join('');
  const openingsSection = openingRows
    ? `<div class="mc-section-head">Opening repertoire</div>
       <table class="op-table">
         <thead><tr><th>ECO</th><th>Opening</th><th>G</th><th>W%</th></tr></thead>
         <tbody>${openingRows}</tbody>
       </table>`
    : '';

  const fmtScore = (w, d, t) => t ? `${(((w + 0.5*d)/t)*100).toFixed(0)}%` : '—';

  document.getElementById('mcBody').innerHTML = `
    ${renderPortraitBlock(p)}
    <div class="mc-name">${escHtml(p.name || '—')}</div>
    <div class="mc-modelid">${escHtml(p.model_id || '')} · ${escHtml(p.backend || '')}</div>
    ${renderMetadata(p.metadata)}

    <div class="mc-row">
      <div>
        <div class="mc-stat-label">ELO</div>
        <div class="mc-stat-value">${p.elo ?? '—'}</div>
      </div>
      <div>
        <div class="mc-stat-label">Record</div>
        <div class="mc-stat-value">${wins}/${draws}/${losses}</div>
        <div class="mc-stat-sub">${g.total_games || 0} games</div>
      </div>
      <div>
        <div class="mc-stat-label">As White</div>
        <div class="mc-stat-value">${fmtScore(c.white_wins||0, c.white_draws||0, wGames)}</div>
        <div class="mc-stat-sub">${wGames} games</div>
      </div>
      <div>
        <div class="mc-stat-label">As Black</div>
        <div class="mc-stat-value">${fmtScore(c.black_wins||0, c.black_draws||0, bGames)}</div>
        <div class="mc-stat-sub">${bGames} games</div>
      </div>
    </div>

    <div class="mc-section-head">Move quality (${total} moves)</div>
    <div class="mc-qbar">${qBar}</div>
    <div class="mc-qbar-legend">
      <span class="lb-best">best ${m.q_best || 0}</span>
      <span class="lb-excellent">excellent ${m.q_excellent || 0}</span>
      <span class="lb-good">good ${m.q_good || 0}</span>
      <span class="lb-inaccuracy">inaccuracy ${m.q_inaccuracy || 0}</span>
      <span class="lb-mistake">mistake ${m.q_mistake || 0}</span>
      <span class="lb-blunder">blunder ${m.q_blunder || 0}</span>
    </div>

    ${openingsSection}
    ${cohSection}

    <div class="mc-section-head">Achievements ${(p.achievements && p.achievements.length) ? '· ' + p.achievements.reduce((s,a)=>s+a.times, 0) : ''}</div>
    ${renderBadges(p.achievements)}

    <div class="mc-section-head">Personality</div>
    ${traits}

    ${profileHtml
      ? `<div class="mc-section-head">Strategic profile</div>${profileHtml}
         <div class="mc-section-head">Recent lessons</div>${lessons}`
      : `<div class="mc-section-head">Coach notes</div>${lessons}`
    }
  `;
}

function renderBadges(achievements) {
  if (!achievements || !achievements.length) {
    return `<div class="mc-no-traits">No achievements yet — keep playing.</div>`;
  }
  return `<div class="mc-badges">` + achievements.map(a => {
    const times = a.times > 1 ? `<span class="b-times">×${a.times}</span>` : '';
    return `<span class="mc-badge badge-${a.code}" title="${escHtml(a.desc)}">${escHtml(a.label)}${times}</span>`;
  }).join('') + `</div>`;
}

function renderMetadata(meta) {
  if (!meta) return '';
  const chips = [];
  const chip = (k, v, href) => {
    const inner = href
      ? `<a href="${href}" target="_blank" rel="noopener">${escHtml(v)}</a>`
      : escHtml(v);
    chips.push(`<span class="mc-meta-chip"><span class="k">${escHtml(k)}</span><span class="v">${inner}</span></span>`);
  };
  if (meta.family)          chip('Family',  meta.family);
  if (meta.param_count) {
    const ap = meta.active_params ? ` (${meta.active_params} active)` : '';
    chip('Params',  meta.param_count + ap);
  }
  if (meta.quantization)    chip('Quant',   meta.quantization);
  if (meta.architecture)    chip('Arch',    meta.architecture);
  if (meta.context_length)  chip('Ctx',     meta.context_length.toLocaleString());
  if (meta.file_size_label) chip('Size',    meta.file_size_label);
  if (meta.license)         chip('License', meta.license);
  if (meta.hf_url)          chip('HF',      'open ↗', meta.hf_url);
  if (!chips.length) return '';
  return `<div class="mc-meta">${chips.join('')}</div>`;
}

// ── Export (Node) / attach to window (browser) ────────────────────────────────

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { parseFen, uciToSquares, computeCaptures, extractModelName, buildSparkline, escHtml, renderBadges, renderMetadata };
} else {
  // Browser: functions are already in the global scope; nothing extra needed.
}

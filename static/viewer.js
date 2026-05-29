// ── Config ───────────────────────────────────────────────────────────────
const API   = '';          // same origin
const WS_URL = `ws://${location.host}/ws`;

// Default LM Studio endpoint — matches the server-side _DEFAULT_LMSTUDIO_URL constant.
const DEFAULT_LMSTUDIO_URL = 'http://localhost:1234/v1';

// Cloud provider registry, populated from /api/providers on page load.
// Shape: { [name]: { label, base_url, models[], configured } }
let _providers = {};

// ── cm-chessboard handle (populated in async boot) ───────────────────────
const _cmcb = {};

const PIECE_SETS = {
  unicode: { K:'♔',Q:'♕',R:'♖',B:'♗',N:'♘',P:'♙', k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟' },
  letters: { K:'K', Q:'Q', R:'R', B:'B', N:'N', P:'P', k:'k', q:'q', r:'r', b:'b', n:'n', p:'p' },
};

const THEMES = {
  wood:     { label:'Wood',      light:'#e8d5b0', dark:'#8b6148' },
  green:    { label:'Green',     light:'#eeeed2', dark:'#769656' },
  blue:     { label:'Blue',      light:'#dee3e6', dark:'#8ca2ad' },
  walnut:   { label:'Walnut',    light:'#f0d9b5', dark:'#b58863' },
  contrast: { label:'Contrast',  light:'#f0f0f0', dark:'#404040' },
  midnight: { label:'Midnight',  light:'#334455', dark:'#1a2535' },
};

const FONTS = {
  mono:   { label:'Mono',   value:"'JetBrains Mono', monospace" },
  system: { label:'System', value:"system-ui, -apple-system, sans-serif" },
};

// Sentinel value used when the user has manually chosen custom board colors
// rather than one of the preset theme swatches.
const THEME_CUSTOM = 'custom';

// ── UI color scheme themes ────────────────────────────────────────────────
// Each entry defines the full set of UI CSS variables.  Board-square colors
// (--sq-*) are managed separately by the board-theme swatch system.
const UI_THEMES = {
  nimzo: {
    label: 'Nimzo', dark: true, bg: '#07090c', text: '#c8d8e8', acc: '#c8921e',
    vars: { '--bg':'#07090c','--bg-panel':'#0c1018','--bg-card':'#111820','--bg-input':'#0a1120',
            '--border':'#1a2535','--border-hi':'#2a3d55',
            '--text':'#c8d8e8','--text-dim':'#3d5570','--text-mid':'#6a8aaa',
            '--gold':'#c8921e','--gold-bright':'#e8b84a' },
  },
  'solarized-dark': {
    label: 'Solarized Dark', dark: true, bg: '#002b36', text: '#839496', acc: '#b58900',
    vars: { '--bg':'#002b36','--bg-panel':'#073642','--bg-card':'#073642','--bg-input':'#00212b',
            '--border':'#0a3e4f','--border-hi':'#2aa198',
            '--text':'#839496','--text-dim':'#28444e','--text-mid':'#657b83',
            '--gold':'#b58900','--gold-bright':'#cb4b16' },
  },
  'solarized-light': {
    label: 'Solarized Light', dark: false, bg: '#fdf6e3', text: '#657b83', acc: '#b58900',
    vars: { '--bg':'#fdf6e3','--bg-panel':'#eee8d5','--bg-card':'#e4dfc9','--bg-input':'#fdf6e3',
            '--border':'#d0cab6','--border-hi':'#2aa198',
            '--text':'#657b83','--text-dim':'#b0aa96','--text-mid':'#839496',
            '--gold':'#b58900','--gold-bright':'#cb4b16' },
  },
  'catppuccin-mocha': {
    label: 'Catppuccin', dark: true, bg: '#1e1e2e', text: '#cdd6f4', acc: '#f9e2af',
    vars: { '--bg':'#1e1e2e','--bg-panel':'#181825','--bg-card':'#313244','--bg-input':'#181825',
            '--border':'#45475a','--border-hi':'#89b4fa',
            '--text':'#cdd6f4','--text-dim':'#45475a','--text-mid':'#a6adc8',
            '--gold':'#f9e2af','--gold-bright':'#fab387' },
  },
  'catppuccin-latte': {
    label: 'Catppuccin Latte', dark: false, bg: '#eff1f5', text: '#4c4f69', acc: '#df8e1d',
    vars: { '--bg':'#eff1f5','--bg-panel':'#e6e9ef','--bg-card':'#dce0e8','--bg-input':'#e6e9ef',
            '--border':'#ccd0da','--border-hi':'#1e66f5',
            '--text':'#4c4f69','--text-dim':'#bcc0cc','--text-mid':'#6c6f85',
            '--gold':'#df8e1d','--gold-bright':'#fe640b' },
  },
  nord: {
    label: 'Nord', dark: true, bg: '#2e3440', text: '#d8dee9', acc: '#ebcb8b',
    vars: { '--bg':'#2e3440','--bg-panel':'#3b4252','--bg-card':'#434c5e','--bg-input':'#2e3440',
            '--border':'#4c566a','--border-hi':'#88c0d0',
            '--text':'#d8dee9','--text-dim':'#3b4252','--text-mid':'#81a1c1',
            '--gold':'#ebcb8b','--gold-bright':'#d08770' },
  },
  dracula: {
    label: 'Dracula', dark: true, bg: '#282a36', text: '#f8f8f2', acc: '#f1fa8c',
    vars: { '--bg':'#282a36','--bg-panel':'#21222c','--bg-card':'#343746','--bg-input':'#21222c',
            '--border':'#44475a','--border-hi':'#bd93f9',
            '--text':'#f8f8f2','--text-dim':'#44475a','--text-mid':'#6272a4',
            '--gold':'#f1fa8c','--gold-bright':'#ffb86c' },
  },
};

// Light/dark toggle: each theme maps to its closest partner of the other brightness
const _UI_THEME_PAIRS = {
  'nimzo':            'solarized-light',
  'solarized-dark':   'solarized-light',
  'catppuccin-mocha': 'catppuccin-latte',
  'nord':             'solarized-light',
  'dracula':          'solarized-light',
  'solarized-light':  'nimzo',
  'catppuccin-latte': 'catppuccin-mocha',
};

const _DEFAULT_SETTINGS = {
  theme:          'wood',
  lightSq:        '#e8d5b0',
  darkSq:         '#8b6148',
  accent:         '#c8921e',
  pieceSet:       'unicode',
  font:           'mono',
  uiTheme:        'nimzo',
  panelCenter:    true,
  panelRight:     true,
  boardBgOpacity: 0.4,
};

// Board background image stored separately — can be several hundred KB as base64.
// Keeping it outside _settings avoids bloating the main JSON blob on every save.
let _boardBgData = localStorage.getItem('nimzo_board_bg') || null;

// Load settings from localStorage
const _settings = Object.assign({}, _DEFAULT_SETTINGS,
  JSON.parse(localStorage.getItem('nimzo_settings') || '{}')
);

function saveSettings() {
  localStorage.setItem('nimzo_settings', JSON.stringify(_settings));
}

function applyUiTheme(id) {
  const theme = UI_THEMES[id] || UI_THEMES.nimzo;
  const root  = document.documentElement;

  // Set the data attribute (drives CSS selector overrides)
  if (id === 'nimzo') {
    root.removeAttribute('data-ui-theme');
  } else {
    root.setAttribute('data-ui-theme', id);
  }

  // Also set vars directly so changes are immediate regardless of specificity
  Object.entries(theme.vars).forEach(([prop, val]) => root.style.setProperty(prop, val));

  // Update toggle button icon
  const btn = document.getElementById('themeToggleBtn');
  if (btn) btn.textContent = theme.dark ? '☀️' : '🌙';
}

function setUiTheme(id) {
  _settings.uiTheme = id;
  saveSettings();
  applyUiTheme(id);
  buildUiThemeSwatches();
}

function buildUiThemeSwatches() {
  const container = document.getElementById('uiThemeGrid');
  if (!container) return;
  container.innerHTML = Object.entries(UI_THEMES).map(([id, t]) => {
    const active = _settings.uiTheme === id ? ' active' : '';
    const borderCol = t.dark ? 'rgba(255,255,255,.15)' : 'rgba(0,0,0,.15)';
    return `<button class="ui-theme-btn${active}" data-ui-theme="${id}"
      style="background:${t.bg};color:${t.text};border-color:${active ? t.acc : borderCol}"
      onclick="setUiTheme('${id}')" title="${t.label}">${t.label}</button>`;
  }).join('');
}

function toggleLightDark() {
  const current = _settings.uiTheme || 'nimzo';
  const partner = _UI_THEME_PAIRS[current] || (UI_THEMES[current]?.dark ? 'solarized-light' : 'nimzo');
  setUiTheme(partner);
}

function importThemeJson(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const data = JSON.parse(e.target.result);
      // Support two common formats:
      // Format A (terminalcolors.com): { background, foreground, black, red, ... }
      // Format B (generic 16-color): { background, foreground, colors: ["#...", ...] }
      const bg   = data.background || data.bg || '#1a1a2e';
      const fg   = data.foreground || data.fg || '#e0e0e0';
      // For accent pick yellow (index 3 in ANSI), fallback to cyan (6), fallback to blue (4)
      const colors16 = data.colors || [];
      const acc  = data.yellow || colors16[3] || data.cyan || colors16[6] || data.blue || colors16[4] || '#c8921e';
      const bhi  = data.cyan   || colors16[6] || data.blue || colors16[4] || '#2aa198';
      // Derive slightly lighter panel bg
      const panelBg = shiftBrightness(bg, 8);
      const cardBg  = shiftBrightness(bg, 14);
      const dim     = data.brightBlack || (colors16[8] || shiftBrightness(fg, -60));

      // Build and apply a custom theme object
      const custom = {
        label: data.name || 'Imported',
        dark: isColorDark(bg),
        bg, text: fg, acc,
        vars: {
          '--bg': bg, '--bg-panel': panelBg, '--bg-card': cardBg, '--bg-input': bg,
          '--border': shiftBrightness(bg, 20), '--border-hi': bhi,
          '--text': fg, '--text-dim': dim, '--text-mid': shiftBrightness(fg, -20),
          '--gold': acc, '--gold-bright': lightenHex(acc, 25),
        },
      };
      // Register as 'imported' so it persists across buildUiThemeSwatches()
      UI_THEMES['imported'] = custom;
      _UI_THEME_PAIRS['imported'] = custom.dark ? 'solarized-light' : 'nimzo';
      setUiTheme('imported');
    } catch(err) {
      alert('Could not parse theme file. Expected terminalcolors.com JSON format.');
    }
  };
  reader.readAsText(file);
}

function isColorDark(hex) {
  const r = parseInt(hex.slice(1,3)||'00',16);
  const g = parseInt(hex.slice(3,5)||'00',16);
  const b = parseInt(hex.slice(5,7)||'00',16);
  return (r*299 + g*587 + b*114) / 1000 < 128;
}

function shiftBrightness(hex, delta) {
  const clamp = v => Math.max(0, Math.min(255, v));
  const r = clamp(parseInt(hex.slice(1,3)||'00',16) + delta);
  const g = clamp(parseInt(hex.slice(3,5)||'00',16) + delta);
  const b = clamp(parseInt(hex.slice(5,7)||'00',16) + delta);
  return '#' + [r,g,b].map(v => v.toString(16).padStart(2,'0')).join('');
}

function applySettings() {
  const root = document.documentElement;
  root.style.setProperty('--sq-light', _settings.lightSq);
  root.style.setProperty('--sq-dark',  _settings.darkSq);
  root.style.setProperty('--ui-font',  FONTS[_settings.font]?.value || FONTS.mono.value);

  // Apply UI color theme (sets --bg, --text, --gold, etc.)
  applyUiTheme(_settings.uiTheme || 'nimzo');

  // Board accent is separate — driven by board theme or custom color picker
  root.style.setProperty('--gold',        _settings.accent);
  root.style.setProperty('--gold-bright', lightenHex(_settings.accent, 30));

  // Restore panel collapse states
  const mainEl = document.querySelector('main');
  if (mainEl) {
    mainEl.classList.toggle('cp-collapsed', !(_settings.panelCenter ?? true));
    mainEl.classList.toggle('rp-collapsed', !(_settings.panelRight  ?? true));
  }
  const btnC = document.getElementById('btnToggleCenter');
  const btnR = document.getElementById('btnToggleRight');
  if (btnC) btnC.classList.toggle('collapsed', !(_settings.panelCenter ?? true));
  if (btnR) btnR.classList.toggle('collapsed', !(_settings.panelRight  ?? true));

  // Apply board background
  applyBoardBg();

  // Sync UI widgets (may not exist yet at initial call)
  syncSettingsUI();
  // Re-render eval graph with new accent if it has data
  if (typeof renderEvalGraph === 'function' && typeof evalHistory !== 'undefined' && evalHistory.length) {
    renderEvalGraph();
  }
}

function syncSettingsUI() {
  // Theme swatches
  document.querySelectorAll('.theme-swatch').forEach(el => {
    el.classList.toggle('active', el.dataset.theme === _settings.theme);
  });
  // Color pickers
  const lEl = document.getElementById('colorLight');
  const dEl = document.getElementById('colorDark');
  const aEl = document.getElementById('colorAccent');
  if (lEl) lEl.value = _settings.lightSq;
  if (dEl) dEl.value = _settings.darkSq;
  if (aEl) aEl.value = _settings.accent;
  // Piece set buttons
  document.querySelectorAll('.piece-set-btn[id^="ps"]').forEach(btn => {
    btn.classList.toggle('active', btn.id === 'ps' + capitalize(_settings.pieceSet));
  });
  // Font buttons
  document.querySelectorAll('.font-btn').forEach(btn => {
    btn.classList.toggle('active', btn.id === 'font' + capitalize(_settings.font));
  });
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

function lightenHex(hex, amount) {
  // Simple brightness boost for accent derived color
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
  const clamp = v => Math.min(255, v + amount);
  return '#' + [clamp(r), clamp(g), clamp(b)].map(v => v.toString(16).padStart(2,'0')).join('');
}

function buildThemeSwatches() {
  const container = document.getElementById('themeSwatches');
  if (!container) return;
  container.innerHTML = Object.entries(THEMES).map(([id, t]) =>
    `<div class="theme-swatch${_settings.theme===id?' active':''}" data-theme="${id}"
         title="${t.label}" onclick="setTheme('${id}')">
       <div class="th-l" style="background:${t.light}"></div>
       <div class="th-d" style="background:${t.dark}"></div>
     </div>`
  ).join('');
}

function setTheme(id) {
  const t = THEMES[id];
  if (!t) return;
  _settings.theme   = id;
  _settings.lightSq = t.light;
  _settings.darkSq  = t.dark;
  saveSettings();
  applySettings();
  buildThemeSwatches();  // refresh active state
  // CSS variables are updated by applySettings(); cm-chessboard reads them via the
  // .cm-chessboard .board .square.white/black overrides — no explicit board redraw needed.
}

function onCustomColor() {
  const lEl = document.getElementById('colorLight');
  const dEl = document.getElementById('colorDark');
  const aEl = document.getElementById('colorAccent');
  _settings.theme   = THEME_CUSTOM;
  _settings.lightSq = lEl.value;
  _settings.darkSq  = dEl.value;
  _settings.accent  = aEl.value;
  saveSettings();
  applySettings();
  buildThemeSwatches();
  renderEvalGraph();  // re-render eval graph with new accent color
}

function setPieceSet(id) {
  // Controls the glyph style used in the captured-piece graveyard only.
  // The main board uses cm-chessboard SVG sprites (Wikimedia CC BY-SA 3.0)
  // and is not affected by this setting.
  _settings.pieceSet = id;
  saveSettings();
  syncSettingsUI();
}

function setFont(id) {
  _settings.font = id;
  saveSettings();
  applySettings();
}

function resetSettings() {
  Object.assign(_settings, _DEFAULT_SETTINGS);
  saveSettings();
  clearBoardBg();   // also removes the separate board-bg localStorage entry
  applySettings();
  buildThemeSwatches();
  buildUiThemeSwatches();
}

// ── Panel collapse toggle ────────────────────────────────────────────────
function togglePanel(which) {
  if (which === 'center') {
    _settings.panelCenter = !(_settings.panelCenter ?? true);
    document.querySelector('main').classList.toggle('cp-collapsed', !_settings.panelCenter);
    const btn = document.getElementById('btnToggleCenter');
    if (btn) btn.classList.toggle('collapsed', !_settings.panelCenter);
  } else {
    _settings.panelRight = !(_settings.panelRight ?? true);
    document.querySelector('main').classList.toggle('rp-collapsed', !_settings.panelRight);
    const btn = document.getElementById('btnToggleRight');
    if (btn) btn.classList.toggle('collapsed', !_settings.panelRight);
  }
  saveSettings();
  // Grid column widths changed — recalculate board size on next frame.
  requestAnimationFrame(sizeBoard);
}

// ── Board background image ───────────────────────────────────────────────
function applyBoardBg() {
  const root = document.documentElement;
  if (_boardBgData) {
    root.style.setProperty('--board-bg-img',     `url("${_boardBgData}")`);
    root.style.setProperty('--board-bg-opacity', String(_settings.boardBgOpacity ?? 0.4));
  } else {
    root.style.setProperty('--board-bg-img', 'none');
  }
  // Sync opacity slider
  const slider = document.getElementById('boardBgOpacity');
  if (slider) slider.value = Math.round((_settings.boardBgOpacity ?? 0.4) * 100);
  // Show/hide Clear button
  const clearBtn = document.getElementById('boardBgClear');
  if (clearBtn) clearBtn.style.display = _boardBgData ? '' : 'none';
}

function setBoardBg(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    _boardBgData = e.target.result;
    try { localStorage.setItem('nimzo_board_bg', _boardBgData); } catch (_) { /* quota */ }
    applyBoardBg();
  };
  reader.readAsDataURL(file);
}

function clearBoardBg() {
  _boardBgData = null;
  localStorage.removeItem('nimzo_board_bg');
  applyBoardBg();
}

function onBoardBgOpacity(val) {
  _settings.boardBgOpacity = Number(val) / 100;
  saveSettings();
  document.documentElement.style.setProperty('--board-bg-opacity', String(_settings.boardBgOpacity));
}

// PIECES is now dynamic — use current piece set
function currentPieces() {
  return PIECE_SETS[_settings.pieceSet] || PIECE_SETS.unicode;
}

const FILES  = ['a','b','c','d','e','f','g','h'];

// ── State ────────────────────────────────────────────────────────────────
let gameState = {
  fen:        'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
  lastUci:    null,
  white:      { name: '—', elo: null, model_id: null, portrait_url: null },
  black:      { name: '—', elo: null, model_id: null, portrait_url: null },
  thinking:   null,
  candidates: [],
  lastEvalCp:  null,
  boardFlipped: localStorage.getItem('boardFlipped') === 'true',
  lastGameId:   null,
  // Human-play state
  humanColor:     null,     // 'white' | 'black' | null
  humanAssisted:  true,     // show Stockfish candidates?
  isHumanTurn:    false,
  humanLegalUci:  [],       // all legal moves for current position
  humanCandidates:[], // UCI of Stockfish candidates
  // Per-player elapsed_ms accumulators (reset each game)
  elapsedSum:   { white: 0, black: 0 },
  elapsedCount: { white: 0, black: 0 },
};

let tournamentStatus = 'idle';
let isPaused = false;

// ── Board sizing ──────────────────────────────────────────────────────────
function sizeBoard() {
  const col   = document.getElementById('boardCol');
  const avail = Math.min(col.clientHeight - 160, col.clientWidth - 32, 560);
  const px    = Math.max(260, avail);
  document.getElementById('boardWrap').style.width  = px + 'px';
  document.getElementById('boardWrap').style.height = px + 'px';
  document.querySelectorAll('.player-strip').forEach(s => s.style.width = px + 'px');
  document.querySelectorAll('.player-col').forEach(s => s.style.width = px + 'px');
  document.documentElement.style.setProperty('--board-px', px + 'px');
  // cm-chessboard auto-fills its container on resize; no explicit redraw needed.
}
window.addEventListener('resize', sizeBoard);

// ── FEN parser / captures — defined in js/viewer_utils.js ─────────────────
// parseFen(), computeCaptures(), STARTING_COUNTS, PIECE_VALUES, GV_ORDER
// are loaded from the external script tag above.

function renderGraveyardInto(el, lostMap, capturedAreWhite, advantage) {
  if (!el) return;
  const parts = [];
  for (const t of GV_ORDER) {
    const n = lostMap[t] || 0;
    if (!n) continue;
    const glyph = capturedAreWhite ? currentPieces()[t.toUpperCase()] : currentPieces()[t];
    for (let i = 0; i < n; i++) parts.push(`<span class="gv-piece">${glyph}</span>`);
  }
  if (advantage > 0) parts.push(`<span class="gv-adv">+${advantage}</span>`);
  el.innerHTML = parts.join('');
}

function renderGraveyards(fen, ids) {
  if (!fen) return;
  const { whiteLost, blackLost, imbalance } = computeCaptures(fen);
  // Black's strip shows the white pieces Black has captured
  renderGraveyardInto(
    document.getElementById(ids.black),
    whiteLost, true,
    imbalance < 0 ? -imbalance : 0,
  );
  // White's strip shows the black pieces White has captured
  renderGraveyardInto(
    document.getElementById(ids.white),
    blackLost, false,
    imbalance > 0 ? imbalance : 0,
  );
}

// uciToSquares() — defined in js/viewer_utils.js (still used for other logic)

// ── cm-chessboard render ──────────────────────────────────────────────────
async function _cmcbRender(animate) {
  if (!_cmcb.ready || !_cmcb.board) return;
  const { MARKER_TYPE, COLOR } = _cmcb;

  // Set board position
  await _cmcb.board.setPosition(gameState.fen, animate);

  // Clear previous last-move markers
  _cmcb.board.removeMarkers(MARKER_TYPE.square);

  // Highlight last-move squares
  if (gameState.lastUci && gameState.lastUci.length >= 4) {
    const fromSq = gameState.lastUci.slice(0, 2);
    const toSq   = gameState.lastUci.slice(2, 4);
    _cmcb.board.addMarker(MARKER_TYPE.square, fromSq);
    _cmcb.board.addMarker(MARKER_TYPE.square, toSq);
  }

  // Clear any lingering legal-move dot markers from a prior selection
  _cmcb.board.removeMarkers(MARKER_TYPE.dot);

  // Human input handling
  if (gameState.isHumanTurn) {
    const humanColorConst = gameState.humanColor === 'black' ? COLOR.black : COLOR.white;
    const candidateUci = gameState.humanAssisted ? gameState.humanCandidates : [];
    const legalUci     = gameState.humanLegalUci;

    _cmcb.board.enableMoveInput(event => {
      const { INPUT_EVENT_TYPE } = _cmcb;

      if (event.type === INPUT_EVENT_TYPE.moveInputStarted) {
        const sq = event.squareFrom;
        if (!legalUci.some(u => u.startsWith(sq))) return false;
        // Show a dot on every legal destination for this piece so the player
        // can click-to-move without relying on the Stockfish candidate arrows.
        _cmcb.board.removeMarkers(MARKER_TYPE.dot);
        legalUci.forEach(u => {
          if (u.startsWith(sq)) _cmcb.board.addMarker(MARKER_TYPE.dot, u.slice(2, 4));
        });
        return true;
      }

      if (event.type === INPUT_EVENT_TYPE.validateMoveInput) {
        _cmcb.board.removeMarkers(MARKER_TYPE.dot);
        const uci = event.squareFrom + event.squareTo;
        // Prefer a candidate destination; fall back to any legal destination
        const candMatches  = candidateUci.filter(u => u.startsWith(uci));
        const legalMatches = legalUci.filter(u => u.startsWith(uci));
        const matches = candMatches.length > 0 ? candMatches : legalMatches;
        if (matches.length > 0) {
          const chosen = matches.find(u => u.endsWith('q')) || matches[0];
          submitHumanMove(chosen);
          return true;
        }
        return false;
      }

      // Piece put back / input canceled — clear dots
      if (event.type === INPUT_EVENT_TYPE.moveInputCanceled) {
        _cmcb.board.removeMarkers(MARKER_TYPE.dot);
      }

      return true;
    }, humanColorConst);
  } else {
    _cmcb.board.disableMoveInput();
  }

  // Keep flip button icon in sync
  const btn = document.getElementById('flipBtn');
  if (btn) btn.title = gameState.boardFlipped ? "Flip to White's perspective" : "Flip to Black's perspective";

  // Refresh captured-pieces graveyards
  renderGraveyards(gameState.fen, { white: 'graveyardWhite', black: 'graveyardBlack' });
}

function toggleFlip() {
  gameState.boardFlipped = !gameState.boardFlipped;
  localStorage.setItem('boardFlipped', gameState.boardFlipped);
  if (_cmcb.ready && _cmcb.board) {
    _cmcb.board.setOrientation(gameState.boardFlipped ? _cmcb.COLOR.black : _cmcb.COLOR.white, false);
  }
  if (_cmcb.ready && _cmcb.rpBoard) {
    _cmcb.rpBoard.setOrientation(gameState.boardFlipped ? _cmcb.COLOR.black : _cmcb.COLOR.white, false);
  }
}

async function submitHumanMove(uci) {
  gameState.isHumanTurn = false;
  const banner = document.getElementById('humanTurnBanner');
  if (banner) banner.classList.remove('show');
  if (_cmcb.ready && _cmcb.board) _cmcb.board.disableMoveInput();

  try {
    const res = await fetch(`${API}/api/human-move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uci }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      console.warn('Human move rejected:', err.detail || res.status);
      // Re-enable human turn on error so they can try again
      gameState.isHumanTurn = true;
      if (banner) banner.classList.add('show');
      _cmcbRender(false);
    }
  } catch(e) {
    console.error('Failed to submit human move:', e);
    gameState.isHumanTurn = true;
    if (banner) banner.classList.add('show');
    _cmcbRender(false);
  }
}

// ── Player strips ─────────────────────────────────────────────────────────
function updatePlayers() {
  document.getElementById('nameWhite').textContent = gameState.white.name;
  document.getElementById('nameBlack').textContent = gameState.black.name;
  document.getElementById('eloWhite').textContent  = gameState.white.elo!=null ? 'ELO '+Math.round(gameState.white.elo) : '—';
  document.getElementById('eloBlack').textContent  = gameState.black.elo!=null ? 'ELO '+Math.round(gameState.black.elo) : '—';
  // Don't show "thinking" spinner for human turns — the board click UI handles it
  const llmThinkingWhite = gameState.thinking==='white' && !gameState.isHumanTurn;
  const llmThinkingBlack = gameState.thinking==='black' && !gameState.isHumanTurn;
  document.getElementById('thinkWhite').classList.toggle('on', llmThinkingWhite);
  document.getElementById('thinkBlack').classList.toggle('on', llmThinkingBlack);
  document.getElementById('boardWrap').classList.toggle('thinking', llmThinkingWhite || llmThinkingBlack);

  // Live eval readout — show current centipawn advantage in each player strip
  const cp  = gameState.lastEvalCp;
  const ewEl = document.getElementById('evalWhite');
  const ebEl = document.getElementById('evalBlack');
  if (cp == null) {
    ewEl.textContent = ''; ebEl.textContent = '';
    ewEl.className = 'p-eval'; ebEl.className = 'p-eval';
  } else {
    const clampedCp = Math.max(-2000, Math.min(2000, cp));
    const pawns     = clampedCp / 100;
    const absStr    = Math.abs(pawns).toFixed(1);
    const whiteAhead = clampedCp > 15;
    const blackAhead = clampedCp < -15;
    const cls = whiteAhead ? 'adv-white' : blackAhead ? 'adv-black' : 'adv-even';
    // White strip: show + when White is ahead, − when behind
    ewEl.textContent = whiteAhead ? `+${absStr}` : blackAhead ? `−${absStr}` : '=';
    ewEl.className   = `p-eval ${cls}`;
    // Black strip: mirror — Black is ahead when cp is negative
    ebEl.textContent = blackAhead ? `+${absStr}` : whiteAhead ? `−${absStr}` : '=';
    ebEl.className   = `p-eval ${cls}`;
  }
}

// ── Analysis pane ─────────────────────────────────────────────────────────
function updateAnalysis() {
  const body  = document.getElementById('analysisBody');
  if (!gameState.thinking) {
    body.innerHTML = '<div class="idle-hint"><div class="king">♟</div><div>Awaiting next move</div></div>';
    return;
  }

  const name  = gameState.thinking==='white' ? gameState.white.name : gameState.black.name;
  const cands = gameState.candidates || [];

  // Human turn: show candidates as clickable list (assisted) or simple prompt (blind)
  if (gameState.isHumanTurn) {
    if (!gameState.humanAssisted || cands.length === 0) {
      body.innerHTML = `<div class="idle-hint"><div class="king">♟</div><div>Click a piece to move</div></div>`;
      return;
    }
    const maxSc = Math.max(...cands.map(c=>c.score_cp!=null?Math.abs(c.score_cp):0), 1);
    let html = `<div class="thinking-tag" style="color:var(--gold-bright)">Your candidates — click to move</div>`;
    cands.forEach((c,i) => {
      const sc  = c.score_cp;
      const str = sc!=null ? (sc>0?'+':'')+(sc/100).toFixed(2) : '?';
      const pct = sc!=null ? Math.round(Math.abs(sc)/maxSc*100) : 50;
      const col = sc==null?'var(--text-dim)':sc>0?'var(--gold)':sc<-100?'var(--q-blunder)':'var(--text-mid)';
      html += `<div class="cand-row" style="cursor:pointer" onclick="submitHumanMove('${c.uci}')">
        <span class="cand-idx">${i+1}</span>
        <span class="cand-san">${c.san}</span>
        <div class="cand-bar"><div class="cand-bar-fill" style="width:${pct}%;background:${col}"></div></div>
        <span class="cand-score">${str}</span>
      </div>`;
    });
    body.innerHTML = html;
    return;
  }

  const maxSc = Math.max(...cands.map(c=>c.score_cp!=null?Math.abs(c.score_cp):0), 1);
  let html = `<div class="thinking-tag on"><div class="dot"></div>${escHtml(name)}</div>`;
  cands.forEach((c,i) => {
    const sc  = c.score_cp;
    const str = sc!=null ? (sc>0?'+':'')+(sc/100).toFixed(2) : '?';
    const pct = sc!=null ? Math.round(Math.abs(sc)/maxSc*100) : 50;
    const col = sc==null?'var(--text-dim)':sc>0?'var(--gold)':sc<-100?'var(--q-blunder)':'var(--text-mid)';
    html += `<div class="cand-row">
      <span class="cand-idx">${i+1}</span>
      <span class="cand-san">${c.san}</span>
      <div class="cand-bar"><div class="cand-bar-fill" style="width:${pct}%;background:${col}"></div></div>
      <span class="cand-score">${str}</span>
    </div>`;
  });
  body.innerHTML = html;
}

// ── Move history ──────────────────────────────────────────────────────────
function addMoveCard(data) {
  const pane = document.getElementById('historyPane');
  const num  = data.move_number;
  const col  = data.color;
  const label= col==='white' ? `${Math.ceil(num/2)}.` : `${Math.ceil(num/2)}…`;
  const q    = (data.quality||'good').toLowerCase();
  const rank = data.candidate_rank;
  const rankStr = rank===1?'★ top pick':rank?`#${rank} candidate`:'';
  const showReason = data.reasoning &&
        data.reasoning!=='(no reasoning)' &&
        data.reasoning!=='(parse failed — defaulted to top candidate)' &&
        !data.reasoning.startsWith('(');

  const showThink = !!(data.thinking_content && data.thinking_content.trim());

  // Reasoning coherence chip
  const cs = data.coherence_score;
  let coherenceHtml = '';
  if (cs != null) {
    const cls = cs >= 7 ? 'hi' : cs <= 3 ? 'lo' : '';
    coherenceHtml = `<span class="move-coherence ${cls}" title="Reasoning coherence score">🎯 ${cs}/10</span>`;
  }
  const isBook       = !!data.is_book_move;
  const timeoutHtml  = data.timed_out ? `<span class="move-timeout" title="Model timed out">⏱ timeout</span>` : '';
  const blindHtml    = data.is_blind_move ? `<span class="move-blind" title="Opening blind move — no Stockfish candidates provided">🎭 blind</span>` : '';
  const bookHtml     = isBook ? `<span class="move-book" title="Forced opening prefix — played automatically before guided play">📖 book</span>` : '';
  const latencyHtml  = (data.elapsed_ms != null && !data.timed_out && !isBook)
    ? `<span class="move-latency" title="Model response time">${(data.elapsed_ms / 1000).toFixed(1)}s</span>`
    : '';

  const card = document.createElement('div');
  card.className = `move-card ${q}${isBook ? ' book' : ''}`;
  card.innerHTML = `
    <div class="move-top">
      <span class="move-num-label">${label}</span>
      <span class="move-san-text">${escHtml(data.san)}</span>
      ${isBook ? '' : `<span class="move-badge ${q}">${q}</span>`}
      ${coherenceHtml}${timeoutHtml}${blindHtml}${bookHtml}${latencyHtml}
    </div>
    ${rankStr && !data.is_blind_move && !isBook ? `<div class="move-rank-text">${rankStr}</div>` : ''}
    ${showReason && !isBook ? `<div class="move-reason">${escHtml(data.reasoning)}</div>` : ''}
    ${showThink ? `<span class="move-think-toggle">🧠 thinking</span><div class="move-think-body">${escHtml(data.thinking_content.trim())}</div>` : ''}`;

  if (showThink) {
    const toggle = card.querySelector('.move-think-toggle');
    const body   = card.querySelector('.move-think-body');
    toggle.addEventListener('click', () => body.classList.toggle('open'));
  }

  pane.prepend(card);
}

// ── Lessons panel ─────────────────────────────────────────────────────────
let _allLessons = {};   // keyed by player name

function showLessons(playerName, color, improve, strength) {
  _allLessons[playerName] = { color, improve, strength };
  renderLessons();
}

function renderLessons() {
  const body = document.getElementById('lessonsBody');
  const entries = Object.entries(_allLessons);
  if (entries.length === 0) {
    body.innerHTML = '<div class="lessons-empty">Lessons appear here after each game</div>';
    return;
  }
  let html = '<div class="lessons-body">';
  for (const [name, { improve, strength }] of entries) {
    html += `<div class="lesson-player">${escHtml(name)}</div>`;
    if (improve.length) {
      html += '<div class="lesson-type-label improve">Areas to improve</div><div class="lesson-group">';
      improve.forEach(l => { html += `<div class="lesson-item improve">${escHtml(l)}</div>`; });
      html += '</div>';
    }
    if (strength.length) {
      html += '<div class="lesson-type-label strength">Strengths</div><div class="lesson-group">';
      strength.forEach(l => { html += `<div class="lesson-item strength">${escHtml(l)}</div>`; });
      html += '</div>';
    }
  }
  html += '</div>';
  body.innerHTML = html;
}

// ── ELO sparkline ─────────────────────────────────────────────────────────
// buildSparkline() — defined in js/viewer_utils.js

// ── Leaderboard ───────────────────────────────────────────────────────────
let _lbRows = [];            // cached full leaderboard data
let _lbHistories = [];       // ELO sparkline data per row
let _lbSortCol = 'elo';      // current sort column key
let _lbSortDir = -1;         // -1 = desc, +1 = asc

function _lbSortFn(col) {
  // Toggle direction if same column, else default to desc
  if (_lbSortCol === col) _lbSortDir *= -1;
  else { _lbSortCol = col; _lbSortDir = -1; }
  _renderLeaderboard();
}

function _lbVal(r, col) {
  if (col === 'elo')    return r.elo ?? 0;
  if (col === 'wins')   return r.wins ?? 0;
  if (col === 'losses') return r.losses ?? 0;
  if (col === 'draws')  return r.draws ?? 0;
  if (col === 'wdl')    return (r.wins ?? 0) / Math.max(r.total_games ?? 1, 1);
  if (col === 'best')   return r.best_game_score ?? -1;
  if (col === 'games')  return r.total_games ?? 0;
  return 0;
}

function _renderLeaderboard() {
  const body = document.getElementById('leaderboardBody');
  if (!_lbRows.length) { body.innerHTML = '<div class="lb-empty">No games yet</div>'; return; }

  const sorted = [..._lbRows].sort((a, b) => _lbSortDir * (_lbVal(b, _lbSortCol) - _lbVal(a, _lbSortCol)));
  const arrow = col => _lbSortCol === col ? (_lbSortDir < 0 ? ' ▼' : ' ▲') : '';
  const th = (col, label, title='') =>
    `<th class="lb-sortable" title="${title}" onclick="_lbSortFn('${col}')">${label}${arrow(col)}</th>`;

  let html = `<table class="lb-table"><thead><tr>
    <th>#</th>
    ${th('elo','Name','Sort by name')}
    ${th('elo','ELO','Sort by ELO')}
    ${th('wdl','W/D/L','Sort by win rate')}
    ${th('best','Best','Best game quality score. Click to replay.')}
    <th title="Achievement badges">★</th>
    <th>Form</th>
    <th></th>
  </tr></thead><tbody>`;

  sorted.forEach((r, i) => {
    const histIdx = _lbRows.indexOf(r);
    const spark = buildSparkline(_lbHistories[histIdx] || []);
    const bestScore = r.best_game_score;
    const bestId    = r.best_game_id;
    const bestCell  = (bestScore != null && bestId != null)
      ? `<td class="lb-best" title="Replay best game (#${bestId})" onclick="openReplay(${bestId})">${Math.round(bestScore)}</td>`
      : `<td class="lb-best dim">—</td>`;
    const badgeCell = r.achievement_count > 0
      ? `<td class="lb-badges-cell" title="${r.achievement_count} achievements — click name for details" onclick="openModelCard('${escHtml(r.model_id).replace(/'/g, "\\'")}')">${r.achievement_count}</td>`
      : `<td class="lb-badges-cell dim">—</td>`;
    // Recent form dots
    const formDots = (r.recent_form || []).map(o => {
      const cls = o === 'W' ? 'win' : o === 'L' ? 'loss' : 'draw';
      return `<span class="form-dot ${cls}" title="${o}"></span>`;
    }).join('');
    html += `<tr>
      <td class="lb-rank">${i+1}</td>
      <td class="lb-name" title="${escHtml(r.model_id)} — click for details" onclick="openModelCard('${escHtml(r.model_id).replace(/'/g, "\\'")}')">${escHtml(r.name)}</td>
      <td class="lb-elo">${r.elo}</td>
      <td class="lb-wdl">${r.wins}/${r.draws}/${r.losses}</td>
      ${bestCell}
      ${badgeCell}
      <td class="lb-form">${formDots || '<span class="dim">—</span>'}</td>
      <td class="lb-spark">${spark}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  body.innerHTML = html;

  // Populate H2H dropdowns with the players we just rendered
  const selA = document.getElementById('h2hPlayerA');
  const selB = document.getElementById('h2hPlayerB');
  if (selA && selB) {
    let optsHtml = '';
    _lbRows.forEach(r => {
      optsHtml += `<option value="${escHtml(r.model_id)}">${escHtml(r.name)}</option>`;
    });
    selA.innerHTML = '<option value="">— Player A —</option>' + optsHtml;
    selB.innerHTML = '<option value="">— Player B —</option>' + optsHtml;
  }
}

async function loadLeaderboard() {
  try {
    const rows = await fetch(`${API}/api/leaderboard`).then(r=>r.json());
    if (!rows.length) {
      document.getElementById('leaderboardBody').innerHTML = '<div class="lb-empty">No games yet</div>';
      return;
    }
    _lbRows = rows;
    _lbHistories = await Promise.all(
      rows.map(r => fetch(`${API}/api/elo-history/${encodeURIComponent(r.model_id)}`)
        .then(res => res.json()).catch(() => []))
    );
    _renderLeaderboard();
  } catch(e) { /* server not ready yet */ }
}

// ── Head-to-head comparison ───────────────────────────────────────────────
async function runH2H() {
  const a = document.getElementById('h2hPlayerA').value;
  const b = document.getElementById('h2hPlayerB').value;
  const body = document.getElementById('h2hBody');
  if (!a || !b) { body.innerHTML = '<div class="h2h-hint">Select two players to compare.</div>'; return; }
  if (a === b) { body.innerHTML = '<div class="h2h-hint">Select two different players.</div>'; return; }
  body.innerHTML = '<div class="h2h-hint">Loading…</div>';
  try {
    const [rec, pA, pB] = await Promise.all([
      fetch(`${API}/api/models/${encodeURIComponent(a)}/h2h/${encodeURIComponent(b)}`).then(r=>r.json()),
      fetch(`${API}/api/models/${encodeURIComponent(a)}/profile`).then(r=>r.json()),
      fetch(`${API}/api/models/${encodeURIComponent(b)}/profile`).then(r=>r.json()),
    ]);
    const nameA = pA.name || a;
    const nameB = pB.name || b;
    const winsA = rec.wins ?? 0;
    const winsB = rec.losses ?? 0;
    const draws = rec.draws ?? 0;
    const total = rec.total ?? 0;
    const pctA = total ? Math.round(100*(winsA + draws*0.5)/total) : '—';
    const pctB = total ? Math.round(100*(winsB + draws*0.5)/total) : '—';

    // Stats from profile responses — profile nests move stats under .moves
    const movA = pA.moves || {};
    const movB = pB.moves || {};
    const blunderRateA = movA.total_moves ? movA.q_blunder / movA.total_moves : null;
    const blunderRateB = movB.total_moves ? movB.q_blunder / movB.total_moves : null;
    const blunderA = blunderRateA != null ? (blunderRateA*100).toFixed(1)+'%' : '—';
    const blunderB = blunderRateB != null ? (blunderRateB*100).toFixed(1)+'%' : '—';
    const rankA    = movA.avg_rank != null ? Number(movA.avg_rank).toFixed(2) : '—';
    const rankB    = movB.avg_rank != null ? Number(movB.avg_rank).toFixed(2) : '—';
    const eloA     = pA.elo ?? '—';
    const eloB     = pB.elo ?? '—';

    let html = `<div class="h2h-compare">
      <div class="h2h-header">
        <span class="h2h-pname">${escHtml(nameA)}</span>
        <span class="h2h-vs">vs</span>
        <span class="h2h-pname">${escHtml(nameB)}</span>
      </div>
      <div class="h2h-score">${winsA} – ${draws} – ${winsB}</div>
      <div class="h2h-sub">${total} game${total===1?'':'s'} · ${pctA}% vs ${pctB}% score</div>
      <div class="h2h-stats">
        <div class="h2h-stat-row">
          <span class="h2h-val">${eloA}</span>
          <span class="h2h-label">ELO</span>
          <span class="h2h-val">${eloB}</span>
        </div>
        <div class="h2h-stat-row">
          <span class="h2h-val">${blunderA}</span>
          <span class="h2h-label">Blunder rate</span>
          <span class="h2h-val">${blunderB}</span>
        </div>
        <div class="h2h-stat-row">
          <span class="h2h-val">${rankA}</span>
          <span class="h2h-label">Avg candidate rank</span>
          <span class="h2h-val">${rankB}</span>
        </div>
      </div>
    </div>`;
    body.innerHTML = html;
  } catch(e) {
    body.innerHTML = '<div class="h2h-hint">Error loading data.</div>';
  }
}

// ── Recent games ──────────────────────────────────────────────────────────
let _historyLimit = 10;

async function loadHistory(append = false) {
  try {
    const games = await fetch(`${API}/api/games?limit=${_historyLimit}`).then(r=>r.json());
    const body  = document.getElementById('historyBody');
    if (!games.length) { body.innerHTML='<div class="lb-empty">No games yet</div>'; return; }
    let html = '';
    const resultLabel = { '1-0':'1-0','0-1':'0-1','1/2-1/2':'½-½' };
    // Store game metadata keyed by id for click handler
    window._recentGamesMeta = window._recentGamesMeta || {};
    games.forEach(g => { window._recentGamesMeta[g.id] = g; });

    games.forEach(g => {
      const res = resultLabel[g.result] || g.result;
      const openingTag = (g.eco_code || g.opening_name)
        ? `<span class="game-opening" title="${escHtml(g.opening_name||'')}">` +
          `${escHtml(g.eco_code||'')}${g.eco_code && g.opening_name ? ' · ' : ''}${escHtml(g.opening_name||'')}</span>`
        : '';
      html += `<div class="game-row" onclick="openReplay(${g.id}, window._recentGamesMeta[${g.id}])">
        <span class="game-result">${res}</span>
        <span class="game-names">${escHtml(g.white_name)} vs ${escHtml(g.black_name)}</span>
        <span class="game-moves">${g.total_moves}m</span>
        ${openingTag}
        <a class="game-lichess" title="Analyse on Lichess" target="_blank" rel="noopener"
           onclick="event.stopPropagation(); openLichessById(${g.id})">↗</a>
        <button class="game-pgn-btn" title="Download PGN" onclick="event.stopPropagation(); downloadGamePgn(${g.id})">↓</button>
      </div>`;
    });
    // Show "load more" button if we got a full page (could be more)
    if (games.length >= _historyLimit) {
      html += `<div class="hist-more-btn" onclick="_historyLimit+=10; loadHistory(true)">↓ load more</div>`;
    }
    body.innerHTML = html;
  } catch(e) {}
}

// ── PGN download ──────────────────────────────────────────────────────────
async function downloadGamePgn(gameId) {
  const url = `${API}/api/games/${gameId}/pgn`;
  const resp = await fetch(url);
  if (!resp.ok) { alert('PGN not found'); return; }
  const text = await resp.text();
  // Try to derive filename from Content-Disposition header
  let filename = `nimzo_game_${gameId}.pgn`;
  const cd = resp.headers.get('content-disposition');
  if (cd) {
    const m = cd.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
    if (m) filename = decodeURIComponent(m[1].replace(/^"|"$/g, ''));
  }
  const blob = new Blob([text], { type: 'application/x-chess-pgn' });
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(blob),
    download: filename,
  });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// ── Mode tabs ─────────────────────────────────────────────────────────────
let currentMode = 'match';

function setMode(mode) {
  currentMode = mode;
  document.getElementById('tabMatch').classList.toggle('active', mode==='match');
  document.getElementById('tabTournament').classList.toggle('active', mode==='tournament');
  document.getElementById('tabPuzzle').classList.toggle('active', mode==='puzzle');
  document.getElementById('matchForm').style.display      = mode==='match' ? '' : 'none';
  document.getElementById('tournamentForm').style.display = mode==='tournament' ? '' : 'none';
  document.getElementById('puzzleForm').style.display     = mode==='puzzle' ? '' : 'none';
  if (mode === 'puzzle') {
    document.getElementById('puzzleHistorySection').style.display = '';
    loadPuzzleHistory();
  }
}

// ── Tournament player slots ────────────────────────────────────────────────
let trnPlayers = [];   // [{id, name, backend, url, model, thinking}]
let trnNextId = 0;

function trnAddPlayer() {
  const id = trnNextId++;
  trnPlayers.push({ id, name: '', backend: 'lmstudio', url: DEFAULT_LMSTUDIO_URL, model: '', thinking: false, style: '' });
  renderTrnPlayerList();
}

function trnRemovePlayer(id) {
  if (trnPlayers.length <= 2) { alert('A tournament requires at least 2 players.'); return; }
  trnPlayers = trnPlayers.filter(p => p.id !== id);
  renderTrnPlayerList();
}

function renderTrnPlayerList() {
  const list = document.getElementById('trnPlayerList');
  const fmt  = document.getElementById('trnFormat').value;
  list.innerHTML = trnPlayers.map((p, idx) => {
    const label = fmt === 'gauntlet' && idx === 0 ? '👑 Champion' : `Player ${idx + 1}`;
    return `<div class="trn-player-row" id="trnRow_${p.id}">
      <div class="trn-player-num">${label}</div>
      ${trnPlayers.length > 2 ? `<button class="trn-remove-btn" onclick="trnRemovePlayer(${p.id})" title="Remove">✕</button>` : ''}
      <input class="ctrl-input" id="trnName_${p.id}" placeholder="Display name" value="${escHtml(p.name)}" oninput="trnSync(${p.id})">
      <select class="ctrl-select" id="trnBackend_${p.id}" onchange="trnSyncBackend(${p.id})">
        <option value="lmstudio" ${p.backend==='lmstudio'?'selected':''}>LM Studio</option>
        <option value="anthropic" ${p.backend==='anthropic'?'selected':''}>Anthropic</option>
        ${Object.entries(_providers).map(([name, prov]) =>
          `<option value="${name}" ${p.backend===name?'selected':''}>${prov.configured ? prov.label : prov.label + ' (no key)'}</option>`
        ).join('')}
      </select>
      <div class="url-row">
        <input class="ctrl-input" id="trnUrl_${p.id}" placeholder="${DEFAULT_LMSTUDIO_URL}" value="${escHtml(p.url)}" oninput="trnSync(${p.id})">
        <button class="fetch-btn" onclick="trnFetchModels(${p.id})" title="Load models">⟳</button>
      </div>
      <select class="ctrl-select" id="trnModel_${p.id}" onchange="trnSyncModel(${p.id})">
        <option value="">— select model —</option>
        ${p.model ? `<option value="${escHtml(p.model)}" selected>${escHtml(p.model)}</option>` : ''}
      </select>
      <select class="ctrl-select" id="trnStyle_${p.id}" onchange="trnSync(${p.id})" title="Playing style">
        <option value="" ${!p.style?'selected':''}>⚖ Balanced</option>
        <option value="aggressive" ${p.style==='aggressive'?'selected':''}>⚔ Aggressive</option>
        <option value="positional" ${p.style==='positional'?'selected':''}>♟ Positional</option>
        <option value="defensive" ${p.style==='defensive'?'selected':''}>🛡 Defensive</option>
      </select>
      <label class="toggle-row">
        <input type="checkbox" id="trnThink_${p.id}" ${p.thinking?'checked':''} onchange="trnSync(${p.id})"> Extended thinking
      </label>
    </div>`;
  }).join('');
}

function trnSync(id) {
  const p = trnPlayers.find(x => x.id === id);
  if (!p) return;
  p.name     = document.getElementById(`trnName_${id}`).value;
  p.url      = document.getElementById(`trnUrl_${id}`).value;
  p.thinking = document.getElementById(`trnThink_${id}`).checked;
  p.style    = document.getElementById(`trnStyle_${id}`)?.value || '';
}

function trnSyncBackend(id) {
  const p = trnPlayers.find(x => x.id === id);
  if (!p) return;
  p.backend = document.getElementById(`trnBackend_${id}`).value;

  // For Anthropic and cloud providers: hide the URL row and populate preset models
  const urlRow  = document.querySelector(`#trnRow_${id} .url-row`);
  const modelSel = document.getElementById(`trnModel_${id}`);

  const presetModels =
    p.backend === 'anthropic'
      ? ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001']
      : isCloudBackend(p.backend)
        ? (_providers[p.backend]?.models || [])
        : null;

  if (presetModels) {
    if (urlRow) urlRow.style.display = 'none';
    if (modelSel) {
      modelSel.innerHTML = presetModels.map(m =>
        `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join('');
      p.model = presetModels[0] || '';
    }
  } else {
    if (urlRow) urlRow.style.display = '';
  }
}

function trnSyncModel(id) {
  const p = trnPlayers.find(x => x.id === id);
  if (!p) return;
  p.model = document.getElementById(`trnModel_${id}`).value;
  if (p.model && !p.name) {
    p.name = extractModelName(p.model);
    const nameEl = document.getElementById(`trnName_${id}`);
    if (nameEl) nameEl.value = p.name;
  }
  if (/qwen/i.test(p.model)) {
    const thinkEl = document.getElementById(`trnThink_${id}`);
    if (thinkEl) { thinkEl.checked = false; p.thinking = false; }
  }
}

async function trnFetchModels(id) {
  const p = trnPlayers.find(x => x.id === id);
  if (!p) return;
  const url = document.getElementById(`trnUrl_${id}`).value || p.url;
  try {
    const data = await fetch(`${API}/api/models?url=${encodeURIComponent(url)}`).then(r=>r.json());
    const sel  = document.getElementById(`trnModel_${id}`);
    if (!sel) return;
    const models = (data.data || []).map(m => m.id || m);
    sel.innerHTML = '<option value="">— select model —</option>' +
      models.map(m => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join('');
    if (p.model) sel.value = p.model;
  } catch(e) {}
}

// Init with 2 default players
function initTrnPlayers() {
  trnPlayers = [];
  trnNextId = 0;
  trnAddPlayer();
  trnAddPlayer();
}

function onTrnFormatChange() {
  const fmt = document.getElementById('trnFormat');
  const pairRow = document.getElementById('trnGamesPairRow');
  if (fmt && pairRow) {
    pairRow.style.display = fmt.value === 'elimination' ? 'none' : '';
  }
  renderTrnPlayerList();
}

// Re-render when format changes (to update "Champion" label)
document.addEventListener('DOMContentLoaded', () => {
  initTrnPlayers();
  const fmt = document.getElementById('trnFormat');
  if (fmt) fmt.addEventListener('change', onTrnFormatChange);
});

// ── Tournament controls ───────────────────────────────────────────────────
async function startTournament() {
  const wBackend = document.getElementById('whiteBackend').value;
  const bBackend = document.getElementById('blackBackend').value;
  const wModel   = wBackend === 'human' ? (document.getElementById('whiteName').value || 'Human') : document.getElementById('whiteModel').value;
  const bModel   = bBackend === 'human' ? (document.getElementById('blackName').value || 'Human') : document.getElementById('blackModel').value;
  if (!wModel || !bModel) { alert('Select models for both players.'); return; }

  const tutorBackend = document.getElementById('tutorBackend').value;
  const tutorModel   = tutorBackend==='none' ? '' : document.getElementById('tutorModel').value;
  const tutorUrl     = tutorBackend==='none' ? '' : document.getElementById('tutorUrl').value;

  const cfg = {
    white_backend:   wBackend,
    white_name:      document.getElementById('whiteName').value || 'White',
    white_model:     wModel,
    white_url:       document.getElementById('whiteUrl').value,
    white_thinking:  document.getElementById('whiteThinking').checked,
    white_style:     document.getElementById('whiteStyle').value,
    black_backend:   bBackend,
    black_name:      document.getElementById('blackName').value || 'Black',
    black_model:     bModel,
    black_url:       document.getElementById('blackUrl').value,
    black_thinking:  document.getElementById('blackThinking').checked,
    black_style:     document.getElementById('blackStyle').value,
    tutor_backend:   tutorBackend==='none' ? 'lmstudio' : tutorBackend,
    tutor_model:     tutorModel,
    tutor_url:       tutorUrl || DEFAULT_LMSTUDIO_URL,
    games:                    parseInt(document.getElementById('gamesCount').value) || 10,
    human_assisted:           document.getElementById('humanAssisted') ? document.getElementById('humanAssisted').checked : true,
    adaptive_difficulty:      document.getElementById('adaptiveDifficulty') ? document.getElementById('adaptiveDifficulty').checked : false,
    white_blind_opening_moves: parseInt(document.getElementById('whiteBlindMoves')?.value) || 0,
    black_blind_opening_moves: parseInt(document.getElementById('blackBlindMoves')?.value) || 0,
    white_blind: document.getElementById('whiteBlind')?.checked ?? false,
    black_blind: document.getElementById('blackBlind')?.checked ?? false,
    white_candidate_count: parseInt(document.getElementById('whiteCandidates')?.value) || null,
    black_candidate_count: parseInt(document.getElementById('blackCandidates')?.value) || null,
    max_moves:                parseInt(document.getElementById('maxMoves')?.value) || 0,
    opening_pgn:              (document.getElementById('openingPgn')?.value || '').trim(),
  };

  const res = await fetch(`${API}/api/tournament/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  }).then(r=>r.json());

  if (res.error) alert(res.error);
}

async function startBracketTournament() {
  // Sync all player fields before reading
  trnPlayers.forEach(p => trnSync(p.id));
  // Validate
  const incomplete = trnPlayers.filter(p => !p.model);
  if (incomplete.length > 0) { alert('Select a model for every player.'); return; }
  if (trnPlayers.length < 2) { alert('Add at least 2 players.'); return; }

  const tutorBackend = document.getElementById('trnTutorBackend').value;
  const tutorModel   = tutorBackend==='none' ? '' : document.getElementById('trnTutorModel').value;
  const tutorUrl     = tutorBackend==='none' ? '' : document.getElementById('trnTutorUrl').value;

  const cfg = {
    players: trnPlayers.map(p => ({
      backend:  p.backend,
      name:     p.name || extractModelName(p.model),
      model_id: p.model,
      url:      p.url,
      thinking: p.thinking,
      style:    p.style || '',
    })),
    format:         document.getElementById('trnFormat').value,
    games_per_pair: parseInt(document.getElementById('trnGamesPair').value) || 2,
    tutor_backend:  tutorBackend==='none' ? 'lmstudio' : tutorBackend,
    tutor_model:    tutorModel,
    tutor_url:      tutorUrl || DEFAULT_LMSTUDIO_URL,
  };

  const res = await fetch(`${API}/api/tournament/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  }).then(r=>r.json());

  if (res.error) alert(res.error);
}

async function pauseTournament() {
  await fetch(`${API}/api/tournament/pause`, { method: 'POST' });
}

async function resumeTournament() {
  await fetch(`${API}/api/tournament/resume`, { method: 'POST' });
}

async function stopTournament() {
  if (!confirm('Stop the current tournament?')) return;
  await fetch(`${API}/api/tournament/stop`, { method: 'POST' });
}

function updateTournamentUI(status, gameNumber, totalGames) {
  tournamentStatus = status;
  isPaused = status === 'paused';

  const badge   = document.getElementById('tournamentBadge');
  const form    = document.getElementById('setupForm');
  const progress= document.getElementById('progressView');
  const btnP    = document.getElementById('btnPause');
  const btnR    = document.getElementById('btnResume');
  const btnS    = document.getElementById('btnStop');
  const info    = document.getElementById('hdrGameInfo');

  const isRunning = status==='running'||status==='paused'||status==='stopping';

  badge.textContent = status.charAt(0).toUpperCase()+status.slice(1);
  badge.className   = 'ctrl-badge ' + (status==='running'?'running':status==='paused'?'paused':status==='stopping'?'stopping':'');

  form.style.display     = isRunning ? 'none' : '';
  progress.style.display = isRunning ? '' : 'none';

  btnP.classList.toggle('show', status==='running');
  btnR.classList.toggle('show', status==='paused');
  btnS.classList.toggle('show', isRunning);
  info.classList.toggle('show', isRunning);

  if (isRunning && totalGames > 0) {
    const pct = Math.round(gameNumber / totalGames * 100);
    document.getElementById('progressText').textContent = `Game ${gameNumber} / ${totalGames}`;
    document.getElementById('progressPct').textContent  = pct + '%';
    document.getElementById('progressFill').style.width = pct + '%';
    info.textContent = `Game ${gameNumber}/${totalGames}`;
  }
}

// ── Model fetching ────────────────────────────────────────────────────────
// Extract base model name: everything after last '/' and before first ':' or '@'
// e.g. "lmstudio-community/gemma-4-e4b@q4_k_m" → "gemma-4-e4b"
// extractModelName() — defined in js/viewer_utils.js

function onModelSelect(side) {
  if (side === 'tutor') return;
  const modelId = document.getElementById(side + 'Model').value;
  if (!modelId) return;

  // Auto-fill display name from model ID
  const nameEl = document.getElementById(side + 'Name');
  if (nameEl) nameEl.value = extractModelName(modelId);

  // Qwen models work better without extended thinking
  const thinkEl = document.getElementById(side + 'Thinking');
  if (thinkEl && /qwen/i.test(modelId)) {
    thinkEl.checked = false;
  }
}

// ── Cloud provider helpers ────────────────────────────────────────────────

async function loadProviders() {
  try {
    _providers = await fetch(`${API}/api/providers`).then(r => r.json());
  } catch(e) {
    _providers = {};
    return;
  }
  // Inject cloud provider options into the static backend <select> elements
  const selIds = ['whiteBackend', 'blackBackend', 'tutorBackend', 'trnTutorBackend'];
  selIds.forEach(selId => {
    const sel = document.getElementById(selId);
    if (!sel) return;
    // Remove any previously-added cloud options (avoid duplicates on re-call)
    sel.querySelectorAll('option[data-cloud]').forEach(o => o.remove());
    // Insert before the "Human" / "none" option, or append
    const anchorOpt = [...sel.options].find(o => o.value === 'human' || o.value === 'none');
    Object.entries(_providers).forEach(([name, p]) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.dataset.cloud = '1';
      opt.textContent = p.configured ? p.label : `${p.label} (no key)`;
      if (!p.configured) opt.style.color = 'var(--text-dim)';
      if (anchorOpt) sel.insertBefore(opt, anchorOpt);
      else sel.appendChild(opt);
    });
  });
  // Re-render tournament player rows so their backend selects include providers
  if (typeof renderTrnPlayerList === 'function') renderTrnPlayerList();
}

function isCloudBackend(backend) {
  return backend in _providers;
}

async function fetchModels(side) {
  const urlId = side === 'tutor' ? 'tutorUrl' : side === 'trnTutor' ? 'trnTutorUrl' : side + 'Url';
  const selId = side === 'tutor' ? 'tutorModel' : side === 'trnTutor' ? 'trnTutorModel' : side + 'Model';
  const url   = document.getElementById(urlId).value.trim();
  if (!url) return;

  try {
    const data = await fetch(`${API}/api/models?url=${encodeURIComponent(url)}`).then(r=>r.json());
    const models = (data.data || []).map(m => typeof m === 'string' ? m : m.id).filter(Boolean);
    const sel = document.getElementById(selId);
    const prev = sel.value;
    sel.innerHTML = '<option value="">— select model —</option>';
    models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = opt.textContent = m;
      if (m === prev) opt.selected = true;
      sel.appendChild(opt);
    });
    if (!prev && models.length === 1) sel.value = models[0];
    onModelSelect(side);
  } catch(e) {
    console.warn('Failed to fetch models:', e);
  }
}

function onBackendChange(side) {
  const backend = document.getElementById(side + 'Backend').value;
  const urlRow  = document.getElementById(side + 'UrlRow');
  // Handle "none" for both tutor variants
  const isTutor = side === 'tutor' || side === 'trnTutor';
  const modelId = side === 'trnTutor' ? 'trnTutorModel' : side + 'Model';

  if (isTutor && backend === 'none') {
    if (urlRow) urlRow.style.display = 'none';
    const ms = document.getElementById(modelId);
    if (ms) ms.style.display = 'none';
    return;
  }

  // Human backend: hide URL, model, and thinking rows; show humanOpts
  if (backend === 'human') {
    if (urlRow) urlRow.style.display = 'none';
    const modelSel = document.getElementById(modelId);
    if (modelSel) { modelSel.innerHTML = '<option value="">— human player —</option>'; modelSel.style.display = 'none'; }
    const thinkRow = document.getElementById(side + 'Thinking');
    if (thinkRow) { thinkRow.parentElement.style.display = 'none'; }
    // Show humanOpts if either white or black is human
    const hoEl = document.getElementById('humanOpts');
    if (hoEl) hoEl.style.display = '';
    return;
  }

  // Restore hidden rows if switching away from human
  if (urlRow) urlRow.style.display = '';
  const modelSel2 = document.getElementById(modelId);
  if (modelSel2) modelSel2.style.display = '';
  const thinkRow2 = document.getElementById(side + 'Thinking');
  if (thinkRow2) thinkRow2.parentElement.style.display = '';

  // Hide humanOpts if neither side is now human
  const wb = document.getElementById('whiteBackend');
  const bb = document.getElementById('blackBackend');
  if (wb && bb && wb.value !== 'human' && bb.value !== 'human') {
    const hoEl = document.getElementById('humanOpts');
    if (hoEl) hoEl.style.display = 'none';
  }

  // Preset-model backends: Anthropic and cloud providers — hide URL row,
  // populate the model select with a known list instead of fetching.
  const presetModels =
    backend === 'anthropic'
      ? ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001']
      : isCloudBackend(backend)
        ? (_providers[backend]?.models || [])
        : null;

  if (presetModels) {
    const sel = document.getElementById(modelId);
    if (sel) {
      sel.innerHTML = '';
      presetModels.forEach(m => {
        const opt = document.createElement('option');
        opt.value = opt.textContent = m;
        sel.appendChild(opt);
      });
    }
    if (urlRow) urlRow.style.display = 'none';
  }
}

// ── Blind game checkbox handler ───────────────────────────────────────────
// When the full-game blind checkbox is ticked, disable (but don't clear) the
// blind opening moves counter — the two modes are mutually exclusive since
// full-game blind already covers every move.
function onBlindChange(side) {
  const blindChecked = document.getElementById(side + 'Blind')?.checked;
  const blindMovesInput = document.getElementById(side + 'BlindMoves');
  if (!blindMovesInput) return;
  blindMovesInput.disabled = !!blindChecked;
  if (blindChecked) blindMovesInput.title = 'Disabled — full-game blind mode is active';
  else blindMovesInput.title = '';
}

// ── WebSocket event dispatch ──────────────────────────────────────────────
function onGameStart(d) {
  gameState.white    = { name: d.white, elo: d.white_elo, model_id: d.white_model_id || null, portrait_url: null };
  gameState.black    = { name: d.black, elo: d.black_elo, model_id: d.black_model_id || null, portrait_url: null };
  gameState.fen      = d.fen || gameState.fen;
  gameState.lastUci    = null;
  gameState.thinking   = null;
  gameState.candidates = [];
  gameState.lastEvalCp = null;
  gameState.isHumanTurn = false;
  gameState.humanLegalUci = [];
  gameState.humanCandidates = [];
  // Determine which color (if any) is the human player
  if (d.white_is_human) gameState.humanColor = 'white';
  else if (d.black_is_human) gameState.humanColor = 'black';
  else gameState.humanColor = null;
  // Do NOT reset humanAssisted here — game_start doesn't carry it, so
  // d.human_assisted is undefined, which would always coerce to true and
  // override the value already set by tournament_status.
  _allLessons = {};
  evalHistory = [];
  gameState.elapsedSum   = { white: 0, black: 0 };
  gameState.elapsedCount = { white: 0, black: 0 };
  document.getElementById('latencyWhite').textContent = '';
  document.getElementById('latencyBlack').textContent = '';
  document.getElementById('evalPane').style.display = 'none';
  document.getElementById('historyPane').innerHTML = '';
  document.getElementById('overlay').classList.remove('show');
  // Reset stat cards — close and clear cached data
  for (const color of ['white', 'black']) {
    _statCardCache[color] = null;
    const cap = color[0].toUpperCase() + color.slice(1);
    const card = document.getElementById(`statCard${cap}`);
    const chev = document.getElementById(`chevron${cap}`);
    if (card) { card.classList.remove('open'); card.innerHTML = ''; }
    if (chev) chev.classList.remove('open');
  }
  // Reset avatars
  ['White','Black'].forEach(c => {
    const el = document.getElementById(`avatar${c}`);
    el.src = ''; el.style.display = 'none';
  });
  updatePlayers(); updateAnalysis(); _cmcbRender(false);
  // Kick off portrait fetch for both players (non-blocking)
  if (d.white_model_id) fetchPortrait(d.white_model_id, 'White');
  if (d.black_model_id) fetchPortrait(d.black_model_id, 'Black');
}

async function fetchPortrait(modelId, color) {
  if (_portraitQuotaExhausted) return;
  try {
    const r = await fetch(`${API}/api/models/${encodeURIComponent(modelId)}/portrait`, { method: 'POST' });
    const j = await r.json();
    if (j.quota_exhausted) _portraitQuotaExhausted = true;
    if (j.portrait_url) {
      gameState[color.toLowerCase()].portrait_url = j.portrait_url;
      const el = document.getElementById(`avatar${color}`);
      el.onload = () => { el.style.display = 'block'; };
      el.src = j.portrait_url;
    }
  } catch(e) { /* portrait optional */ }
}

function onThinking(d) {
  gameState.fen        = d.fen || gameState.fen;
  gameState.thinking   = d.color;
  gameState.candidates = d.candidates || [];
  gameState.isBlindMove = !!d.is_blind_move;
  if (d.color==='white' && d.player) gameState.white.name = d.player;
  if (d.color==='black' && d.player) gameState.black.name = d.player;

  // Human-play setup
  gameState.isHumanTurn   = !!d.is_human_turn;
  gameState.humanLegalUci = d.legal_uci || [];
  gameState.humanCandidates = (d.candidates || []).map(c => c.uci);

  // Show/hide "YOUR MOVE" banner
  const banner = document.getElementById('humanTurnBanner');
  if (banner) banner.classList.toggle('show', gameState.isHumanTurn);

  // Show/hide blind-mode indicator on the active player's thinking row
  const thinkEl = document.getElementById(d.color === 'white' ? 'thinkWhite' : 'thinkBlack');
  if (thinkEl) {
    const badge = thinkEl.querySelector('.blind-badge');
    if (d.is_blind_move) {
      if (!badge) thinkEl.insertAdjacentHTML('beforeend', '<span class="blind-badge">BLIND</span>');
    } else {
      if (badge) badge.remove();
    }
  }

  // Draw candidate arrows (clear old ones first; skip in blind mode — no arrows)
  if (_cmcb.ready && _cmcb.board) {
    _cmcb.board.removeArrows();
    if (!d.is_blind_move) {
      (gameState.candidates || []).forEach((cand, i) => {
        const uci = cand.uci || cand.move || '';
        if (uci.length >= 4) {
          const from = uci.slice(0, 2), to = uci.slice(2, 4);
          _cmcb.board.addArrow(i === 0 ? _cmcb.ARROW_TYPE.default : _cmcb.ARROW_TYPE.secondary, from, to);
        }
      });
    }
  }

  updatePlayers(); updateAnalysis(); _cmcbRender(false);
}

function onMove(d) {
  gameState.fen        = d.fen;
  gameState.lastUci    = d.uci;
  gameState.thinking   = null;
  gameState.candidates = [];
  gameState.isHumanTurn = false;
  gameState.humanLegalUci = [];
  const banner = document.getElementById('humanTurnBanner');
  if (banner) banner.classList.remove('show');
  if (d.score_cp_white != null) gameState.lastEvalCp = d.score_cp_white;
  // Accumulate per-player avg response time (skip book moves and timeouts)
  if (d.elapsed_ms != null && !d.is_book_move && !d.timed_out) {
    const col = (d.move_number % 2 === 1) ? 'white' : 'black';
    gameState.elapsedSum[col]   += d.elapsed_ms;
    gameState.elapsedCount[col] += 1;
    const avg = gameState.elapsedSum[col] / gameState.elapsedCount[col];
    const el  = document.getElementById(`latency${col[0].toUpperCase() + col.slice(1)}`);
    if (el) el.textContent = `⌚ ${(avg / 1000).toFixed(1)}s`;
  }
  // Clear candidate arrows on move
  if (_cmcb.ready && _cmcb.board) _cmcb.board.removeArrows();
  updatePlayers(); updateAnalysis(); _cmcbRender(true);  // true = animate
  addMoveCard(d);
  pushEval(d.move_number, d.score_cp_white);
}

function onGameOver(d) {
  gameState.thinking = null;
  gameState.isHumanTurn = false;
  // Clear candidate arrows on game over
  if (_cmcb.ready && _cmcb.board) _cmcb.board.removeArrows();
  const banner = document.getElementById('humanTurnBanner');
  if (banner) banner.classList.remove('show');
  updatePlayers();

  const resultMap = { '1-0':'White Wins','0-1':'Black Wins','1/2-1/2':'Draw' };
  const label = resultMap[d.result] || d.result;
  const term  = d.termination ? d.termination.charAt(0).toUpperCase()+d.termination.slice(1) : '';

  gameState.lastGameId = d.game_id || null;
  document.getElementById('ovResult').textContent  = label;
  document.getElementById('ovSub').textContent     = [term, d.total_moves?`${d.total_moves} moves`:''].filter(Boolean).join(' · ');
  document.getElementById('ovOpening').textContent = d.opening_name
    ? `${d.opening_eco} · ${d.opening_name}` : '';
  document.getElementById('ovDownloadBtn').style.display = d.game_id ? '' : 'none';
  document.getElementById('ovLichessBtn').style.display  = d.game_id ? '' : 'none';

  // ELO delta — compute before gameState.white/black.elo is updated below
  function _eloDeltaChip(before, after) {
    if (before == null || after == null) return '';
    const delta = Math.round(after - before);
    if (delta === 0) return `<span class="ov-elo-delta zero">±0</span>`;
    const sign = delta > 0 ? '+' : '';
    const cls  = delta > 0 ? 'pos' : 'neg';
    return `<span class="ov-elo-delta ${cls}">${sign}${delta}</span>`;
  }
  const eloHtml = `
    <div class="ov-elo-block"><div class="ov-elo-name">${escHtml(gameState.white.name)}</div>
      <div class="ov-elo-val">${d.white_elo_after!=null?Math.round(d.white_elo_after):'—'}${_eloDeltaChip(gameState.white.elo, d.white_elo_after)}</div></div>
    <div class="ov-elo-block"><div class="ov-elo-name">${escHtml(gameState.black.name)}</div>
      <div class="ov-elo-val">${d.black_elo_after!=null?Math.round(d.black_elo_after):'—'}${_eloDeltaChip(gameState.black.elo, d.black_elo_after)}</div></div>`;
  document.getElementById('ovElos').innerHTML = eloHtml;

  // Freshly-earned achievements
  const ach = d.achievements || { white: [], black: [] };
  const renderForSide = (color, list) => list.map(a =>
    `<span class="mc-badge badge-${a.code}" title="${escHtml(a.desc)} (${color})">${escHtml(a.label)}</span>`
  ).join('');
  const badgesHtml = renderForSide('White', ach.white || []) + renderForSide('Black', ach.black || []);
  document.getElementById('ovBadges').innerHTML = badgesHtml;
  document.getElementById('ovBadgesLabel').style.display = badgesHtml ? '' : 'none';

  document.getElementById('overlay').classList.add('show');

  if (d.white_elo_after!=null) gameState.white.elo = d.white_elo_after;
  if (d.black_elo_after!=null) gameState.black.elo = d.black_elo_after;
  updatePlayers();
  loadLeaderboard();
  loadHistory();
  // Refresh any open stat cards to show updated ELO
  for (const color of ['white', 'black']) {
    const cap  = color[0].toUpperCase() + color.slice(1);
    const card = document.getElementById(`statCard${cap}`);
    if (card && card.classList.contains('open')) loadStatCard(color);
  }
}

function onLessons(d) {
  showLessons(d.player, d.color, d.improve || [], d.strength || []);
}

function onLessonGenerating(d) {
  const el = document.getElementById('lessonSpinner');
  if (!el) return;
  const tutor = document.getElementById('lsTutor');
  if (tutor) tutor.textContent = d.tutor_model ? `via ${d.tutor_model}` : '';
  el.classList.add('show');
}

function onLessonsSaved() {
  const el = document.getElementById('lessonSpinner');
  if (el) el.classList.remove('show');
}

function renderStandings(standings) {
  const sec  = document.getElementById('standingsSection');
  const body = document.getElementById('standingsBody');
  if (!standings || !standings.length) { sec.style.display = 'none'; return; }
  sec.style.display = '';

  // Build a model_id → name lookup for series tooltips
  const nameMap = {};
  standings.forEach(s => { nameMap[s.model_id] = s.name; });

  let html = `<div class="standings-wrap">
    <table class="stn-table">
      <thead><tr>
        <th>#</th><th>Player</th><th>Pts</th><th>W-D-L</th>
      </tr></thead><tbody>`;
  standings.forEach((s, i) => {
    // Build series tooltip: "vs Llama: 2-0, vs Gemma: 1-1"
    let seriesTip = '';
    if (s.series && Object.keys(s.series).length) {
      seriesTip = Object.entries(s.series).map(([oppId, wins]) => {
        const myW  = wins[s.model_id]   || 0;
        const oppW = wins[oppId] || 0;
        return `vs ${nameMap[oppId] || oppId}: ${myW}-${oppW}`;
      }).join(', ');
    }
    const seriesCell = seriesTip
      ? `<td class="stn-series" title="${escHtml(seriesTip)}">series ⓘ</td>`
      : '';
    html += `<tr class="${i===0?'stn-leader':''}">
      <td class="stn-rank">${i+1}</td>
      <td class="stn-name">${escHtml(s.name)}</td>
      <td class="stn-pts">${s.points}</td>
      <td class="stn-wdl">${s.wins}-${s.draws}-${s.losses}</td>
      ${seriesCell}
    </tr>`;
  });
  html += '</tbody></table></div>';
  body.innerHTML = html;
}

function onStandingsUpdate(d) {
  renderStandings(d.standings);
}

// ── Elimination bracket ───────────────────────────────────────────────────

function renderBracket(bracket) {
  const sec  = document.getElementById('bracketSection');
  const body = document.getElementById('bracketBody');
  if (!bracket || !bracket.rounds || !bracket.rounds.length) {
    if (sec) sec.style.display = 'none';
    return;
  }
  if (sec) sec.style.display = '';

  const rounds = bracket.rounds;

  // Detect champion: winner of the final match
  const finalMatch = rounds[rounds.length - 1].matches[0];
  const champion = finalMatch && finalMatch.winner
    ? { id: finalMatch.winner, name: finalMatch.winner === finalMatch.white ? finalMatch.white_name : finalMatch.black_name }
    : null;

  let html = '';

  // Champion banner
  if (champion) {
    html += `<div class="bracket-champion">🏆 Champion: ${escHtml(champion.name)}</div>`;
  }

  html += '<div class="bracket-wrap">';

  rounds.forEach((round, rIdx) => {
    const isLast = rIdx === rounds.length - 1;
    html += `<div class="bracket-round">
      <div class="bracket-round-name">${escHtml(round.name)}</div>`;

    round.matches.forEach((m, mIdx) => {
      const wWon    = m.winner && m.winner === m.white;
      const bWon    = m.winner && m.winner === m.black;
      const isBye   = m.bye;
      const pending = !m.winner && !isBye;
      const isChampMatch = champion && m.winner === champion.id && isLast;

      const wSeed = m.white_seed ? `<span class="bracket-seed">${m.white_seed}</span>` : '';
      const bSeed = m.black_seed ? `<span class="bracket-seed">${m.black_seed}</span>` : '';

      html += `<div class="bracket-match${pending ? ' pending' : ''}${isBye ? ' bye' : ''}${isChampMatch ? ' champion' : ''}">`;
      html += `<div class="bracket-player${wWon ? ' winner' : bWon ? ' loser' : ''}">${wSeed}${escHtml(m.white_name || 'TBD')}</div>`;
      html += `<div class="bracket-vs">${isBye ? '—' : 'vs'}</div>`;
      html += `<div class="bracket-player${bWon ? ' winner' : wWon ? ' loser' : ''}">${bSeed}${escHtml(m.black_name || 'TBD')}</div>`;
      if (m.winner) {
        const wname = wWon ? (m.white_name || '') : (m.black_name || '');
        html += `<div class="bracket-winner-tag">${isChampMatch ? '🏆' : '▶'} ${escHtml(wname)}</div>`;
      }
      html += '</div>';

      // Connector line between matches (except last round)
      if (!isLast && mIdx % 2 === 0 && mIdx + 1 < round.matches.length) {
        html += '<div class="bracket-connector"></div>';
      }
    });

    html += '</div>'; // .bracket-round
  });

  html += '</div>'; // .bracket-wrap
  body.innerHTML = html;
}

function onBracketUpdate(d) {
  renderBracket(d.bracket);
}

function onTournamentComplete(d) {
  renderStandings(d.standings);
  if (d.bracket) renderBracket(d.bracket);
  loadLeaderboard();
  loadTournamentHistory();
  // Show winner title in game-over overlay style
  if (d.winner && d.title) {
    const ov = document.getElementById('overlay');
    document.getElementById('ovResult').textContent  = '🏆 Tournament Complete';
    document.getElementById('ovSub').textContent     = `Winner: ${d.winner.name}`;
    document.getElementById('ovOpening').textContent = '';
    document.getElementById('ovElos').innerHTML = `<div class="ov-title-badge">"${escHtml(d.title)}"</div>`;
    document.getElementById('ovBadgesLabel').style.display = 'none';
    document.getElementById('ovBadges').innerHTML = '';
    document.getElementById('ovDownloadBtn').style.display = 'none';
    ov.style.display = 'flex';
  }
}

async function loadTournamentHistory() {
  try {
    const history = await fetch(`${API}/api/tournament/history`).then(r=>r.json());
    const body = document.getElementById('tournamentHistoryBody');
    if (!history || !history.length) {
      body.innerHTML = '<div class="lb-empty">No tournaments yet</div>';
      return;
    }
    const fmtLabel = { round_robin: 'Round Robin', gauntlet: 'Gauntlet', match: 'Match', elimination: 'Elimination' };
    body.innerHTML = history.map(t => {
      const date  = t.finished_at ? t.finished_at.slice(0,10) : (t.started_at||'').slice(0,10);
      const games = t.total_games || '?';
      return `<div class="th-row">
        <span class="th-format">${escHtml(fmtLabel[t.format]||t.format)}</span>
        <span class="th-winner">${escHtml(t.winner_name || '—')}</span>
        <span class="th-title">${t.title ? '"'+escHtml(t.title)+'"' : ''}</span>
        <span class="th-meta">${games}g · ${date}</span>
      </div>`;
    }).join('');
  } catch(e) {}
}

function onTournamentStatus(d) {
  updateTournamentUI(d.status, d.game_number, d.total_games);
  if (d.white)      gameState.white.name = d.white;
  if (d.black)      gameState.black.name = d.black;
  if (d.white_elo)  gameState.white.elo  = d.white_elo;
  if (d.black_elo)  gameState.black.elo  = d.black_elo;
  if (d.white_is_human != null) {
    if (d.white_is_human) gameState.humanColor = 'white';
    else if (d.black_is_human) gameState.humanColor = 'black';
    else gameState.humanColor = null;
  }
  if (d.human_assisted != null) gameState.humanAssisted = d.human_assisted;
  // Clear thinking state when the tournament stops — prevents stale
  // "● thinking" indicator and analysis dot from lingering on screen.
  if (d.status === 'idle' || d.status === 'stopping') {
    gameState.thinking = null;
    gameState.isHumanTurn = false;
    const banner = document.getElementById('humanTurnBanner');
    if (banner) banner.classList.remove('show');
  }
  // Show/hide live standings
  if (d.standings) renderStandings(d.standings);
  else if (d.format === 'match' || d.format === 'elimination' || !d.format) {
    document.getElementById('standingsSection').style.display = 'none';
  }
  // Show/hide bracket (elimination format)
  if (d.bracket) renderBracket(d.bracket);
  else if (d.format !== 'elimination') {
    const bsec = document.getElementById('bracketSection');
    if (bsec) bsec.style.display = 'none';
  }
  updatePlayers();
  updateAnalysis();
  if (d.status === 'idle') { loadLeaderboard(); loadTournamentHistory(); }
}

function onInitialState(d) {
  updateTournamentUI(d.status || 'idle', d.game_number || 0, d.total_games || 0);
  if (d.standings) renderStandings(d.standings);
  if (d.bracket)   renderBracket(d.bracket);
  loadTournamentHistory();
}

// ── Inline stat cards ─────────────────────────────────────────────────────
// Cache: { white: {open, profile, eloHist} | null, black: ... }
const _statCardCache = { white: null, black: null };

function toggleStatCard(color) {
  const card = document.getElementById(`statCard${color[0].toUpperCase() + color.slice(1)}`);
  const chevron = document.getElementById(`chevron${color[0].toUpperCase() + color.slice(1)}`);
  if (!card) return;
  const opening = !card.classList.contains('open');
  card.classList.toggle('open', opening);
  if (chevron) chevron.classList.toggle('open', opening);
  if (opening) loadStatCard(color);
}

async function loadStatCard(color) {
  const cap    = color[0].toUpperCase() + color.slice(1);
  const player = gameState[color];
  const card   = document.getElementById(`statCard${cap}`);
  if (!card || !player.model_id) {
    if (card) card.innerHTML = '<div class="sc-row" style="padding:4px 0;color:var(--text-dim);font-size:9px">No model active</div>';
    return;
  }
  card.innerHTML = '<div class="sc-row" style="padding:4px 0;color:var(--text-dim);font-size:9px">Loading…</div>';
  try {
    const oppColor  = color === 'white' ? 'black' : 'white';
    const oppId     = gameState[oppColor].model_id;
    const [profile, eloHist, h2h] = await Promise.all([
      fetch(`${API}/api/models/${encodeURIComponent(player.model_id)}/profile`).then(r => r.json()),
      fetch(`${API}/api/elo-history/${encodeURIComponent(player.model_id)}`).then(r => r.json()).catch(() => []),
      oppId
        ? fetch(`${API}/api/models/${encodeURIComponent(player.model_id)}/h2h/${encodeURIComponent(oppId)}`).then(r => r.json()).catch(() => null)
        : Promise.resolve(null),
    ]);
    _statCardCache[color] = { profile, eloHist, h2h };
    renderStatCard(color, profile, eloHist, h2h);
  } catch(e) {
    if (card) card.innerHTML = '<div class="sc-row" style="padding:4px 0;color:var(--text-dim);font-size:9px">Failed to load</div>';
  }
}

function renderStatCard(color, p, eloHist, h2h) {
  const cap  = color[0].toUpperCase() + color.slice(1);
  const card = document.getElementById(`statCard${cap}`);
  if (!card) return;

  const m = p.moves || {};
  const c = p.color || {};
  const g = p.games || {};
  const total   = m.total_moves || 0;
  const wins    = (c.white_wins||0)  + (c.black_wins||0);
  const draws   = (c.white_draws||0) + (c.black_draws||0);
  const losses  = (c.white_losses||0)+ (c.black_losses||0);
  const blRate  = total ? ((m.q_blunder||0)/total*100).toFixed(1)+'%' : '—';
  const avgRank = m.avg_rank ? m.avg_rank.toFixed(1) : '—';

  // Mini sparkline from ELO history (last 10 data points)
  const hist10 = (eloHist || []).slice(-10).map(e => e.elo || e);
  const spark  = hist10.length >= 2
    ? `<div class="sc-sparkline">${buildSparkline(hist10, 68, 18, 'var(--gold)')}</div>`
    : '';

  // H2H vs current opponent
  let h2hHtml = '';
  if (h2h && h2h.total > 0) {
    h2hHtml = `<div class="sc-stat">
      <span class="sc-val">${h2h.wins}-${h2h.draws}-${h2h.losses}</span>
      <span class="sc-lbl">vs opp</span>
    </div>`;
  }

  // Tournament standing if bracket running
  let tournHtml = '';
  if (tournamentStatus === 'running' && gameState.standings) {
    const row = gameState.standings.find(s => s.model_id === p.model_id);
    if (row) {
      const pts = typeof row.points !== 'undefined' ? row.points : '—';
      tournHtml = `<div class="sc-stat">
        <span class="sc-val">${pts}</span>
        <span class="sc-lbl">pts</span>
      </div>`;
    }
  }

  // Style badge
  const style  = p.style || '';
  const badge  = style ? `<span class="sc-badge">${escHtml(style)}</span>` : '';

  card.innerHTML = `
    <div class="sc-row">
      <div class="sc-stat">
        <span class="sc-val">${p.elo ?? '—'}</span>
        <span class="sc-lbl">ELO</span>
      </div>
      ${spark ? `<div class="sc-stat">${spark}<span class="sc-lbl">trend</span></div>` : ''}
      <div class="sc-stat">
        <span class="sc-val">${wins}/${draws}/${losses}</span>
        <span class="sc-lbl">W/D/L</span>
      </div>
      <div class="sc-stat">
        <span class="sc-val">${blRate}</span>
        <span class="sc-lbl">blunders</span>
      </div>
      <div class="sc-stat">
        <span class="sc-val">${avgRank}</span>
        <span class="sc-lbl">avg cand</span>
      </div>
      ${h2hHtml}
      ${tournHtml}
      ${badge ? `<div class="sc-stat" style="border:none">${badge}</div>` : ''}
      <div class="sc-stat" style="border:none;cursor:pointer;color:var(--text-mid)"
           onclick="openModelCard('${escHtml(p.model_id || '').replace(/'/g,"\\'")}')">
        <span class="sc-val" style="font-size:9px">↗</span>
        <span class="sc-lbl">full card</span>
      </div>
    </div>`;
}

function dispatch(msg) {
  try {
    const d = JSON.parse(msg);
    switch (d.type) {
      case 'game_start':        onGameStart(d);        break;
      case 'thinking':          onThinking(d);         break;
      case 'move':              onMove(d);             break;
      case 'game_over':         onGameOver(d);         break;
      case 'lessons':           onLessons(d);          break;
      case 'lesson_generating': onLessonGenerating(d); break;
      case 'lessons_saved':     onLessonsSaved();      break;
      case 'tournament_status':      onTournamentStatus(d);      break;
      case 'standings_update':       onStandingsUpdate(d);       break;
      case 'tournament_complete':    onTournamentComplete(d);    break;
      case 'bracket_update':         onBracketUpdate(d);         break;
      case 'state':                  onInitialState(d);          break;
      case 'puzzle_gauntlet_start':  onPuzzleGauntletStart(d);  break;
      case 'puzzle_thinking':        onPuzzleThinking(d);        break;
      case 'puzzle_result':          onPuzzleResult(d);          break;
      case 'puzzle_gauntlet_over':   onPuzzleGauntletOver(d);   break;
    }
  } catch(e) { console.warn('Bad WS message:', e); }
}

// ── WebSocket ─────────────────────────────────────────────────────────────
let ws, reconnTimer;

function setConn(status) {
  const map = { connected:'live', disconnected:'dead', reconnecting:'waiting' };
  document.getElementById('dot').className   = 'dot ' + (map[status]||'waiting');
  document.getElementById('connLabel').textContent = status==='connected'?'live':status;
}

function connect() {
  clearTimeout(reconnTimer);
  setConn('reconnecting');
  try { ws = new WebSocket(WS_URL); } catch(e) { schedReconn(); return; }
  ws.onopen    = () => setConn('connected');
  ws.onmessage = e  => dispatch(e.data);
  ws.onerror   = () => {};
  ws.onclose   = () => { setConn('disconnected'); schedReconn(); };
}

function schedReconn() { reconnTimer = setTimeout(connect, 2500); }

// ── Collapsible panels ────────────────────────────────────────────────────
function downloadPgn() {
  const id = gameState.lastGameId;
  if (!id) return;
  const a = document.createElement('a');
  a.href = `${API}/api/games/${id}/pgn`;
  a.download = '';   // server sets filename via Content-Disposition
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function _fetchAndOpenLichess(gameId) {
  try {
    // Fetch the annotated PGN, strip lengthy reasoning comments so the URL
    // stays compact (Lichess only needs moves + glyphs for analysis).
    const resp = await fetch(`${API}/api/games/${gameId}/pgn`);
    let pgn = await resp.text();
    // Remove { ... } comment blocks (reasoning text) but keep move glyphs
    pgn = pgn.replace(/\{[^}]*\}/g, '').replace(/\s{2,}/g, ' ').trim();
    window.open(`https://lichess.org/paste?pgn=${encodeURIComponent(pgn)}`, '_blank', 'noopener');
  } catch(e) {
    window.open('https://lichess.org/analysis', '_blank', 'noopener');
  }
}

function openLichess() {
  const id = gameState.lastGameId;
  if (!id) return;
  _fetchAndOpenLichess(id);
}

function openLichessById(gameId) {
  _fetchAndOpenLichess(gameId);
}

function exportAllPgn(modelId) {
  const url = modelId
    ? `${API}/api/games/export?model_id=${encodeURIComponent(modelId)}`
    : `${API}/api/games/export`;
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ── Game replay ───────────────────────────────────────────────────────────
const QUALITY_GLYPH = { best:'!!', excellent:'!', inaccuracy:'?!', mistake:'?', blunder:'??' };
const QUALITY_COLOR = { best:'#ffd700', excellent:'#56c45a', good:'', inaccuracy:'#f0d030', mistake:'#f09020', blunder:'#e83030' };

const replay = { moves: [], cursor: 0, meta: null, gameId: null };
let _rpAutoplayTimer = null;

function rpToggleAutoplay() {
  if (_rpAutoplayTimer) {
    clearInterval(_rpAutoplayTimer);
    _rpAutoplayTimer = null;
  } else {
    _rpAutoplayTimer = setInterval(() => {
      if (replay.cursor >= replay.moves.length) {
        clearInterval(_rpAutoplayTimer);
        _rpAutoplayTimer = null;
        const btn = document.getElementById('rpPlay');
        if (btn) btn.textContent = '▶';
        return;
      }
      rpGo(replay.cursor + 1);
    }, 1200);
  }
  const btn = document.getElementById('rpPlay');
  if (btn) btn.textContent = _rpAutoplayTimer ? '⏸' : '▶';
}

async function openReplay(gameId, meta) {
  try {
    // If caller didn't pass meta (e.g. opened from leaderboard), fetch it.
    if (!meta) {
      meta = await fetch(`${API}/api/games/${gameId}`).then(r => r.json());
    }
    const moves = await fetch(`${API}/api/games/${gameId}/moves`).then(r => r.json());
    replay.moves  = moves;
    replay.cursor = 0;
    replay.meta   = meta;
    replay.gameId = gameId;

    // Populate player strips
    document.getElementById('rpNameWhite').textContent = meta.white_name;
    document.getElementById('rpNameBlack').textContent = meta.black_name;
    document.getElementById('rpEloWhite').textContent  = `ELO ${Math.round(meta.white_elo_before)} → ${Math.round(meta.white_elo_after)}`;
    document.getElementById('rpEloBlack').textContent  = `ELO ${Math.round(meta.black_elo_before)} → ${Math.round(meta.black_elo_after)}`;
    document.getElementById('rpTitle').textContent     = `${meta.white_name} vs ${meta.black_name}  ·  ${meta.result}`;

    // Build per-player quality summary
    const wSum = {blunder:0, mistake:0, inaccuracy:0};
    const bSum = {blunder:0, mistake:0, inaccuracy:0};
    moves.forEach(m => {
      const s = m.move_number % 2 === 1 ? wSum : bSum;
      if (m.quality === 'blunder')    s.blunder++;
      else if (m.quality === 'mistake')    s.mistake++;
      else if (m.quality === 'inaccuracy') s.inaccuracy++;
    });
    function _summaryChips(s) {
      const parts = [];
      if (s.blunder)    parts.push(`<span class="rp-sum-chip blunder">${s.blunder}??</span>`);
      if (s.mistake)    parts.push(`<span class="rp-sum-chip mistake">${s.mistake}?</span>`);
      if (s.inaccuracy) parts.push(`<span class="rp-sum-chip inaccuracy">${s.inaccuracy}?!</span>`);
      return parts.join('') || '<span class="rp-sum-chip clean">clean</span>';
    }
    const summaryHtml = `<div class="rp-summary">
      <span class="rp-sum-label">${escHtml(meta.white_name)}</span>${_summaryChips(wSum)}
      <span class="rp-sum-sep">·</span>
      <span class="rp-sum-label">${escHtml(meta.black_name)}</span>${_summaryChips(bSum)}
    </div>`;

    // Build move list
    const list = document.getElementById('rpMoveList');
    let listHtml = summaryHtml + `<div class="rp-move-item" data-idx="0" onclick="rpGo(0)" style="color:var(--text-dim);font-style:italic">
      <span class="rp-move-num"></span><span class="rp-move-san">start</span>
    </div>`;
    moves.forEach((m, i) => {
      const isWhite  = m.move_number % 2 === 1;
      const numLabel = isWhite ? `${Math.ceil(m.move_number / 2)}.` : '';
      const glyph    = QUALITY_GLYPH[m.quality] || '';
      const color    = QUALITY_COLOR[m.quality] || 'var(--text)';
      const latency  = (m.elapsed_ms != null && !m.timed_out)
        ? `<span class="rp-elapsed">${(m.elapsed_ms/1000).toFixed(1)}s</span>` : '';
      const evalBadge = m.score_cp != null
        ? `<span class="rp-eval-badge">${m.score_cp > 0 ? '+' : ''}${(m.score_cp/100).toFixed(2)}</span>` : '';
      listHtml += `<div class="rp-move-item" data-idx="${i+1}" onclick="rpGo(${i+1})">
        <span class="rp-move-num">${numLabel}</span>
        <span class="rp-move-san" style="color:${color}">${m.move_san}${glyph}</span>
        <span class="rp-move-qual" style="color:${color}">${glyph}</span>
        ${latency}${evalBadge}
      </div>`;
    });
    list.innerHTML = listHtml;

    document.getElementById('replayModal').classList.add('show');
    rpRender();
    rpRenderEvalChart();
  } catch(e) { console.error('Replay load failed', e); }
}

function closeReplay() {
  document.getElementById('replayModal').classList.remove('show');
  if (_rpAutoplayTimer) { clearInterval(_rpAutoplayTimer); _rpAutoplayTimer = null; }
}

function copyReplayLink() {
  if (!replay.gameId) return;
  const url = `${location.origin}/watch/${replay.gameId}`;
  const btn = document.getElementById('rpShareBtn');
  navigator.clipboard.writeText(url).then(() => {
    btn.textContent = '✓';
    setTimeout(() => { btn.textContent = '🔗'; }, 1400);
  }).catch(() => {
    // Fallback for insecure / older contexts
    prompt('Copy this link:', url);
  });
}

// ── Model card modal ──────────────────────────────────────────────────────

// Store current model card's model_id so upload handler can reference it
let _mcCurrentModelId = null;
// Session flag: true once server reports quota exhausted
let _portraitQuotaExhausted = false;

function renderPortraitBlock(p) {
  const mid    = escHtml(p.model_id || '');
  const midJs  = (p.model_id || '').replace(/\\/g,'\\\\').replace(/'/g, "\\'");
  const upBtn  = `<button class="mc-portrait-btn" onclick="triggerPortraitUpload('${midJs}')">📷 Upload photo</button>`;
  const regenBtn = (p.user_provided_portrait || _portraitQuotaExhausted) ? '' :
    `<button class="mc-portrait-btn" onclick="regenPortrait('${midJs}')">↺ Regenerate AI</button>`;
  const quotaNote = _portraitQuotaExhausted
    ? `<div class="mc-quota-notice">Portrait generation unavailable (API quota)</div>` : '';

  const actions = `<div class="mc-portrait-actions">${upBtn}${regenBtn}</div>${quotaNote}`;

  if (p.portrait_url) {
    return `<img class="mc-portrait" src="${escHtml(p.portrait_url)}" alt="${escHtml(p.name || '')} portrait">${actions}`;
  }
  const family = (p.metadata && p.metadata.family) || '';
  const icon = family ? family[0].toUpperCase() : '♟';
  return `<div class="mc-portrait-placeholder">${icon}</div>${actions}`;
}

function triggerPortraitUpload(modelId) {
  _mcCurrentModelId = modelId;
  document.getElementById('portraitUploadInput').value = '';
  document.getElementById('portraitUploadInput').click();
}

async function handlePortraitUpload(event) {
  const file = event.target.files[0];
  if (!file || !_mcCurrentModelId) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch(`${API}/api/models/${encodeURIComponent(_mcCurrentModelId)}/portrait/upload`, {
      method: 'POST', body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(`Upload failed: ${err.detail || r.status}`);
      return;
    }
    const j = await r.json();
    if (j.portrait_url) {
      // Refresh the model card
      openModelCard(_mcCurrentModelId);
      // Update in-game avatar if this is an active player
      for (const color of ['white','black']) {
        if (gameState[color].model_id === _mcCurrentModelId) {
          const el = document.getElementById(`avatar${color[0].toUpperCase() + color.slice(1)}`);
          el.onload = () => { el.style.display = 'block'; };
          el.src = j.portrait_url;
          gameState[color].portrait_url = j.portrait_url;
        }
      }
    }
  } catch(e) { console.error('Portrait upload failed:', e); }
}

async function regenPortrait(modelId) {
  // Swap portrait area to spinner while generating
  const placeholder = document.getElementById('mcCard').querySelector('.mc-portrait, .mc-portrait-placeholder');
  if (placeholder) placeholder.outerHTML = `<div class="mc-portrait-generating"><div class="spinner"></div>Painting…</div>`;
  try {
    const r = await fetch(`${API}/api/models/${encodeURIComponent(modelId)}/portrait`, { method: 'POST' });
    const j = await r.json();
    if (j.quota_exhausted) {
      _portraitQuotaExhausted = true;
    }
    if (j.portrait_url) {
      openModelCard(modelId);
    } else {
      const gen = document.getElementById('mcCard').querySelector('.mc-portrait-generating');
      if (gen) gen.outerHTML = `<div class="mc-portrait-placeholder">♟</div>`;
    }
  } catch(e) {
    const gen = document.getElementById('mcCard').querySelector('.mc-portrait-generating');
    if (gen) gen.outerHTML = `<div class="mc-portrait-placeholder">♟</div>`;
  }
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

// Generic sparkline from a plain array of numbers (used for coherence trend).
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

function rpGo(idx) {
  replay.cursor = Math.max(0, Math.min(idx, replay.moves.length));
  rpRender();
}

function rpRender() {
  const { moves, cursor } = replay;
  const STARTING_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

  // FEN: position 0 = start, position N = after move N
  const fen    = cursor === 0 ? STARTING_FEN : moves[cursor - 1].fen_after;
  const lastUci = cursor === 0 ? null : moves[cursor - 1].move_uci;

  rpDrawBoard(fen, lastUci);

  // Counter
  const total = moves.length;
  const label = cursor === 0
    ? `start`
    : `${Math.ceil(moves[cursor-1].move_number / 2)}${moves[cursor-1].move_number % 2 === 1 ? '.' : '...'} ${moves[cursor-1].move_san}`;
  document.getElementById('rpCounter').textContent = `${cursor}/${total}  ${label}`;

  // Button states
  document.getElementById('rpFirst').disabled = cursor === 0;
  document.getElementById('rpPrev').disabled  = cursor === 0;
  document.getElementById('rpNext').disabled  = cursor === total;
  document.getElementById('rpLast').disabled  = cursor === total;

  // Highlight active move in list
  document.querySelectorAll('#rpMoveList .rp-move-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.idx) === cursor);
  });
  // Scroll active item into view
  const active = document.querySelector('#rpMoveList .rp-move-item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });

  // Reasoning panel — show reasoning for the current move
  const rpReasEl = document.getElementById('rpReasoning');
  if (rpReasEl) {
    if (cursor > 0 && moves[cursor - 1] && moves[cursor - 1].reasoning) {
      const m = moves[cursor - 1];
      const isWhite = m.move_number % 2 === 1;
      const mover = isWhite
        ? (replay.meta && replay.meta.white_name ? replay.meta.white_name : 'White')
        : (replay.meta && replay.meta.black_name ? replay.meta.black_name : 'Black');
      const elapsed = m.elapsed_ms != null ? `<span class="rp-reas-time">${(m.elapsed_ms/1000).toFixed(1)}s</span>` : '';
      rpReasEl.innerHTML = `<div class="rp-reas-mover">${escHtml(mover)}${elapsed}</div>`
        + `<div class="rp-reas-text">${escHtml(m.reasoning)}</div>`;
      rpReasEl.style.display = '';
    } else {
      rpReasEl.style.display = 'none';
    }
  }

  // Update autoplay button label
  const playBtn = document.getElementById('rpPlay');
  if (playBtn) playBtn.textContent = _rpAutoplayTimer ? '⏸' : '▶';

  // Update eval chart cursor
  rpRenderEvalChart();
}

function rpDrawBoard(fen, lastUci) {
  if (!_cmcb.ready || !_cmcb.rpBoard) return;
  const { MARKER_TYPE } = _cmcb;

  _cmcb.rpBoard.setPosition(fen || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', false);
  _cmcb.rpBoard.removeMarkers(MARKER_TYPE.square);

  if (lastUci && lastUci.length >= 4) {
    _cmcb.rpBoard.addMarker(MARKER_TYPE.square, lastUci.slice(0, 2));
    _cmcb.rpBoard.addMarker(MARKER_TYPE.square, lastUci.slice(2, 4));
  }

  // Refresh captured-pieces graveyards for replay
  renderGraveyards(fen, { white: 'rpGraveyardWhite', black: 'rpGraveyardBlack' });
}

// ── Replay eval chart ─────────────────────────────────────────────────────
function rpRenderEvalChart() {
  const el = document.getElementById('rpEvalChart');
  if (!el) return;
  const { moves, cursor } = replay;
  const hasEval = moves.some(m => m.score_cp != null);
  if (!hasEval || moves.length < 2) { el.style.display = 'none'; return; }
  el.style.display = '';

  const W    = el.clientWidth || 240;
  const H    = 44;
  const pad  = 2;
  const MAX  = 600;   // clamp at ±6 pawns

  // Index 0 = start (eval 0), index i+1 = after move i
  const rawEvals = [0, ...moves.map(m => m.score_cp)];
  // Forward-fill nulls from previous known value
  for (let i = 1; i < rawEvals.length; i++) {
    if (rawEvals[i] == null) rawEvals[i] = rawEvals[i - 1] ?? 0;
  }
  const n = rawEvals.length;

  const px = i => pad + (i / (n - 1)) * (W - pad * 2);
  const py = v => {
    const c = Math.max(-MAX, Math.min(MAX, v));
    return pad + (1 - (c + MAX) / (2 * MAX)) * (H - pad * 2);
  };
  const mid = py(0);

  // White-advantage fill (above midline) and black-advantage fill (below)
  const whiteD = `M ${px(0).toFixed(1)},${mid.toFixed(1)} ` +
    rawEvals.map((v, i) => `L ${px(i).toFixed(1)},${Math.min(py(v), mid).toFixed(1)}`).join(' ') +
    ` L ${px(n - 1).toFixed(1)},${mid.toFixed(1)} Z`;
  const blackD = `M ${px(0).toFixed(1)},${mid.toFixed(1)} ` +
    rawEvals.map((v, i) => `L ${px(i).toFixed(1)},${Math.max(py(v), mid).toFixed(1)}`).join(' ') +
    ` L ${px(n - 1).toFixed(1)},${mid.toFixed(1)} Z`;

  const pts = rawEvals.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(' ');

  // Cursor vertical line
  const cIdx = Math.min(cursor, n - 1);
  const cx   = px(cIdx).toFixed(1);

  // Clickable transparent rects — one per inter-move segment
  const stepW = n > 1 ? (W - pad * 2) / (n - 1) : W;
  const clicks = rawEvals.map((_, i) => {
    const x = (px(i) - stepW / 2).toFixed(1);
    return `<rect x="${x}" y="${pad}" width="${stepW.toFixed(1)}" height="${H - pad * 2}"
              fill="transparent" style="cursor:pointer" onclick="rpGo(${i})"/>`;
  }).join('');

  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="display:block;width:100%">
    <rect x="${pad}" y="${pad}" width="${W - pad * 2}" height="${H - pad * 2}" fill="var(--bg-sidebar)" rx="2"/>
    <path d="${whiteD}" fill="rgba(220,220,220,0.18)"/>
    <path d="${blackD}" fill="rgba(20,20,20,0.40)"/>
    <polyline points="${pts}" fill="none" stroke="var(--text-mid)" stroke-width="1"
              stroke-linejoin="round" stroke-linecap="round"/>
    <line x1="${pad}" y1="${mid.toFixed(1)}" x2="${W - pad}" y2="${mid.toFixed(1)}"
          stroke="var(--border)" stroke-width="0.5" stroke-dasharray="2,2"/>
    <line x1="${cx}" y1="${pad}" x2="${cx}" y2="${H - pad}"
          stroke="var(--gold)" stroke-width="1.5" opacity="0.85"/>
    ${clicks}
  </svg>`;
}

// Keyboard navigation for replay
document.addEventListener('keydown', e => {
  // Escape closes whichever modal is open
  if (e.key === 'Escape') {
    if (document.getElementById('modelModal').classList.contains('show')) closeModelCard();
    if (document.getElementById('replayModal').classList.contains('show')) closeReplay();
    return;
  }
  if (!document.getElementById('replayModal').classList.contains('show')) return;
  if (e.key === 'ArrowLeft'  || e.key === 'ArrowDown')  rpGo(replay.cursor - 1);
  if (e.key === 'ArrowRight' || e.key === 'ArrowUp')    rpGo(replay.cursor + 1);
  if (e.key === 'Home')  rpGo(0);
  if (e.key === 'End')   rpGo(replay.moves.length);
});

function toggleSection(id) {
  document.getElementById(id).classList.toggle('collapsed');
}

// ── Eval graph ────────────────────────────────────────────────────────────
let evalHistory = [];   // [{move, eval}]  eval = centipawns from White's POV

function pushEval(moveNumber, scoreCpWhite) {
  if (scoreCpWhite == null) return;
  evalHistory.push({ move: moveNumber, eval: scoreCpWhite });
  renderEvalGraph();
}

function renderEvalGraph() {
  const pane = document.getElementById('evalPane');
  const svg  = document.getElementById('evalGraph');
  if (evalHistory.length < 2) { pane.style.display = 'none'; return; }
  pane.style.display = '';

  const W = 280, H = 46, MID = H / 2, MAX = 800;
  const n = evalHistory.length;

  const pts = evalHistory.map((e, i) => {
    const x = (i / (n - 1)) * W;
    const clamped = Math.max(-MAX, Math.min(MAX, e.eval));
    const y = MID - (clamped / MAX) * (MID - 2);
    return [x, y];
  });

  // Filled area: white advantage above mid, black below
  const polyPts = pts.map(([x,y]) => `${x},${y}`).join(' ');
  const fillAbove = `M 0,${MID} ` + pts.map(([x,y]) => `L ${x},${Math.min(y,MID)}`).join(' ') + ` L ${W},${MID} Z`;
  const fillBelow = `M 0,${MID} ` + pts.map(([x,y]) => `L ${x},${Math.max(y,MID)}`).join(' ') + ` L ${W},${MID} Z`;

  svg.innerHTML = `
    <rect width="${W}" height="${MID}" fill="rgba(255,255,255,0.025)"/>
    <rect y="${MID}" width="${W}" height="${MID}" fill="rgba(0,0,0,0.25)"/>
    <path d="${fillAbove}" fill="rgba(232,184,74,0.18)"/>
    <path d="${fillBelow}" fill="rgba(22,22,22,0.5)"/>
    <line x1="0" y1="${MID}" x2="${W}" y2="${MID}" stroke="#1a2535" stroke-width="1"/>
    <polyline points="${polyPts}" fill="none" stroke="${getComputedStyle(document.documentElement).getPropertyValue('--gold').trim() || '#c8921e'}" stroke-width="1.5" stroke-linejoin="round"/>`;
}

// ── Utility — escHtml() defined in js/viewer_utils.js ─────────────────────

// ── Boot ──────────────────────────────────────────────────────────────────
applySettings();   // apply persisted settings before first render
buildThemeSwatches();
buildUiThemeSwatches();

(async () => {
  // ── Load cm-chessboard modules ──────────────────────────────────────────
  const ASSETS = 'https://cdn.jsdelivr.net/npm/cm-chessboard@8/';
  const [
    { Chessboard, COLOR, INPUT_EVENT_TYPE, FEN, BORDER_TYPE, PIECES_FILE_TYPE },
    { Markers, MARKER_TYPE },
    { Arrows, ARROW_TYPE },
  ] = await Promise.all([
    import('https://cdn.jsdelivr.net/npm/cm-chessboard@8/src/Chessboard.js'),
    import('https://cdn.jsdelivr.net/npm/cm-chessboard@8/src/extensions/markers/Markers.js'),
    import('https://cdn.jsdelivr.net/npm/cm-chessboard@8/src/extensions/arrows/Arrows.js'),
  ]);

  // ── Initialize main board ────────────────────────────────────────────────
  _cmcb.board = new Chessboard(document.getElementById('board'), {
    position: gameState.fen,
    orientation: gameState.boardFlipped ? COLOR.black : COLOR.white,
    assetsUrl: ASSETS,
    style: {
      cssClass: 'default',
      showCoordinates: true,
      borderType: BORDER_TYPE.none,
      animationDuration: 180,
      pieces: { type: PIECES_FILE_TYPE.svgSprite, file: 'assets/pieces/standard.svg' },
    },
    extensions: [
      { class: Markers, props: { autoMarkers: MARKER_TYPE.frame } },
      { class: Arrows,  props: { sprite: ASSETS + 'src/extensions/arrows/arrows.svg' } },
    ],
  });

  // ── Initialize replay board (read-only, no arrows needed) ───────────────
  _cmcb.rpBoard = new Chessboard(document.getElementById('rpBoard'), {
    position: FEN.empty,
    orientation: gameState.boardFlipped ? COLOR.black : COLOR.white,
    assetsUrl: ASSETS,
    style: {
      cssClass: 'default',
      showCoordinates: true,
      borderType: BORDER_TYPE.none,
      animationDuration: 0,
      pieces: { type: PIECES_FILE_TYPE.svgSprite, file: 'assets/pieces/standard.svg' },
    },
    extensions: [{ class: Markers }],
  });

  // ── Expose module exports on _cmcb for use by other functions ───────────
  _cmcb.COLOR            = COLOR;
  _cmcb.INPUT_EVENT_TYPE = INPUT_EVENT_TYPE;
  _cmcb.FEN              = FEN;
  _cmcb.MARKER_TYPE      = MARKER_TYPE;
  _cmcb.ARROW_TYPE       = ARROW_TYPE;
  _cmcb.ready            = true;

  // ── Kick off the rest of the boot sequence ──────────────────────────────
  sizeBoard();
  connect();
  loadProviders();
  loadLeaderboard();
  loadHistory();
  loadTournamentHistory();
  setInterval(loadLeaderboard, 30000);

  // ── Puzzle gauntlet ────────────────────────────────────────────────────

  // Live score accumulator: {model_id: {name, solved, total}}
  let puzzleScores = {};
  let puzzlePlayers = [];  // [{id, name, backend, url, model, thinking}]
  let puzzleNextId = 0;

  function puzzleAddPlayer() {
    const id = puzzleNextId++;
    puzzlePlayers.push({ id, name: '', backend: 'lmstudio', url: DEFAULT_LMSTUDIO_URL, model: '', thinking: false });
    renderPuzzlePlayers();
  }

  function puzzleRemovePlayer(id) {
    puzzlePlayers = puzzlePlayers.filter(p => p.id !== id);
    renderPuzzlePlayers();
  }

  function puzzleSync(id) {
    const p = puzzlePlayers.find(p => p.id === id);
    if (!p) return;
    p.name     = (document.getElementById(`pzName_${id}`) || {}).value || '';
    p.backend  = (document.getElementById(`pzBackend_${id}`) || {}).value || 'lmstudio';
    p.url      = (document.getElementById(`pzUrl_${id}`) || {}).value || DEFAULT_LMSTUDIO_URL;
    p.model    = (document.getElementById(`pzModel_${id}`) || {}).value || '';
    p.thinking = (document.getElementById(`pzThinking_${id}`) || {}).checked || false;
  }

  function renderPuzzlePlayers() {
    const container = document.getElementById('puzzlePlayerList');
    if (!container) return;
    container.innerHTML = '';
    puzzlePlayers.forEach(p => {
      const div = document.createElement('div');
      div.className = 'trn-player-row';
      div.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:9px;color:var(--text-dim)">Player</span>
          <button class="trn-remove-btn" onclick="puzzleRemovePlayer(${p.id})">✕</button>
        </div>
        <input class="ctrl-input" id="pzName_${p.id}" placeholder="Display name" value="${p.name}" oninput="puzzleSync(${p.id})">
        <select class="ctrl-select" id="pzBackend_${p.id}" onchange="puzzleSync(${p.id});onPzBackendChange(${p.id})">
          <option value="lmstudio"${p.backend==='lmstudio'?' selected':''}>LM Studio</option>
          <option value="anthropic"${p.backend==='anthropic'?' selected':''}>Anthropic</option>
        </select>
        <div class="url-row" id="pzUrlRow_${p.id}">
          <input class="ctrl-input" id="pzUrl_${p.id}" placeholder="${DEFAULT_LMSTUDIO_URL}" value="${p.url}" oninput="puzzleSync(${p.id})">
          <button class="fetch-btn" onclick="fetchPzModels(${p.id})" title="Load models">⟳</button>
        </div>
        <select class="ctrl-select" id="pzModel_${p.id}" onchange="puzzleSync(${p.id})"><option value="">— select model —</option></select>
        <label class="toggle-row"><input type="checkbox" id="pzThinking_${p.id}"${p.thinking?' checked':''}> Extended thinking</label>
      `;
      container.appendChild(div);
      if (p.backend === 'lmstudio') fetchPzModels(p.id);
    });
  }

  function onPzBackendChange(id) {
    const backend = (document.getElementById(`pzBackend_${id}`) || {}).value;
    const urlRow  = document.getElementById(`pzUrlRow_${id}`);
    if (urlRow) urlRow.style.display = backend === 'anthropic' ? 'none' : '';
  }

  async function fetchPzModels(id) {
    const urlEl = document.getElementById(`pzUrl_${id}`);
    const sel   = document.getElementById(`pzModel_${id}`);
    if (!urlEl || !sel) return;
    const url = urlEl.value || DEFAULT_LMSTUDIO_URL;
    try {
      const data = await fetch(`${API}/api/models?url=${encodeURIComponent(url)}`).then(r => r.json());
      const models = (data.data || []).map(m => m.id).filter(Boolean);
      const cur = sel.value;
      sel.innerHTML = '<option value="">— select model —</option>' +
        models.map(m => `<option value="${m}"${m===cur?' selected':''}>${m}</option>`).join('');
    } catch (_) {}
  }

  async function startPuzzleGauntlet() {
    puzzlePlayers.forEach(p => puzzleSync(p.id));
    if (puzzlePlayers.length === 0) { alert('Add at least one player.'); return; }
    const missing = puzzlePlayers.filter(p => !p.model);
    if (missing.length > 0) { alert('Select a model for every player.'); return; }

    const cfg = {
      players:         puzzlePlayers.map(p => ({
        backend:  p.backend,
        name:     p.name || extractModelName(p.model),
        model_id: p.model,
        url:      p.url,
        thinking: p.thinking,
      })),
      candidate_count: parseInt(document.getElementById('puzzleCandidates').value) || 5,
      puzzles_file:    document.getElementById('puzzleFile').value || 'positions.toml',
      move_timeout:    parseInt(document.getElementById('puzzleTimeout').value) || 0,
    };

    const res = await fetch(`${API}/api/puzzle/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    }).then(r => r.json());

    if (res.error) alert(res.error);
  }

  // ── Puzzle WebSocket handlers ─────────────────────────────────────────

  function onPuzzleGauntletStart(d) {
    puzzleScores = {};
    (d.player_names || []).forEach(name => {
      puzzleScores[name] = { name, solved: 0, total: 0 };
    });

    document.getElementById('setupForm').style.display = 'none';
    document.getElementById('puzzleProgressView').style.display = '';
    document.getElementById('puzzleScoreSection').style.display = '';
    renderPuzzleScoreboard();

    const badge = document.getElementById('tournamentBadge');
    badge.textContent = 'Puzzle';
    badge.className = 'ctrl-badge running';
  }

  function onPuzzleThinking(d) {
    // Show the current puzzle on the board
    if (d.fen && window._board) window._board.setPosition(d.fen);

    const total = Object.values(puzzleScores).reduce((s, p) => Math.max(s, p.total), 0);
    const count = d.puzzle_index + 1;
    const pct   = Math.round((total / (count * Object.keys(puzzleScores).length || 1)) * 100);

    const progressText = document.getElementById('puzzleProgressText');
    const progressPct  = document.getElementById('puzzleProgressPct');
    const progressFill = document.getElementById('puzzleProgressFill');
    const descEl       = document.getElementById('puzzleCurrentDesc');

    if (progressText) progressText.textContent = `Puzzle ${d.puzzle_index + 1}`;
    if (progressPct)  progressPct.textContent  = `${d.player} thinking…`;
    if (progressFill) progressFill.style.width  = `${pct}%`;
    if (descEl)       descEl.textContent        = d.description || '';
  }

  function onPuzzleResult(d) {
    const sc = puzzleScores[d.player];
    if (sc) {
      sc.total += 1;
      if (d.solved) sc.solved += 1;
    }
    renderPuzzleScoreboard();

    const total = Object.values(puzzleScores)[0]?.total || 1;
    const pct   = Math.round((total / (d.puzzle_index + 1 || 1)) * 100);
    const el    = document.getElementById('puzzleProgressFill');
    if (el) el.style.width = `${pct}%`;
  }

  function onPuzzleGauntletOver(d) {
    // Final scoreboard
    const scoreEl = document.getElementById('puzzleScoreBody');
    if (scoreEl) {
      scoreEl.innerHTML = renderPuzzleScoreTable(d.scores || []);
    }

    const badge = document.getElementById('tournamentBadge');
    badge.textContent = 'Done';
    badge.className = 'ctrl-badge';

    document.getElementById('puzzleProgressView').style.display = 'none';
    document.getElementById('setupForm').style.display = '';

    loadPuzzleHistory();
  }

  function renderPuzzleScoreboard() {
    const el = document.getElementById('puzzleScoreBody');
    if (!el) return;
    const entries = Object.values(puzzleScores).map(s => ({
      player:   s.name,
      solved:   s.solved,
      total:    s.total,
      fraction: s.total ? s.solved / s.total : 0,
      avg_rank: null,
    }));
    entries.sort((a, b) => b.fraction - a.fraction);
    el.innerHTML = renderPuzzleScoreTable(entries);
  }

  function renderPuzzleScoreTable(scores) {
    if (!scores || scores.length === 0) return '<div class="lb-empty">No results yet</div>';
    return `<table class="puzzle-score-table">
      <thead><tr>
        <th>Player</th><th>Solved</th><th>%</th><th>Avg rank</th>
      </tr></thead>
      <tbody>
        ${scores.map((s, i) => `<tr class="${i===0?'puzzle-winner':''}">
          <td>${escHtml(s.player || s.name || '')}</td>
          <td>${s.solved}/${s.total}</td>
          <td>${(s.fraction * 100).toFixed(0)}%</td>
          <td>${s.avg_rank != null ? s.avg_rank.toFixed(1) : '—'}</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
  }

  async function loadPuzzleHistory() {
    const el = document.getElementById('puzzleHistoryBody');
    if (!el) return;
    try {
      const gauntlets = await fetch(`${API}/api/puzzle/results`).then(r => r.json());
      if (!gauntlets || gauntlets.length === 0) {
        el.innerHTML = '<div class="lb-empty">No gauntlets yet</div>';
        return;
      }
      el.innerHTML = gauntlets.map(g => {
        const date = g.started_at ? g.started_at.slice(0, 10) : '?';
        const scoresHtml = (g.scores || [])
          .map(s => `<div class="puzzle-hist-score">${escHtml(s.name)}: ${s.solved}/${s.total} (${(s.fraction*100).toFixed(0)}%)</div>`)
          .join('');
        return `<div class="puzzle-hist-entry">
          <div class="puzzle-hist-head">${date} · ${g.puzzle_count} puzzles · ${g.status}</div>
          ${scoresHtml}
        </div>`;
      }).join('');
    } catch (_) {
      el.innerHTML = '<div class="lb-empty">Failed to load</div>';
    }
  }

  // Expose globals needed by HTML onclick attributes
  window.puzzleAddPlayer    = puzzleAddPlayer;
  window.puzzleRemovePlayer = puzzleRemovePlayer;
  window.fetchPzModels      = fetchPzModels;
  window.startPuzzleGauntlet= startPuzzleGauntlet;
  window.loadPuzzleHistory  = loadPuzzleHistory;

  // ── End puzzle gauntlet section ────────────────────────────────────────

  // Auto-fetch models for all lmstudio slots on page load
  ['white', 'black', 'tutor'].forEach(side => {
    const backend = document.getElementById(side + 'Backend');
    if (backend && backend.value === 'lmstudio') fetchModels(side);
  });

  // Re-fetch when the URL input loses focus (user typed a different endpoint)
  ['white', 'black', 'tutor'].forEach(side => {
    const urlId = side === 'tutor' ? 'tutorUrl' : side + 'Url';
    const el = document.getElementById(urlId);
    if (el) el.addEventListener('change', () => fetchModels(side));
  });

  // Auto-open replay for /watch/<id> deep-links and ?game=<id> query params
  (function _autoReplay() {
    const pathMatch = location.pathname.match(/\/watch\/(\d+)$/);
    const gameIdStr = pathMatch ? pathMatch[1] : new URLSearchParams(location.search).get('game');
    if (gameIdStr) openReplay(parseInt(gameIdStr, 10));
  })();
})();

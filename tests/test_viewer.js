/**
 * tests/test_viewer.js — unit tests for pure utility functions in static/viewer_utils.js.
 *
 * Run with:  node --test tests/test_viewer.js
 * No build step, no npm install — uses Node's built-in test runner (Node ≥ 18).
 */
'use strict';

const { test } = require('node:test');
const assert   = require('node:assert/strict');
const path     = require('node:path');

const {
  parseFen,
  uciToSquares,
  computeCaptures,
  extractModelName,
  buildSparkline,
  escHtml,
  authHeaders,
  _buildValueSparkline,
  _setApiKey,
  renderBadges,
  renderMetadata,
} = require(path.join(__dirname, '..', 'static', 'viewer_utils.js'));

const STARTING_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';


// ── parseFen ──────────────────────────────────────────────────────────────────

test('parseFen: starting position has 8 rows', () => {
  const board = parseFen(STARTING_FEN);
  assert.equal(board.length, 8);
});

test('parseFen: every row has 8 columns', () => {
  const board = parseFen(STARTING_FEN);
  for (const row of board) assert.equal(row.length, 8);
});

test('parseFen: rank 8 (index 0) is black pieces', () => {
  const board = parseFen(STARTING_FEN);
  assert.deepEqual(board[0], ['r','n','b','q','k','b','n','r']);
});

test('parseFen: rank 7 (index 1) is black pawns', () => {
  const board = parseFen(STARTING_FEN);
  assert.deepEqual(board[1], ['p','p','p','p','p','p','p','p']);
});

test('parseFen: rank 5 (index 2) is empty', () => {
  const board = parseFen(STARTING_FEN);
  assert.deepEqual(board[2], [null,null,null,null,null,null,null,null]);
});

test('parseFen: rank 2 (index 6) is white pawns', () => {
  const board = parseFen(STARTING_FEN);
  assert.deepEqual(board[6], ['P','P','P','P','P','P','P','P']);
});

test('parseFen: rank 1 (index 7) is white pieces', () => {
  const board = parseFen(STARTING_FEN);
  assert.deepEqual(board[7], ['R','N','B','Q','K','B','N','R']);
});

test('parseFen: numeric run expansion — empty rank', () => {
  const board = parseFen('8/8/8/8/8/8/8/8 w - - 0 1');
  for (const row of board)
    assert.deepEqual(row, [null,null,null,null,null,null,null,null]);
});

test('parseFen: mixed digits and pieces', () => {
  // 4k3 → null,null,null,null,k,null,null,null
  const board = parseFen('4k3/8/8/8/8/8/8/4K3 w - - 0 1');
  assert.equal(board[0][4], 'k');
  assert.equal(board[0][0], null);
});

test('parseFen: ignores extra FEN fields after first space', () => {
  // Should not crash on unusual but valid FEN with move number
  const board = parseFen('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1');
  assert.equal(board.length, 8);
  assert.equal(board[4][4], 'P'); // e4 square
});


// ── uciToSquares ─────────────────────────────────────────────────────────────

test('uciToSquares: null on empty string', () => {
  assert.deepEqual(uciToSquares(''), [null, null]);
});

test('uciToSquares: null on undefined', () => {
  assert.deepEqual(uciToSquares(undefined), [null, null]);
});

test('uciToSquares: null on too-short string', () => {
  assert.deepEqual(uciToSquares('e2e'), [null, null]);
});

test('uciToSquares: e2e4 from-square is col=4,row=6', () => {
  const [from] = uciToSquares('e2e4');
  assert.equal(from.col, 4); // e = index 4
  assert.equal(from.row, 6); // rank 2 → row = 8-2 = 6
});

test('uciToSquares: e2e4 to-square is col=4,row=4', () => {
  const [, to] = uciToSquares('e2e4');
  assert.equal(to.col, 4);
  assert.equal(to.row, 4); // rank 4 → row = 8-4 = 4
});

test('uciToSquares: a1h8 corner to corner', () => {
  const [from, to] = uciToSquares('a1h8');
  assert.equal(from.col, 0); assert.equal(from.row, 7); // a1
  assert.equal(to.col,   7); assert.equal(to.row,   0); // h8
});

test('uciToSquares: d7d8 pawn promotion square', () => {
  const [from, to] = uciToSquares('d7d8q'); // promotion suffix ignored (length >= 4)
  assert.equal(from.col, 3); assert.equal(from.row, 1); // d7
  assert.equal(to.col,   3); assert.equal(to.row,   0); // d8
});

test('uciToSquares: g1f3 knight from g1', () => {
  const [from, to] = uciToSquares('g1f3');
  assert.equal(from.col, 6); assert.equal(from.row, 7);
  assert.equal(to.col,   5); assert.equal(to.row,   5);
});


// ── extractModelName ──────────────────────────────────────────────────────────

test('extractModelName: plain model id unchanged', () => {
  assert.equal(extractModelName('qwen3-8b'), 'qwen3-8b');
});

test('extractModelName: strips namespace prefix', () => {
  assert.equal(extractModelName('google/gemma-3-27b-it'), 'gemma-3-27b-it');
});

test('extractModelName: strips @ version suffix', () => {
  assert.equal(extractModelName('qwen3-30b-a3b@q4_k_m'), 'qwen3-30b-a3b');
});

test('extractModelName: strips : tag suffix', () => {
  assert.equal(extractModelName('llama3:latest'), 'llama3');
});

test('extractModelName: strips both prefix and suffix', () => {
  assert.equal(extractModelName('lmstudio/qwen3-8b@q8'), 'qwen3-8b');
});

test('extractModelName: empty string returns empty string', () => {
  assert.equal(extractModelName(''), '');
});

test('extractModelName: multiple slashes — takes last segment', () => {
  assert.equal(extractModelName('org/sub/model-name'), 'model-name');
});


// ── computeCaptures ───────────────────────────────────────────────────────────

test('computeCaptures: starting position — no captures', () => {
  const { whiteLost, blackLost, imbalance } = computeCaptures(STARTING_FEN);
  for (const t of ['q','r','b','n','p']) {
    assert.equal(whiteLost[t], 0, `whiteLost[${t}] should be 0`);
    assert.equal(blackLost[t], 0, `blackLost[${t}] should be 0`);
  }
  assert.equal(imbalance, 0);
});

test('computeCaptures: missing white queen → whiteLost.q = 1', () => {
  // Starting FEN but with white queen removed (4K3 row has no queen)
  const fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    .replace('RNBQKBNR', 'RNB1KBNR'); // remove white queen
  const { whiteLost } = computeCaptures(fen);
  assert.equal(whiteLost.q, 1);
});

test('computeCaptures: missing black pawn → blackLost.p = 1', () => {
  const fen = STARTING_FEN.replace('pppppppp', 'ppppppp1');
  const { blackLost } = computeCaptures(fen);
  assert.equal(blackLost.p, 1);
});

test('computeCaptures: imbalance — white up a rook', () => {
  // Remove one black rook from starting position
  const fen = STARTING_FEN.replace('rnbqkbnr', '1nbqkbnr');
  const { imbalance } = computeCaptures(fen);
  // Black lost a rook (5cp) → white is ahead → imbalance > 0
  assert.equal(imbalance, 5);
});

test('computeCaptures: imbalance — black up a queen', () => {
  // Remove white queen
  const fen = STARTING_FEN.replace('RNBQKBNR', 'RNB1KBNR');
  const { imbalance } = computeCaptures(fen);
  // White lost queen (9cp) → black is ahead → imbalance < 0
  assert.equal(imbalance, -9);
});

test('computeCaptures: empty board except kings has zero imbalance', () => {
  const { imbalance } = computeCaptures('4k3/8/8/8/8/8/8/4K3 w - - 0 1');
  assert.equal(imbalance, 0);
});


// ── buildSparkline ────────────────────────────────────────────────────────────

test('buildSparkline: empty array returns empty string', () => {
  assert.equal(buildSparkline([]), '');
});

test('buildSparkline: single entry returns empty string', () => {
  assert.equal(buildSparkline([{ elo_after: 1200 }]), '');
});

test('buildSparkline: two entries returns SVG string', () => {
  const svg = buildSparkline([{ elo_after: 1200 }, { elo_after: 1220 }]);
  assert.ok(svg.startsWith('<svg'), 'should start with <svg');
  assert.ok(svg.includes('polyline'), 'should contain a polyline');
});

test('buildSparkline: SVG has correct viewBox dimensions', () => {
  const svg = buildSparkline([{ elo_after: 1200 }, { elo_after: 1220 }]);
  assert.ok(svg.includes('viewBox="0 0 58 20"'));
});

test('buildSparkline: flat history (all same ELO) — no division by zero', () => {
  const hist = [1200, 1200, 1200].map(e => ({ elo_after: e }));
  const svg = buildSparkline(hist);
  assert.ok(svg.includes('<svg'), 'should produce SVG even for flat data');
  assert.ok(!svg.includes('NaN'), 'should not produce NaN coordinates');
  assert.ok(!svg.includes('Infinity'), 'should not produce Infinity coordinates');
});

test('buildSparkline: many points — polyline has correct number of coordinate pairs', () => {
  const hist = [1200, 1220, 1210, 1230, 1215].map(e => ({ elo_after: e }));
  const svg = buildSparkline(hist);
  // The polyline `points` attribute should have 5 coordinate pairs (one per data point)
  const match = svg.match(/polyline points="([^"]+)"/);
  assert.ok(match, 'should have a polyline with points');
  const pairs = match[1].trim().split(' ');
  assert.equal(pairs.length, 5);
});

test('buildSparkline: null input returns empty string', () => {
  assert.equal(buildSparkline(null), '');
});


// ── escHtml ───────────────────────────────────────────────────────────────────

test('escHtml: plain string unchanged', () => {
  assert.equal(escHtml('hello world'), 'hello world');
});

test('escHtml: escapes ampersand', () => {
  assert.equal(escHtml('foo & bar'), 'foo &amp; bar');
});

test('escHtml: escapes less-than', () => {
  assert.equal(escHtml('<script>'), '&lt;script&gt;');
});

test('escHtml: escapes greater-than', () => {
  assert.equal(escHtml('a > b'), 'a &gt; b');
});

test('escHtml: escapes double quote', () => {
  assert.equal(escHtml('"hello"'), '&quot;hello&quot;');
});

test('escHtml: escapes all special chars in one string', () => {
  assert.equal(escHtml('<a href="x&y">'), '&lt;a href=&quot;x&amp;y&quot;&gt;');
});

test('escHtml: coerces non-string to string', () => {
  assert.equal(escHtml(42), '42');
  assert.equal(escHtml(null), 'null');
});

// S-4 XSS audit — these tests document the specific injection vectors that were
// audited and confirm escHtml correctly neutralises them.

test('S-4: tournament title with HTML chars is safe (onTournamentComplete badge)', () => {
  // d.title is derived from _WINNER_TITLES (server-controlled fixed list), but
  // must still be escaped when embedded in innerHTML as defence-in-depth.
  const title = '<script>alert(1)</script>';
  const safe = `<div class="ov-title-badge">"${escHtml(title)}"</div>`;
  assert.ok(!safe.includes('<script>'), 'raw script tag must not appear');
  assert.ok(safe.includes('&lt;script&gt;'), 'must be HTML-entity escaped');
});

test('S-4: tournament format fallback with HTML chars is safe (loadTournamentHistory)', () => {
  // fmtLabel[t.format]||t.format — when t.format is an unknown value it falls
  // through to raw t.format; that value now passes through escHtml.
  const fmt = '<img src=x onerror=alert(1)>';
  const fmtLabel = { round_robin: 'Round Robin', gauntlet: 'Gauntlet', match: 'Match' };
  const safe = escHtml(fmtLabel[fmt] || fmt);
  assert.ok(!safe.includes('<img'), 'raw img tag must not appear');
  assert.ok(safe.includes('&lt;img'), 'must be HTML-entity escaped');
});

test('S-4: known format labels pass through escHtml unchanged', () => {
  // Valid format strings have no HTML-special characters — escHtml is a no-op.
  assert.equal(escHtml('Round Robin'), 'Round Robin');
  assert.equal(escHtml('Gauntlet'), 'Gauntlet');
  assert.equal(escHtml('Match'), 'Match');
});

// ── _buildValueSparkline ──────────────────────────────────────────────────────

test('_buildValueSparkline: fewer than 2 points returns empty string', () => {
  assert.equal(_buildValueSparkline([], 60, 20, 'red'), '');
  assert.equal(_buildValueSparkline([5], 60, 20, 'red'), '');
  assert.equal(_buildValueSparkline(null, 60, 20, 'red'), '');
});

test('_buildValueSparkline: returns an SVG string for valid data', () => {
  const svg = _buildValueSparkline([1, 5, 3, 7], 60, 20, '#ff0000');
  assert.ok(svg.includes('<svg'), 'should contain <svg');
  assert.ok(svg.includes('polyline'), 'should contain polyline element');
  assert.ok(svg.includes('polygon'), 'should contain polygon fill element');
});

test('_buildValueSparkline: SVG honours supplied width and height', () => {
  const svg = _buildValueSparkline([1, 2, 3], 80, 30, 'blue');
  assert.ok(svg.includes('width="80"'), 'width attribute should be 80');
  assert.ok(svg.includes('height="30"'), 'height attribute should be 30');
  assert.ok(svg.includes('viewBox="0 0 80 30"'), 'viewBox should match dimensions');
});

test('_buildValueSparkline: SVG uses supplied stroke color', () => {
  const svg = _buildValueSparkline([1, 2, 3], 60, 20, 'var(--accent)');
  assert.ok(svg.includes('stroke="var(--accent)"'), 'stroke should match supplied color');
});

test('_buildValueSparkline: handles flat data (all same value)', () => {
  // range becomes 1 (guarded) so the sparkline should still render without NaN
  const svg = _buildValueSparkline([5, 5, 5], 60, 20, 'red');
  assert.ok(svg.includes('<svg'), 'flat data should still produce SVG');
  assert.ok(!svg.includes('NaN'), 'no NaN values in output');
});

test('_buildValueSparkline: single-digit and high-value data produce finite coords', () => {
  const svg = _buildValueSparkline([0, 1000, 500, 750, 250], 100, 40, 'green');
  assert.ok(!svg.includes('NaN'), 'no NaN coords');
  assert.ok(!svg.includes('Infinity'), 'no Infinity coords');
});

// ── authHeaders ───────────────────────────────────────────────────────────────

test('authHeaders: no key set — returns empty object when no extras', () => {
  _setApiKey('');
  assert.deepEqual(authHeaders(), {});
});

test('authHeaders: no key set — returns copy of extra headers unchanged', () => {
  _setApiKey('');
  const h = authHeaders({ 'Content-Type': 'application/json' });
  assert.deepEqual(h, { 'Content-Type': 'application/json' });
});

test('authHeaders: key set — injects X-API-Key header', () => {
  _setApiKey('secret-1234');
  const h = authHeaders();
  assert.equal(h['X-API-Key'], 'secret-1234');
  _setApiKey('');
});

test('authHeaders: key set — merges X-API-Key with caller-supplied headers', () => {
  _setApiKey('mytoken');
  const h = authHeaders({ 'Content-Type': 'application/json' });
  assert.equal(h['X-API-Key'], 'mytoken');
  assert.equal(h['Content-Type'], 'application/json');
  _setApiKey('');
});

test('authHeaders: does not mutate the extra argument', () => {
  _setApiKey('mutcheck');
  const extra = { foo: 'bar' };
  authHeaders(extra);
  assert.equal(Object.keys(extra).length, 1, 'extra object must not gain X-API-Key');
  _setApiKey('');
});

test('authHeaders: no X-API-Key when key is empty string', () => {
  _setApiKey('');
  const h = authHeaders({ Authorization: 'Bearer tok' });
  assert.ok(!Object.prototype.hasOwnProperty.call(h, 'X-API-Key'), 'X-API-Key must be absent');
});

// ── renderBadges ──────────────────────────────────────────────────────────────

test('renderBadges: null returns placeholder div', () => {
  const html = renderBadges(null);
  assert.ok(html.includes('No achievements'), 'should show placeholder text');
});

test('renderBadges: empty array returns placeholder div', () => {
  const html = renderBadges([]);
  assert.ok(html.includes('No achievements'), 'empty list should show placeholder');
});

test('renderBadges: times=1 — no ×N multiplier chip', () => {
  const html = renderBadges([{ code: 'first-blood', label: 'First Blood', desc: 'First win', times: 1 }]);
  assert.ok(!html.includes('×'), 'times=1 should not show ×N chip');
  assert.ok(html.includes('First Blood'), 'label should appear in output');
});

test('renderBadges: times>1 — shows ×N multiplier chip', () => {
  const html = renderBadges([{ code: 'hattrick', label: 'Hat Trick', desc: 'Three in a row', times: 3 }]);
  assert.ok(html.includes('×3'), '×3 chip should appear for times=3');
});

test('renderBadges: label and desc are HTML-escaped', () => {
  const html = renderBadges([{ code: 'x', label: '<b>XSS</b>', desc: '<img src=x>', times: 1 }]);
  assert.ok(!html.includes('<b>'),   'raw <b> tag must not appear in label');
  assert.ok(!html.includes('<img'),  'raw <img> tag must not appear in desc title');
  assert.ok(html.includes('&lt;b&gt;'), 'label must be HTML-entity escaped');
});

test('renderBadges: multiple achievements all rendered', () => {
  const html = renderBadges([
    { code: 'a', label: 'Alpha', desc: 'First',  times: 1 },
    { code: 'b', label: 'Beta',  desc: 'Second', times: 2 },
  ]);
  assert.ok(html.includes('Alpha'), 'first badge label should appear');
  assert.ok(html.includes('Beta'),  'second badge label should appear');
  assert.ok(html.includes('×2'),    '×2 chip should appear for second badge');
});

test('renderBadges: uses badge-<code> CSS class', () => {
  const html = renderBadges([{ code: 'topgun', label: 'Top Gun', desc: 'Ace', times: 1 }]);
  assert.ok(html.includes('badge-topgun'), 'badge-<code> class should be present');
});

// ── renderMetadata ────────────────────────────────────────────────────────────

test('renderMetadata: null returns empty string', () => {
  assert.equal(renderMetadata(null), '');
});

test('renderMetadata: undefined returns empty string', () => {
  assert.equal(renderMetadata(undefined), '');
});

test('renderMetadata: empty object returns empty string (no chips)', () => {
  assert.equal(renderMetadata({}), '');
});

test('renderMetadata: family chip is rendered', () => {
  const html = renderMetadata({ family: 'Llama 3' });
  assert.ok(html.includes('Llama 3'), 'family value should appear');
  assert.ok(html.includes('Family'),  'Family label should appear');
});

test('renderMetadata: param_count chip is rendered', () => {
  const html = renderMetadata({ param_count: '7B' });
  assert.ok(html.includes('7B'),     'param_count value should appear');
  assert.ok(html.includes('Params'), 'Params label should appear');
});

test('renderMetadata: active_params appended to param_count chip', () => {
  const html = renderMetadata({ param_count: '30B', active_params: '3B' });
  assert.ok(html.includes('30B'),       'total params should appear');
  assert.ok(html.includes('3B active'), 'active params annotation should appear');
});

test('renderMetadata: quantization chip is rendered', () => {
  const html = renderMetadata({ quantization: 'Q4_K_M' });
  assert.ok(html.includes('Q4_K_M'), 'quantization value should appear');
  assert.ok(html.includes('Quant'),  'Quant label should appear');
});

test('renderMetadata: hf_url produces an anchor tag opening in new tab', () => {
  const html = renderMetadata({ hf_url: 'https://huggingface.co/meta-llama/Llama-3' });
  assert.ok(html.includes('<a '),            'should contain an anchor tag');
  assert.ok(html.includes('target="_blank"'), 'link should open in new tab');
  assert.ok(html.includes('rel="noopener"'), 'link should have noopener rel');
});

test('renderMetadata: context_length rendered with toLocaleString formatting', () => {
  const html = renderMetadata({ context_length: 131072 });
  assert.ok(html.includes('Ctx'), 'Ctx label should appear');
  // toLocaleString is locale-dependent, just check that it renders at all
  assert.ok(html.length > 0, 'should produce output');
});

test('renderMetadata: values are HTML-escaped', () => {
  const html = renderMetadata({ family: '<script>alert(1)</script>' });
  assert.ok(!html.includes('<script>'),       'raw script tag must not appear');
  assert.ok(html.includes('&lt;script&gt;'), 'family value must be HTML-escaped');
});

test('renderMetadata: multiple chips all rendered', () => {
  const html = renderMetadata({ family: 'Qwen3', param_count: '30B', quantization: 'Q8_0' });
  assert.ok(html.includes('Qwen3'),  'family chip');
  assert.ok(html.includes('30B'),    'params chip');
  assert.ok(html.includes('Q8_0'),   'quant chip');
});

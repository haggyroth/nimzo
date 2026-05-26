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

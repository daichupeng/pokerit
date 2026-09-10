// Run with: node --test tests/js/table_save.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.resolve(__dirname, '../../src/poker_trainer/static/js/table.js'), 'utf8');
// Expose the existing private class only inside the test VM; no app test hook.
assert(source.includes('window.PokerTable = {'));
const context = { window: {}, WebSocket: { OPEN: 1 }, sessionStorage: { removeItem() {} } };
vm.runInNewContext(source.replace('window.PokerTable = {', 'window.TestTableUI = TableUI; window.PokerTable = {'), context);

function table() {
  const ui = Object.create(context.window.TestTableUI.prototype);
  ui.$endGame = { disabled: true, textContent: 'Game ended' };
  ui.gameFinished = true;
  ui.disableControls = () => { ui.controlsDisabled = true; };
  ui.setMessage = text => { ui.message = text; };
  ui.sent = [];
  ui.ws = { readyState: 1, send: text => ui.sent.push(JSON.parse(text)) };
  return ui;
}

test('failed final save exposes retry and clears only after saved acknowledgement', () => {
  const ui = table();
  ui.onMessage({ type: 'persist_error', finished: true, message: 'Retry saving' });
  assert.equal(ui.$endGame.disabled, false);
  assert.equal(ui.$endGame.textContent, 'Retry save');
  assert.equal(ui.controlsDisabled, true);
  ui.endGame();
  assert.deepEqual(ui.sent, [{ type: 'retry_save' }]);
  assert.equal(ui.saveFailed, true);
  ui.onMessage({ type: 'saved', db_game_id: 'saved-id' });
  assert.equal(ui.saveFailed, false);
  assert.equal(ui.$endGame.disabled, true);
  assert.equal(ui.message, 'Game over. Result saved.');
});

test('successful midgame retry restores the end-game button without ending play', () => {
  const ui = table();
  ui.gameFinished = false;
  ui.onMessage({ type: 'persist_error', finished: false, message: 'Retry saving' });
  ui.endGame();
  ui.onMessage({ type: 'save_status', saved: true });
  assert.equal(ui.gameFinished, false);
  assert.equal(ui.saveFailed, false);
  assert.equal(ui.$endGame.disabled, false);
  assert.equal(ui.$endGame.textContent, 'End game');
  assert.equal(ui.message, 'Completed hands saved.');
});

test('retry after connection loss reconnects without sending an action', () => {
  const ui = table();
  ui.saveFailed = true;
  ui.ws.readyState = 3;
  ui.connect = () => { ui.reconnected = true; };
  ui.endGame();
  assert.equal(ui.reconnected, true);
  assert.deepEqual(ui.sent, []);
});

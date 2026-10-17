import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createNetworkTransport } from '../client/transport.mjs';

const identity = { agentId: 'example_agent', sessionKey: 'example-session' };
const handle = 'a'.repeat(32);
function fixture() {
  const calls = []; let grants = { default: 'node1', contexts: [{ id: 'local' }, { id: 'node1', nodeId: 'example-node' }] };
  let reply = request => request.params.op === 'open' ? { state: 'open', id: handle }
    : request.params.op === 'write' ? { state: 'open', written: Buffer.from(request.params.data, 'base64').length }
    : request.params.op === 'read' ? { state: 'open', data: Buffer.from('reply').toString('base64') } : { state: 'closed' };
  const transport = createNetworkTransport({ resolveContexts: async () => grants,
    invoke: async request => { calls.push(request); return reply(request); } });
  return { calls, transport, setGrants(value) { grants = value; }, setReply(value) { reply = value; } };
}
test('context and trusted session travel with every operation; large writes are chunked', async () => {
  const f = fixture(); const socket = await f.transport.open(identity, { host: '192.0.2.10', port: 443 });
  await socket.write(Buffer.alloc(4500, 7));
  assert.deepEqual(f.calls.filter(call => call.params.op === 'write').map(call => Buffer.from(call.params.data, 'base64').length), [2048, 2048, 404]);
  assert.equal((await socket.read()).toString(), 'reply'); await socket.close();
  for (const call of f.calls) { assert.equal(call.nodeId, 'example-node'); assert.equal(call.sessionKey, identity.sessionKey); assert.equal(call.params.context, 'node1'); }
});
test('context revocation stops existing streams and still attempts narrowly scoped cleanup', async () => {
  const f = fixture(); const socket = await f.transport.open(identity, { host: '192.0.2.10', port: 443 });
  f.setGrants({ contexts: [] });
  await assert.rejects(socket.write('x'), /denied/);
  assert.equal(f.calls.at(-1).params.op, 'close');
  assert.equal(f.calls.some(call => call.params.op === 'write'), false);
});
test('no implicit fallback to local or another node; reassignment invalidates a stream', async () => {
  const f = fixture();
  await assert.rejects(f.transport.open(identity, { context: 'node2', host: '192.0.2.10', port: 443 }), /denied/);
  await assert.rejects(f.transport.open(identity, { context: 'local', host: '192.0.2.10', port: 443 }), /local transport/);
  const socket = await f.transport.open(identity, { host: '192.0.2.10', port: 443 });
  f.setGrants({ contexts: [{ id: 'node1', nodeId: 'different-node' }] });
  await assert.rejects(socket.read(), /changed/); assert.equal(f.calls.at(-1).nodeId, 'example-node');
});
test('partial TCP acknowledgement resumes from its exact offset', async () => {
  const f = fixture(); const socket = await f.transport.open(identity, { host: '192.0.2.10', port: 443 });
  f.setReply(request => request.params.op === 'write'
    ? { state: 'open', written: Buffer.from(request.params.data, 'base64').length > 3 ? 3 : 2 } : { state: 'closed' });
  await socket.write(Buffer.from('hello'));
  assert.deepEqual(f.calls.filter(call => call.params.op === 'write').map(call => Buffer.from(call.params.data, 'base64').toString()), ['hello', 'lo']);
  await socket.close();
});
test('abort closes the original handle without replaying work', async () => {
  const f = fixture(); const controller = new AbortController();
  const socket = await f.transport.open(identity, { host: '192.0.2.10', port: 443, signal: controller.signal });
  controller.abort(new Error('cancelled')); await assert.rejects(socket.write('x'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.calls.at(-1).params.op, 'close');
});
test('oversized UDP sends and malformed node replies fail visibly', async () => {
  const f = fixture(); const socket = await f.transport.open(identity, { host: '192.0.2.10', port: 53, protocol: 'udp' });
  await assert.rejects(socket.write(Buffer.alloc(1201)), /1200/);
  f.setReply(() => ({ state: 'open', data: '!!!!' }));
  await assert.rejects(socket.read(), /Invalid read payload/);
});
test('scan uses explicit targets and carries the selected context', async () => {
  const f = fixture();
  f.setReply(request => request.params.op === 'start' ? { state: 'running', id: handle }
    : { state: 'done', complete: false, cancelled: false, results: [{ host: '192.0.2.10', port: 443, observation: 'tcp_open' }] });
  const result = await f.transport.probe(identity, { kind: 'scan', targets: [{ host: '192.0.2.10', port: 443 }] });
  assert.equal(result.context, 'node1'); assert.equal(result.results[0].observation, 'tcp_open');
  assert.equal(result.complete, false);
  assert.equal(f.calls.at(-1).params.op, 'cancel');
});

import { isIPv4 } from 'node:net';

/**
 * Shared protocol client. The host supplies native node.invoke and current grants.
 * resolveContexts must derive its answer from trusted execution identity, never
 * from model-authored tool parameters. It is rechecked before every operation.
 */
export function createNetworkTransport({ invoke, resolveContexts }) {
  if (typeof invoke !== 'function' || typeof resolveContexts !== 'function') throw new TypeError('Host callbacks required');
  const pause = (signal) => new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason ?? new Error('Aborted'));
    const abort = () => { clearTimeout(timer); reject(signal.reason ?? new Error('Aborted')); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, 15);
    signal?.addEventListener('abort', abort, { once: true });
  });
  async function resolve(identity, requested) {
    const grants = await resolveContexts(identity);
    const id = requested ?? grants.default ?? 'local';
    const entry = grants.contexts?.find(context => context.id === id);
    if (!entry) throw new Error('Network context denied');
    if (id === 'local') throw new Error('Use the host local transport for context local');
    if (!entry.nodeId || !identity.sessionKey) throw new Error('Node and trusted session identity required');
    return { ...entry };
  }
  async function call(identity, context, command, params, { signal, cleanup = false } = {}) {
    if (!cleanup) {
      signal?.throwIfAborted();
      const current = await resolve(identity, context.id);
      if (current.nodeId !== context.nodeId) throw new Error('Network context changed');
    }
    const response = await invoke({ nodeId: context.nodeId, command, sessionKey: identity.sessionKey,
      params: { ...params, context: context.id }, signal, timeoutMs: 5000 });
    if (!response || typeof response !== 'object' || response.state === 'error')
      throw new Error(response?.code ?? 'Invalid node response');
    return response;
  }
  function target(host, port) {
    if (!isIPv4(host) || !Number.isInteger(port) || port < 1 || port > 65535) throw new TypeError('IPv4 target and port required');
  }
  return {
    async open(identity, { context: requested, host, port, protocol = 'tcp', signal }) {
      target(host, port);
      if (!['tcp', 'udp'].includes(protocol)) throw new TypeError('Expected tcp or udp');
      const context = await resolve(identity, requested);
      const send = (params, options = {}) => call(identity, context, 'network.transport.v1', params, options);
      const opened = await send({ op: 'open', host, port, protocol }, { signal });
      if (!/^[a-f0-9]{32}$/.test(opened.id)) throw new Error('Invalid node handle');
      const id = opened.id;
      let closed = false;
      const cleanup = async () => {
        if (closed) return;
        closed = true;
        signal?.removeEventListener('abort', onAbort);
        await send({ op: 'close', id }, { cleanup: true });
      };
      const onAbort = () => { cleanup().catch(() => {}); };
      signal?.addEventListener('abort', onAbort, { once: true });
      try {
        signal?.throwIfAborted();
        const deadline = Date.now() + 5000;
        let state = opened.state;
        while (state === 'connecting') {
          if (Date.now() >= deadline) throw new Error('Connection timed out');
          await pause(signal); state = (await send({ op: 'poll', id }, { signal })).state;
        }
        if (state !== 'open') throw new Error('Connection failed');
      } catch (error) { await cleanup().catch(() => {}); throw error; }
      const alive = () => { if (closed) throw new Error('Connection closed'); signal?.throwIfAborted(); };
      let writing = false, reading = false;
      return {
        context: context.id, nodeId: context.nodeId,
        async write(bytes) {
          alive();
          if (writing) throw new Error('Concurrent writes are not supported');
          const data = Buffer.from(bytes);
          if (protocol === 'udp' && data.length > 1200) throw new Error('Datagram exceeds 1200 bytes');
          if (!data.length) throw new Error('Empty writes are not supported');
          writing = true;
          try {
            let offset = 0;
            const deadline = Date.now() + 10000;
            while (offset < data.length) {
              alive();
              if (Date.now() >= deadline) throw new Error('Write timed out');
              const chunk = data.subarray(offset, offset + 2048);
              const response = await send({ op: 'write', id, data: chunk.toString('base64') }, { signal });
              if (!Number.isInteger(response.written) || response.written < 0 || response.written > chunk.length ||
                (protocol === 'udp' && response.written !== 0 && response.written !== data.length)) throw new Error('Invalid write acknowledgement');
              offset += response.written;
              if (!response.written) await pause(signal);
            }
          } catch (error) { await cleanup().catch(() => {}); throw error; }
          finally { writing = false; }
        },
        async read({ timeoutMs = 5000 } = {}) {
          alive();
          if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 10000) throw new TypeError('Read timeout must be 1-10000 ms');
          if (reading) throw new Error('Concurrent reads are not supported');
          reading = true;
          try {
            const deadline = Date.now() + timeoutMs;
            while (Date.now() < deadline) {
              alive();
              const response = await send({ op: 'read', id }, { signal });
              if (response.state === 'eof') return null;
              if (response.data !== undefined) {
                if (typeof response.data !== 'string' || response.data.length > 2732) throw new Error('Invalid read payload');
                const data = Buffer.from(response.data, 'base64');
                if (data.toString('base64') !== response.data || data.length > (protocol === 'udp' ? 1200 : 2048)) throw new Error('Invalid read payload');
                return data;
              }
              await pause(signal);
            }
            return undefined;
          } catch (error) { await cleanup().catch(() => {}); throw error; }
          finally { reading = false; }
        },
        async shutdownWrite() { alive(); await send({ op: 'shutdown', id }, { signal }); },
        close: cleanup,
      };
    },
    async probe(identity, { context: requested, kind, targets, signal }) {
      if (!['ping', 'scan'].includes(kind) || !Array.isArray(targets) || targets.length < 1 || targets.length > 32)
        throw new TypeError('Use ping or scan with 1-32 explicit targets');
      for (const entry of targets) target(entry.host, kind === 'ping' ? 1 : entry.port);
      const context = await resolve(identity, requested);
      const send = (params, options = {}) => call(identity, context, 'network.probe.v1', params, options);
      const started = await send({ op: 'start', kind, targets }, { signal });
      if (!/^[a-f0-9]{32}$/.test(started.id)) throw new Error('Invalid probe handle');
      const deadline = Date.now() + 10000;
      try {
        while (Date.now() < deadline) {
          signal?.throwIfAborted();
          const result = await send({ op: 'poll', id: started.id }, { signal });
          if (result.state === 'done') return { context: context.id, complete: result.complete, cancelled: result.cancelled, results: result.results };
          await pause(signal);
        }
        throw new Error('Probe timed out');
      } finally {
        await send({ op: 'cancel', id: started.id }, { cleanup: true }).catch(() => {});
      }
    },
  };
}

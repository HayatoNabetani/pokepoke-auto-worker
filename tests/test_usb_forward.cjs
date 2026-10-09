const test = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const {once} = require('node:events');
const {createForwardServer} = require('../usb-forward.cjs');

test('a normal upstream close preserves the full response for a slow client',
  {timeout: 10000}, async t => {
    const payload = Buffer.alloc(2 * 1024 * 1024, 'x');
    const upstream = net.createServer(socket => {
      socket.once('data', () => socket.end(payload));
    });
    upstream.listen(0, '127.0.0.1');
    await once(upstream, 'listening');
    t.after(() => upstream.close());
    const forward = createForwardServer(() => new Promise((resolve, reject) => {
      const socket = net.connect(upstream.address().port, '127.0.0.1');
      socket.once('connect', () => resolve(socket));
      socket.once('error', reject);
    }));
    forward.listen(0, '127.0.0.1');
    await once(forward, 'listening');
    t.after(() => forward.close());
    const client = net.connect(forward.address().port, '127.0.0.1');
    t.after(() => client.destroy());
    await once(client, 'connect');
    const chunks = [];
    client.on('data', chunk => chunks.push(chunk));
    client.pause();
    client.write('request');
    setTimeout(() => client.resume(), 50);
    await once(client, 'end');
    assert.deepEqual(Buffer.concat(chunks), payload);
  });

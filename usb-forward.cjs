const net = require('node:net');
function createForwardServer(connect) {
  return net.createServer(async client => {
    client.pause();
    try {
      const remote = await connect();
      if (client.destroyed) { remote.destroy(); return; }
      remote.on('error', () => client.destroy());
      client.on('error', () => remote.destroy());
      client.on('close', () => remote.destroy());
      // pipe() ends the client after a normal upstream EOF. Destroying it here
      // would discard response bytes still waiting in the client's write buffer.
      remote.on('close', () => { if (!remote.readableEnded) client.destroy(); });
      client.pipe(remote).pipe(client);
      client.resume();
    } catch (err) {
      console.error(err.message);
      client.destroy();
    }
  });
}

module.exports = {createForwardServer};
if (require.main === module) {
  const {utilities} = require(process.env.IOS_DEVICE_MODULE || 'appium-ios-device');
  const udid = process.env.IPHONE_UDID;
  if (!udid) throw new Error('IPHONE_UDID must be configured');
  const server = createForwardServer(() => utilities.connectPort(udid, 8100));
  server.listen(8100, '127.0.0.1', () => console.log('iPhone WDA: http://127.0.0.1:8100'));
  process.on('SIGINT', () => { server.close(); process.exit(0); });
  process.on('SIGTERM', () => { server.close(); process.exit(0); });
}

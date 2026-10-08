const net = require('node:net');
const {utilities} = require(process.env.IOS_DEVICE_MODULE || 'appium-ios-device');
const udid = process.env.IPHONE_UDID;
if (!udid) throw new Error('IPHONE_UDID must be configured');
const server = net.createServer(async client => {
  client.pause();
  try {
    const remote = await utilities.connectPort(udid, 8100);
    remote.on('error', () => client.destroy());
    client.on('error', () => remote.destroy());
    client.on('close', () => remote.destroy());
    remote.on('close', () => client.destroy());
    client.pipe(remote).pipe(client);
    client.resume();
  } catch (err) {
    console.error(err.message);
    client.destroy();
  }
});
server.listen(8100, '127.0.0.1', () => console.log('iPhone WDA: http://127.0.0.1:8100'));
process.on('SIGINT', () => { server.close(); process.exit(0); });

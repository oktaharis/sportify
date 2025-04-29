// api/index.js
const serverless = require('serverless-http');
const app = require('../server.js');     // impor Express app yang diekspor
module.exports = serverless(app);     // bungkus jadi serverless function

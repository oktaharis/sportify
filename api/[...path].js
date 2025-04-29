const serverless = require('serverless-http');
const app = require('../server');  // import Express app

module.exports = serverless(app);

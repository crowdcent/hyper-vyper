const fs = require('node:fs');
const solc = require('solc');
const input = fs.readFileSync(0, 'utf8');
process.stdout.write(JSON.stringify({version: solc.version(), output: JSON.parse(solc.compile(input))}));

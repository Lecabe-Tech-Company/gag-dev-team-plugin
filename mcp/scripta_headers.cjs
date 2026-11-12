'use strict';
const fs = require('node:fs');
const path = require('node:path');
try {
  const tokenFile = path.join(__dirname, '..', '..', 'scripta-token');
  if (fs.lstatSync(tokenFile).isSymbolicLink()) throw new Error();
  const token = fs.readFileSync(tokenFile, 'utf8');
  if (!token.trim() || token.length > 4096 || /[\r\n\0]/.test(token)) throw new Error();
  process.stdout.write(JSON.stringify({Authorization: 'Bearer ' + token.trim()}) + '\n');
} catch {
  process.stderr.write('Configure sua chave do Scripta na janela de conexão.\n');
  process.exitCode = 1;
}

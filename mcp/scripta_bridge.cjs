'use strict';
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
let session, protocol;
const endpoint = 'https://scripta-mcp.lecabe.com.br/mcp';
const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
async function forward(message) {
  const tokenPath = path.join(__dirname, '..', '..', 'scripta-token');
  if (fs.lstatSync(tokenPath).isSymbolicLink()) throw new Error('config');
  const token = fs.readFileSync(tokenPath, 'utf8').trim();
  if (!token || token.length > 4096 || /[\r\n\0]/.test(token)) throw new Error('config');
  const headers = {Authorization: 'Bearer ' + token,
    'Content-Type': 'application/json', Accept: 'application/json, text/event-stream'};
  if (session) headers['Mcp-Session-Id'] = session;
  if (protocol) headers['MCP-Protocol-Version'] = protocol;
  const response = await fetch(endpoint, {
    method: 'POST', headers, body: JSON.stringify(message), redirect: 'error',
    signal: AbortSignal.timeout(60000)
  });
  if (!response.ok) throw new Error('remote');
  session = response.headers.get('Mcp-Session-Id') || session;
  if (!Object.hasOwn(message, 'id')) return;
  function output(result) {
    if (message.method === 'initialize' && result.result?.protocolVersion) protocol = result.result.protocolVersion;
    emit(result);
  }
  if (!(response.headers.get('Content-Type') || '').includes('text/event-stream')) {
    const text = await response.text();
    if (text.length > 8 * 1024 * 1024) throw new Error('size');
    output(JSON.parse(text));
    return;
  }
  const decoder = new TextDecoder();
  let buffer = '', total = 0;
  for await (const chunk of response.body) {
    total += chunk.length;
    if (total > 8 * 1024 * 1024) throw new Error('size');
    buffer += decoder.decode(chunk, {stream: true}).replace(/\r\n/g, '\n');
    let split;
    while ((split = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, split); buffer = buffer.slice(split + 2);
      const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (!data) continue;
      const result = JSON.parse(data);
      output(result);
      if (result.id === message.id) { await response.body.cancel().catch(() => {}); return; }
    }
  }
}
let queue = Promise.resolve();
readline.createInterface({input: process.stdin, crlfDelay: Infinity}).on('line', line => {
  let message;
  try { if (line.length > 1024 * 1024) throw new Error(); message = JSON.parse(line); }
  catch { emit({jsonrpc: '2.0', id: null, error: {code: -32700, message: 'Mensagem MCP inválida.'}}); return; }
  queue = queue.then(() => forward(message)).catch(() => {
    if (Object.hasOwn(message, 'id')) emit({jsonrpc: '2.0', id: message.id,
      error: {code: -32000, message: 'Não foi possível consultar o Scripta. Confira sua conexão e chave de acesso.'}});
  });
});

'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
function python() {
  const options = process.platform === 'win32' ? [['py', ['-3']], ['python', []], ['python3', []]] : [['python3', []], ['python', []]];
  for (const [name, prefix] of options) {
    if (spawnSync(name, [...prefix, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'], {stdio:'ignore'}).status === 0)
      return [name, prefix];
  }
  throw new Error('Instale Python 3.11+ para usar os hooks do projeto.');
}
function deny(harness, reason) {
  if (harness === 'cursor') return {permission:'deny', user_message:reason, agent_message:reason};
  if (harness === 'antigravity') return {decision:'deny', reason};
  return {hookSpecificOutput:{hookEventName:'PreToolUse',permissionDecision:'deny',permissionDecisionReason:reason}};
}
exports.hook = (harness, event) => {
  try {
    const [name, prefix] = python();
    const child = spawnSync(name, [...prefix, path.join(__dirname, '..', 'hooks', 'scripts', 'team_hooks.py'), harness, event], {
      input:fs.readFileSync(0), encoding:'utf8', timeout:290000, maxBuffer:4 * 1024 * 1024
    });
    if (child.status !== 0) throw new Error('Verificação do time não concluída.');
    process.stdout.write(child.stdout);
  } catch {
    process.stdout.write(JSON.stringify(event === 'PreToolUse'
      ? deny(harness, 'Não foi possível executar o hook do time. Regularize a integração; a análise Graphify do PR continua obrigatória e deve concluir antes da abertura.')
      : (harness === 'antigravity' && event === 'Stop' ? {decision:'stop'} : {})) + '\n');
  }
};

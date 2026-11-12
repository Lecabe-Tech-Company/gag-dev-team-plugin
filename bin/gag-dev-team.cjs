#!/usr/bin/env node
'use strict';
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const candidates = process.platform === 'win32'
  ? [['py', ['-3']], ['python', []], ['python3', []]]
  : [['python3', []], ['python', []]];
let python;
for (const [command, prefix] of candidates) {
  const probe = spawnSync(command, [...prefix, '-c',
    'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'], {stdio: 'ignore'});
  if (probe.status === 0) { python = [command, prefix]; break; }
}
if (!python) {
  process.stderr.write('Instale Python 3.11+ e tente novamente.\n');
  process.exit(1);
}
const [command, prefix] = python;
const child = spawnSync(command, [...prefix, path.join(__dirname, '..', 'scripts', 'gag_dev_team.py'),
  ...process.argv.slice(2)], {stdio: 'inherit'});
process.exit(child.status ?? 1);

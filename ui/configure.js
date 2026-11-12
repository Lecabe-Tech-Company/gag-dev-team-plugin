'use strict';
const form = document.querySelector('#configure-form');
const button = document.querySelector('#save');
const token = document.querySelector('#token');
const status = document.querySelector('#status');
const session = location.pathname.split('/')[1];
let busy = false;
function show(message, state) {
  status.textContent = message;
  status.dataset.state = state;
}
async function followProgress() {
  try {
    const response = await fetch('api/status', {cache: 'no-store'});
    if (!response.ok) throw new Error();
    const result = await response.json();
    show(result.message, result.status);
    if (result.status === 'installing' || result.status === 'saving') {
      setTimeout(followProgress, 700);
    } else {
      busy = result.status === 'done';
      button.disabled = busy;
    }
  } catch {
    busy = false;
    button.disabled = false;
    show('Conexão local interrompida. Confira o terminal e reabra configure.', 'error');
  }
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  button.disabled = true;
  show('Salvando sua configuração…', 'saving');
  try {
    const response = await fetch('api/save', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-GAG-Session': session},
      body: JSON.stringify({token: token.value})
    });
    const result = await response.json();
    if (!response.ok) {
      busy = false;
      button.disabled = false;
      show(result.error || 'Não foi possível salvar. Confira sua chave.', 'error');
      return;
    }
    token.value = '';
    await followProgress();
  } catch {
    busy = false;
    button.disabled = false;
    show('Não foi possível salvar. Confira se configure continua aberto no terminal.', 'error');
  }
});

const toggleToken = document.querySelector('#toggle-token');
toggleToken.addEventListener('click', () => {
  const visible = token.type === 'password';
  token.type = visible ? 'text' : 'password';
  toggleToken.textContent = visible ? 'Ocultar' : 'Mostrar';
  toggleToken.setAttribute('aria-label', visible ? 'Ocultar chave de acesso' : 'Mostrar chave de acesso');
});

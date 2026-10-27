'use strict';

const $ = (id) => document.getElementById(id);
let config;
let csrf = '';
let busy = false;

function message(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}

async function api(path, body, method = 'POST') {
  const headers = {};
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  const response = await fetch(`/api/admin/auth/${path}`, {
    method, credentials: 'same-origin', cache: 'no-store', headers,
    ...(method === 'GET' ? {} : { body: JSON.stringify(body ?? {}) }),
  });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const error = new Error(data?.detail?.message || '요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.');
    error.status = response.status;
    throw error;
  }
  return data;
}

function decode(value) {
  const raw = atob(value.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

function encode(value) {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function optionsForBrowser(options, registration) {
  const result = { ...options, challenge: decode(options.challenge) };
  if (registration) result.user = { ...options.user, id: decode(options.user.id) };
  const field = registration ? 'excludeCredentials' : 'allowCredentials';
  if (options[field]) result[field] = options[field].map((item) => ({ ...item, id: decode(item.id) }));
  return result;
}

function credentialForServer(credential, registration) {
  const response = { clientDataJSON: encode(credential.response.clientDataJSON) };
  if (registration) {
    response.attestationObject = encode(credential.response.attestationObject);
    response.transports = credential.response.getTransports?.() ?? [];
  } else {
    response.authenticatorData = encode(credential.response.authenticatorData);
    response.signature = encode(credential.response.signature);
    response.userHandle = credential.response.userHandle ? encode(credential.response.userHandle) : null;
  }
  return { id: credential.id, rawId: encode(credential.rawId), type: credential.type, response };
}

function requireWebAuthn() {
  if (!window.isSecureContext || !window.PublicKeyCredential || !navigator.credentials) {
    throw new Error('이 환경에서는 패스키를 사용할 수 없습니다. HTTPS와 패스키를 지원하는 브라우저에서 열어 주세요.');
  }
}

async function renderLogin() {
  csrf = '';
  $('session').hidden = true;
  config = await api('config', null, 'GET');
  $('login').hidden = false;
  $('passkey-login').hidden = config.mode !== 'webauthn' || !config.has_passkey;
  $('setup-form').hidden = config.mode !== 'webauthn' || config.has_passkey;
  $('token-form').hidden = config.mode !== 'manual_jwt';
}

async function showSession(session) {
  csrf = session.csrf_token;
  $('login').hidden = true;
  $('session').hidden = false;
  $('expires').textContent = `로그인 만료: ${new Date(session.expires_at * 1000).toLocaleString('ko-KR')}`;
  $('passkey-management').hidden = config.mode !== 'webauthn';
  if (config.mode === 'webauthn') {
    const credentials = await api('credentials', null, 'GET');
    $('credentials').replaceChildren();
    for (const credential of credentials) {
      const item = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = credential.label;
      const remove = document.createElement('button');
      remove.textContent = '삭제';
      remove.className = 'secondary';
      remove.disabled = !credential.can_delete;
      remove.dataset.locked = String(!credential.can_delete);
      remove.setAttribute('aria-label', `${credential.label} 삭제`);
      remove.addEventListener('click', () => run(async () => {
        if (!window.confirm(`‘${credential.label}’ 패스키를 삭제할까요? 모든 기기에서 로그아웃됩니다.`)) return;
        await api(`credentials/${encodeURIComponent(credential.id)}`, {}, 'DELETE');
        await renderLogin();
        message('패스키를 삭제했습니다. 남은 패스키로 다시 로그인해 주세요.');
      }));
      item.append(label, remove);
      $('credentials').append(item);
    }
  }
}

async function run(action) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach((button) => { button.disabled = true; });
  try {
    await action();
  } catch (error) {
    if (error.status === 401) {
      try { await renderLogin(); } catch { /* Preserve the original error. */ }
    }
    const errors = {
      NotAllowedError: '패스키 인증이 취소되었거나 시간이 만료되었습니다. 다시 시도해 주세요.',
      AbortError: '패스키 인증이 취소되었습니다. 다시 시도해 주세요.',
      InvalidStateError: '이 기기에 이미 등록된 패스키가 있습니다. 다른 기기나 보안 키를 사용해 주세요.',
      NotSupportedError: '이 기기는 요청한 패스키 인증을 지원하지 않습니다.',
      SecurityError: '패스키를 사용할 수 있는 주소인지 확인해 주세요.',
      UnknownError: '기기에서 패스키 인증을 완료하지 못했습니다. 다시 시도해 주세요.',
      NotReadableError: '인증 기기에 접근할 수 없습니다. 연결 상태를 확인해 주세요.',
      TypeError: '서버에 연결할 수 없습니다. 연결 상태를 확인해 주세요.',
      SyntaxError: '서버 응답을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.',
    };
    const text = errors[error.name] || error.message;
    message(text || '인증을 완료할 수 없습니다.', true);
  } finally {
    busy = false;
    document.querySelectorAll('button').forEach((button) => { button.disabled = button.dataset.locked === 'true'; });
  }
}

async function register(code, label) {
  requireWebAuthn();
  const start = await api('registration/options', { ...(code ? { registration_code: code } : {}) });
  const credential = await navigator.credentials.create({ publicKey: optionsForBrowser(start.options, true) });
  if (!credential) throw new Error('패스키 등록이 취소되었습니다.');
  const session = await api('registration/verify', {
    challenge_id: start.challenge_id, credential: credentialForServer(credential, true), label,
    ...(code ? { registration_code: code } : {}),
  });
  await showSession(session);
  message('패스키를 등록했습니다.');
}

$('setup-form').addEventListener('submit', (event) => {
  event.preventDefault();
  run(async () => {
    const code = $('registration-code').value.trim();
    $('registration-code').value = '';
    await register(code, $('setup-label').value.trim());
  });
});
$('add-form').addEventListener('submit', (event) => {
  event.preventDefault();
  run(async () => {
    await register(null, $('add-label').value.trim());
    $('add-label').value = '';
  });
});
$('login-button').addEventListener('click', () => run(async () => {
  requireWebAuthn();
  const start = await api('authentication/options', {});
  const credential = await navigator.credentials.get({ publicKey: optionsForBrowser(start.options, false) });
  if (!credential) throw new Error('패스키 인증이 취소되었습니다.');
  await showSession(await api('authentication/verify', {
    challenge_id: start.challenge_id, credential: credentialForServer(credential, false),
  }));
  message('로그인했습니다.');
}));
$('token-form').addEventListener('submit', (event) => {
  event.preventDefault();
  run(async () => {
    const token = $('login-token').value.trim();
    $('login-token').value = '';
    await showSession(await api('token/exchange', { token }));
    message('로그인했습니다.');
  });
});
$('logout-button').addEventListener('click', () => run(async () => {
  await api('logout', {});
  await renderLogin();
  message('로그아웃했습니다.');
}));

run(async () => {
  config = await api('config', null, 'GET');
  try {
    await showSession(await api('session', null, 'GET'));
    message('관리자로 로그인되어 있습니다.');
  } catch (error) {
    if (error.status !== 401) throw error;
    await renderLogin();
    message('인증 방법을 확인하고 로그인해 주세요.');
  }
});

/* Shared passwordless account helpers. Every mutation carries the page CSRF token. */
function base64urlToBuffer(value) {
    const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(base64 + '='.repeat((4 - base64.length % 4) % 4));
    return Uint8Array.from(binary, character => character.charCodeAt(0)).buffer;
}

function bufferToBase64url(buffer) {
    return btoa(String.fromCharCode(...new Uint8Array(buffer)))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

async function accountRequest(url, body) {
    const options = {credentials: 'same-origin', headers: {'Accept': 'application/json'}};
    if (body !== undefined) {
        options.method = 'POST';
        options.headers['Content-Type'] = 'application/json';
        options.headers['X-CSRF-Token'] = document.querySelector('meta[name="csrf-token"]')?.content || '';
        options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) throw new Error('Your session expired. Refresh the page and sign in again.');
    const result = await response.json();
    if (!response.ok || result.success === false) throw new Error(result.error || 'This request could not be completed.');
    return result;
}

function requirePasskeys() {
    if (!window.isSecureContext) throw new Error('Passkeys need a secure HTTPS connection.');
    if (!window.PublicKeyCredential || !navigator.credentials) throw new Error('This browser does not support passkeys. Try a current Safari, Chrome, Edge, or Firefox browser.');
}

function passkeyError(error) {
    if (error.name === 'NotAllowedError') return 'The passkey request was canceled or timed out. You can try again.';
    if (error.name === 'InvalidStateError') return 'This passkey is already registered. Choose a different device or passkey.';
    return error.message || 'The passkey request could not be completed.';
}

async function registerPasskey(optionsUrl, verifyUrl, passkeyName, registrationBody = {}) {
    requirePasskeys();
    const options = await accountRequest(optionsUrl, registrationBody);
    options.challenge = base64urlToBuffer(options.challenge);
    options.user.id = base64urlToBuffer(options.user.id);
    if (options.excludeCredentials) options.excludeCredentials = options.excludeCredentials.map(c => ({...c, id: base64urlToBuffer(c.id)}));
    const credential = await navigator.credentials.create({publicKey: options});
    if (!credential) throw new Error('No passkey was created. Please try again.');
    return accountRequest(verifyUrl, {
        id: bufferToBase64url(credential.rawId), rawId: bufferToBase64url(credential.rawId),
        type: credential.type, name: passkeyName || 'Passkey',
        response: {
            attestationObject: bufferToBase64url(credential.response.attestationObject),
            clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
            transports: credential.response.getTransports ? credential.response.getTransports() : [],
        },
    });
}

async function authenticatePasskey(optionsUrl, verifyUrl) {
    requirePasskeys();
    const options = await accountRequest(optionsUrl, {});
    options.challenge = base64urlToBuffer(options.challenge);
    if (options.allowCredentials) options.allowCredentials = options.allowCredentials.map(c => ({...c, id: base64urlToBuffer(c.id)}));
    const credential = await navigator.credentials.get({publicKey: options});
    if (!credential) throw new Error('No passkey was selected. Please try again.');
    return accountRequest(verifyUrl, {
        id: bufferToBase64url(credential.rawId), rawId: bufferToBase64url(credential.rawId),
        type: credential.type, next: new URLSearchParams(window.location.search).get('next'),
        response: {
            authenticatorData: bufferToBase64url(credential.response.authenticatorData),
            clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
            signature: bufferToBase64url(credential.response.signature),
            userHandle: credential.response.userHandle ? bufferToBase64url(credential.response.userHandle) : null,
        },
    });
}

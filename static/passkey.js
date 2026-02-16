function base64urlToBuffer(base64url) {
    const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
    const pad = base64.length % 4;
    const padded = pad ? base64 + '='.repeat(4 - pad) : base64;
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
}

function bufferToBase64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

async function registerPasskey(optionsUrl, verifyUrl, passkeyName) {
    const optRes = await fetch(optionsUrl, {method: 'POST'});
    if (!optRes.ok) throw new Error('Failed to get registration options');
    const opts = await optRes.json();

    opts.challenge = base64urlToBuffer(opts.challenge);
    opts.user.id = base64urlToBuffer(opts.user.id);
    if (opts.excludeCredentials) {
        opts.excludeCredentials = opts.excludeCredentials.map(c => ({
            ...c, id: base64urlToBuffer(c.id)
        }));
    }

    const credential = await navigator.credentials.create({publicKey: opts});

    const body = {
        id: bufferToBase64url(credential.rawId),
        rawId: bufferToBase64url(credential.rawId),
        type: credential.type,
        name: passkeyName || 'Passkey',
        response: {
            attestationObject: bufferToBase64url(credential.response.attestationObject),
            clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        },
    };

    const verifyRes = await fetch(verifyUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    return await verifyRes.json();
}

async function authenticatePasskey(optionsUrl, verifyUrl) {
    const optRes = await fetch(optionsUrl, {method: 'POST'});
    if (!optRes.ok) throw new Error('Failed to get authentication options');
    const opts = await optRes.json();

    opts.challenge = base64urlToBuffer(opts.challenge);
    if (opts.allowCredentials) {
        opts.allowCredentials = opts.allowCredentials.map(c => ({
            ...c, id: base64urlToBuffer(c.id)
        }));
    }

    const credential = await navigator.credentials.get({publicKey: opts});

    const body = {
        id: bufferToBase64url(credential.rawId),
        rawId: bufferToBase64url(credential.rawId),
        type: credential.type,
        response: {
            authenticatorData: bufferToBase64url(credential.response.authenticatorData),
            clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
            signature: bufferToBase64url(credential.response.signature),
            userHandle: credential.response.userHandle ? bufferToBase64url(credential.response.userHandle) : null,
        },
    };

    const verifyRes = await fetch(verifyUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    return await verifyRes.json();
}

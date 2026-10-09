(() => {
    'use strict';
    const preview = document.body.dataset.preview === 'true';
    const hasError = Boolean(document.querySelector('.form-notice.error'));
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const openButton = document.getElementById('openInvitation');
    const invitation = document.getElementById('invitationContent');
    const flap = document.querySelector('.envelope-flap');
    const letter = document.querySelector('.envelope-letter');
    const body = document.body;
    const artwork = document.querySelector('.envelope-artwork');
    const envelope = document.querySelector('.envelope');
    const stage = document.querySelector('.envelope-stage');
    let animating = false;
    let layoutPending = false;

    function fitArtwork() {
        if (!artwork?.naturalWidth || !artwork.naturalHeight || !stage || !envelope) return;
        if (animating) { layoutPending = true; return; }
        const bounds = stage.getBoundingClientRect();
        if (!bounds.width || !bounds.height) return;
        const style = window.getComputedStyle(stage);
        const availableWidth = bounds.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - 24;
        const availableHeight = bounds.height - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom) - 32;
        if (availableWidth <= 0 || availableHeight <= 0) return;
        const ratio = artwork.naturalWidth / artwork.naturalHeight;
        const cardHeight = Math.min(220, 360 / ratio), cardWidth = cardHeight * ratio;
        const envelopeWidth = Math.max(130, cardWidth + 32), envelopeHeight = Math.max(100, cardHeight + 24);
        const gap = 18;
        const sceneHeight = envelopeHeight + Math.max(cardHeight + gap, envelopeHeight * .57 + 8);
        const scale = Math.min(1, availableWidth / envelopeWidth, availableHeight / sceneHeight);
        const top = (envelopeHeight - cardHeight) / 2;
        const sizes = {
            'envelope-width': envelopeWidth * scale, 'envelope-height': envelopeHeight * scale,
            'card-width': cardWidth * scale, 'card-height': cardHeight * scale, 'card-top': top * scale,
            'card-lift': -(top + cardHeight + gap) * scale,
            'seal-size': Math.min(44, Math.max(24, Math.min(envelopeWidth, envelopeHeight) * scale * .2)),
        };
        // Width, height and lift must change together: interpolating just the
        // lift after a resize would briefly push resized art through the front.
        envelope.classList.add('artwork-is-sizing');
        for (const [name, value] of Object.entries(sizes)) envelope.style.setProperty(`--art-${name}`, `${value}px`);
        envelope.classList.add('envelope--artwork');
        window.getComputedStyle(letter).transform;
        envelope.classList.remove('artwork-is-sizing');
        layoutPending = false;
    }

    if (artwork && envelope && stage) {
        artwork.addEventListener('load', fitArtwork);
        artwork.addEventListener('error', () => envelope.classList.remove('envelope--artwork'));
        if (artwork.complete) fitArtwork();
        if ('ResizeObserver' in window) new ResizeObserver(fitArtwork).observe(stage);
        else window.addEventListener('resize', fitArtwork);
    }

    function reportPreviewState() {
        if (!preview || window.parent === window) return;
        window.parent.postMessage({type: 'invitation-preview-state', animating}, window.origin);
    }

    // Wait for the actual CSS movement, including its delay. The timeout also
    // completes the sequence if a background tab suppresses transitionend.
    function move(element, update) {
        return new Promise((resolve) => {
            let timer;
            const finish = () => {
                element.removeEventListener('transitionend', onEnd);
                window.clearTimeout(timer);
                resolve();
            };
            const onEnd = (event) => {
                if (event.target === element && event.propertyName === 'transform') finish();
            };
            element.addEventListener('transitionend', onEnd);
            update();
            const style = window.getComputedStyle(element);
            const milliseconds = (value) => Number.parseFloat(value) * (value.trim().endsWith('ms') ? 1 : 1000);
            const duration = milliseconds(style.transitionDuration) + milliseconds(style.transitionDelay);
            timer = window.setTimeout(finish, reducedMotion ? 0 : duration + 80);
        });
    }

    function showInvitation() {
        invitation.hidden = false;
        openButton.setAttribute('aria-expanded', 'true');
        openButton.querySelector('.open-label').textContent = preview ? 'Replay the opening' : 'Invitation opened';
        body.dataset.invitationState = 'open';
    }

    async function openInvitation() {
        if (animating || !invitation || !openButton || !flap || !letter) return;
        animating = true;
        openButton.disabled = true;
        reportPreviewState();
        body.classList.remove('invitation-is-static');
        // Commit the current pose before changing classes on a static preview.
        window.getComputedStyle(letter).transform;
        if (preview && body.classList.contains('invitation-is-open') && !reducedMotion) {
            body.dataset.invitationState = 'closing';
            openButton.querySelector('.open-label').textContent = 'Replaying…';
            // The paper must be completely inside before the flap folds down.
            await move(letter, () => body.classList.remove('invitation-is-open'));
            await move(flap, () => body.classList.remove('envelope-is-open'));
        }
        body.dataset.invitationState = 'opening';
        reportPreviewState();
        await move(flap, () => body.classList.add('envelope-is-open'));
        await move(letter, () => body.classList.add('invitation-is-open'));
        showInvitation();
        if (!preview) {
            document.getElementById('eventTitle')?.focus({ preventScroll: true });
            invitation.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
        }
        animating = false;
        if (layoutPending) fitArtwork();
        openButton.disabled = !preview;
        reportPreviewState();
    }

    if (openButton && invitation) {
        openButton.hidden = false;
        openButton.setAttribute('aria-expanded', preview ? 'true' : 'false');
        invitation.hidden = !preview && !hasError;
        body.dataset.invitationState = 'closed';
        if (preview || hasError) {
            body.classList.add('invitation-is-static', 'envelope-is-open', 'invitation-is-open');
            showInvitation();
            openButton.disabled = !preview;
        }
        openButton.addEventListener('click', openInvitation);
    }

    if (preview) document.addEventListener('click', (event) => {
        if (event.target.closest('a')) event.preventDefault();
    });
    if (preview) {
        window.addEventListener('message', (event) => {
            if (event.source !== window.parent || event.origin !== window.origin || event.data?.type !== 'invitation-preview') return;
            if (event.data.command === 'status') reportPreviewState();
            if (event.data.command === 'replay' && body.dataset.previewView === 'opening') openInvitation();
        });
        reportPreviewState();
    }

    const form = document.querySelector('.rsvp-form');
    if (!form) return;
    const yesRadio = document.getElementById('yes');
    const noRadio = document.getElementById('no');
    const guestFields = document.getElementById('guestsInputContainer');
    const dietaryFields = document.getElementById('dietaryContainer');
    const adults = document.getElementById('num_adults');
    const children = document.getElementById('num_children');
    const partyError = document.getElementById('partyError');
    const status = form.querySelector('.form-status');
    const submit = form.querySelector('[type="submit"]');
    const originalSubmit = submit?.innerHTML;
    const capacity = Number.parseInt(form.dataset.maxGuests, 10) || 10;

    function validateParty() {
        if (!adults || !children || !yesRadio) return;
        const total = Number(adults.value) + Number(children.value);
        const tooMany = yesRadio.checked && total > capacity;
        const message = tooMany ? `Your host can welcome up to ${capacity} ${capacity === 1 ? 'guest' : 'guests'} per invitation, including you.` : '';
        adults.setCustomValidity(message);
        if (partyError) partyError.textContent = message;
        adults.setAttribute('aria-invalid', tooMany ? 'true' : 'false');
    }

    function toggleGuestFields() {
        if (!yesRadio || !guestFields || !dietaryFields) return;
        const attending = yesRadio.checked;
        guestFields.hidden = !attending;
        dietaryFields.hidden = !attending;
        if (adults) { adults.required = attending; adults.disabled = !attending; }
        if (children) { children.required = attending; children.disabled = !attending; }
        const dietaryInput = dietaryFields.querySelector('textarea');
        if (dietaryInput) dietaryInput.disabled = !attending;
        validateParty();
    }

    yesRadio?.addEventListener('change', toggleGuestFields);
    noRadio?.addEventListener('change', toggleGuestFields);
    adults?.addEventListener('input', validateParty);
    children?.addEventListener('input', validateParty);
    toggleGuestFields();

    form.addEventListener('submit', (event) => {
        if (preview) {
            event.preventDefault();
            if (status) status.textContent = 'This is a design preview. Your response has not been sent.';
            return;
        }
        validateParty();
        if (!form.checkValidity()) {
            event.preventDefault();
            form.reportValidity();
            return;
        }
        if (submit) {
            submit.disabled = true;
            submit.textContent = 'Sending your RSVP…';
        }
        if (status) status.textContent = 'Sending your RSVP…';
    });

    window.addEventListener('pageshow', (event) => {
        if (event.persisted && submit && !preview) {
            submit.disabled = false;
            submit.innerHTML = originalSubmit;
            if (status) status.textContent = '';
        }
    });
})();

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
    const cover = document.querySelector('.invitation-cover');
    const artwork = cover?.querySelector('.invitation-artwork');
    const envelope = document.querySelector('.envelope');
    const stage = document.querySelector('.envelope-stage');
    const openingOnly = preview && body.dataset.previewView === 'opening';
    let animating = false;
    let layoutPending = false;
    let artworkReady = false;
    let display, flightAnimation;

    function fitDisplay() {
        if (!display || !artwork?.naturalWidth) return;
        const bounds = stage.getBoundingClientRect();
        if (!bounds.width || !bounds.height) return;
        const ratio = artwork.naturalWidth / artwork.naturalHeight;
        const width = Math.min(bounds.width - 32, (bounds.height - 24) * ratio);
        if (width <= 0) return;
        display.style.width = `${width}px`;
        display.style.height = `${width / ratio}px`;
    }

    function fitArtwork(force = false) {
        if (!artwork?.naturalWidth || !artwork.naturalHeight || !stage || !envelope) return;
        if (animating && force !== true) {
            layoutPending = true;
            // A resize must not strand the flying image at stale viewport coordinates.
            if (flightAnimation && flightAnimation.playState !== 'finished') flightAnimation.finish();
            return;
        }
        if (body.classList.contains('artwork-is-presented')) { fitDisplay(); layoutPending = false; return; }
        const bounds = stage.getBoundingClientRect();
        if (!bounds.width || !bounds.height) return;
        const style = window.getComputedStyle(stage);
        const availableWidth = bounds.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - 16;
        const availableHeight = bounds.height - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom) - 32;
        if (availableWidth <= 0 || availableHeight <= 0) return;
        const ratio = artwork.naturalWidth / artwork.naturalHeight;
        const envelopeWidth = Math.min(760, availableWidth * .94);
        const envelopeHeight = Math.min(envelopeWidth / 1.62, availableHeight * .8);
        const cardHeight = Math.min(envelopeHeight - 24, (envelopeWidth - 32) / ratio), cardWidth = cardHeight * ratio;
        const gap = 18;
        const sceneHeight = envelopeHeight + Math.max(cardHeight + gap, envelopeHeight * .57 + 8);
        const extractionScale = Math.min(.86, availableHeight / sceneHeight);
        const top = (envelopeHeight - cardHeight) / 2;
        const sizes = {
            'envelope-width': envelopeWidth, 'envelope-height': envelopeHeight,
            'card-width': cardWidth, 'card-height': cardHeight, 'card-top': top,
            'card-lift': -(top + cardHeight + gap),
            'seal-size': Math.min(54, Math.max(28, envelopeHeight * .2)),
        };
        // Width, height and lift must change together: interpolating just the
        // lift after a resize would briefly push resized art through the front.
        envelope.classList.add('artwork-is-sizing');
        for (const [name, value] of Object.entries(sizes)) envelope.style.setProperty(`--art-${name}`, `${value}px`);
        envelope.style.setProperty('--art-extraction-scale', extractionScale);
        envelope.classList.add('envelope--artwork');
        window.getComputedStyle(letter).transform;
        envelope.classList.remove('artwork-is-sizing');
        layoutPending = false;
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

    function artworkTarget() {
        if (!openingOnly) return cover;
        if (!display) {
            display = document.createElement('div');
            display.className = 'artwork-display';
            stage.append(display);
        }
        display.hidden = false;
        fitDisplay();
        stage.removeAttribute('aria-hidden');
        return display;
    }

    async function presentArtwork(animate) {
        const from = artwork.getBoundingClientRect();
        const scene = stage.getBoundingClientRect();
        const sceneStyle = window.getComputedStyle(stage);
        for (const [key, value] of Object.entries({left:scene.left, top:scene.top, width:scene.width, height:scene.height})) {
            stage.style.setProperty(`--scene-${key}`, `${value}px`);
        }
        stage.style.setProperty('--scene-padding', sceneStyle.padding);
        // Reserve the final image's space while the same node is in flight.
        cover.style.aspectRatio = `${artwork.naturalWidth} / ${artwork.naturalHeight}`;
        showInvitation();
        body.classList.add('artwork-is-presented');
        const target = artworkTarget();
        if (!animate || reducedMotion || !artwork.animate || !from.width || !from.height) {
            target.append(artwork);
            return;
        }
        body.classList.add('artwork-is-flying');
        body.dataset.invitationState = 'presenting';
        const to = target.getBoundingClientRect();
        if (!to.width || !to.height) {
            target.append(artwork);
            body.classList.remove('artwork-is-flying');
            return;
        }
        const flight = document.createElement('div');
        flight.className = 'artwork-flight';
        flight.setAttribute('aria-hidden', 'true');
        Object.assign(flight.style, {left:`${to.left}px`, top:`${to.top}px`, width:`${to.width}px`, height:`${to.height}px`});
        body.append(flight);
        flight.append(artwork);
        // Extraction eases to a stop. Begin the forward flight at rest too,
        // then build speed gently so the handoff does not feel like a jump.
        const flightDuration = 1300;
        flightAnimation = flight.animate([
            {transform:`translate(${from.left-to.left}px, ${from.top-to.top}px) scale(${from.width/to.width}, ${from.height/to.height})`},
            {transform:'translate(0, 0) scale(1)'},
        ], {duration:flightDuration, easing:'cubic-bezier(.4, 0, .2, 1)', fill:'both'});
        let timer;
        try {
            await Promise.race([flightAnimation.finished.catch(() => {}), new Promise(resolve => {timer=window.setTimeout(resolve, flightDuration + 200);})]);
        } finally {
            window.clearTimeout(timer);
            flightAnimation.cancel(); flightAnimation = null;
            target.append(artwork);
            flight.remove();
            body.classList.remove('artwork-is-flying');
        }
    }

    function resetArtwork() {
        body.classList.add('invitation-is-static');
        body.classList.remove('artwork-is-presented', 'envelope-is-open', 'invitation-is-open');
        if (display) display.hidden = true;
        stage.setAttribute('aria-hidden', 'true');
        letter.append(artwork);
        invitation.hidden = true;
        fitArtwork(true);
        window.getComputedStyle(letter).transform;
        body.classList.remove('invitation-is-static');
    }

    function prepareArtwork() {
        if (!artwork.naturalWidth || !artwork.naturalHeight || artworkReady) return;
        if (animating) { layoutPending = true; return; }
        artworkReady = true;
        envelope.setAttribute('aria-hidden', 'true');
        envelope.classList.add('envelope--artwork');
        cover.style.aspectRatio = `${artwork.naturalWidth} / ${artwork.naturalHeight}`;
        fitArtwork(true);
        if (preview || hasError || body.dataset.invitationState === 'open') {
            presentArtwork(false);
        } else {
            letter.append(artwork);
            fitArtwork();
        }
    }

    async function openInvitation() {
        if (animating || !invitation || !openButton || !flap || !letter) return;
        animating = true;
        openButton.disabled = true;
        reportPreviewState();
        if (artworkReady && body.classList.contains('artwork-is-presented')) resetArtwork();
        body.classList.remove('invitation-is-static');
        // Commit the current pose before changing classes on a static preview.
        window.getComputedStyle(letter).transform;
        if (!artworkReady && preview && body.classList.contains('invitation-is-open') && !reducedMotion) {
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
        if (artworkReady) await presentArtwork(true);
        showInvitation();
        if (!preview) {
            document.getElementById('eventTitle')?.focus({ preventScroll: true });
            invitation.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
        }
        animating = false;
        if (!artworkReady && artwork?.naturalWidth) prepareArtwork();
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

    if (artwork && envelope && stage) {
        artwork.addEventListener('load', prepareArtwork);
        if (artwork.complete) prepareArtwork();
        if ('ResizeObserver' in window) new ResizeObserver(() => fitArtwork()).observe(stage);
        window.addEventListener('resize', () => fitArtwork());
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

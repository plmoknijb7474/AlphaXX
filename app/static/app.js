(() => {
  const openers = document.querySelectorAll('[data-dialog-open]');
  openers.forEach((button) => {
    button.addEventListener('click', () => {
      const dialog = document.getElementById(button.dataset.dialogOpen);
      if (!dialog || typeof dialog.showModal !== 'function') return;
      dialog.showModal();
      dialog.classList.remove('dialog-enter');
      requestAnimationFrame(() => dialog.classList.add('dialog-enter'));
    });
  });

  document.querySelectorAll('[data-dialog-close]').forEach((button) => {
    button.addEventListener('click', () => button.closest('dialog')?.close());
  });

  document.querySelectorAll('.model-dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  const paymentCards = document.querySelectorAll('[data-payment-card]');
  const updatePaymentCards = () => {
    paymentCards.forEach((card) => {
      const radio = card.querySelector('input[type="radio"]');
      card.classList.toggle('is-selected', Boolean(radio?.checked));
    });
  };
  paymentCards.forEach((card) => {
    card.addEventListener('click', () => {
      const radio = card.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
      card.classList.remove('clicked');
      void card.offsetWidth;
      card.classList.add('clicked');
      updatePaymentCards();
    });
  });
  updatePaymentCards();

  document.querySelectorAll('.model-pick input').forEach((checkbox) => {
    checkbox.addEventListener('change', () => {
      checkbox.closest('[data-model-pick-card]')?.classList.toggle('is-picked', checkbox.checked);
    });
  });

  // Tiny companion: follows the pointer subtly and reacts to taps. No backend action is triggered.
  const companion = document.querySelector('.alpha-companion');
  if (companion) {
    let resetTimer;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reducedMotion) {
      window.addEventListener('pointermove', (event) => {
        if (event.pointerType !== 'mouse') return;
        const rect = companion.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const dx = Math.max(-1, Math.min(1, (event.clientX - cx) / 260));
        const dy = Math.max(-1, Math.min(1, (event.clientY - cy) / 260));
        companion.style.setProperty('--buddy-x', `${dx * 3}px`);
        companion.style.setProperty('--buddy-y', `${dy * 2}px`);
        companion.style.setProperty('--buddy-tilt', `${dx * 5}deg`);
      }, { passive: true });
    }
    companion.addEventListener('click', () => {
      companion.classList.remove('is-playing');
      void companion.offsetWidth;
      companion.classList.add('is-playing');
      window.clearTimeout(resetTimer);
      resetTimer = window.setTimeout(() => companion.classList.remove('is-playing'), 900);
    });
  }

})();

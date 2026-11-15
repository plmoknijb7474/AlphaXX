(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  let toastTimer;
  function notify(message) {
    const toast = $('#toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2300);
  }

  // The customer's visual theme follows Damascus time, not the device timezone.
  function updateSyriaMood() {
    const clock = $('#syria-time');
    const label = $('#mood-label');
    const symbol = $('#mood-symbol');
    if (!clock || !label || !symbol) return;
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Asia/Damascus', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
    }).formatToParts(new Date());
    const hour = Number(parts.find(part => part.type === 'hour')?.value ?? 12);
    const minute = parts.find(part => part.type === 'minute')?.value ?? '00';
    const mood = hour >= 5 && hour < 17 ? 'morning' : (hour >= 17 && hour < 20 ? 'evening' : 'night');
    document.documentElement.dataset.mood = mood;
    label.textContent = mood.toUpperCase();
    symbol.textContent = mood === 'morning' ? '☀' : mood === 'evening' ? '◒' : '☾';
    const displayHour = hour % 12 || 12;
    clock.textContent = `SYRIA · ${String(displayHour).padStart(2, '0')}:${minute} ${hour >= 12 ? 'PM' : 'AM'}`;
  }
  updateSyriaMood();
  setInterval(updateSyriaMood, 60_000);

  const pages = ['api', 'usage', 'plans', 'models'];
  function showPage(page) {
    if (!pages.includes(page)) return;
    $$('.page').forEach(section => section.classList.toggle('active', section.dataset.page === page));
    $$('[data-go]').forEach(button => button.classList.toggle('active', button.dataset.go === page));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  $$('[data-go]').forEach(button => button.addEventListener('click', () => showPage(button.dataset.go)));

  async function copyText(value, label) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const helper = document.createElement('textarea');
        helper.value = value;
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.select();
        const ok = document.execCommand('copy');
        helper.remove();
        if (!ok) throw new Error('copy failed');
      }
      notify(`${label} copied`);
    } catch (_) {
      notify('Copy is unavailable in this browser.');
    }
  }
  $$('[data-copy]').forEach(button => button.addEventListener('click', () => {
    copyText(button.dataset.copy || '', button.dataset.label || 'Value');
  }));

  const pet = $('#companion');
  if (pet) {
    const petTip = $('.pet-tip', pet);
    const petMessages = ['Hello there!', 'Boop! That tickles.', 'Let’s explore together.', 'I’m floating!', 'You found me!', 'Have a lovely day.'];
    const petMoves = ['play', 'wiggle', 'twirl', 'shy'];
    let petMessageIndex = 0;
    let petMoveTimer;
    let petAutoTimer;
    function animatePet(move = 'play') {
      petMoves.forEach(name => pet.classList.remove(name));
      void pet.offsetWidth;
      pet.classList.add(move);
      clearTimeout(petMoveTimer);
      petMoveTimer = setTimeout(() => pet.classList.remove(move), 950);
      if (petTip) {
        petTip.textContent = petMessages[petMessageIndex % petMessages.length];
        petMessageIndex += 1;
      }
    }
    pet.addEventListener('click', () => {
      const selected = pet.classList.toggle('selected');
      pet.setAttribute('aria-pressed', String(selected));
      animatePet(petMoves[Math.floor(Math.random() * petMoves.length)]);
      notify(selected ? 'Your little companion noticed you.' : 'Your companion is back to exploring.');
    });
    pet.addEventListener('pointerdown', () => pet.classList.add('touching'), { passive: true });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(name => pet.addEventListener(name, () => pet.classList.remove('touching'), { passive: true }));

    window.addEventListener('pointermove', event => {
      const rect = pet.getBoundingClientRect();
      const dxRaw = event.clientX - (rect.left + rect.width / 2);
      const dyRaw = event.clientY - (rect.top + rect.height / 2);
      const distance = Math.hypot(dxRaw, dyRaw);
      const dx = Math.max(-1, Math.min(1, dxRaw / 125));
      const dy = Math.max(-1, Math.min(1, dyRaw / 125));
      pet.style.setProperty('--look-x', `${dx * 3.5}px`);
      pet.style.setProperty('--look-y', `${dy * 2.5}px`);
      pet.classList.toggle('curious', distance < 170);
    }, { passive: true });

    function schedulePetMoment() {
      clearTimeout(petAutoTimer);
      petAutoTimer = setTimeout(() => {
        if (!document.hidden && !window.matchMedia('(prefers-reduced-motion: reduce)').matches && !pet.classList.contains('selected')) {
          animatePet(Math.random() > .5 ? 'wiggle' : 'shy');
        }
        schedulePetMoment();
      }, 9000 + Math.random() * 7000);
    }
    schedulePetMoment();
    document.addEventListener('visibilitychange', () => { if (!document.hidden) schedulePetMoment(); });
  }
})();

// Loading screen for the service team: the starter cranks, the engine catches, the
// headlights blink on and the blue underglow lights up, then the screen fades away.
// The sound is synthesised, so no audio file is needed; the phone may keep it muted
// until the first tap, in which case the animation simply plays without it.
(function () {
  const SEEN = "car-started";

  function engineSound() {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const now = ctx.currentTime;
    const master = ctx.createGain();
    master.gain.value = 0.55;
    master.connect(ctx.destination);

    // Starter motor: three rough pulses of filtered noise.
    const noise = ctx.createBuffer(1, ctx.sampleRate * 1.2, ctx.sampleRate);
    const samples = noise.getChannelData(0);
    for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1;
    const starter = ctx.createBufferSource();
    starter.buffer = noise;
    const band = ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = 220;
    band.Q.value = 2.5;
    const crank = ctx.createGain();
    crank.gain.value = 0;
    for (let i = 0; i < 4; i++) {
      const t = now + i * 0.22;
      crank.gain.setValueAtTime(0.0, t);
      crank.gain.linearRampToValueAtTime(0.9, t + 0.05);
      crank.gain.linearRampToValueAtTime(0.15, t + 0.18);
    }
    crank.gain.linearRampToValueAtTime(0, now + 1.0);
    starter.connect(band).connect(crank).connect(master);
    starter.start(now);
    starter.stop(now + 1.1);

    // Engine: a low sawtooth that revs up when it catches and settles to idle.
    const engine = ctx.createOscillator();
    engine.type = "sawtooth";
    const low = ctx.createBiquadFilter();
    low.type = "lowpass";
    low.frequency.value = 420;
    const rumble = ctx.createGain();
    rumble.gain.setValueAtTime(0, now);
    rumble.gain.linearRampToValueAtTime(0.0, now + 0.85);
    rumble.gain.linearRampToValueAtTime(0.7, now + 1.0);
    rumble.gain.linearRampToValueAtTime(0.45, now + 1.8);
    rumble.gain.linearRampToValueAtTime(0.0, now + 3.4);
    engine.frequency.setValueAtTime(38, now + 0.85);
    engine.frequency.exponentialRampToValueAtTime(95, now + 1.25);
    engine.frequency.exponentialRampToValueAtTime(46, now + 2.0);
    // Uneven idle, like a real four-cylinder.
    const wobble = ctx.createOscillator();
    wobble.frequency.value = 9;
    const wobbleDepth = ctx.createGain();
    wobbleDepth.gain.value = 3;
    wobble.connect(wobbleDepth).connect(engine.frequency);
    engine.connect(low).connect(rumble).connect(master);
    engine.start(now + 0.8);
    wobble.start(now + 0.8);
    engine.stop(now + 3.5);
    wobble.stop(now + 3.5);
  }

  function haptics(tg) {
    if (!tg || !tg.HapticFeedback) return;
    [0, 220, 440, 660].forEach((ms) =>
      setTimeout(() => tg.HapticFeedback.impactOccurred("heavy"), ms)
    );
    setTimeout(() => tg.HapticFeedback.notificationOccurred("success"), 1050);
  }

  function close(splash) {
    splash.classList.add("leaving");
    setTimeout(() => splash.remove(), 750);
  }

  const PHRASES = [
    [0, "Заводим Гранту…"],
    [1200, "Прогреваем двигатель…"],
    [2200, "Включаем фары…"],
    [3100, "Едем к силомерам 🚀"],
  ];

  function narrate(splash) {
    const label = splash.querySelector(".loading-text");
    PHRASES.forEach(([at, text]) =>
      setTimeout(() => {
        label.classList.add("swap");
        setTimeout(() => { label.textContent = text; label.classList.remove("swap"); }, 250);
      }, at)
    );
  }

  window.showCarSplash = function () {
    const splash = document.getElementById("car-splash");
    if (!splash) return;
    let seen = false;
    try { seen = sessionStorage.getItem(SEEN) === "1"; } catch (_) { /* storage blocked */ }
    if (seen) { splash.remove(); return; }
    try { sessionStorage.setItem(SEEN, "1"); } catch (_) { /* storage blocked */ }

    // Lift the splash out of the swapped screen so it survives the next htmx swap.
    document.body.appendChild(splash);
    splash.hidden = false;
    splash.addEventListener("click", () => close(splash));
    const tg = window.Telegram && window.Telegram.WebApp;
    narrate(splash);
    setTimeout(() => {
      try { engineSound(); } catch (_) { /* no audio, the lights still work */ }
      haptics(tg);
      splash.classList.add("cranking");
    }, 500);
    setTimeout(() => splash.classList.replace("cranking", "running"), 1450);
    setTimeout(() => close(splash), 4300);
  };
})();

// Loading screen of the service app: plays the car video with its sound and fades into
// the screen underneath as the smoke clears. The server includes it on the first visit
// of the day only. If the phone won't start sound on its own, a tap starts the video.
(function () {
  const FADE_BEFORE_END = 0.9;

  window.showCarSplash = function () {
    const splash = document.getElementById("car-splash");
    if (!splash || splash.dataset.started) return;
    splash.dataset.started = "1";

    // Lift it out of the swapped screen so the next htmx swap doesn't take it away.
    document.body.appendChild(splash);
    splash.hidden = false;
    const video = splash.querySelector("video");
    const tap = splash.querySelector(".splash-tap");
    let closing = false;

    function close() {
      if (closing) return;
      closing = true;
      const step = video.volume / 9;
      const fade = setInterval(() => {
        video.volume = Math.max(0, video.volume - step);
        if (video.volume === 0) clearInterval(fade);
      }, 100);
      splash.classList.add("leaving");
      setTimeout(() => splash.remove(), 950);
    }

    function start() {
      tap.hidden = true;
      return video.play();
    }

    video.addEventListener("timeupdate", () => {
      if (video.duration && video.currentTime >= video.duration - FADE_BEFORE_END) close();
    });
    video.addEventListener("ended", close);
    video.addEventListener("error", close);
    // A slow connection shouldn't hold the worker on a black screen.
    const stuck = setTimeout(() => { if (video.paused) close(); }, 8000);
    video.addEventListener("playing", () => clearTimeout(stuck), { once: true });

    start().catch(() => {
      // Sound needs a tap on this phone: wait for it, the poster stays on screen.
      tap.hidden = false;
      splash.addEventListener("click", () => start().catch(close), { once: true });
    });
  };
})();

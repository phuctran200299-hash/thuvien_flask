// Slider và carousel trang chủ: cuộn bằng scroll-snap (vuốt được trên điện thoại),
// JS chỉ thêm nút trước/sau, chấm chỉ vị trí và tự chạy (tắt khi người dùng chọn giảm chuyển động).
(function () {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const behavior = reduceMotion ? 'auto' : 'smooth';

  // ---------- Slider một khung hình (tiêu điểm) ----------
  document.querySelectorAll('[data-slider]').forEach(function (root) {
    const track = root.querySelector('[data-track]');
    const slides = Array.from(track.children);
    const dots = Array.from(root.querySelectorAll('[data-dot]'));
    const progress = root.querySelector('.spot-progress');
    const autoplay = reduceMotion ? 0 : parseInt(root.dataset.autoplay || '0', 10);
    let index = 0, timer = null, paused = false, rafId = null;
    if (slides.length < 2) return;
    root.style.setProperty('--autoplay', autoplay + 'ms');

    const closest = function () {
      const center = track.scrollLeft + track.clientWidth / 2;
      let best = 0, min = Infinity;
      slides.forEach(function (s, i) {
        const d = Math.abs(s.offsetLeft + s.offsetWidth / 2 - center);
        if (d < min) { min = d; best = i; }
      });
      return best;
    };
    const schedule = function () {
      clearTimeout(timer);
      if (progress) {
        progress.classList.remove('is-running');
        void progress.offsetWidth; // khởi động lại thanh tiến trình
      }
      if (!autoplay || paused) return;
      if (progress) progress.classList.add('is-running');
      timer = setTimeout(function () { go(index + 1); }, autoplay);
    };
    const sync = function (i) {
      index = i;
      dots.forEach(function (d, k) {
        d.classList.toggle('is-active', k === i);
        d.setAttribute('aria-current', k === i ? 'true' : 'false');
      });
      slides.forEach(function (s, k) { s.inert = k !== i; });
      schedule();
    };
    const go = function (i) {
      const n = (i + slides.length) % slides.length;
      track.scrollTo({ left: slides[n].offsetLeft, behavior: behavior });
      sync(n);
    };

    track.addEventListener('scroll', function () {
      if (rafId) return;
      rafId = requestAnimationFrame(function () {
        rafId = null;
        const i = closest();
        if (i !== index) sync(i);
      });
    }, { passive: true });

    root.querySelector('[data-prev]')?.addEventListener('click', function () { go(index - 1); });
    root.querySelector('[data-next]')?.addEventListener('click', function () { go(index + 1); });
    dots.forEach(function (d, k) { d.addEventListener('click', function () { go(k); }); });

    const pause = function (state) { paused = state; root.classList.toggle('is-paused', state); schedule(); };
    root.addEventListener('mouseenter', function () { pause(true); });
    root.addEventListener('mouseleave', function () { pause(false); });
    root.addEventListener('focusin', function () { pause(true); });
    root.addEventListener('focusout', function (e) { if (!root.contains(e.relatedTarget)) pause(false); });
    document.addEventListener('visibilitychange', function () { pause(document.hidden); });

    sync(closest());
  });

  // ---------- Dải carousel nhiều thẻ ----------
  document.querySelectorAll('[data-rail]').forEach(function (root) {
    const track = root.querySelector('[data-track]');
    const prev = root.querySelector('[data-prev]');
    const next = root.querySelector('[data-next]');
    let rafId = null;
    const update = function () {
      const max = track.scrollWidth - track.clientWidth - 2;
      if (prev) prev.disabled = track.scrollLeft <= 2;
      if (next) next.disabled = track.scrollLeft >= max;
      track.classList.toggle('rail-fade', track.scrollLeft < max);
    };
    const step = function (dir) { track.scrollBy({ left: dir * track.clientWidth * 0.85, behavior: behavior }); };
    prev?.addEventListener('click', function () { step(-1); });
    next?.addEventListener('click', function () { step(1); });
    track.addEventListener('scroll', function () {
      if (rafId) return;
      rafId = requestAnimationFrame(function () { rafId = null; update(); });
    }, { passive: true });
    window.addEventListener('resize', update);
    update();
  });
})();

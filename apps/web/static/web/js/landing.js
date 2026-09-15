/* Движение на лендинге.

   Правило одно: страница обязана работать без этого файла. Он ничего не
   рендерит и ничего не грузит — только доигрывает то, что уже отрисовано
   сервером. Поэтому появление блоков прячется классом `has-js`, который
   ставится инлайново в <head>: если JS отключён, класса нет и всё видно.

   Обработчиков прокрутки и движения мыши ровно по одному, и оба сведены в
   requestAnimationFrame: считать позиции на каждое событие — самый простой
   способ уронить плавность на слабой машине.

   Всё выключается системной настройкой «уменьшить движение»: тогда файл
   только доводит счётчики до конечных значений и выходит. */

(function () {
  "use strict";

  var reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $$ = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };

  /* --------------------------------------------------------- появление */
  /* Блоки въезжают на 14 px один раз и больше не двигаются: повторное
     появление при каждой прокрутке вверх-вниз читается как баг, а не как
     оформление. Соседи внутри группы идут с задержкой по индексу. */

  function initReveal() {
    var items = $$("[data-reveal]");
    if (!items.length) return;

    $$("[data-reveal-group]").forEach(function (group) {
      $$("[data-reveal]", group)
        .filter(function (node) {
          return node.closest("[data-reveal-group]") === group;
        })
        .forEach(function (node, index) {
          // Больше шести шагов задержки превращают выход блока в ожидание.
          node.style.setProperty("--i", Math.min(index, 6));
        });
    });

    if (reduced || !("IntersectionObserver" in window)) {
      items.forEach(function (node) { node.classList.add("is-in", "is-done"); });
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var node = entry.target;
        node.classList.add("is-in");
        io.unobserve(node);
        // will-change снимаем после проигрыша, иначе слой висит вечно.
        setTimeout(function () { node.classList.add("is-done"); }, 1200);
      });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.08 });

    items.forEach(function (node) { io.observe(node); });
  }

  /* ---------------------------------------------------------- счётчики */
  /* Цифры на первом экране докручиваются один раз при показе. Кривая —
     easeOutExpo: почти весь путь проходится сразу, а последние проценты
     доезжают медленно, поэтому взгляд успевает прочитать итог. */

  function runCounter(node) {
    var target = parseFloat(node.dataset.count);
    var decimals = parseInt(node.dataset.decimals || "0", 10);
    var format = function (value) {
      return value.toLocaleString("ru-RU", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });
    };

    if (reduced || !isFinite(target)) {
      node.textContent = format(target);
      return;
    }

    var duration = 1400;
    var started = null;

    function step(now) {
      if (started === null) started = now;
      var t = Math.min(1, (now - started) / duration);
      var eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
      node.textContent = format(target * eased);
      if (t < 1) requestAnimationFrame(step);
    }

    requestAnimationFrame(step);
  }

  function initCounters() {
    var nodes = $$("[data-count]");
    if (!nodes.length) return;

    if (!("IntersectionObserver" in window)) {
      nodes.forEach(runCounter);
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        io.unobserve(entry.target);
        runCounter(entry.target);
      });
    }, { threshold: 0.6 });

    nodes.forEach(function (node) { io.observe(node); });
  }

  /* ------------------------------------------------------ блик на стекле */
  /* Отражение под курсором. Слушатель один на всю страницу, координаты
     пишутся в CSS-переменные карточки — рисует их браузер, JS не трогает
     ни один стиль, кроме двух чисел. */

  function initSpotlight() {
    if (reduced || !matchMedia("(hover: hover)").matches) return;

    var current = null;
    var rect = null;
    var point = null;
    var queued = false;

    function paint() {
      queued = false;
      if (!current || !rect || !point) return;
      current.style.setProperty("--mx", (point.x - rect.left) + "px");
      current.style.setProperty("--my", (point.y - rect.top) + "px");
    }

    document.addEventListener("pointermove", function (event) {
      var card = event.target.closest ? event.target.closest(".glass") : null;

      if (card !== current) {
        current = card;
        // Границы карточки читаем только при смене цели: getBoundingClientRect
        // на каждое движение мыши заставляет браузер пересчитывать раскладку.
        rect = card ? card.getBoundingClientRect() : null;
      }
      if (!card) return;

      point = { x: event.clientX, y: event.clientY };
      if (!queued) {
        queued = true;
        requestAnimationFrame(paint);
      }
    }, { passive: true });
  }

  /* ------------------------------------------- шапка, меню и параллакс */
  /* Один обработчик прокрутки на три задачи: фон шапки, смещение ореола
     под вывеской и подсветка текущего пункта меню. */

  function initScroll() {
    var header = document.querySelector(".header");
    var halo = document.querySelector(".hero-halo");
    var links = $$(".nav a[href^='#']");
    var sections = links
      .map(function (link) { return document.querySelector(link.getAttribute("href")); })
      .filter(Boolean);

    var queued = false;

    function update() {
      queued = false;
      var y = window.pageYOffset;

      if (header) header.classList.toggle("is-scrolled", y > 24);

      // Ореол отстаёт от прокрутки — глубина сцены. Ограничение нужно,
      // чтобы на длинной странице пятно не уехало из первого экрана.
      if (halo && !reduced) {
        halo.style.setProperty("--hero-shift", Math.min(y * 0.18, 120) + "px");
      }
    }

    window.addEventListener("scroll", function () {
      if (queued) return;
      queued = true;
      requestAnimationFrame(update);
    }, { passive: true });

    update();

    if (!sections.length || !("IntersectionObserver" in window)) return;

    // Текущим считается блок, пересёкший линию под шапкой. Отсюда
    // rootMargin: верх окна опускается на высоту шапки, низ поднимается.
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        links.forEach(function (link) {
          link.classList.toggle(
            "is-current",
            link.getAttribute("href") === "#" + entry.target.id
          );
        });
      });
    }, { rootMargin: "-72px 0px -62% 0px" });

    sections.forEach(function (section) { spy.observe(section); });
  }

  /* --------------------------------------------------------------- FAQ */
  /* <details> открывается мгновенно: браузер снимает с содержимого
     display:none, и переход по высоте проиграть не успевает. Поэтому
     открытие и закрытие ведём сами — раскрытие анимируется дробной
     строкой grid, её браузер интерполирует, в отличие от height:auto. */

  function initFaq() {
    $$(".faq details").forEach(function (details) {
      var summary = details.querySelector("summary");
      var answer = details.querySelector(".faq-answer");
      if (!summary || !answer) return;

      summary.addEventListener("click", function (event) {
        if (reduced) return;
        event.preventDefault();

        if (details.open) {
          answer.style.gridTemplateRows = "1fr";
          // Принудительный пересчёт: без него браузер склеит установку и
          // сброс в один кадр и анимации снова не будет.
          void answer.offsetHeight;
          answer.style.gridTemplateRows = "0fr";
          answer.addEventListener("transitionend", function done() {
            answer.removeEventListener("transitionend", done);
            answer.style.gridTemplateRows = "";
            details.open = false;
          });
        } else {
          details.open = true;
          answer.style.gridTemplateRows = "0fr";
          void answer.offsetHeight;
          answer.style.gridTemplateRows = "1fr";
          answer.addEventListener("transitionend", function done() {
            answer.removeEventListener("transitionend", done);
            answer.style.gridTemplateRows = "";
          });
        }
      });
    });
  }

  /* ------------------------------------------------------ мокап на паузу */
  /* Показ сценария крутится 12 секунд по кругу. За пределами экрана он
     только греет процессор и съедает батарею на телефоне. */

  function initMockup() {
    var mockup = document.querySelector(".mockup");
    if (!mockup || !("IntersectionObserver" in window)) return;

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        mockup.classList.toggle("is-paused", !entry.isIntersecting);
      });
    }, { threshold: 0 });

    io.observe(mockup);
  }

  /* --------------------------------------------------------------- старт */

  function init() {
    try {
      initReveal();
      initCounters();
      initSpotlight();
      initScroll();
      initFaq();
      initMockup();
    } catch (err) {
      // Оформление не стоит того, чтобы из-за него пропал текст: если
      // что-то упало на полпути, показываем всё как есть.
      $$("[data-reveal]").forEach(function (node) {
        node.classList.add("is-in", "is-done");
      });
      console.error(err);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

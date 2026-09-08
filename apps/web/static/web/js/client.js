/* Клиентская страница: вход по SMS, запись в четыре шага, свои записи.

   Состояние черновика приходит и по REST, и по WebSocket в одном формате,
   поэтому рисует его одна функция — renderDraft. WebSocket только ускоряет
   обновление, всё работает и без него. */

(function () {
  "use strict";

  const { fmt, icon, $, $$, el, empty, ask, toast, guard } = App;

  const api = App.createClient("client", { onSignedOut: () => signOut(true) });

  const state = {
    me: null,
    draft: null,
    points: [],
    oils: [],
    days: [],
    activeDay: null,
    slots: [],
    scope: "upcoming",
    phone: "",
  };

  let ticker = null;
  let socket = null;

  /* ----------------------------------------------------------- утилиты */

  const NEXT_STEP_INDEX = { select_point: 0, select_oil: 1, select_slot: 2, confirm: 3 };

  function isAlive(draft) {
    return Boolean(draft && draft.is_open && draft.is_alive);
  }

  function show(id, visible) {
    const node = document.getElementById(id);
    if (node) node.hidden = !visible;
  }

  /* -------------------------------------------------------------- вход */

  async function requestOtp() {
    const phone = $("#phone").value.trim();
    if (!phone) return;

    const data = await guard(() => api.request("/auth/otp/request/", {
      method: "POST", body: { phone }, auth: false,
    }));
    if (!data) return;

    state.phone = data.phone;
    show("auth-step-phone", false);
    show("auth-step-code", true);
    $("#auth-sub").textContent = "Код отправлен на " + data.phone;

    if (data.debug_code) {
      $("#code").value = data.debug_code;
      $("#otp-hint").textContent = "Режим разработки: код " + data.debug_code + " уже подставлен.";
    } else {
      $("#otp-hint").textContent = "Код действует 5 минут.";
    }
    $("#code").focus();
  }

  async function verifyOtp() {
    const code = $("#code").value.trim();
    if (!code) return;

    const data = await guard(() => api.request("/auth/otp/verify/", {
      method: "POST", body: { phone: state.phone, code }, auth: false,
    }));
    if (!data) return;

    api.store.save(data.access, data.refresh);
    state.me = data.user;

    toast(data.is_new_user ? "Добро пожаловать! Заполните профиль." : "С возвращением!", "ok");
    await afterSignIn();

    if (data.is_new_user) document.getElementById("profile").scrollIntoView({ behavior: "smooth" });
  }

  function signOut(silent) {
    api.signOut();
    if (socket) { socket.close(); socket = null; }
    stopTicker();
    state.me = null;
    state.draft = null;
    if (!silent) toast("Вы вышли из аккаунта");
    renderAuthState();
  }

  async function afterSignIn() {
    renderAuthState();
    await Promise.all([loadDraft(), loadBookings()]);
    openSocket();
  }

  function renderAuthState() {
    const authorized = Boolean(state.me);

    show("auth-section", !authorized);
    show("booking", authorized);
    show("my", authorized);
    show("profile", authorized);
    show("hero", !authorized);

    $("#btn-signin").hidden = authorized;
    $("#btn-signout").hidden = !authorized;

    if (authorized) {
      $("#full-name").value = state.me.full_name || "";
      $("#car-model").value = state.me.car_model || "";
      $("#car-plate").value = state.me.car_plate || "";
      $("#profile-phone").textContent = state.me.phone + " · вход по SMS";
    } else {
      show("auth-step-phone", true);
      show("auth-step-code", false);
      $("#auth-sub").textContent = "Пришлём код в SMS — пароль придумывать не нужно.";
      $("#step-panel").innerHTML = "";
    }
  }

  /* ---------------------------------------------------------- черновик */

  async function loadDraft() {
    const draft = await guard(() => api.get("/bookings/drafts/current/"));
    renderDraft(draft === undefined ? null : draft);
  }

  async function startDraft(restart) {
    const draft = await guard(() => api.post("/bookings/drafts/", { restart: Boolean(restart) }));
    if (draft) {
      renderDraft(draft);
      document.getElementById("booking").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  async function step(path, body) {
    if (!state.draft) return;
    const draft = await guard(() => api.post("/bookings/drafts/" + state.draft.id + "/" + path + "/", body));
    if (draft) renderDraft(draft);
    // Черновик мог протухнуть, пока клиент думал: сервер вернёт 410, guard
    // покажет причину, а мы перечитаем состояние и нарисуем актуальный экран.
    else await loadDraft();
  }

  function renderDraft(draft) {
    state.draft = draft;

    renderDraftActions();
    renderSteps();
    renderTimer();
    renderStepPanel();
  }

  function renderDraftActions() {
    const box = $("#draft-actions");
    box.innerHTML = "";

    if (isAlive(state.draft)) {
      box.append(
        el("button", { class: "btn btn-sm", type: "button", html: icon("refresh", 15) + "Начать заново",
          onClick: () => startDraft(true) }),
        el("button", { class: "btn btn-sm btn-danger", type: "button", text: "Прервать",
          onClick: async () => {
            const yes = await ask({ title: "Прервать запись?", text: "Выбранное время сразу освободится.", confirmLabel: "Прервать", danger: true });
            if (yes) await step("cancel", {});
          } })
      );
    } else {
      box.append(el("button", { class: "btn btn-primary", type: "button", text: "Начать запись",
        onClick: () => startDraft(false) }));
    }
  }

  function renderSteps() {
    const draft = state.draft;
    const current = isAlive(draft) ? NEXT_STEP_INDEX[draft.next_action] : -1;

    const rows = [
      { label: "Адрес", value: draft && draft.service_point ? draft.service_point.name : "не выбран" },
      { label: "Масло", value: draft && draft.oil ? draft.oil.title : "не выбрано" },
      { label: "Время", value: draft && draft.slot_start ? fmt.dateTime(draft.slot_start) : "не выбрано" },
      { label: "Подтверждение", value: draft && draft.step === "confirmed" ? "готово" : "финальный шаг" },
    ];

    $("#steps").innerHTML = rows
      .map((row, i) => {
        const done = isAlive(draft) ? i < current : false;
        const active = i === current;
        return (
          '<div class="step' + (active ? " is-active" : "") + (done ? " is-done" : "") + '">' +
          '<div class="step-label"><span class="step-num">' + (done ? "✓" : i + 1) + "</span>" + row.label + "</div>" +
          '<div class="step-value">' + row.value + "</div></div>"
        );
      })
      .join("");
  }

  function renderTimer() {
    stopTicker();
    const draft = state.draft;

    if (!isAlive(draft)) {
      show("timer-bar", false);
      return;
    }

    show("timer-bar", true);
    const total = Math.max(draft.seconds_left, 1);
    let left = draft.seconds_left;

    const paint = () => {
      const low = left <= 60;
      $("#timer-value").textContent = fmt.clock(left);
      $("#timer-value").classList.toggle("is-low", low);
      $("#timer-fill").style.width = Math.max(0, (left / total) * 100) + "%";
      $("#timer-fill").classList.toggle("is-low", low);
    };

    paint();
    ticker = setInterval(() => {
      left -= 1;
      paint();
      if (left <= 0) {
        stopTicker();
        // Время вышло — сервер уже погасил черновик, забираем актуальное состояние.
        loadDraft();
      }
    }, 1000);
  }

  function stopTicker() {
    if (ticker) clearInterval(ticker);
    ticker = null;
  }

  /* --------------------------------------------------------- шаги записи */

  function renderStepPanel() {
    const panel = $("#step-panel");
    panel.innerHTML = "";
    const draft = state.draft;

    if (!isAlive(draft)) {
      panel.append(el("div", { class: "card" }, [
        empty(
          draft && draft.close_reason === "expired"
            ? "Пять минут вышли, запись не сохранилась. Начните заново — это быстро."
            : "Нажмите «Начать запись», чтобы выбрать адрес, масло и время.",
          draft && draft.close_reason === "expired" ? "clock" : "calendar"
        ),
      ]));
      return;
    }

    const card = el("div", { class: "card" });
    panel.append(card);

    if (draft.next_action === "select_point") renderPointsStep(card);
    else if (draft.next_action === "select_oil") renderOilsStep(card);
    else if (draft.next_action === "select_slot") renderSlotsStep(card);
    else renderConfirmStep(card);
  }

  function stepHead(card, title, sub) {
    card.append(el("div", { class: "card-head" }, [
      el("div", {}, [
        el("div", { class: "card-title", text: title }),
        el("div", { class: "card-sub", text: sub }),
      ]),
    ]));
  }

  function renderPointsStep(card) {
    stepHead(card, "Шаг 1. Выберите адрес", "Обе точки работают без выходных.");

    const list = el("div", { class: "stack" });
    state.points.forEach((point) => {
      list.append(el("button", {
        class: "pick", type: "button",
        onClick: () => step("select-point", { service_point_id: point.id }),
      }, [
        el("span", { class: "pick-icon", html: icon("pin", 19) }),
        el("span", { class: "pick-body" }, [
          el("span", { class: "pick-title", text: point.name }),
          el("span", { class: "pick-meta", text: point.address + " · " + workHours(point) }),
        ]),
      ]));
    });
    card.append(list);
  }

  async function renderOilsStep(card) {
    stepHead(card, "Шаг 2. Выберите масло", "Цена указана вместе с работой.");
    const list = el("div", { class: "stack" });
    card.append(list);

    const pointId = state.draft.service_point.id;
    const oils = await guard(() => api.get("/service-points/" + pointId + "/oils/"));
    state.oils = oils || [];

    if (!state.oils.length) {
      list.append(empty("На этой точке сейчас нет масла в наличии.", "drop"));
      return;
    }

    state.oils.forEach((oil) => {
      list.append(el("button", {
        class: "pick", type: "button",
        disabled: oil.available_quantity <= 0,
        onClick: () => step("select-oil", { oil_id: oil.id }),
      }, [
        el("span", { class: "pick-icon", html: icon("drop", 19) }),
        el("span", { class: "pick-body" }, [
          el("span", { class: "pick-title", text: oil.title }),
          el("span", { class: "pick-meta",
            text: oil.oil_type_display + " · осталось " + oil.available_quantity +
              " " + fmt.plural(oil.available_quantity, "канистра", "канистры", "канистр") }),
        ]),
        el("span", { class: "pick-price", text: fmt.money(oil.total_price) }),
      ]));
    });
  }

  async function renderSlotsStep(card) {
    stepHead(card, "Шаг 3. Выберите время", "Показаны только свободные слоты.");

    const daysBox = el("div", { class: "day-scroll" });
    const slotsBox = el("div", { style: "margin-top:16px" });
    card.append(daysBox, slotsBox);

    const pointId = state.draft.service_point.id;
    const data = await guard(() => api.get("/service-points/" + pointId + "/slots/"));
    state.days = (data && data.available_days) || [];

    if (!state.days.length) {
      slotsBox.append(empty("Свободных дней в ближайшие две недели нет.", "calendar"));
      return;
    }

    if (!state.days.includes(state.activeDay)) state.activeDay = state.days[0];

    const paintDays = () => {
      daysBox.innerHTML = "";
      state.days.forEach((day) => {
        daysBox.append(el("button", {
          class: "day", type: "button",
          "aria-pressed": String(day === state.activeDay),
          onClick: () => { state.activeDay = day; paintDays(); loadSlots(pointId, day, slotsBox); },
        }, [
          el("span", { class: "day-dow", text: fmt.dow(day) }),
          el("span", { class: "day-num", text: fmt.date(day) }),
        ]));
      });
    };

    paintDays();
    await loadSlots(pointId, state.activeDay, slotsBox);
  }

  async function loadSlots(pointId, day, box) {
    box.innerHTML = "";
    const data = await guard(() => api.get("/service-points/" + pointId + "/slots/?date=" + day));
    const slots = (data && data.slots) || [];

    if (!slots.length) {
      box.append(empty("На этот день свободного времени нет — выберите другой.", "clock"));
      return;
    }

    const grid = el("div", { class: "slot-grid" });
    slots.forEach((slot) => {
      grid.append(el("button", {
        class: "slot", type: "button",
        onClick: () => step("select-slot", { start_at: slot.start_at }),
      }, [
        el("span", { text: slot.local_time }),
        el("small", { text: slot.free_posts + " " + fmt.plural(slot.free_posts, "пост", "поста", "постов") }),
      ]));
    });
    box.append(grid);
  }

  function renderConfirmStep(card) {
    const draft = state.draft;
    stepHead(card, "Шаг 4. Подтверждение", "Проверьте детали — после подтверждения придёт SMS с кодом записи.");

    const oil = draft.oil;
    const rows = [
      ["Адрес", draft.service_point.name + ", " + draft.service_point.address],
      ["Время", fmt.dateFull(draft.slot_start) + ", " + fmt.time(draft.slot_start)],
      ["Масло", oil.title],
      ["Стоимость", fmt.money(oil.price) + " масло + " + fmt.money(oil.work_price) + " работа"],
    ];

    const summary = el("div", { class: "stack-sm", style: "margin-bottom:16px" });
    rows.forEach(([label, value]) => {
      summary.append(el("div", { class: "row", style: "justify-content:space-between;gap:16px" }, [
        el("span", { class: "hint", text: label }),
        el("span", { style: "font-weight:600;text-align:right", text: value }),
      ]));
    });

    summary.append(el("div", { class: "divider" }));
    summary.append(el("div", { class: "row", style: "justify-content:space-between" }, [
      el("span", { style: "font-weight:600", text: "Итого" }),
      el("span", { style: "font-weight:700;font-size:19px", text: fmt.money(oil.total_price) }),
    ]));

    const comment = el("input", { id: "comment", placeholder: "Например: подъеду на пять минут раньше" });

    card.append(summary,
      el("div", { class: "field", style: "margin-bottom:14px" }, [
        el("label", { for: "comment", text: "Комментарий (необязательно)" }), comment,
      ]),
      el("button", {
        class: "btn btn-primary btn-lg btn-block", type: "button", html: icon("check", 16) + "Подтвердить запись",
        onClick: () => confirmDraft(comment.value.trim()),
      })
    );
  }

  async function confirmDraft(comment) {
    const booking = await guard(() =>
      api.post("/bookings/drafts/" + state.draft.id + "/confirm/", { comment })
    );
    if (!booking) { await loadDraft(); return; }

    toast("Код записи — " + booking.code + ". Ждём вас " + fmt.dateTime(booking.start_at) + ".", "ok", "Вы записаны");
    state.scope = "upcoming";
    syncScopeTabs();
    await Promise.all([loadDraft(), loadBookings()]);
    document.getElementById("my").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* --------------------------------------------------------- мои записи */

  async function loadBookings() {
    const data = await guard(() => api.get("/bookings/?scope=" + state.scope));
    const box = $("#bookings");
    box.innerHTML = "";

    const items = (data && data.results) || [];
    if (!items.length) {
      box.append(el("div", { class: "card card-flat" }, [
        empty(state.scope === "upcoming" ? "Предстоящих записей нет." : "Здесь появятся завершённые записи.", "calendar"),
      ]));
      return;
    }

    items.forEach((booking) => box.append(bookingCard(booking)));
  }

  function bookingCard(booking) {
    const start = new Date(booking.start_at);
    const badge = {
      pending: ["badge-info", "Ожидает"],
      in_progress: ["badge-warn", "В работе"],
      completed: ["badge-ok", "Выполнена"],
    }[booking.status] || ["badge-danger", booking.status_display];

    const actions = el("div", { class: "row row-end" });
    if (booking.can_cancel) {
      actions.append(el("button", {
        class: "btn btn-sm btn-danger", type: "button", text: "Отменить",
        onClick: async () => {
          const reason = await ask({
            title: "Отменить запись " + booking.code + "?",
            text: "Скажите пару слов — это поможет сервису.",
            placeholder: "Причина (необязательно)",
            confirmLabel: "Отменить запись",
            danger: true,
            withInput: true,
          });
          if (reason === null) return;
          const ok = await guard(() => api.post("/bookings/" + booking.id + "/cancel/", { reason }));
          if (ok) { toast("Запись отменена", "ok"); await loadBookings(); }
        },
      }));
    }

    return el("div", { class: "booking-card" }, [
      el("div", { class: "booking-when" }, [
        el("div", { class: "booking-day", text: start.getDate() }),
        el("div", { class: "booking-month", text: fmt.date(booking.start_at).split(" ")[1] }),
        el("div", { class: "booking-time", text: fmt.time(booking.start_at) }),
      ]),
      el("div", { class: "booking-info" }, [
        el("div", { class: "booking-code", text: "Код " + booking.code }),
        el("div", { class: "booking-title", text: booking.oil_title }),
        el("div", { class: "booking-meta", text: booking.service_point.address }),
        booking.cancel_reason
          ? el("div", { class: "booking-meta", style: "margin-top:4px", text: "Причина: " + booking.cancel_reason })
          : null,
      ]),
      el("div", { class: "stack-sm", style: "align-items:flex-end" }, [
        el("span", { class: "badge " + badge[0], text: badge[1] }),
        el("span", { style: "font-weight:680", text: fmt.money(booking.total_price) }),
        actions,
      ]),
    ]);
  }

  function syncScopeTabs() {
    $$(".tab[data-scope]").forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab.dataset.scope === state.scope));
    });
  }

  /* ------------------------------------------------------------- адреса */

  function workHours(point) {
    return point.opens_at.slice(0, 5) + "–" + point.closes_at.slice(0, 5);
  }

  async function loadPoints() {
    const points = await guard(() => api.request("/service-points/", { auth: false }));
    state.points = points || [];

    const box = $("#points-list");
    box.innerHTML = "";
    state.points.forEach((point) => {
      box.append(el("div", { class: "card" }, [
        el("div", { class: "row", style: "gap:12px;align-items:flex-start" }, [
          el("span", { class: "pick-icon", html: icon("pin", 19) }),
          el("div", { style: "flex:1;min-width:0" }, [
            el("div", { class: "card-title", text: point.name }),
            el("div", { class: "card-sub", text: point.address }),
          ]),
        ]),
        el("div", { class: "divider" }),
        el("div", { class: "row", style: "gap:18px" }, [
          el("span", { class: "hint", html: icon("clock", 14) + " " + workHours(point) }),
          el("span", { class: "hint", text: point.posts_count + " " + fmt.plural(point.posts_count, "пост", "поста", "постов") }),
          el("span", { class: "hint", text: "слот " + point.slot_minutes + " мин" }),
          point.phone ? el("a", { class: "hint", href: "tel:" + point.phone, text: point.phone }) : null,
        ]),
      ]));
    });
  }

  /* ---------------------------------------------------------- websocket */

  function openSocket() {
    if (!api.isAuthorized || socket) return;

    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(proto + "://" + location.host + "/ws/booking/?token=" + api.store.access);

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.event.startsWith("draft.")) renderDraft(message.payload);
      if (message.event.startsWith("booking.")) loadBookings();
      if (message.event === "booking.cancelled") {
        toast("Сервис отменил запись — подробности в списке записей.", "warn", "Запись отменена");
      }
    };

    socket.onclose = () => {
      socket = null;
      // Канал вспомогательный: если он отвалился, экран продолжает жить на REST.
      if (api.isAuthorized) setTimeout(openSocket, 5000);
    };
  }

  /* --------------------------------------------------------------- старт */

  function bindEvents() {
    $("#btn-otp").onclick = requestOtp;
    $("#btn-login").onclick = verifyOtp;
    $("#btn-otp-back").onclick = () => {
      show("auth-step-phone", true);
      show("auth-step-code", false);
      $("#auth-sub").textContent = "Пришлём код в SMS — пароль придумывать не нужно.";
    };

    $("#phone").addEventListener("keydown", (e) => { if (e.key === "Enter") requestOtp(); });
    $("#code").addEventListener("keydown", (e) => { if (e.key === "Enter") verifyOtp(); });

    $("#btn-signin").onclick = () => document.getElementById("auth-section").scrollIntoView({ behavior: "smooth" });
    $("#btn-signout").innerHTML = icon("logout", 16);
    $("#btn-signout").onclick = () => signOut(false);

    $("#btn-hero-start").onclick = () => {
      if (api.isAuthorized) startDraft(false);
      else document.getElementById("auth-section").scrollIntoView({ behavior: "smooth" });
    };

    $("#btn-profile").onclick = async () => {
      const user = await guard(() => api.patch("/auth/me/", {
        full_name: $("#full-name").value.trim(),
        car_model: $("#car-model").value.trim(),
        car_plate: $("#car-plate").value.trim(),
      }));
      if (user) { state.me = user; toast("Профиль сохранён", "ok"); }
    };

    $$(".tab[data-scope]").forEach((tab) => {
      tab.onclick = () => { state.scope = tab.dataset.scope; syncScopeTabs(); loadBookings(); };
    });

    $$("[data-icon]").forEach((node) => { node.innerHTML = icon(node.dataset.icon, 17); });
  }

  (async function init() {
    bindEvents();
    renderAuthState();
    await loadPoints();

    if (!api.isAuthorized) return;

    const me = await guard(() => api.get("/auth/me/"));
    if (!me) { signOut(true); return; }

    state.me = me;
    await afterSignIn();
  })();
})();

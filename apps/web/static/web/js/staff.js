/* Рабочее место сотрудника — общее для мастера и администратора.

   Обе панели ходят в один и тот же `/api/v1/master/…`: разница только в
   правах на стороне сервера (мастер видит свои точки) и в том, что у
   администратора сверху появляется вкладка метрик.

   Список живёт в реальном времени: канал `ws/master/` присылает сигнал, что
   у какой-то записи что-то изменилось, и панель перечитывает текущую выборку.
   Вставлять пришедшую строку в таблицу самостоятельно нельзя — пришлось бы
   повторить на клиенте всю логику фильтров (дата, статус, точка, поиск), а
   значит однажды показать запись, которая под фильтр не подходит.

   Опрос раз в 20 секунд остаётся, но включается только когда канал недоступен:
   реальное время не должно зависеть от того, разрешён ли WebSocket в сети. */

(function (global) {
  "use strict";

  const { fmt, icon, $, $$, el, empty, ask, toast, guard } = App;

  const api = App.createClient("staff", { onSignedOut: () => signOut(true) });

  const state = {
    me: null,
    role: "master",
    points: [],
    bookings: [],
    pollTimer: null,
    reloadTimer: null,
    socket: null,
    reconnectAt: null,
    onReady: null,
  };

  const STATUS_BADGE = {
    pending: ["badge-info", "Ожидает"],
    in_progress: ["badge-warn", "В работе"],
    completed: ["badge-ok", "Выполнена"],
    cancelled_by_client: ["badge-danger", "Отменена клиентом"],
    cancelled_by_master: ["badge-danger", "Отменена сервисом"],
    no_show: ["badge-danger", "Не приехал"],
  };

  /* -------------------------------------------------------------- вход */

  async function requestOtp() {
    const phone = $("#phone").value.trim();
    if (!phone) return;

    const data = await guard(() => api.request("/auth/otp/request/", {
      method: "POST", body: { phone }, auth: false,
    }));
    if (!data) return;

    state.phone = data.phone;
    $("#auth-step-phone").hidden = true;
    $("#auth-step-code").hidden = false;
    $("#auth-sub").textContent = "Код отправлен на " + data.phone;

    if (data.debug_code) {
      $("#code").value = data.debug_code;
      $("#otp-hint").textContent = "Режим разработки: код " + data.debug_code + " подставлен.";
    }
    $("#code").focus();
  }

  async function verifyOtp() {
    const data = await guard(() => api.request("/auth/otp/verify/", {
      method: "POST", body: { phone: state.phone, code: $("#code").value.trim() }, auth: false,
    }));
    if (!data) return;

    if (!allowed(data.user.role)) {
      denyAccess(data.user.role);
      return;
    }

    api.store.save(data.access, data.refresh);
    state.me = data.user;
    await enterWorkspace();
  }

  /** Панель мастера открыта мастеру и админу, панель админа — только админу. */
  function allowed(role) {
    return state.role === "admin" ? role === "admin" : role === "master" || role === "admin";
  }

  /** Роль не подходит для этой панели.

      Сессию при этом не рвём: токен общий для обеих панелей, и разлогин выбросил
      бы мастера из его собственного рабочего места только за то, что он зашёл не
      по тому адресу. Просто объясняем, куда идти. */
  function denyAccess(role) {
    const forMaster = role === "master" || role === "admin";
    $("#auth-sub").innerHTML = state.role === "admin"
      ? "Эта панель доступна только администратору." +
        (forMaster ? ' Рабочее место мастера — <a href="/master/">/master/</a>.' : "")
      : "Этот номер не принадлежит сотруднику сервиса. " +
        'Записаться можно на <a href="/">сайте клиента</a>.';
    toast("Недостаточно прав для этой панели.", "error", "Нет доступа");
  }

  function signOut(silent) {
    api.signOut();
    closeSocket();
    stopPolling();
    state.me = null;
    if (!silent) toast("Вы вышли");
    renderAuthState();
  }

  function renderAuthState() {
    const inside = Boolean(state.me);
    $("#auth-section").hidden = inside;
    $("#workspace").hidden = !inside;
    $("#btn-signout").hidden = !inside;

    const badge = $("#me-badge");
    badge.hidden = !inside;
    if (inside) {
      badge.textContent = (state.me.full_name || state.me.phone) +
        " · " + (state.me.role === "admin" ? "администратор" : "мастер");
    }
  }

  async function enterWorkspace() {
    renderAuthState();
    await loadPoints();
    await reload();
    openSocket();
    if (state.onReady) state.onReady({ api, points: state.points });
  }

  /* ------------------------------------------------------------ справочники */

  async function loadPoints() {
    const points = await guard(() => api.request("/service-points/", { auth: false }));
    state.points = points || [];

    $$("#f-point, #m-point").forEach((select) => {
      const first = select.options[0];
      select.innerHTML = "";
      select.append(first);
      state.points.forEach((point) => {
        select.append(el("option", { value: point.id, text: point.name }));
      });
    });
  }

  /* --------------------------------------------------------------- записи */

  function filters() {
    const params = new URLSearchParams();
    const date = $("#f-date").value;
    const point = $("#f-point").value;
    const status = $("#f-status").value;
    const search = $("#f-search").value.trim();

    if (date) params.set("date", date);
    if (point) params.set("service_point", point);
    if (status) params.set("status", status);
    if (search) params.set("search", search);
    return params;
  }

  async function reload() {
    const params = filters();

    const [list, summary] = await Promise.all([
      guard(() => api.get("/master/bookings/?" + params.toString())),
      guard(() => api.get("/master/bookings/summary/?" + summaryParams().toString())),
      loadLive(),
    ]);

    if (list) renderRows(list.results);
    if (summary) renderSummary(summary);
  }

  function summaryParams() {
    const params = new URLSearchParams();
    if ($("#f-date").value) params.set("date", $("#f-date").value);
    if ($("#f-point").value) params.set("service_point", $("#f-point").value);
    return params;
  }

  function renderSummary(summary) {
    $("#day-caption").textContent = "Записи за " + fmt.dateFull(summary.date) + ".";

    const cards = [
      { label: "Всего записей", value: fmt.number(summary.total), hint: "за день" },
      { label: "Ждут приёма", value: fmt.number(summary.pending), hint: summary.in_progress + " в работе" },
      { label: "Выполнено", value: fmt.number(summary.completed),
        hint: summary.cancelled + " отменено, " + summary.no_show + " не приехали" },
      { label: "Выручка", value: fmt.money(summary.revenue), hint: "по выполненным", accent: true },
    ];

    $("#summary").innerHTML = cards
      .map((card) =>
        '<div class="stat' + (card.accent ? " stat-accent" : "") + '">' +
        '<div class="stat-label">' + card.label + "</div>" +
        '<div class="stat-value">' + card.value + "</div>" +
        '<div class="stat-hint">' + card.hint + "</div></div>"
      )
      .join("");
  }

  function renderRows(items) {
    state.bookings = items;
    const tbody = $("#rows");
    tbody.innerHTML = "";

    if (!items.length) {
      tbody.append(el("tr", {}, [
        el("td", { colspan: "8" }, [empty("За выбранные фильтры записей нет.", "inbox")]),
      ]));
      return;
    }

    items.forEach((booking) => {
      const badge = STATUS_BADGE[booking.status] || ["badge", booking.status_display];

      tbody.append(el("tr", {}, [
        el("td", { class: "nowrap" }, [
          // local_time приходит от сервера в часовом поясе точки: браузер
          // мастера может стоять в другом регионе, и его время тут ни при чём.
          el("div", { class: "cell-main", text: booking.local_time.split(" ")[1] }),
          el("div", { class: "cell-sub", text: booking.service_point_name }),
        ]),
        el("td", { class: "mono nowrap", text: booking.code }),
        el("td", {}, [
          el("div", { class: "cell-main", text: booking.client_name || "Без имени" }),
          el("a", { class: "cell-sub", href: "tel:" + booking.client_phone, text: booking.client_phone }),
        ]),
        el("td", {}, [
          el("div", { text: booking.car_model || "—" }),
          booking.car_plate ? el("div", { class: "cell-sub mono", text: booking.car_plate }) : null,
        ]),
        el("td", { text: booking.oil_title }),
        el("td", { class: "num nowrap", text: fmt.money(booking.total_price) }),
        el("td", {}, [
          el("span", { class: "badge " + badge[0], text: badge[1] }),
          booking.cancel_reason
            ? el("div", { class: "cell-sub", style: "margin-top:4px", text: booking.cancel_reason })
            : null,
        ]),
        el("td", { class: "nowrap" }, [rowActions(booking)]),
      ]));
    });
  }

  function rowActions(booking) {
    const box = el("div", { class: "row", style: "gap:6px;flex-wrap:nowrap" });

    const act = (label, cls, path, body) =>
      el("button", {
        class: "btn btn-sm " + cls, type: "button", text: label,
        onClick: async () => {
          const ok = await guard(() => api.post("/master/bookings/" + booking.id + "/" + path + "/", body || {}));
          if (ok) { toast("Готово", "ok"); await reload(); }
        },
      });

    if (booking.status === "pending") {
      box.append(act("В работу", "btn-primary", "start"));
    }
    if (booking.status === "in_progress") {
      box.append(act("Выполнено", "btn-ok", "complete"));
    }
    if (booking.status === "pending") {
      box.append(el("button", {
        class: "btn btn-sm", type: "button", text: "Не приехал",
        onClick: async () => {
          const yes = await ask({
            title: "Клиент не приехал?",
            text: "Запись закроется, слот на прошедшее время не вернётся.",
            confirmLabel: "Отметить",
          });
          if (!yes) return;
          const ok = await guard(() => api.post("/master/bookings/" + booking.id + "/no-show/", { reason: "" }));
          if (ok) { toast("Отмечено", "ok"); await reload(); }
        },
      }));
    }
    if (booking.status === "pending" || booking.status === "in_progress") {
      box.append(el("button", {
        class: "btn btn-sm btn-danger", type: "button", text: "Отменить",
        onClick: async () => {
          const reason = await ask({
            title: "Отмена записи " + booking.code,
            text: "Причина уйдёт клиенту в SMS — напишите понятно.",
            placeholder: "Например: сломался подъёмник",
            confirmLabel: "Отменить и уведомить",
            danger: true, withInput: true, required: true,
          });
          if (!reason) return;
          const ok = await guard(() => api.post("/master/bookings/" + booking.id + "/cancel/", { reason }));
          if (ok) { toast("Клиенту отправлено SMS", "ok", "Запись отменена"); await reload(); }
        },
      }));
    }

    if (!box.children.length) box.append(el("span", { class: "cell-sub", text: "—" }));
    return box;
  }

  /* ---------------------------------------------------------- черновики */

  async function loadLive() {
    const drafts = await guard(() => api.get("/master/live-drafts/"));
    if (!drafts) return;

    const box = $("#live");
    const counter = $("#live-count");
    box.innerHTML = "";

    counter.hidden = !drafts.length;
    counter.textContent = drafts.length + " " + fmt.plural(drafts.length, "человек", "человека", "человек");

    if (!drafts.length) {
      box.append(el("div", { class: "card card-flat" }, [empty("Сейчас никто не записывается.", "users")]));
      return;
    }

    drafts.forEach((draft) => {
      const low = draft.seconds_left <= 60;
      box.append(el("div", { class: "card", style: "padding:14px" }, [
        el("div", { class: "row", style: "gap:14px" }, [
          el("span", { class: "pick-icon", html: icon("user", 19) }),
          el("div", { style: "flex:1;min-width:0" }, [
            el("div", { class: "cell-main", text: draft.client_name || "Без имени" }),
            el("div", { class: "cell-sub",
              text: draft.client_phone + " · " + (draft.oil_title || "масло не выбрано") +
                (draft.slot_start ? " · " + fmt.dateTime(draft.slot_start) : "") }),
          ]),
          el("span", { class: "badge " + (low ? "badge-danger" : "badge-accent") }, [
            el("span", { class: "dot" + (low ? " pulse" : "") }),
            el("span", { text: fmt.clock(draft.seconds_left) }),
          ]),
        ]),
      ]));
    });
  }

  /* -------------------------------------------------------- реальное время */

  function openSocket() {
    if (!api.isAuthorized || state.socket) return;

    setLiveStatus("connecting");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(
      proto + "://" + location.host + "/ws/master/?token=" + api.store.access
    );
    state.socket = socket;

    socket.onopen = () => {
      setLiveStatus("live");
      // Пока канал был закрыт, что-то могло измениться — подтягиваем актуальное.
      stopPolling();
      reload();
    };

    socket.onmessage = (event) => onSignal(JSON.parse(event.data));

    socket.onclose = (event) => {
      state.socket = null;
      if (!state.me) return;

      // 4403 — роль не подходит, переподключаться бессмысленно.
      if (event.code === 4403) {
        setLiveStatus("denied");
        return;
      }

      setLiveStatus("offline");
      startPolling();
      setTimeout(openSocket, 5000);
    };
  }

  function closeSocket() {
    if (state.socket) {
      const socket = state.socket;
      state.socket = null;
      socket.onclose = null;
      socket.close();
    }
    clearTimeout(state.reloadTimer);
    state.reloadTimer = null;
  }

  function onSignal(message) {
    if (message.event === "master.ready" || message.event === "pong") return;

    if (message.event === "booking.created") {
      const payload = message.payload || {};
      toast(
        "Код " + payload.code + (payload.local_time ? ", на " + payload.local_time : ""),
        "ok",
        "Новая запись"
      );
    }

    // События идут пачками (закрытие черновика + создание записи, шаги
    // черновика подряд), поэтому перечитываем список один раз на всплеск.
    clearTimeout(state.reloadTimer);
    state.reloadTimer = setTimeout(reload, 400);
  }

  const LIVE_STATUS = {
    live: ["badge-ok", "в реальном времени", false],
    connecting: ["badge", "подключение…", true],
    offline: ["badge-warn", "обновление раз в 20 сек", true],
    denied: ["badge-danger", "нет доступа к каналу", false],
  };

  function setLiveStatus(kind) {
    const [cls, text, pulse] = LIVE_STATUS[kind];
    const badge = $("#live-status");
    if (!badge) return;

    badge.className = "badge " + cls;
    $("#live-status-text").textContent = text;
    $("#live-dot").classList.toggle("pulse", pulse);
  }

  /* Резервный опрос — только когда канал недоступен. */
  function startPolling() {
    if (state.pollTimer) return;
    state.pollTimer = setInterval(() => { if (!document.hidden) reload(); }, 20000);
  }

  function stopPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  /* --------------------------------------------------------------- старт */

  function bindEvents() {
    $("#btn-otp").onclick = requestOtp;
    $("#btn-login").onclick = verifyOtp;
    $("#btn-otp-back").onclick = () => {
      $("#auth-step-phone").hidden = false;
      $("#auth-step-code").hidden = true;
    };
    $("#phone").addEventListener("keydown", (e) => { if (e.key === "Enter") requestOtp(); });
    $("#code").addEventListener("keydown", (e) => { if (e.key === "Enter") verifyOtp(); });

    $("#btn-signout").innerHTML = icon("logout", 16);
    $("#btn-signout").onclick = () => signOut(false);

    $("#btn-reload").onclick = reload;
    $("#btn-reset").onclick = () => {
      $("#f-date").value = fmt.isoDate();
      $("#f-point").value = "";
      $("#f-status").value = "";
      $("#f-search").value = "";
      reload();
    };

    ["#f-date", "#f-point", "#f-status"].forEach((sel) => { $(sel).onchange = reload; });

    let searchTimer = null;
    $("#f-search").oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(reload, 350);
    };

    // Вкладки «Смена» / «Метрики» — только в панели администратора.
    $$(".tab[data-tab]").forEach((tab) => {
      tab.onclick = () => {
        $$(".tab[data-tab]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
        $$("[data-panel]").forEach((panel) => {
          panel.hidden = panel.dataset.panel !== tab.dataset.tab;
        });
      };
    });
  }

  async function init(options) {
    state.role = (options && options.role) || "master";
    state.onReady = options && options.onReady;

    bindEvents();
    $("#f-date").value = fmt.isoDate();
    renderAuthState();

    if (!api.isAuthorized) return;

    const me = await guard(() => api.get("/auth/me/"));
    if (!me) { signOut(true); return; }
    if (!allowed(me.role)) { denyAccess(me.role); return; }

    state.me = me;
    await enterWorkspace();
  }

  global.Staff = { init, reload };
})(window);

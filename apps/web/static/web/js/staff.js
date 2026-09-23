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
    catalog: null,
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
    // Полоса, а не четыре больших карточки: мастеру нужны цифры одним
    // взглядом над таблицей, а не половина экрана до первой записи.
    const kpis = [
      ["Всего", fmt.number(summary.total)],
      ["Ждут", fmt.number(summary.pending)],
      ["В работе", fmt.number(summary.in_progress)],
      ["Выполнено", fmt.number(summary.completed)],
      ["Отмены и неявки", fmt.number(summary.cancelled + summary.no_show)],
      [Number(summary.points_spent) > 0
        ? "Выручка · ещё " + fmt.money(summary.points_spent) + " баллами"
        : "Выручка", fmt.money(summary.revenue), true],
    ];
    const box = $("#summary");
    box.innerHTML = "";
    kpis.forEach(([label, value, accent]) => {
      box.append(el("div", { class: "kpi" + (accent ? " kpi-accent" : "") }, [
        el("span", { class: "kpi-label", text: label }),
        el("span", { class: "kpi-value", text: value }),
      ]));
    });
  }

  function renderRows(items) {
    state.bookings = items;
    const tbody = $("#rows");
    tbody.innerHTML = "";

    if (!items.length) {
      tbody.append(el("tr", { class: "row-empty" }, [
        el("td", { colspan: "6" }, [empty("На этот день записей нет.", "inbox")]),
      ]));
      return;
    }

    items.forEach((booking) => {
      const badge = STATUS_BADGE[booking.status] || ["badge", booking.status_display];
      const paidWithPoints = Number(booking.points_spent) > 0;
      const car = [booking.car_model, booking.car_plate].filter(Boolean).join(" ");

      tbody.append(el("tr", { class: "status-" + booking.status }, [
        el("td", { class: "nowrap", "data-label": "Время" }, [
          // local_time приходит от сервера в часовом поясе точки: браузер
          // мастера может стоять в другом регионе, и его время тут ни при чём.
          el("div", { class: "cell-main", text: booking.local_time.split(" ")[1] }),
          el("div", { class: "cell-sub mono", text: booking.code }),
        ]),
        el("td", { "data-label": "Клиент и машина" }, [
          el("div", { class: "cell-main", text: booking.client_name || "Без имени" }),
          el("div", { class: "cell-sub" }, [
            el("a", { href: "tel:" + booking.client_phone, text: booking.client_phone }),
            car ? document.createTextNode(" · " + car) : null,
          ]),
        ]),
        el("td", { class: "cell-oil", "data-label": "Масло" }, [
          el("div", { text: booking.oil_title }),
          state.points.length > 1 ? el("div", { class: "cell-sub", text: booking.service_point_name }) : null,
        ]),
        el("td", { class: "num nowrap", "data-label": "Сумма" }, [
          el("div", { class: "cell-main", text: fmt.money(booking.total_price) }),
          paidWithPoints
            ? el("div", { class: "cell-sub", text: "баллами " + fmt.money(booking.points_spent) })
            : null,
        ]),
        el("td", { "data-label": "Статус" }, [
          el("span", { class: "badge " + badge[0], text: badge[1] }),
          booking.cancel_reason
            ? el("div", { class: "cell-sub", style: "margin-top:4px", text: booking.cancel_reason })
            : null,
        ]),
        el("td", { class: "num nowrap", "data-label": "" }, [rowActions(booking)]),
      ]));
    });
  }

  async function post(path, body, okText) {
    const ok = await guard(() => api.post(path, body || {}));
    if (ok) { toast(okText || "Готово", "ok"); await reload(); }
    return ok;
  }

  function rowActions(booking) {
    const box = el("div", { class: "row-actions" });
    const base = "/master/bookings/" + booking.id + "/";
    const btn = (label, cls, onClick) =>
      el("button", { class: "btn btn-sm " + cls, type: "button", text: label, onClick });

    // Главное действие по статусу — одно и первое: «в работу», потом «выполнено».
    if (booking.status === "pending") {
      box.append(btn("В работу", "btn-primary", () => post(base + "start/", {}, "Запись в работе")));
    }
    if (booking.status === "in_progress") {
      box.append(btn("Выполнено", "btn-ok", () => openCheckout(booking)));
    }
    if (booking.status === "pending") {
      box.append(btn("Не приехал", "btn-ghost", async () => {
        const yes = await ask({
          title: "Клиент не приехал?",
          text: "Запись закроется, слот на прошедшее время не вернётся.",
          confirmLabel: "Отметить",
        });
        if (yes) post(base + "no-show/", { reason: "" }, "Отмечено");
      }));
    }
    if (booking.status === "pending" || booking.status === "in_progress") {
      box.append(btn("Отменить", "btn-ghost btn-danger", async () => {
        const reason = await ask({
          title: "Отмена записи " + booking.code,
          text: "Причина уйдёт клиенту в SMS — напишите понятно.",
          placeholder: "Например: сломался подъёмник",
          confirmLabel: "Отменить и уведомить",
          danger: true, withInput: true, required: true,
        });
        if (reason) post(base + "cancel/", { reason }, "Запись отменена, клиенту отправлено SMS");
      }));
    }

    if (!box.children.length) box.append(el("span", { class: "cell-sub no-actions", text: "—" }));
    return box;
  }

  /* ------------------------------------------------------------ расчёт */

  /** Окно «Выполнено»: чек, баллы клиента и сколько он решил ими закрыть.

      Решает клиент, мастер только вводит. Потолок и баланс считает сервер —
      окно показывает их, чтобы мастер не узнавал о лимите по ошибке. */
  async function openCheckout(booking) {
    const quote = await guard(() => api.get("/master/bookings/" + booking.id + "/points/"));
    if (!quote) return;

    const total = Number(booking.total_price);
    const maxSpend = Math.floor(Number(quote.max_spend));
    const input = el("input", {
      type: "number", min: "0", max: String(maxSpend), step: "1", value: "0",
      inputmode: "numeric", id: "checkout-points", disabled: maxSpend <= 0,
    });
    const toPay = el("span", { class: "checkout-total", text: fmt.money(total) });
    const confirm = el("button", { class: "btn btn-ok", type: "button", text: "Завершить" });

    const points = () => Math.min(Math.max(Math.floor(Number(input.value) || 0), 0), maxSpend);
    const refresh = () => {
      const p = points();
      toPay.textContent = fmt.money(total - p);
      confirm.textContent = p > 0 ? "Завершить, списать " + fmt.number(p) + " баллов" : "Завершить без баллов";
    };
    input.oninput = refresh;

    const line = (label, value, cls) =>
      el("div", { class: "checkout-line" + (cls ? " " + cls : "") }, [
        el("span", { text: label }), el("span", { class: "num", text: value }),
      ]);

    const pointsBlock = maxSpend > 0
      ? el("div", { class: "checkout-points" }, [
        el("div", { class: "checkout-points-head" }, [
          el("span", { class: "cell-main", text: "Баллы клиента: " + fmt.number(quote.balance) }),
          el("span", { class: "cell-sub",
            text: "можно списать до " + fmt.number(maxSpend) + " (" + quote.max_discount_percent + "% чека)" }),
        ]),
        el("label", { class: "label", for: "checkout-points", text: "Сколько баллов списать — решает клиент" }),
        el("div", { class: "row" }, [
          el("div", { style: "flex:1;min-width:120px" }, [input]),
          el("button", { class: "btn", type: "button", text: "Максимум",
            onClick: () => { input.value = String(maxSpend); refresh(); } }),
          el("button", { class: "btn btn-ghost", type: "button", text: "Не списывать",
            onClick: () => { input.value = "0"; refresh(); } }),
        ]),
      ])
      : el("p", { class: "hint", text: Number(quote.balance) > 0
        ? "Баллы есть, но в этот чек списать нельзя."
        : "У клиента нет баллов — списывать нечего." });

    const body = el("div", { class: "stack" }, [
      el("div", { class: "checkout-lines" }, [
        line("Масло · " + booking.oil_title, fmt.money(booking.oil_price)),
        line("Работа", fmt.money(booking.work_price)),
        line("Итого", fmt.money(total), "checkout-sum"),
      ]),
      pointsBlock,
      el("div", { class: "checkout-line checkout-pay" }, [el("span", { text: "К оплате" }), toPay]),
    ]);

    const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
    const dlg = App.dialog({
      title: "Расчёт · " + booking.code,
      sub: (booking.client_name || "Клиент") + " · " + (booking.car_model || "") +
        (booking.car_plate ? " " + booking.car_plate : ""),
      body, actions: [cancel, confirm], wide: true,
    });
    cancel.onclick = dlg.close;
    confirm.onclick = async () => {
      confirm.disabled = true;
      const p = points();
      const ok = await guard(() => api.post("/master/bookings/" + booking.id + "/complete/", { points: String(p) }));
      confirm.disabled = false;
      if (!ok) return;
      dlg.close();
      toast(p > 0 ? "Списано " + fmt.number(p) + " баллов, к оплате " + fmt.money(total - p)
        : "К оплате " + fmt.money(total), "ok", "Запись выполнена");
      await reload();
    };
    refresh();
  }

  /* ------------------------------------------------------- масла и склад */

  const OIL_TYPES = [
    ["synthetic", "Синтетическое"],
    ["semi_synthetic", "Полусинтетическое"],
    ["mineral", "Минеральное"],
  ];

  async function loadOils() {
    const data = await guard(() => api.get("/master/oils/"));
    if (!data) return;
    state.catalog = data;
    renderOils();
  }

  function renderOils() {
    const data = state.catalog;
    if (!data) return;
    const query = $("#o-search").value.trim().toLowerCase();
    const showInactive = $("#o-inactive").checked;

    const head = $("#oils-head");
    head.innerHTML = "";
    head.append(el("tr", {}, [
      el("th", { text: "Масло" }),
      el("th", { class: "num", text: "Масло, ₽" }),
      el("th", { class: "num", text: "Работа, ₽" }),
      el("th", { class: "num", text: "Итого" }),
      ...data.points.map((point) => el("th", { class: "num", text: "Остаток · " + point.name })),
      el("th", { text: "В продаже" }),
      el("th", { class: "num", text: "" }),
    ]));

    const rows = data.oils.filter((oil) =>
      (showInactive || oil.is_active) &&
      (!query || oil.title.toLowerCase().includes(query)));

    const tbody = $("#oils-rows");
    tbody.innerHTML = "";
    if (!rows.length) {
      tbody.append(el("tr", { class: "row-empty" }, [
        el("td", { colspan: String(6 + data.points.length) }, [
          empty(query ? "Ничего не нашлось." : "Масел пока нет — добавьте первое.", "drop"),
        ]),
      ]));
      return;
    }

    rows.forEach((oil) => {
      tbody.append(el("tr", { class: oil.is_active ? "" : "is-muted" }, [
        el("td", { "data-label": "Масло" }, [
          el("div", { class: "cell-main", text: oil.brand + " " + oil.name }),
          el("div", { class: "cell-sub", text: oil.viscosity + " · " + oil.oil_type_display + " · " + oil.volume_liters + " л" }),
        ]),
        el("td", { class: "num", "data-label": "Масло, ₽", text: fmt.money(oil.price) }),
        el("td", { class: "num", "data-label": "Работа, ₽", text: fmt.money(oil.work_price) }),
        el("td", { class: "num cell-main", "data-label": "Итого", text: fmt.money(oil.total_price) }),
        ...data.points.map((point) => el("td", { class: "num", "data-label": "Остаток · " + point.name }, [
          stockInput(oil, point),
        ])),
        el("td", { "data-label": "В продаже" }, [activeToggle(oil)]),
        el("td", { class: "num", "data-label": "" }, [
          el("button", { class: "icon-btn", type: "button", title: "Изменить", "aria-label": "Изменить " + oil.title,
            html: icon("edit", 16), onClick: () => openOilForm(oil) }),
        ]),
      ]));
    });
  }

  function stockInput(oil, point) {
    const current = oil.stock[point.id] || 0;
    const input = el("input", {
      class: "qty-input" + (current <= 2 ? " is-low" : ""), type: "number", min: "0", step: "1",
      value: String(current), inputmode: "numeric", "aria-label": "Остаток " + oil.title + " на " + point.name,
    });
    input.onchange = async () => {
      const quantity = Math.max(0, Math.floor(Number(input.value) || 0));
      const ok = await guard(() => api.post("/master/oils/" + oil.id + "/stock/", {
        service_point: point.id, quantity,
      }));
      if (!ok) { input.value = String(current); return; }
      oil.stock[point.id] = quantity;
      input.classList.toggle("is-low", quantity <= 2);
      toast(oil.brand + " " + oil.name + ": " + quantity + " шт. на " + point.name, "ok", "Остаток сохранён");
    };
    return input;
  }

  function activeToggle(oil) {
    const box = el("input", { type: "checkbox", checked: oil.is_active, "aria-label": "В продаже: " + oil.title });
    box.onchange = async () => {
      const ok = await guard(() => api.patch("/master/oils/" + oil.id + "/", { is_active: box.checked }));
      if (!ok) { box.checked = !box.checked; return; }
      oil.is_active = box.checked;
      renderOils();
    };
    return el("label", { class: "check" }, [box, el("span", { text: box.checked ? "да" : "нет" })]);
  }

  /** Форма масла: новое или правка существующего. */
  function openOilForm(oil) {
    const isNew = !oil;
    const field = (id, label, attrs) => {
      const input = el("input", Object.assign({ id }, attrs));
      return [el("div", { class: "field" }, [el("label", { for: id, text: label }), input]), input];
    };

    const [fBrand, brand] = field("oil-brand", "Бренд", { value: oil ? oil.brand : "", placeholder: "Shell", required: true });
    const [fName, name] = field("oil-name", "Название", { value: oil ? oil.name : "", placeholder: "Helix HX8", required: true });
    const [fVisc, visc] = field("oil-visc", "Вязкость", { value: oil ? oil.viscosity : "", placeholder: "5W-30", required: true });
    const [fVol, vol] = field("oil-vol", "Объём канистры, л", { type: "number", step: "0.1", min: "0.1", value: oil ? oil.volume_liters : "4" });
    const [fPrice, price] = field("oil-price", "Цена масла, ₽", { type: "number", step: "1", min: "0", value: oil ? Math.round(oil.price) : "" });
    const [fWork, work] = field("oil-work", "Стоимость работы, ₽", { type: "number", step: "1", min: "0", value: oil ? Math.round(oil.work_price) : "" });

    const type = el("select", { id: "oil-type" },
      OIL_TYPES.map(([value, label]) => el("option", { value, text: label, selected: oil ? oil.oil_type === value : value === "synthetic" })));

    const stockInputs = isNew
      ? state.catalog.points.map((point) => {
        const input = el("input", { id: "oil-stock-" + point.id, type: "number", min: "0", step: "1", value: "0" });
        return [point, input, el("div", { class: "field" }, [
          el("label", { for: input.id, text: "Остаток · " + point.name }), input,
        ])];
      })
      : [];

    const body = el("div", { class: "form-grid" }, [
      fBrand, fName, fVisc,
      el("div", { class: "field" }, [el("label", { for: "oil-type", text: "Тип" }), type]),
      fVol, fPrice, fWork,
      ...stockInputs.map((row) => row[2]),
    ]);

    const save = el("button", { class: "btn btn-primary", type: "button", text: isNew ? "Добавить" : "Сохранить" });
    const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
    const dlg = App.dialog({
      title: isNew ? "Новое масло" : "Изменить масло",
      sub: isNew ? "Появится в приложении на точках, где остаток больше нуля." : "Уже созданные записи не изменятся — в них цена на момент брони.",
      body, actions: [cancel, save], wide: true,
    });
    cancel.onclick = dlg.close;

    save.onclick = async () => {
      if (!brand.value.trim() || !name.value.trim() || !visc.value.trim() || price.value === "" || work.value === "") {
        toast("Заполните бренд, название, вязкость и обе цены.", "error");
        return;
      }
      const payload = {
        brand: brand.value.trim(), name: name.value.trim(), viscosity: visc.value.trim().toUpperCase(),
        oil_type: type.value, volume_liters: vol.value, price: price.value, work_price: work.value,
      };
      if (isNew) {
        payload.initial_stock = stockInputs.map(([point, input]) => ({
          service_point: point.id, quantity: Math.max(0, Math.floor(Number(input.value) || 0)),
        }));
      }
      save.disabled = true;
      const ok = await guard(() => isNew
        ? api.post("/master/oils/", payload)
        : api.patch("/master/oils/" + oil.id + "/", payload));
      save.disabled = false;
      if (!ok) return;
      dlg.close();
      toast(payload.brand + " " + payload.name, "ok", isNew ? "Масло добавлено" : "Сохранено");
      await loadOils();
    };
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
      box.append(el("p", { class: "hint", text: "Сейчас никто не записывается." }));
      return;
    }

    drafts.forEach((draft) => {
      const low = draft.seconds_left <= 60;
      box.append(el("div", { class: "live-row" }, [
        el("div", { style: "flex:1;min-width:0" }, [
          el("div", { class: "cell-main", text: draft.client_name || "Без имени" }),
          el("div", { class: "cell-sub",
            text: (draft.oil_title || "масло не выбрано") +
              (draft.slot_start ? " · " + fmt.dateTime(draft.slot_start) : "") }),
        ]),
        el("span", { class: "badge " + (low ? "badge-danger" : "badge-accent") }, [
          el("span", { class: "dot" + (low ? " pulse" : "") }),
          el("span", { text: fmt.clock(draft.seconds_left) }),
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

    // Дата листается кнопками: мастер чаще всего смотрит «сегодня» и
    // «завтра», и календарь ради этого открывать незачем.
    const shiftDay = (delta) => {
      const d = new Date(($("#f-date").value || fmt.isoDate()) + "T12:00:00");
      d.setDate(d.getDate() + delta);
      $("#f-date").value = fmt.isoDate(d);
      reload();
    };
    $("#day-prev").innerHTML = icon("left", 16);
    $("#day-next").innerHTML = icon("right", 16);
    $("#day-prev").onclick = () => shiftDay(-1);
    $("#day-next").onclick = () => shiftDay(1);
    $("#day-today").onclick = () => { $("#f-date").value = fmt.isoDate(); reload(); };

    $("#btn-add-oil").onclick = () => openOilForm(null);
    $("#o-search").oninput = renderOils;
    $("#o-inactive").onchange = renderOils;

    ["#f-date", "#f-point", "#f-status"].forEach((sel) => { $(sel).onchange = reload; });

    let searchTimer = null;
    $("#f-search").oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(reload, 350);
    };

    // Вкладки «Записи» / «Масла и склад» (и «Метрики» у администратора).
    // Масла загружаются при первом открытии вкладки — смене они не нужны.
    $$(".tab[data-tab]").forEach((tab) => {
      tab.onclick = () => {
        $$(".tab[data-tab]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
        $$("[data-panel]").forEach((panel) => {
          panel.hidden = panel.dataset.panel !== tab.dataset.tab;
        });
        if (tab.dataset.tab === "oils") loadOils();
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

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
    // Каталог услуг: точки сотрудника и категории с услугами. Им же
    // пользуется окно «Записать клиента» — за списком своих точек.
    services: null,
    servicePoint: null,
    categoryId: null,
    // Очередь «Кому позвонить» — перечитывается вместе со сменой, чтобы
    // счётчик на вкладке не врал.
    calls: [],
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

  /** Вход по телефону и паролю.

      Кодом сотрудники не входят: сервер закрыл вход кодом на их номера,
      иначе пароль обходился бы звонком на телефон мастера. */
  async function login(event) {
    if (event) event.preventDefault();
    const phone = $("#phone").value.trim();
    const password = $("#password").value;
    if (!phone || !password) {
      toast("Введите телефон и пароль.", "error");
      return;
    }

    const button = $("#btn-login");
    button.disabled = true;
    const data = await guard(() => api.request("/auth/staff/login/", {
      method: "POST", body: { phone, password }, auth: false,
    }));
    button.disabled = false;
    if (!data) return;

    if (!allowed(data.user.role)) {
      denyAccess(data.user.role);
      return;
    }

    $("#password").value = "";
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
      loadCalls(),
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
    renderCallQueue();
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

    // Следующая машина — первая ожидающая запись, время которой ещё не
    // прошло (с запасом на опоздание). Её мастер ищет глазами чаще всего,
    // поэтому строка подсвечена, как «Up next» в расписаниях Fresha и
    // Jobber на Mobbin. На другой день подсветки нет: там «следующей» нет.
    const late = Date.now() - 15 * 60 * 1000;
    const next = items.find((b) => b.status === "pending" && new Date(b.start_at).getTime() >= late);
    const nextId = next && new Date(next.start_at).toDateString() === new Date().toDateString() ? next.id : null;

    items.forEach((booking) => {
      const badge = STATUS_BADGE[booking.status] || ["badge", booking.status_display];
      const isNext = booking.id === nextId;
      const paidWithPoints = Number(booking.points_spent) > 0;
      const car = [booking.car_model, booking.car_plate].filter(Boolean).join(" ");

      tbody.append(el("tr", { class: "status-" + booking.status + (isNext ? " is-next" : "") }, [
        el("td", { class: "nowrap", "data-label": "Время" }, [
          // local_time приходит от сервера в часовом поясе точки: браузер
          // мастера может стоять в другом регионе, и его время тут ни при чём.
          el("div", { class: "cell-main", text: booking.local_time.split(" ")[1] }),
          el("div", { class: "cell-sub mono", text: booking.code }),
          isNext ? el("span", { class: "next-tag", text: "Следующая" }) : null,
        ]),
        el("td", { "data-label": "Клиент и машина" }, [
          el("div", { class: "cell-main", text: booking.client_name || "Без имени" }),
          el("div", { class: "cell-sub" }, [
            el("a", { href: "tel:" + booking.client_phone, text: booking.client_phone }),
            car ? document.createTextNode(" · " + car) : null,
          ]),
        ]),
        el("td", { class: "cell-service", "data-label": "Услуга" }, [
          // «Подберите на месте»: клиент ждёт звонка — мастер выбирает услугу
          // вместе с ним (решение заказчика: в течение 30 минут в рабочее время).
          isWaitingCall(booking)
            ? el("span", { class: "badge badge-warn", text: "Позвонить, подобрать услугу" })
            : el("div", { text: booking.service_title }),
          el("div", { class: "cell-sub", text: [
            booking.category_title,
            state.points.length > 1 ? booking.service_point_name : "",
          ].filter(Boolean).join(" · ") }),
        ]),
        el("td", { class: "num nowrap", "data-label": "Сумма" }, [
          // Итог к оплате: если мастер поправил его при расчёте, рядом —
          // цена записи, чтобы разница была видна без открытия истории.
          el("div", { class: "cell-main", text: booking.needs_service ? "—" : fmt.money(booking.final_price) }),
          booking.final_price !== booking.total_price
            ? el("div", { class: "cell-sub", text: "по записи " + fmt.money(booking.total_price) })
            : null,
          paidWithPoints
            ? el("div", { class: "cell-sub", text: "баллами " + fmt.money(booking.points_spent) })
            : null,
        ]),
        el("td", { "data-label": "Статус" }, [
          // Точка цвета статуса перед словом — как в таблицах Remote: статус
          // считывается периферийным зрением, не читая подпись.
          el("span", { class: "badge " + badge[0] }, [el("span", { class: "dot" }), badge[1]]),
          booking.cancel_reason
            ? el("div", { class: "cell-sub", style: "margin-top:4px", text: booking.cancel_reason })
            : null,
        ]),
        el("td", { class: "num nowrap", "data-label": "" }, [rowActions(booking)]),
      ]));
    });
  }

  /** «Кому позвонить» — строкой над сводкой: это дело на сейчас, а не
      цифра дня. Самое срочное — словами, остальное — числом и ссылкой на
      вкладку со всей очередью. */
  function renderCallQueue() {
    const calls = state.calls || [];
    let note = $("#call-queue");
    if (!note) {
      note = el("div", { class: "note note-warn", id: "call-queue", role: "status" });
      $("#summary").before(note);
    }
    note.hidden = !calls.length;
    if (!calls.length) return;
    const first = calls[0];
    note.innerHTML = icon("phone");
    note.append(el("span", {
      // Строчной — только первая буква: в подсказке бывает название
      // категории, и «замена масла» с маленькой читается как опечатка.
      text: "Позвонить: " + (first.client_name || first.client_phone) + " — " +
        first.hint.charAt(0).toLowerCase() + first.hint.slice(1) +
        (calls.length > 1 ? ". И ещё " + (calls.length - 1) + " в очереди." : "."),
    }), el("button", {
      class: "btn btn-sm", type: "button", text: "Кому позвонить",
      onClick: () => openTab("calls"),
    }));
  }

  const isWaitingCall = (booking) =>
    booking.needs_service && (booking.status === "pending" || booking.status === "in_progress");

  /** Услуга после звонка: клиент просил подобрать на месте. Список — то,
      что доступно на точке записи в её категории; цены записи поставит
      сервер. */
  async function openSetService(booking) {
    const query = "?service_point=" + booking.service_point +
      (booking.service_category ? "&category=" + booking.service_category : "");
    const rows = await guard(() => api.get("/master/walk-in/services/" + query));
    if (!rows) return;
    if (!rows.length) { toast("В этой категории сейчас нечего выбрать.", "error"); return; }
    const select = el("select", { id: "set-service" }, rows.map((row) =>
      el("option", { value: row.id, text: row.name + " · " + fmt.money(row.total_price) })));
    const car = [booking.car_model, booking.car_plate].filter(Boolean).join(" ");
    const body = el("div", { class: "stack" }, [
      el("p", { class: "hint" }, [
        document.createTextNode("Клиент просил подобрать услугу" +
          (booking.category_title ? " («" + booking.category_title + "»)" : "") + ". Позвоните: "),
        el("a", { href: "tel:" + booking.client_phone, text: booking.client_phone }),
        document.createTextNode(car ? " · " + car : ""),
      ]),
      el("div", { class: "field" }, [el("label", { for: "set-service", text: "Услуга" }), select]),
    ]);
    const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
    const save = el("button", { class: "btn btn-primary", type: "button", text: "Сохранить услугу" });
    const dlg = App.dialog({ title: "Услуга · " + booking.code, sub: booking.client_name || "Клиент", body, actions: [cancel, save] });
    cancel.onclick = dlg.close;
    save.onclick = async () => {
      save.disabled = true;
      const ok = await guard(() => api.post("/master/bookings/" + booking.id + "/set-service/", { service: select.value }));
      save.disabled = false;
      if (!ok) return;
      dlg.close();
      toast("Услуга выбрана: " + ok.service_title, "ok");
      await reload();
    };
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

    // Клиент ждёт звонка — это первым: без услуги запись не выполнить.
    if (isWaitingCall(booking)) {
      box.append(btn("Выбрать услугу", "btn-primary", () => openSetService(booking)));
    }
    // Главное действие по статусу — одно и первое: «в работу», потом «выполнено».
    if (booking.status === "pending" && !isWaitingCall(booking)) {
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

    const bookedPrice = Number(booking.total_price);
    const balance = Math.floor(Number(quote.balance));
    const percent = Number(quote.max_discount_percent);
    const alreadySpent = Number(booking.points_spent) || 0;

    // Итог мастер правит, если добавил работу, долил материала или уступил.
    // Сервер считает потолок баллов от итога — окно считает так же, чтобы
    // мастер видел лимит до нажатия, а не из ошибки.
    const finalInput = el("input", {
      type: "number", min: "1", step: "1", value: String(Math.round(bookedPrice)),
      inputmode: "numeric", id: "checkout-final",
    });
    const reasonInput = el("input", {
      id: "checkout-reason", maxlength: "500", placeholder: "Например: долили 1 л",
    });
    const reasonField = el("div", { class: "field" }, [
      el("label", { for: "checkout-reason", text: "Почему изменили" }), reasonInput,
    ]);
    const pointsInput = el("input", {
      type: "number", min: "0", step: "1", value: "0", inputmode: "numeric", id: "checkout-points",
    });
    const toPay = el("span", { class: "checkout-total" });
    const capText = el("span", { class: "cell-sub" });
    const changeText = el("span", { class: "cell-sub" });
    const confirm = el("button", { class: "btn btn-ok", type: "button" });

    const finalPrice = () => {
      const value = Math.round(Number(finalInput.value));
      return value > 0 ? value : null;
    };
    const maxSpend = () => {
      const final = finalPrice() || 0;
      return Math.max(Math.min(balance, Math.floor(final * percent / 100) - alreadySpent), 0);
    };
    const points = () => Math.min(Math.max(Math.floor(Number(pointsInput.value) || 0), 0), maxSpend());

    const refresh = () => {
      const final = finalPrice();
      const changed = final !== null && final !== Math.round(bookedPrice);
      reasonField.hidden = !changed;
      changeText.textContent = changed
        ? (final > bookedPrice ? "+" : "−") + fmt.money(Math.abs(final - bookedPrice)) + " к цене записи"
        : "как при записи";

      const limit = maxSpend();
      pointsInput.max = String(limit);
      pointsInput.disabled = limit <= 0;
      if (Number(pointsInput.value) > limit) pointsInput.value = String(limit);
      capText.textContent = "можно списать до " + fmt.number(limit) + " (" + percent + "% итога)";

      const p = points();
      toPay.textContent = final === null ? "—" : fmt.money(final - p);
      confirm.disabled = final === null;
      confirm.textContent = p > 0 ? "Завершить, списать " + fmt.number(p) + " баллов" : "Завершить без баллов";
    };
    finalInput.oninput = refresh;
    pointsInput.oninput = refresh;

    const line = (label, value, cls) =>
      el("div", { class: "checkout-line" + (cls ? " " + cls : "") }, [
        el("span", { text: label }), el("span", { class: "num", text: value }),
      ]);

    const pointsBlock = balance > 0
      ? el("div", { class: "checkout-points" }, [
        el("div", { class: "checkout-points-head" }, [
          el("span", { class: "cell-main", text: "Баллы клиента: " + fmt.number(quote.balance) }),
          capText,
        ]),
        el("label", { class: "label", for: "checkout-points", text: "Сколько баллов списать — решает клиент" }),
        el("div", { class: "row" }, [
          el("div", { style: "flex:1;min-width:120px" }, [pointsInput]),
          el("button", { class: "btn", type: "button", text: "Максимум",
            onClick: () => { pointsInput.value = String(maxSpend()); refresh(); } }),
          el("button", { class: "btn btn-ghost", type: "button", text: "Не списывать",
            onClick: () => { pointsInput.value = "0"; refresh(); } }),
        ]),
      ])
      : el("p", { class: "hint", text: "У клиента нет баллов — списывать нечего." });

    const body = el("div", { class: "stack" }, [
      el("div", { class: "checkout-lines" }, [
        // Позиции чека по записи: услуга и её цена на момент брони.
        ...(booking.services || []).map((item) => line(
          item.title + (item.quantity > 1 ? " × " + item.quantity : ""),
          fmt.money(Number(item.price) * item.quantity))),
        line("По записи", fmt.money(bookedPrice), "checkout-sum"),
      ]),
      el("div", { class: "form-grid" }, [
        el("div", { class: "field" }, [
          el("label", { for: "checkout-final", text: "Итог, ₽" }), finalInput, changeText,
        ]),
        reasonField,
      ]),
      pointsBlock,
      el("div", { class: "checkout-line checkout-pay" }, [el("span", { text: "К оплате" }), toPay]),
    ]);

    const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
    const dlg = App.dialog({
      title: "Расчёт · " + booking.code,
      // Без машины в записи точка-разделитель повисала бы в конце строки.
      sub: [booking.client_name || "Клиент",
        [booking.car_model, booking.car_plate].filter(Boolean).join(" ")].filter(Boolean).join(" · "),
      body, actions: [cancel, confirm], wide: true,
    });
    cancel.onclick = dlg.close;
    confirm.onclick = async () => {
      const final = finalPrice();
      if (final === null) return;
      confirm.disabled = true;
      const p = points();
      const payload = { points: String(p) };
      if (final !== Math.round(bookedPrice)) {
        payload.final_price = String(final);
        payload.reason = reasonInput.value.trim();
      }
      const ok = await guard(() => api.post("/master/bookings/" + booking.id + "/complete/", payload));
      confirm.disabled = false;
      if (!ok) return;
      dlg.close();
      toast(p > 0 ? "Списано " + fmt.number(p) + " баллов, к оплате " + fmt.money(final - p)
        : "К оплате " + fmt.money(final), "ok", "Запись выполнена");
      await reload();
    };
    refresh();
  }

  /* ------------------------------------------------- записать клиента */

  /** Окно «Записать клиента»: позвонил или приехал без записи.

      Проверки — на сервере, те же, что у записи из приложения; окно только
      показывает то, что реально можно выбрать: услуги в наличии и свободное
      время точки. Время — без запаса до начала: мастер ставит и в слот,
      который уже идёт, если пост свободен. */
  async function openWalkIn() {
    if (!state.services) {
      // Свои точки сотрудника приходят вместе с каталогом услуг: список
      // /service-points/ публичный и отдаёт все адреса сети.
      const data = await guard(() => api.get("/master/service-categories/"));
      if (!data) return;
      state.services = data;
    }
    const points = state.services.points;
    if (!points.length) { toast("У вас нет доступных точек.", "error"); return; }

    // carId — машина клиента, выбранная кнопкой из подсказки. Пусто —
    // машину описывают поля «Машина» и «Госномер», сервер найдёт её среди
    // машин клиента по номеру или добавит новую.
    const form = { slot: null, filled: {}, carId: null };
    const input = (id, attrs) => el("input", Object.assign({ id }, attrs));
    const field = (label, control, extra) =>
      el("div", { class: "field" + (extra ? " " + extra : "") }, [
        el("label", { for: control.id, text: label }), control,
      ]);

    const phone = input("wi-phone", { type: "tel", inputmode: "tel", placeholder: "+7 900 000-00-00", autocomplete: "off" });
    const phoneHint = el("span", { class: "hint", text: "Есть в базе — имя и машина подставятся." });
    const name = input("wi-name", { placeholder: "Как обращаться", autocomplete: "off" });
    const car = input("wi-car", { placeholder: "Марка и модель", autocomplete: "off" });
    const plate = input("wi-plate", { placeholder: "Необязательно", autocomplete: "off" });
    const carChoice = el("div", { class: "choice-row", role: "group", "aria-label": "Машина клиента" });
    const carChoiceField = el("div", { class: "field field-wide", hidden: true }, [
      el("span", { class: "label", text: "Машина клиента" }), carChoice,
    ]);

    /* Выбор машины кнопкой подставляет её в поля; правка полей руками
       значит «другая машина» — выбор снимается. */
    function pickCar(chosen) {
      form.carId = chosen ? chosen.id : null;
      $$("button", carChoice).forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.car === (chosen ? chosen.id : ""))));
      if (chosen) {
        car.value = chosen.title;
        plate.value = chosen.plate;
      } else {
        car.value = "";
        plate.value = "";
        car.focus();
      }
    }
    [car, plate].forEach((box) => box.addEventListener("input", () => {
      if (!form.carId) return;
      form.carId = null;
      $$("button", carChoice).forEach((b) => b.setAttribute("aria-pressed", "false"));
    }));

    function renderCars(cars) {
      carChoice.innerHTML = "";
      carChoiceField.hidden = !cars.length;
      if (!cars.length) return;
      cars.forEach((c) => {
        const btn = el("button", {
          class: "btn btn-sm", type: "button", "aria-pressed": "false", "data-car": c.id,
          text: [c.title, c.plate].filter(Boolean).join(" · "),
        });
        btn.onclick = () => pickCar(c);
        carChoice.append(btn);
      });
      const other = el("button", { class: "btn btn-sm btn-ghost", type: "button", "data-car": "", text: "Другая машина" });
      other.onclick = () => pickCar(null);
      carChoice.append(other);
      // Основная выбрана сразу, если мастер ещё не начал вводить машину сам.
      if (!car.value && !plate.value) pickCar(cars.find((c) => c.is_primary) || cars[0]);
    }
    const point = el("select", { id: "wi-point" },
      points.map((p) => el("option", { value: p.id, text: p.name })));
    const service = el("select", { id: "wi-service" });
    const date = input("wi-date", { type: "date", value: fmt.isoDate(), min: fmt.isoDate() });
    const slotBox = el("div", { class: "slot-grid", role: "group", "aria-label": "Свободное время" });
    const comment = input("wi-comment", { placeholder: "Необязательно", maxlength: "500" });

    /* Клиент по номеру: подставляем, но не затираем то, что мастер уже ввёл. */
    let lookedUp = "";
    async function lookup() {
      const raw = phone.value.trim();
      if (raw.replace(/\D/g, "").length < 10 || raw === lookedUp) return;
      lookedUp = raw;
      let found;
      try {
        found = await api.get("/master/walk-in/lookup/?phone=" + encodeURIComponent(raw));
      } catch (err) {
        phoneHint.textContent = err.message;
        phoneHint.classList.add("hint-error");
        return;
      }
      phoneHint.classList.toggle("hint-error", !found.is_client);
      renderCars(found.cars || []);
      if (!found.is_client) {
        phoneHint.textContent = "Это номер сотрудника — записать на него нельзя.";
        return;
      }
      phoneHint.textContent = found.found
        ? "Клиент есть в базе — данные подставлены."
        : "Новый клиент: заведём по этому номеру, в приложение он войдёт по нему же.";
      // Машину подставляет выбор кнопкой выше, здесь — только имя.
      [[name, found.full_name]].forEach(([box, value]) => {
        if (value && (!box.value || form.filled[box.id] === box.value)) {
          box.value = value;
          form.filled[box.id] = value;
        }
      });
    }
    phone.onblur = lookup;
    phone.oninput = () => { if (phone.value.replace(/\D/g, "").length >= 11) lookup(); };

    /* Услуги — одним списком, сгруппированным по категориям: мастер на
       телефоне с клиентом ищет глазами, а не листает два выпадающих. */
    async function loadOptions() {
      service.innerHTML = "";
      service.append(el("option", { value: "", text: "Загружаем…" }));
      const rows = await guard(() => api.get("/master/walk-in/services/?service_point=" + point.value));
      service.innerHTML = "";
      if (!rows || !rows.length) {
        service.append(el("option", { value: "", text: "Нечего выбрать на этой точке" }));
        return;
      }
      const groups = new Map();
      rows.forEach((row) => {
        if (!groups.has(row.category_title)) {
          groups.set(row.category_title, el("optgroup", { label: row.category_title }));
          service.append(groups.get(row.category_title));
        }
        groups.get(row.category_title).append(el("option", {
          value: row.id,
          text: row.name + " · " + fmt.money(row.total_price) +
            (row.available_quantity === null ? "" : " · " + row.available_quantity + " шт."),
        }));
      });
    }

    async function loadSlots() {
      form.slot = null;
      slotBox.innerHTML = "";
      const data = await guard(() => api.get(
        "/master/walk-in/slots/?service_point=" + point.value + "&date=" + (date.value || fmt.isoDate())));
      if (!data) return;
      if (!data.slots.length) {
        slotBox.append(el("p", { class: "hint", text: "На этот день свободного времени нет." }));
        return;
      }
      data.slots.forEach((slot) => {
        const btn = el("button", {
          class: "btn btn-sm", type: "button", text: slot.local_time, "aria-pressed": "false",
          title: slot.free_posts > 1 ? "Свободно постов: " + slot.free_posts : "Последний свободный пост",
        });
        btn.onclick = () => {
          form.slot = slot.start_at;
          $$("button", slotBox).forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        };
        slotBox.append(btn);
      });
    }

    /* Первый день, где у точки есть свободное время: вечером «сегодня» уже
       пусто, и мастер не должен листать календарь, чтобы это понять. */
    async function pickFirstDay() {
      const data = await guard(() => api.get("/master/walk-in/slots/?service_point=" + point.value));
      if (data && data.available_days.length) date.value = data.available_days[0];
      await loadSlots();
    }

    point.onchange = () => { loadOptions(); pickFirstDay(); };
    date.onchange = loadSlots;

    const body = el("div", { class: "form-grid" }, [
      el("div", { class: "field" }, [el("label", { for: "wi-phone", text: "Телефон" }), phone, phoneHint]),
      field("Имя", name),
      carChoiceField,
      field("Машина", car),
      field("Госномер", plate),
      field("Адрес", point),
      field("Услуга", service),
      el("div", { class: "field field-wide" }, [
        el("label", { for: "wi-date", text: "День и время" }),
        el("div", { class: "stack-sm" }, [date, slotBox]),
      ]),
      field("Комментарий", comment, "field-wide"),
    ]);

    const save = el("button", { class: "btn btn-primary", type: "button", text: "Записать" });
    const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
    const dlg = App.dialog({
      title: "Записать клиента",
      sub: "По звонку или без записи. Клиенту уйдёт SMS о записи.",
      body, actions: [cancel, save], wide: true,
    });
    cancel.onclick = dlg.close;

    save.onclick = async () => {
      const missing = [
        [!phone.value.trim(), "телефон"], [!name.value.trim(), "имя"],
        [!service.value, "услугу"], [!form.slot, "время"],
      ].filter(([bad]) => bad).map(([, label]) => label);
      if (missing.length) { toast("Укажите: " + missing.join(", ") + ".", "error"); return; }

      save.disabled = true;
      try {
        const booking = await api.post("/master/bookings/", {
          phone: phone.value.trim(), full_name: name.value.trim(),
          car_model: car.value.trim(), car_plate: plate.value.trim().toUpperCase(),
          car_id: form.carId,
          service_point: point.value, service: service.value, start_at: form.slot,
          comment: comment.value.trim(),
        });
        dlg.close();
        toast(booking.client_name + " · " + booking.local_time + " · код " + booking.code, "ok", "Клиент записан");
        // Показываем день новой записи: записывают часто на завтра, и
        // мастер должен увидеть её в списке, а не гадать, куда она делась.
        const [d, m, y] = booking.local_time.split(" ")[0].split(".");
        $("#f-date").value = y + "-" + m + "-" + d;
        await reload();
      } catch (err) {
        toast(err.message || "Что-то пошло не так. Попробуйте ещё раз.", "error", "Не получилось");
        // Пока мастер заполнял окно, время или последнюю единицу услуги
        // могли занять из приложения — показываем то, что осталось.
        if (err.code === "slot_taken" || err.code === "slot_too_soon") loadSlots();
        if (err.code === "service_out_of_stock") loadOptions();
      } finally {
        save.disabled = false;
      }
    };

    phone.focus();
    loadOptions();
    pickFirstDay();
  }

  /* -------------------------------------------------------------- услуги */

  /** Вид для дневника клиента — те же значения, что `ServiceJournalKind`. */
  const JOURNAL_KINDS = [
    ["oil", "Замена масла"],
    ["tires", "Шиномонтаж"],
    ["wash", "Мойка"],
    ["service", "ТО и ремонт"],
    ["other", "Другое"],
  ];

  async function loadServices() {
    const data = await guard(() => api.get("/master/service-categories/"));
    if (!data) return;
    state.services = data;

    const select = $("#s-point");
    const ids = data.points.map((p) => p.id);
    if (!ids.includes(state.servicePoint)) state.servicePoint = ids[0] || null;
    select.innerHTML = "";
    data.points.forEach((p) => select.append(el("option", { value: p.id, text: p.name, selected: p.id === state.servicePoint })));
    // Одна точка — выбирать не из чего, поле только занимает место.
    select.hidden = data.points.length < 2;
    renderServices();
  }

  const pointCategories = () => (state.services ? state.services.categories : [])
    .filter((c) => c.service_point === state.servicePoint);

  function renderServices() {
    if (!state.services) return;
    const showInactive = $("#s-inactive").checked;
    const query = $("#s-search").value.trim().toLowerCase();
    const categories = pointCategories().filter((c) => showInactive || c.is_active);
    if (!categories.some((c) => c.id === state.categoryId)) {
      state.categoryId = categories.length ? categories[0].id : null;
    }

    const list = $("#s-categories");
    list.innerHTML = "";
    if (!categories.length) {
      list.append(el("p", { class: "hint", text: state.services.points.length
        ? "Категорий пока нет — заведите первую: «Замена масла», «Шиномонтаж», «Мойка»."
        : "У вас нет доступных точек." }));
    }
    categories.forEach((category) => {
      const active = category.services.filter((s) => s.is_active).length;
      const pick = el("button", {
        class: "btn", type: "button", "aria-pressed": String(category.id === state.categoryId),
        "aria-label": "Категория " + category.name + (category.is_active
          ? ", " + active + " " + fmt.plural(active, "услуга", "услуги", "услуг") : ", выключена"),
      }, [
        el("span", { class: "cell-main", text: category.name }),
        el("span", { class: "cell-sub", text: category.is_active
          ? active + " " + fmt.plural(active, "услуга", "услуги", "услуг")
          : "выключена" }),
      ]);
      pick.onclick = () => { state.categoryId = category.id; renderServices(); };
      list.append(el("div", { class: "cat-item" + (category.is_active ? "" : " is-muted") }, [
        pick,
        el("button", { class: "icon-btn", type: "button", title: "Изменить категорию",
          "aria-label": "Изменить категорию " + category.name, html: icon("edit", 16),
          onClick: () => openCategoryForm(category) }),
      ]));
    });

    $("#btn-add-service").disabled = !state.categoryId;
    const category = categories.find((c) => c.id === state.categoryId);
    const rows = (category ? category.services : []).filter((s) =>
      (showInactive || s.is_active) && (!query || s.name.toLowerCase().includes(query)));

    const tbody = $("#s-rows");
    tbody.innerHTML = "";
    if (!rows.length) {
      tbody.append(el("tr", { class: "row-empty" }, [
        el("td", { colspan: "6" }, [empty(
          !category ? "Выберите или заведите категорию."
            : query ? "Ничего не нашлось."
              : "В этой категории пока нет услуг — добавьте первую.", "drop")]),
      ]));
      return;
    }
    rows.forEach((service) => {
      tbody.append(el("tr", { class: service.is_active ? "" : "is-muted" }, [
        el("td", { "data-label": "Услуга" }, [
          el("div", { class: "cell-main", text: service.name }),
          service.description ? el("div", { class: "cell-sub", text: service.description }) : null,
        ]),
        el("td", { class: "num", "data-label": "Цена", text: fmt.money(service.price) }),
        el("td", { class: "num", "data-label": "Из них материал" }, [
          el("div", { text: Number(service.material_price) ? fmt.money(service.material_price) : "—" }),
          Number(service.material_price)
            ? el("div", { class: "cell-sub", text: "работа " + fmt.money(service.work_price) })
            : null,
        ]),
        el("td", { "data-label": "Количество" }, [
          service.is_limited ? quantityInput(service) : el("span", { class: "cell-sub", text: "без учёта" }),
        ]),
        el("td", { "data-label": "В работе" }, [activeToggle(service)]),
        el("td", { class: "num", "data-label": "" }, [
          el("button", { class: "icon-btn", type: "button", title: "Изменить",
            "aria-label": "Изменить " + service.name, html: icon("edit", 16),
            onClick: () => openServiceForm(service) }),
        ]),
      ]));
    });
  }

  async function patchService(service, body) {
    return guard(() => api.patch("/master/services/" + service.id + "/", body));
  }

  /** Остаток — абсолютное число после пересчёта, сохраняется сразу. */
  function quantityInput(service) {
    const current = service.quantity;
    const input = el("input", {
      class: "qty-input" + (current <= 2 ? " is-low" : ""), type: "number", min: "0", step: "1",
      value: String(current), inputmode: "numeric", "aria-label": "Остаток: " + service.name,
    });
    input.onchange = async () => {
      const quantity = Math.max(0, Math.floor(Number(input.value) || 0));
      const ok = await patchService(service, { quantity });
      if (!ok) { input.value = String(current); return; }
      service.quantity = ok.quantity;
      input.classList.toggle("is-low", ok.quantity <= 2);
      toast(service.name + ": " + ok.quantity + " шт.", "ok", "Остаток сохранён");
    };
    return input;
  }

  function activeToggle(service) {
    const box = el("input", { type: "checkbox", checked: service.is_active, "aria-label": "В работе: " + service.name });
    box.onchange = async () => {
      const ok = await patchService(service, { is_active: box.checked });
      if (!ok) { box.checked = !box.checked; return; }
      service.is_active = ok.is_active;
      renderServices();
    };
    return el("label", { class: "check" }, [box, el("span", { text: box.checked ? "да" : "нет" })]);
  }

  const formField = (id, label, control, extra) => el("div", { class: "field" + (extra ? " " + extra : "") }, [
    el("label", { for: id, text: label }), control,
  ]);
  // Не `.field`: его подписи — заглавные, как у полей ввода, а подпись
  // галочки — это фраза, и капсом она читается как крик.
  const checkField = (id, label, checked, hint) => {
    const box = el("input", { id, type: "checkbox", checked });
    return [el("div", { class: "field-wide stack-sm" }, [
      el("label", { class: "check" }, [box, el("span", { text: label })]),
      hint ? el("span", { class: "hint", text: hint }) : null,
    ]), box];
  };

  /** Категория: новая на выбранной точке или правка существующей. */
  function openCategoryForm(category) {
    const isNew = !category;
    const pointId = isNew ? state.servicePoint : category.service_point;
    if (!pointId) { toast("Нет точки, на которой завести категорию.", "error"); return; }
    const point = state.services.points.find((p) => p.id === pointId);

    const name = el("input", { id: "cat-name", value: isNew ? "" : category.name, placeholder: "Например: Шиномонтаж", maxlength: "120" });
    const order = el("input", { id: "cat-order", type: "number", min: "0", step: "1", value: String(isNew ? 100 : category.sort_order) });
    const kind = el("select", { id: "cat-kind" }, JOURNAL_KINDS.map(([value, label]) =>
      el("option", { value, text: label, selected: (isNew ? "other" : category.journal_kind) === value })));
    const [onSiteField, onSite] = checkField("cat-on-site", "Можно записаться, не выбрав услугу",
      isNew ? true : category.allow_on_site, "Клиент выберет «подберите на месте», мастер перезвонит и подберёт услугу.");
    const [activeField, active] = checkField("cat-active", "Включена — видна клиенту", isNew ? true : category.is_active);

    const body = el("div", { class: "form-grid" }, [
      formField("cat-name", "Название", name),
      formField("cat-order", "Порядок показа", order),
      formField("cat-kind", "Вид в дневнике клиента", kind, "field-wide"),
      el("p", { class: "hint field-wide", text: "Напоминание о замене масла у клиента двигают только категории вида «Замена масла»." }),
      onSiteField, activeField,
    ]);
    const save = el("button", { class: "btn btn-primary", type: "button", text: isNew ? "Добавить" : "Сохранить" });
    const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
    const dlg = App.dialog({
      title: isNew ? "Новая категория" : "Изменить категорию",
      sub: point ? "Точка: " + point.name : "",
      body, actions: [cancel, save], wide: true,
    });
    cancel.onclick = dlg.close;
    save.onclick = async () => {
      if (!name.value.trim()) { toast("Назовите категорию.", "error"); return; }
      const payload = {
        name: name.value.trim(), sort_order: Math.max(0, Math.floor(Number(order.value) || 0)),
        journal_kind: kind.value, allow_on_site: onSite.checked, is_active: active.checked,
      };
      if (isNew) payload.service_point = pointId;
      save.disabled = true;
      const ok = await guard(() => isNew
        ? api.post("/master/service-categories/", payload)
        : api.patch("/master/service-categories/" + category.id + "/", payload));
      save.disabled = false;
      if (!ok) return;
      dlg.close();
      state.categoryId = ok.id;
      toast(ok.name, "ok", isNew ? "Категория добавлена" : "Сохранено");
      await loadServices();
    };
    name.focus();
  }

  /** Услуга: новая в выбранной категории или правка существующей. */
  function openServiceForm(service) {
    const isNew = !service;
    const category = pointCategories().find((c) => c.id === (isNew ? state.categoryId : service.category));
    if (!category) { toast("Сначала выберите категорию.", "error"); return; }

    const name = el("input", { id: "svc-name", value: isNew ? "" : service.name, maxlength: "160", placeholder: "Например: Шиномонтаж R16" });
    const price = el("input", { id: "svc-price", type: "number", min: "0", step: "1", inputmode: "numeric", value: isNew ? "" : String(Math.round(service.price)) });
    const material = el("input", { id: "svc-material", type: "number", min: "0", step: "1", inputmode: "numeric", value: isNew ? "0" : String(Math.round(service.material_price)) });
    const description = el("input", { id: "svc-description", maxlength: "500", value: isNew ? "" : service.description, placeholder: "Необязательно" });
    const order = el("input", { id: "svc-order", type: "number", min: "0", step: "1", value: String(isNew ? 100 : service.sort_order) });
    const quantity = el("input", { id: "svc-quantity", type: "number", min: "0", step: "1", inputmode: "numeric", value: String(isNew ? 0 : service.quantity) });
    const [limitedField, limited] = checkField("svc-limited", "Количество ограничено",
      isNew ? false : service.is_limited, "Ведём остаток: услуга пропадает у клиента, когда он кончился. Мойку не отмечайте.");
    const quantityField = formField("svc-quantity", "Остаток сейчас", quantity);
    const [activeField, active] = checkField("svc-active", "Включена в работу — видна клиенту", isNew ? true : service.is_active);
    const workText = el("span", { class: "hint" });

    const refresh = () => {
      quantityField.hidden = !limited.checked;
      const p = Number(price.value) || 0;
      const m = Number(material.value) || 0;
      workText.textContent = m > p ? "Материал не может стоить больше услуги." : "Работа: " + fmt.money(p - m);
      workText.classList.toggle("hint-error", m > p);
    };
    [price, material].forEach((box) => { box.oninput = refresh; });
    limited.onchange = refresh;

    const body = el("div", { class: "form-grid" }, [
      formField("svc-name", "Название", name, "field-wide"),
      formField("svc-price", "Цена, ₽ — её называете клиенту", price),
      el("div", { class: "field" }, [el("label", { for: "svc-material", text: "Из них материал, ₽" }), material, workText]),
      formField("svc-description", "Описание", description),
      formField("svc-order", "Порядок показа", order),
      limitedField, quantityField, activeField,
    ]);
    const save = el("button", { class: "btn btn-primary", type: "button", text: isNew ? "Добавить" : "Сохранить" });
    const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
    const dlg = App.dialog({
      title: isNew ? "Новая услуга" : "Изменить услугу",
      sub: isNew ? "Категория: " + category.name : "Уже созданные записи не изменятся — в них цена на момент брони.",
      body, actions: [cancel, save], wide: true,
    });
    cancel.onclick = dlg.close;
    save.onclick = async () => {
      if (!name.value.trim() || price.value === "") { toast("Укажите название и цену.", "error"); return; }
      if ((Number(material.value) || 0) > Number(price.value)) { toast("Материал не может стоить больше услуги.", "error"); return; }
      const payload = {
        name: name.value.trim(), description: description.value.trim(),
        price: String(Math.round(Number(price.value))), material_price: String(Math.round(Number(material.value) || 0)),
        is_limited: limited.checked, quantity: Math.max(0, Math.floor(Number(quantity.value) || 0)),
        is_active: active.checked, sort_order: Math.max(0, Math.floor(Number(order.value) || 0)),
      };
      if (isNew) payload.category = category.id;
      save.disabled = true;
      const ok = await guard(() => isNew ? api.post("/master/services/", payload) : patchService(service, payload));
      save.disabled = false;
      if (!ok) return;
      dlg.close();
      toast(ok.name, "ok", isNew ? "Услуга добавлена" : "Сохранено");
      await loadServices();
    };
    refresh();
    name.focus();
  }

  /* ---------------------------------------------------------- звонки */

  const CALL_BADGE = {
    on_site: "badge-warn", callback: "badge-info", late: "badge-danger",
    tomorrow: "badge", off_hours: "badge", no_show: "badge-danger",
  };
  const OUTCOMES = [["reached", "Дозвонился"], ["no_answer", "Не дозвонился"], ["callback", "Перезвонить"]];

  async function loadCalls() {
    const point = $("#f-point").value;
    const rows = await guard(() => api.get("/master/calls/" + (point ? "?service_point=" + point : "")));
    if (!rows) return;
    state.calls = rows;
    const badge = $("#calls-count");
    badge.hidden = !rows.length;
    badge.textContent = String(rows.length);
    renderCalls();
  }

  /** Последний звонок одной строкой: итог, время, кто. */
  function lastCallText(call) {
    if (!call) return "ещё не звонили";
    const when = new Date(call.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    return call.outcome_display.toLowerCase() + " в " + when + (call.actor ? " · " + call.actor : "");
  }

  function renderCalls() {
    const tbody = $("#calls-rows");
    if (!tbody) return;
    tbody.innerHTML = "";
    if (!state.calls.length) {
      tbody.append(el("tr", { class: "row-empty" }, [
        el("td", { colspan: "5" }, [empty("Звонить сейчас некому.", "phone")]),
      ]));
      return;
    }
    const today = new Date().toLocaleDateString("ru-RU");
    state.calls.forEach((item) => {
      const [date, time] = item.local_time.split(" ");
      tbody.append(el("tr", {}, [
        el("td", { class: "nowrap", "data-label": "Когда" }, [
          el("div", { class: "cell-main", text: time }),
          el("div", { class: "cell-sub mono", text: [date === today ? "" : date.slice(0, 5), item.booking_code].filter(Boolean).join(" · ") }),
        ]),
        el("td", { "data-label": "Клиент" }, [
          el("div", { class: "cell-main", text: item.client_name || "Без имени" }),
          el("div", { class: "cell-sub" }, [
            el("a", { href: "tel:" + item.client_phone, text: item.client_phone }),
            state.points.length > 1 ? document.createTextNode(" · " + item.service_point_name) : null,
          ]),
        ]),
        el("td", { "data-label": "Зачем" }, [
          el("span", { class: "badge " + (CALL_BADGE[item.reason] || "badge") }, [el("span", { class: "dot" }), item.reason_display]),
          el("div", { class: "cell-sub", style: "margin-top:4px", text: item.hint }),
        ]),
        el("td", { "data-label": "Последний звонок" }, [
          el("div", { class: "cell-sub", text: lastCallText(item.last_call) }),
          item.attempts ? el("div", { class: "cell-sub", text: "не дозвонились: " + item.attempts }) : null,
        ]),
        el("td", { class: "num nowrap", "data-label": "" }, [
          el("button", { class: "btn btn-sm btn-primary", type: "button", text: "Отметить звонок",
            onClick: () => openCallDialog(item) }),
        ]),
      ]));
    });
  }

  /** Отметка звонка: итог, «перезвонить в …», заметка и журнал по записи. */
  async function openCallDialog(item) {
    const journalPath = item.booking
      ? "/master/bookings/" + item.booking + "/calls/"
      : "/master/clients/" + item.client + "/calls/";
    const history = await guard(() => api.get(journalPath));
    if (!history) return;

    const form = { outcome: null };
    const outcomes = el("div", { class: "choice-row", role: "group", "aria-label": "Итог звонка" });
    const when = el("input", { id: "call-when", type: "datetime-local" });
    const quick = el("div", { class: "choice-row" });
    const whenField = el("div", { class: "field field-wide", hidden: true }, [
      el("label", { for: "call-when", text: "Перезвонить в" }), when, quick,
    ]);
    const note = el("input", { id: "call-note", maxlength: "500", placeholder: "Например: приедет к 15:30, просит Shell" });

    const pad = (n) => String(n).padStart(2, "0");
    const toLocalInput = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
    const point = state.points.find((p) => p.id === item.service_point);
    const shortcuts = [
      ["Через 30 минут", () => new Date(Date.now() + 30 * 60000)],
      ["Через час", () => new Date(Date.now() + 60 * 60000)],
    ];
    if (point && point.opens_at) {
      shortcuts.push(["Завтра к открытию", () => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        const [h, m] = point.opens_at.split(":");
        d.setHours(Number(h), Number(m), 0, 0);
        return d;
      }]);
    }
    shortcuts.forEach(([label, make]) => quick.append(el("button", {
      class: "btn btn-sm btn-ghost", type: "button", text: label,
      onClick: () => { when.value = toLocalInput(make()); },
    })));

    OUTCOMES.forEach(([value, label]) => {
      const btn = el("button", { class: "btn btn-sm", type: "button", text: label, "aria-pressed": "false" });
      btn.onclick = () => {
        form.outcome = value;
        $$("button", outcomes).forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        whenField.hidden = value !== "callback";
        if (value === "callback" && !when.value) when.value = toLocalInput(new Date(Date.now() + 30 * 60000));
      };
      outcomes.append(btn);
    });

    const journal = history.length
      ? el("div", { class: "stack-sm" }, history.slice(0, 5).map((call) => el("div", { class: "live-row" }, [
        el("div", { style: "flex:1;min-width:0" }, [
          el("div", { class: "cell-main", text: call.outcome_display + (call.callback_at ? " · на " + fmt.dateTime(call.callback_at) : "") }),
          el("div", { class: "cell-sub", text: [fmt.dateTime(call.created_at), call.actor, call.note].filter(Boolean).join(" · ") }),
        ]),
      ])))
      : el("p", { class: "hint", text: "Звонков по этой записи ещё не было." });

    const body = el("div", { class: "stack" }, [
      el("p", { class: "hint" }, [
        // Подсказка бывает вопросом («приедет?») — точку после неё не ставим.
        document.createTextNode(item.hint + (/[?.!]$/.test(item.hint) ? " " : ". ") + "Позвоните: "),
        el("a", { href: "tel:" + item.client_phone, text: item.client_phone }),
      ]),
      el("div", { class: "field" }, [el("span", { class: "label", text: "Чем закончился звонок" }), outcomes]),
      el("div", { class: "form-grid" }, [
        whenField,
        el("div", { class: "field field-wide" }, [el("label", { for: "call-note", text: "Заметка" }), note]),
      ]),
      el("div", { class: "stack-sm" }, [el("span", { class: "label", text: "Журнал звонков" }), journal]),
    ]);
    const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
    const save = el("button", { class: "btn btn-primary", type: "button", text: "Сохранить" });
    const dlg = App.dialog({
      title: "Звонок · " + (item.client_name || item.client_phone),
      sub: item.reason_display + (item.booking_code ? " · запись " + item.booking_code : ""),
      body, actions: [cancel, save], wide: true,
    });
    cancel.onclick = dlg.close;
    save.onclick = async () => {
      if (!form.outcome) { toast("Выберите, чем закончился звонок.", "error"); return; }
      const payload = { outcome: form.outcome, reason: item.reason, note: note.value.trim() };
      if (form.outcome === "callback") {
        if (!when.value) { toast("Когда перезвонить?", "error"); return; }
        payload.callback_at = new Date(when.value).toISOString();
      }
      if (!item.booking) payload.service_point = item.service_point;
      save.disabled = true;
      const ok = await guard(() => api.post(journalPath, payload));
      save.disabled = false;
      if (!ok) return;
      dlg.close();
      toast(ok.outcome_display + (ok.callback_at ? " · " + fmt.dateTime(ok.callback_at) : ""), "ok", "Звонок отмечен");
      await reload();
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
            text: (draft.service_title || "услуга не выбрана") +
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
    // Форма, а не кнопка с onclick: Enter в любом поле и менеджер паролей
    // браузера работают сами.
    $("#auth-form").onsubmit = login;

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

    $("#btn-add-category").onclick = () => openCategoryForm(null);
    $("#btn-add-service").onclick = () => openServiceForm(null);
    $("#btn-walk-in").onclick = openWalkIn;
    $("#s-search").oninput = renderServices;
    $("#s-inactive").onchange = renderServices;
    $("#s-point").onchange = () => {
      state.servicePoint = $("#s-point").value;
      state.categoryId = null;
      renderServices();
    };

    ["#f-date", "#f-point", "#f-status"].forEach((sel) => { $(sel).onchange = reload; });

    let searchTimer = null;
    $("#f-search").oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(reload, 350);
    };

    // Вкладки «Записи» / «Услуги» (и «Метрики» у администратора). Каталог
    // загружается при открытии вкладки — смене он не нужен.
    $$(".tab[data-tab]").forEach((tab) => {
      tab.onclick = () => openTab(tab.dataset.tab);
    });
  }

  function openTab(name) {
    $$(".tab[data-tab]").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
    $$("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== name; });
    if (name === "services") loadServices();
    if (name === "calls") renderCalls();
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

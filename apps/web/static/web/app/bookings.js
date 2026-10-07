/* Записи: ближайшая запись с действиями, «Записаться», история.

   Одна вкладка вместо прежних «Запись» и «Мои записи»: человек открывает
   её, чтобы узнать «когда мне ехать» или записаться, и оба ответа — на
   первом экране. Мастер записи открывается окном поверх (`Sheet`); его
   черновик живёт на сервере, поэтому закрытое окно или другая вкладка
   его не теряют — здесь появляется «Продолжить запись». */

import { BookingWizard, SlotPicker, Timer } from "app/booking";
import {
  CONFIG, LoadError, Sheet, api, ask, bus, call, html, money, takeBookingRequest, toast, useEffect,
  useLoad, useState, visitTime,
} from "app/lib";

const STATUS = {
  pending: ["badge-info", "Ожидает"],
  in_progress: ["badge-warn", "В работе"],
  completed: ["badge-ok", "Выполнена"],
  cancelled_by_client: ["badge-danger", "Отменена вами"],
  cancelled_by_master: ["badge-danger", "Отменена сервисом"],
  no_show: ["badge-danger", "Не приехали"],
};

const rows = (data) => (data ? data.results || data : []);
const icon = (name) => ({ __html: window.App.icon(name, 18) });

export function Bookings() {
  const upcoming = useLoad(() => api.get("/bookings/?scope=upcoming"));
  const history = useLoad(() => api.get("/bookings/?scope=history"));
  const draft = useLoad(() => api.get("/bookings/drafts/current/"));
  // «Записаться» нажали на другом экране (гараж) — мастер открыт сразу.
  const [wizard, setWizard] = useState(() => takeBookingRequest());
  const [moving, setMoving] = useState(null);

  function reloadAll() {
    upcoming.reload();
    history.reload();
    draft.reload();
  }

  useEffect(() => bus.on("bookings:changed", reloadAll), []);
  // «Записаться» с других экранов (гараж, пустые состояния) открывает мастер здесь.
  useEffect(() => bus.on("booking:start", () => { takeBookingRequest(); setWizard(true); }), []);

  async function cancel(booking) {
    const reason = await ask({
      title: "Отменить запись " + booking.code + "?",
      text: "Время сразу освободится — его смогут занять другие.",
      placeholder: "Причина (необязательно)",
      confirmLabel: "Отменить запись", danger: true, withInput: true,
    });
    // `ask` с полем возвращает строку (в том числе пустую) или null при «Отмена».
    if (reason === null) return;
    const ok = await call(() => api.post("/bookings/" + booking.id + "/cancel/", { reason: reason || "" }));
    if (ok) { toast("Запись отменена", "ok"); reloadAll(); }
  }

  async function reschedule(booking, startAt) {
    const moved = await call(() => api.post("/bookings/" + booking.id + "/reschedule/", { start_at: startAt }));
    if (!moved) return;
    setMoving(null);
    toast("Новое время — " + visitTime(moved.start_at, moved.service_point.timezone), "ok", "Запись перенесена");
    reloadAll();
  }

  function closeWizard() {
    setWizard(false);
    reloadAll();
  }

  const next = rows(upcoming.data);
  const past = rows(history.data);
  const liveDraft = draft.data && draft.data.is_alive ? draft.data : null;
  const loading = upcoming.data === undefined || history.data === undefined;

  let body;
  if (upcoming.error && !upcoming.data) {
    body = html`<${LoadError} error=${upcoming.error} onRetry=${reloadAll} />`;
  } else if (loading) {
    body = html`<p class="muted center">Загружаем…</p>`;
  } else {
    body = html`<div class="stack-lg">
      ${liveDraft && html`<${ResumeBanner} draft=${liveDraft} onOpen=${() => setWizard(true)} onExpire=${draft.reload} />`}
      ${next.length > 0
        ? html`<${NextBooking} booking=${next[0]} onCancel=${cancel} onMove=${setMoving} />`
        : !past.length && html`<div class="empty-state">
            <b>Запишитесь на замену масла</b>
            <p>Выберите адрес и удобное время — это пара минут. Пост будет ждать вас.</p>
          </div>`}
      ${!liveDraft && html`<button class="btn btn-primary btn-block btn-lg" type="button" onClick=${() => setWizard(true)}>
        ${next.length ? "Записаться ещё" : "Записаться"}</button>`}
      ${next.length > 1 && html`<section class="stack">
        <span class="kicker">Ещё записи</span>
        ${next.slice(1).map((b) => html`<${CompactBooking} key=${b.id} booking=${b} onCancel=${cancel} onMove=${setMoving} />`)}
      </section>`}
      ${(past.length > 0 || next.length > 0) && html`<section class="stack">
        <span class="kicker">История</span>
        ${past.length
          ? past.map((b) => html`<${CompactBooking} key=${b.id} booking=${b} />`)
          : html`<p class="muted">Здесь будут прошлые визиты.</p>`}
      </section>`}
    </div>`;
  }

  return html`<main class="screen">
    <div class="screen-head"><h1>Записи</h1></div>
    ${body}
    ${wizard && html`<${Sheet} title="Запись на замену масла" onClose=${closeWizard}>
      <${BookingWizard} onClose=${closeWizard} onBooked=${() => bus.emit("bookings:changed")} />
    </${Sheet}>`}
    ${moving && html`<${Sheet} title="Перенести запись" onClose=${() => setMoving(null)}>
      <div class="stack">
        <p class="muted">Сейчас: ${visitTime(moving.start_at, moving.service_point.timezone)}, ${moving.service_point.address}.
          Выберите новое время на том же адресе.</p>
        <${SlotPicker} pointId=${moving.service_point.id} zone=${moving.service_point.timezone}
          pointName=${moving.service_point.name} actionLabel="Перенести"
          onPick=${(startAt) => reschedule(moving, startAt)} />
      </div>
    </${Sheet}>`}
  </main>`;
}

/** Начатая и не законченная запись: черновик держит время, пока идёт таймер. */
function ResumeBanner({ draft, onOpen, onExpire }) {
  return html`<button class="card pad resume" type="button" onClick=${onOpen}>
    <span class="resume-body">
      <b>Вы записываетесь</b>
      <span class="muted">Выбранное держится за вами ещё</span>
    </span>
    <${Timer} seconds=${draft.seconds_left} stamp=${draft.id} onExpire=${onExpire} />
    <span class="resume-go">Продолжить</span>
  </button>`;
}

/** Адрес на карте: маршрут до точки, а без координат — поиск по адресу. */
function routeUrl(point) {
  if (point.latitude && point.longitude) {
    return "https://yandex.ru/maps/?rtext=~" + point.latitude + "," + point.longitude + "&rtt=auto";
  }
  return "https://yandex.ru/maps/?text=" + encodeURIComponent(point.address);
}

const telHref = (phone) => "tel:" + String(phone || CONFIG.phone).replace(/[^\d+]/g, "");

function carLine(booking) {
  return [booking.car_model, booking.car_plate].filter(Boolean).join(" · ");
}

/** Ближайшая запись — крупно, со всем, что может понадобиться по дороге. */
function NextBooking({ booking, onCancel, onMove }) {
  const [cls, label] = STATUS[booking.status] || ["badge", booking.status_display];
  const point = booking.service_point;
  return html`<article class="card pad">
    <div class="booking-head">
      <span class="kicker">Ближайшая запись</span>
      <span class=${"badge " + cls}>${label}</span>
    </div>
    <div class="next-when">${visitTime(booking.start_at, point.timezone)}</div>
    <div class="booking-lines">
      <span>${point.address}</span>
      <span>${booking.oil_title}</span>
      ${carLine(booking) && html`<span>${carLine(booking)}</span>`}
      <span>Код записи <b class="mono">${booking.code}</b> — назовите его на посту</span>
    </div>
    <div class="action-grid">
      <a class="btn" href=${routeUrl(point)} target="_blank" rel="noopener">
        <span class="btn-ico" dangerouslySetInnerHTML=${icon("pin")}></span>Маршрут</a>
      <a class="btn" href=${telHref(point.phone)}>
        <span class="btn-ico" dangerouslySetInnerHTML=${icon("phone")}></span>Позвонить</a>
      ${booking.can_reschedule && html`<button class="btn" type="button" onClick=${() => onMove(booking)}>
        <span class="btn-ico" dangerouslySetInnerHTML=${icon("clock")}></span>Перенести</button>`}
      ${booking.can_cancel && html`<button class="btn btn-danger" type="button" onClick=${() => onCancel(booking)}>
        <span class="btn-ico" dangerouslySetInnerHTML=${icon("x")}></span>Отменить</button>`}
    </div>
    ${!booking.can_cancel && booking.status === "pending" && html`<p class="hint" style="margin-top:12px">
      Перенести или отменить можно не позже чем за ${CONFIG.cancelDeadline} мин до визита.
      Не успеваете — позвоните.</p>`}
  </article>`;
}

/** Строка списка: остальные предстоящие и история. */
function CompactBooking({ booking, onCancel, onMove }) {
  const [cls, label] = STATUS[booking.status] || ["badge", booking.status_display];
  const zone = booking.service_point && booking.service_point.timezone;
  // Сумма — только у выполненной записи: это чек, который клиент оплатил.
  const paid = booking.final_price != null;
  const withPoints = Number(booking.points_spent) > 0;
  return html`<article class="card pad">
    <div class="booking-head">
      <span class="booking-when">${visitTime(booking.start_at, zone)}</span>
      <span class=${"badge " + cls}>${label}</span>
    </div>
    <div class="booking-lines">
      <span>${[booking.oil_title, carLine(booking)].filter(Boolean).join(" · ")}</span>
      ${booking.cancel_reason && html`<span>Причина: ${booking.cancel_reason}</span>`}
    </div>
    ${paid && html`<div class="booking-foot">
      <span class="muted">${withPoints ? money(booking.paid_amount) + " деньгами + " + money(booking.points_spent) + " баллами" : ""}</span>
      <span class="booking-price">${money(booking.final_price)}</span>
    </div>`}
    ${(booking.can_reschedule || booking.can_cancel) && onCancel && html`<div class="row" style="margin-top:12px">
      ${booking.can_reschedule && html`<button class="btn btn-sm" type="button" onClick=${() => onMove(booking)}>Перенести</button>`}
      ${booking.can_cancel && html`<button class="btn btn-sm btn-ghost btn-danger" type="button" onClick=${() => onCancel(booking)}>Отменить</button>`}
    </div>`}
  </article>`;
}

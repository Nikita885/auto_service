/* Главная: когда мне ехать, что пора сделать, сколько баллов.

   Выбор заказчика (редизайн, октябрь 2026): вкладка «Главная» вместо
   «Записей». Ближайшая запись — «билет» с кодом на корешке, под ней —
   напоминание о масле из гаража (главный повод записаться) и баллы;
   ниже — остальные записи и история. Мастер записи открывается окном
   снизу; черновик живёт на сервере, поэтому закрытое окно его не теряет —
   здесь появляется «Продолжить запись». */

import { BookingWizard, SlotPicker, Timer } from "app/booking";
import {
  CONFIG, InfoRow, LoadError, Sheet, Skel, api, bus, call, daysUntil, fmt, formatPhone, html, money,
  startBooking, takeBookingRequest, toast, useEffect, useLoad, useNet, useState, visitTime,
} from "app/lib";

/* Статусы глазами клиента: «Ждём вас» понятнее, чем «Ожидает». */
const STATUS = {
  pending: ["is-wait", "Ждём вас"],
  in_progress: ["is-work", "Машина в работе"],
  completed: ["is-ok", "Выполнена"],
  cancelled_by_client: ["is-off", "Отменили вы"],
  cancelled_by_master: ["is-bad", "Отменил сервис"],
  no_show: ["is-off", "Не приехали"],
};

const rows = (data) => (data ? data.results || data : []);
const svg = (name, size) => ({ __html: window.App.icon(name, size || 20) });
const points = (n) => fmt.number(n) + " " + fmt.plural(Math.floor(Number(n)), "балл", "балла", "баллов");

/** Приветствие по часам телефона — не по поясу точки: это про человека. */
function greeting(name) {
  const h = new Date().getHours();
  const part = h < 5 ? "Доброй ночи" : h < 12 ? "Доброе утро" : h < 18 ? "Добрый день" : "Добрый вечер";
  return name ? part + ", " + name.split(" ")[0] : part;
}

export function Home({ user }) {
  const upcoming = useLoad(() => api.get("/bookings/?scope=upcoming"), [], "upcoming");
  const history = useLoad(() => api.get("/bookings/?scope=history"), [], "history");
  const draft = useLoad(() => api.get("/bookings/drafts/current/"));
  const car = useLoad(loadPrimaryCar, [], "home.car");
  const bonus = useLoad(() => api.get("/referral/"), [], "referral");
  const net = useNet();
  // «Записаться» нажали на другом экране (гараж) — мастер открыт сразу.
  const [wizard, setWizard] = useState(() => takeBookingRequest());
  const [moving, setMoving] = useState(null);
  const [cancelling, setCancelling] = useState(null);
  const [more, setMore] = useState(null);
  const [opened, setOpened] = useState(null);

  function reloadAll() {
    upcoming.reload();
    history.reload();
    draft.reload();
  }

  useEffect(() => bus.on("bookings:changed", reloadAll), []);
  useEffect(() => bus.on("booking:start", () => { takeBookingRequest(); setWizard(true); }), []);

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
  const first = upcoming.data === undefined;
  const canBook = !net.offline;

  let body;
  if (upcoming.error && !upcoming.data) {
    body = html`<${LoadError} error=${upcoming.error} onRetry=${reloadAll} />`;
  } else if (first) {
    body = html`<${HomeSkeleton} />`;
  } else {
    body = html`<div class="stack-lg">
      ${liveDraft && html`<${ResumeBanner} draft=${liveDraft} onOpen=${() => setWizard(true)} onExpire=${draft.reload} />`}
      ${next.length > 0
        ? html`<${Ticket} booking=${next[0]} onMove=${setMoving} onMore=${setMore} />`
        : html`<section class="card pad invite-book">
            <span class="empty-ico" dangerouslySetInnerHTML=${svg("calendar", 24)}></span>
            <div>
              <b>Запишитесь на замену масла</b>
              <p class="muted">Выберите адрес и время — пост будет ждать вас, без очереди.</p>
            </div>
            ${!liveDraft && html`<button class="btn btn-primary btn-block btn-lg" type="button" disabled=${!canBook}
              onClick=${() => setWizard(true)}>${canBook ? "Записаться" : "Записаться — нужна сеть"}</button>`}
          </section>`}
      <${OilStrip} data=${car.data} />
      <${BonusStrip} data=${bonus.data} />
      ${next.length > 0 && !liveDraft && html`<button class="btn btn-block" type="button" disabled=${!canBook}
        onClick=${() => setWizard(true)}>${canBook ? "Записаться на другое время" : "Записаться — нужна сеть"}</button>`}
      ${next.length > 1 && html`<section>
        <h2 class="section-title">Ещё записи</h2>
        <div class="list">${next.slice(1).map((b) => html`<${BookingRow} key=${b.id} booking=${b} onOpen=${setOpened} />`)}</div>
      </section>`}
      ${past.length > 0 && html`<section>
        <h2 class="section-title">История</h2>
        <div class="list">${past.map((b) => html`<${BookingRow} key=${b.id} booking=${b} onOpen=${setOpened} />`)}</div>
      </section>`}
    </div>`;
  }

  return html`<main class="screen">
    <div class="screen-head"><h1>${greeting(user && user.full_name)}</h1></div>
    ${body}
    ${wizard && html`<${Sheet} tall title="Запись на замену масла" onClose=${closeWizard}>
      <${BookingWizard} onClose=${closeWizard} onBooked=${() => bus.emit("bookings:changed")} />
    </${Sheet}>`}
    ${moving && html`<${Sheet} tall title="Перенести запись" onClose=${() => setMoving(null)}>
      <div class="stack">
        <p class="muted">Сейчас: ${visitTime(moving.start_at, moving.service_point.timezone)},
          ${moving.service_point.name}. Новое время — на том же адресе.</p>
        <${SlotPicker} pointId=${moving.service_point.id} zone=${moving.service_point.timezone}
          pointName=${moving.service_point.name} actionLabel="Перенести"
          onPick=${(startAt) => reschedule(moving, startAt)} />
      </div>
    </${Sheet}>`}
    ${more && html`<${MoreSheet} booking=${more} onClose=${() => setMore(null)}
      onMove=${() => { setMore(null); setMoving(more); }}
      onCancel=${() => { setMore(null); setCancelling(more); }} />`}
    ${cancelling && html`<${CancelSheet} booking=${cancelling} onClose=${() => setCancelling(null)}
      onDone=${() => { setCancelling(null); reloadAll(); }} />`}
    ${opened && html`<${BookingSheet} booking=${opened} onClose=${() => setOpened(null)} />`}
  </main>`;
}

/** Основная машина и её сводка — для строки «масло» на главной. */
async function loadPrimaryCar() {
  const cars = await api.get("/garage/cars/");
  const primary = (cars || []).find((c) => c.is_primary) || (cars || [])[0];
  if (!primary) return { car: null };
  const summary = await api.get("/garage/cars/" + primary.id + "/summary/");
  return { car: primary, oil: (summary.reminders || []).find((r) => r.kind === "oil") || null };
}

function HomeSkeleton() {
  return html`<div class="stack-lg" aria-busy="true">
    <div class="card pad ticket-skel">
      <${Skel} w="35%" h="var(--space-3)" />
      <${Skel} w="55%" h="var(--fs-number)" />
      <${Skel} w="80%" />
      <${Skel} w="65%" />
      <div class="ticket-actions">${[0, 1, 2, 3].map(() => html`<${Skel} w="var(--touch)" h="var(--touch)" r="50%" />`)}</div>
    </div>
    <${Skel} h="var(--control-lg)" r="var(--radius)" />
    <${Skel} h="var(--control-lg)" r="var(--radius)" />
  </div>`;
}

/** Начатая и не законченная запись: выбранное держится, пока идёт таймер. */
function ResumeBanner({ draft, onOpen, onExpire }) {
  return html`<button class="resume" type="button" onClick=${onOpen}>
    <span class="resume-body">
      <b>Вы записываетесь</b>
      <span class="muted">Выбранное держится за вами</span>
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
const carLine = (booking) => [booking.car_model, booking.car_plate].filter(Boolean).join(" · ");

/** «Среда, 14 октября» и «13:00» отдельно: время — главное, его крупно. */
function dayAndTime(iso, zone) {
  const d = new Date(iso);
  const opts = { timeZone: zone || undefined };
  try {
    return {
      day: d.toLocaleDateString("ru-RU", { ...opts, weekday: "long", day: "numeric", month: "long" }),
      time: d.toLocaleTimeString("ru-RU", { ...opts, hour: "2-digit", minute: "2-digit" }),
    };
  } catch (e) {
    return { day: fmt.date(iso), time: fmt.time(iso) };
  }
}

/** Ближайшая запись — «билет»: время крупно, код на корешке.

    Быстрые действия — круглыми кнопками в ряд (Zocdoc на Mobbin): маршрут,
    звонок, перенос; отмена спрятана в «Ещё», случайно её не нажать. */
function Ticket({ booking, onMove, onMore }) {
  const point = booking.service_point;
  const [cls, label] = STATUS[booking.status] || ["", booking.status_display];
  const soon = daysUntil(booking.start_at, point.timezone);
  const when = dayAndTime(booking.start_at, point.timezone);
  return html`<article class="ticket">
    <div class="ticket-main">
      <div class="ticket-head">
        <span class="kicker">${soon || "Ближайшая запись"}</span>
        <span class=${"status " + cls}>${label}</span>
      </div>
      <div class="ticket-when">
        <span class="ticket-day">${when.day}</span>
        <span class="ticket-time">${when.time}</span>
      </div>
      <div class="info-list">
        <${InfoRow} icon="pin" label=${point.name}>${point.address}</${InfoRow}>
        ${booking.oil_on_site
          ? html`<${InfoRow} icon="drop" label="Масло подберём на месте">Мастер позвонит и поможет выбрать</${InfoRow}>`
          : html`<${InfoRow} icon="drop">${booking.oil_title}</${InfoRow}>`}
        ${carLine(booking) && html`<${InfoRow} icon="car">${carLine(booking)}</${InfoRow}>`}
      </div>
      <div class="ticket-actions">
        <a class="round-act" href=${routeUrl(point)} target="_blank" rel="noopener">
          <span dangerouslySetInnerHTML=${svg("pin")}></span>Маршрут</a>
        <a class="round-act" href=${telHref(point.phone)}>
          <span dangerouslySetInnerHTML=${svg("phone")}></span>Позвонить</a>
        ${booking.can_reschedule && html`<button class="round-act" type="button" onClick=${() => onMove(booking)}>
          <span dangerouslySetInnerHTML=${svg("clock")}></span>Перенести</button>`}
        <button class="round-act" type="button" onClick=${() => onMore(booking)}>
          <span dangerouslySetInnerHTML=${svg("more")}></span>Ещё</button>
      </div>
    </div>
    <div class="ticket-stub">
      <span class="muted">Код на посту</span>
      <b class="ticket-code">${booking.code}</b>
    </div>
  </article>`;
}

/** Масло по основной машине: сколько осталось — и запись в одно касание. */
function OilStrip({ data }) {
  if (!data) return null;
  if (!data.car) {
    return html`<button class="strip" type="button" onClick=${() => bus.emit("goto", "garage")}>
      <span class="strip-ico" dangerouslySetInnerHTML=${svg("car")}></span>
      <span class="strip-body"><b>Добавьте машину</b><span class="muted">Подскажем, когда менять масло</span></span>
      <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
    </button>`;
  }
  const r = data.oil;
  const name = data.car.title || data.car.plate || "Машина";
  if (!r || r.status === "unknown") {
    return html`<button class="strip" type="button" onClick=${() => bus.emit("goto", "garage")}>
      <span class="strip-ico" dangerouslySetInnerHTML=${svg("drop")}></span>
      <span class="strip-body"><b>Когда меняли масло?</b><span class="muted">${name} · добавьте замену, подскажем следующую</span></span>
      <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
    </button>`;
  }
  const km = r.left_km != null ? (r.left_km < 0 ? "пробег превышен на " + fmt.number(-r.left_km) + " км" : "через " + fmt.number(r.left_km) + " км") : "";
  const date = r.due_date ? new Date(r.due_date + "T12:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long" }) : "";
  const text = r.status === "overdue" ? "Пора менять масло" : "Замена масла " + (km || "до " + date);
  const sub = r.status === "overdue" ? (km || "срок прошёл " + date) : km && date ? "или до " + date : name;
  const urgent = r.status !== "ok";
  return html`<button class=${"strip" + (urgent ? " is-" + r.status : "")} type="button"
    onClick=${() => (urgent ? startBooking() : bus.emit("goto", "garage"))}>
    <span class="strip-ico" dangerouslySetInnerHTML=${svg("drop")}></span>
    <span class="strip-body"><b>${text}</b><span class="muted">${sub}</span></span>
    ${urgent ? html`<span class="strip-go">Записаться</span>` : html`<span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>`}
  </button>`;
}

function BonusStrip({ data }) {
  if (!data || !data.enabled) return null;
  const payout = Number(data.expected_payout);
  return html`<button class="strip" type="button" onClick=${() => bus.emit("goto", "bonus")}>
    <span class="strip-ico" dangerouslySetInnerHTML=${svg("wallet")}></span>
    <span class="strip-body">
      <b>${points(Math.floor(Number(data.balance)))}</b>
      <span class="muted">${payout > 0 ? "ночью придёт ещё " + fmt.number(payout) : "можно оплатить часть замены"}</span>
    </span>
    <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
  </button>`;
}

/** Строка списка: остальные предстоящие и история. Касание — подробности. */
function BookingRow({ booking, onOpen }) {
  const [cls, label] = STATUS[booking.status] || ["", booking.status_display];
  const zone = booking.service_point && booking.service_point.timezone;
  return html`<button class="list-row" type="button" onClick=${() => onOpen(booking)}>
    <span class="list-body">
      <b>${visitTime(booking.start_at, zone)}</b>
      <span class=${"status-line " + cls}><span class="dot"></span>${label}</span>
    </span>
    ${booking.final_price != null && html`<b class="list-side">${money(booking.final_price)}</b>`}
    <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
  </button>`;
}

/** Подробности записи из истории — окном снизу. */
function BookingSheet({ booking, onClose }) {
  const [cls, label] = STATUS[booking.status] || ["", booking.status_display];
  const point = booking.service_point;
  const withPoints = Number(booking.points_spent) > 0;
  return html`<${Sheet} title=${visitTime(booking.start_at, point.timezone)} onClose=${onClose}>
    <div class="stack">
      <span class=${"status " + cls}>${label}</span>
      <div class="card pad info-list">
        <${InfoRow} icon="pin" label=${point.name}>${point.address}</${InfoRow}>
        <${InfoRow} icon="drop" label="Масло">${booking.oil_title}</${InfoRow}>
        ${carLine(booking) && html`<${InfoRow} icon="car" label="Машина">${carLine(booking)}</${InfoRow}>`}
      </div>
      ${booking.cancel_reason && html`<p class="muted">Причина отмены: ${booking.cancel_reason}</p>`}
      ${booking.final_price != null && html`<div class="card pad">
        <div class="summary-row"><span>Итог</span><span>${money(booking.final_price)}</span></div>
        ${withPoints && html`<div class="summary-row"><span>Деньгами</span><span>${money(booking.paid_amount)}</span></div>
          <div class="summary-row"><span>Баллами</span><span>${money(booking.points_spent)}</span></div>`}
      </div>`}
      <div class="row"><span class="muted">Код записи</span><span class="spacer"></span><b class="mono">${booking.code}</b></div>
    </div>
  </${Sheet}>`;
}

/** «Ещё» у билета: перенос и отмена, и почему их может не быть. */
function MoreSheet({ booking, onClose, onMove, onCancel }) {
  const point = booking.service_point;
  return html`<${Sheet} title="Запись" onClose=${onClose}>
    <div class="list">
      ${booking.can_reschedule && html`<button class="list-row" type="button" onClick=${onMove}>
        <span class="strip-ico" dangerouslySetInnerHTML=${svg("clock")}></span>
        <span class="list-body"><b>Перенести</b><span class="muted">На другое время на этом же адресе</span></span>
        <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
      </button>`}
      <a class="list-row" href=${telHref(point.phone)}>
        <span class="strip-ico" dangerouslySetInnerHTML=${svg("phone")}></span>
        <span class="list-body"><b>Позвонить на пост</b><span class="muted">${point.phone ? formatPhone(point.phone) : CONFIG.phone}</span></span>
      </a>
      ${booking.can_cancel && html`<button class="list-row is-danger" type="button" onClick=${onCancel}>
        <span class="strip-ico" dangerouslySetInnerHTML=${svg("x")}></span>
        <span class="list-body"><b>Отменить запись</b><span class="muted">Время сразу освободится</span></span>
      </button>`}
    </div>
    ${!booking.can_cancel && booking.status === "pending" && html`<p class="hint">
      Перенести или отменить в приложении можно не позже чем за ${CONFIG.cancelDeadline} мин до визита.
      Не успеваете — позвоните.</p>`}
  </${Sheet}>`;
}

const CANCEL_REASONS = ["Не успеваю", "Передумал", "Записался на другое время", "Заболел"];

/** Отмена — окном снизу: что будет, причина касанием, отказ подписан
    по смыслу («Оставить запись»), а не «Отмена» рядом с «Отменить». */
function CancelSheet({ booking, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const when = visitTime(booking.start_at, booking.service_point.timezone);

  async function confirm() {
    setBusy(true);
    const ok = await call(() => api.post("/bookings/" + booking.id + "/cancel/", { reason }));
    setBusy(false);
    if (ok) { toast("Запись на " + when + " отменена", "ok"); onDone(); }
  }

  return html`<${Sheet} title=${"Отменить запись на " + when + "?"} onClose=${onClose}
    actions=${html`
      <button class="btn btn-danger-solid btn-lg" type="button" disabled=${busy} onClick=${confirm}>
        ${busy ? "Отменяем…" : "Отменить запись"}</button>
      <button class="btn btn-lg" type="button" onClick=${onClose}>Оставить запись</button>`}>
    <div class="stack">
      <p class="muted">Время сразу освободится — его смогут занять другие.</p>
      <span class="label">Причина, если хотите</span>
      <div class="chips">
        ${CANCEL_REASONS.map((r) => html`<button class="chip" type="button" key=${r}
          aria-pressed=${String(reason === r)} onClick=${() => setReason(reason === r ? "" : r)}>${r}</button>`)}
      </div>
    </div>
  </${Sheet}>`;
}

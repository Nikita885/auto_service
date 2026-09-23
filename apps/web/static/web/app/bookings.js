/* Мои записи: предстоящие и история, отмена своей записи. */

import {
  LoadError, api, ask, bus, call, html, money, toast, useEffect, useLoad, useState, visitTime,
} from "app/lib";

const STATUS = {
  pending: ["badge-info", "Ожидает"],
  in_progress: ["badge-warn", "В работе"],
  completed: ["badge-ok", "Выполнена"],
  cancelled_by_client: ["badge-danger", "Отменена вами"],
  cancelled_by_master: ["badge-danger", "Отменена сервисом"],
  no_show: ["badge-danger", "Не приехали"],
};

export function Bookings() {
  const [scope, setScope] = useState("upcoming");
  const list = useLoad(() => api.get("/bookings/?scope=" + scope), [scope]);

  useEffect(() => bus.on("bookings:changed", list.reload), [list.reload]);

  async function cancel(booking) {
    const reason = await ask({
      title: "Отменить запись " + booking.code + "?",
      text: "Пост и канистра сразу освободятся.",
      placeholder: "Причина (необязательно)",
      confirmLabel: "Отменить запись", danger: true, withInput: true,
    });
    // `ask` с полем возвращает строку (в том числе пустую) или null при «Отмена».
    if (reason === null) return;
    const ok = await call(() => api.post("/bookings/" + booking.id + "/cancel/", { reason: reason || "" }));
    if (ok) { toast("Запись отменена", "ok"); list.reload(); }
  }

  const items = list.data ? list.data.results : [];

  return html`<main class="screen">
    <div class="screen-head"><h1>Мои записи</h1></div>
    <div class="seg" role="tablist">
      <button type="button" aria-pressed=${String(scope === "upcoming")} onClick=${() => setScope("upcoming")}>Предстоящие</button>
      <button type="button" aria-pressed=${String(scope === "history")} onClick=${() => setScope("history")}>История</button>
    </div>
    ${list.error && !list.data ? html`<${LoadError} error=${list.error} onRetry=${list.reload} />`
      : list.loading && !list.data ? html`<p class="muted center">Загружаем…</p>`
      : !items.length ? html`<div class="empty-state">
          <b>${scope === "upcoming" ? "Записей пока нет" : "История пуста"}</b>
          <p>${scope === "upcoming" ? "Запишитесь на удобное время — это пара минут." : "Здесь будут прошлые визиты."}</p>
          ${scope === "upcoming" && html`<button class="btn btn-primary" type="button" style="margin-top:12px"
            onClick=${() => bus.emit("goto", "booking")}>Записаться</button>`}
        </div>`
      : html`<div class="stack-lg">${items.map((b) => html`<${BookingCard} key=${b.id} booking=${b} onCancel=${cancel} />`)}</div>`}
  </main>`;
}

function BookingCard({ booking, onCancel }) {
  const [cls, label] = STATUS[booking.status] || ["badge", booking.status_display];
  const withPoints = Number(booking.points_spent) > 0;
  const zone = booking.service_point && booking.service_point.timezone;
  return html`<article class="card pad">
    <div class="booking-head">
      <span class="booking-when">${visitTime(booking.start_at, zone)}</span>
      <span class=${"badge " + cls}>${label}</span>
    </div>
    <div class="booking-lines">
      <span>${booking.service_point ? booking.service_point.address : ""}</span>
      <span>${booking.oil_title}</span>
      <span>Код записи <b class="mono">${booking.code}</b></span>
      ${booking.cancel_reason && html`<span>Причина: ${booking.cancel_reason}</span>`}
    </div>
    <div class="booking-foot">
      <span class="muted">${withPoints ? money(booking.paid_amount) + " деньгами + " + money(booking.points_spent) + " баллами" : ""}</span>
      <span class="booking-price">${money(booking.total_price)}</span>
    </div>
    ${booking.can_cancel && html`<button class="btn btn-danger btn-block" type="button" style="margin-top:12px"
      onClick=${() => onCancel(booking)}>Отменить запись</button>`}
  </article>`;
}

/* Профиль: кто вы, ваши машины, адреса сервиса и выход.

   Сгруппированный список (выбор заказчика при редизайне, Turo и Rivian на
   Mobbin): шапка с именем и телефоном, ниже — строки. Имя правится окном
   снизу: его видит мастер, когда вы приезжаете. Страницы политики
   обработки данных пока нет — строки на неё тоже нет: мёртвая ссылка хуже
   её отсутствия (тексты по 152-ФЗ — за заказчиком). */

import { useCars } from "app/cars";
import {
  CONFIG, LoadError, Sheet, Skel, api, ask, bus, call, formatPhone, html, toast, useLoad, useState,
} from "app/lib";

const svg = (name, size) => ({ __html: window.App.icon(name, size || 20) });
const telHref = (phone) => "tel:" + String(phone || CONFIG.phone).replace(/[^\d+]/g, "");

export function Profile() {
  const me = useLoad(() => api.get("/auth/me/"), [], "me");
  const { cars } = useCars();
  const [open, setOpen] = useState(null); // name | points

  async function signOut() {
    const yes = await ask({
      title: "Выйти из аккаунта?",
      text: "Войти обратно можно по номеру телефона.",
      confirmLabel: "Выйти", cancelLabel: "Остаться", danger: true,
    });
    if (!yes) return;
    api.signOut();
    bus.emit("signout");
  }

  if (me.error && !me.data) {
    return html`<main class="screen"><${LoadError} error=${me.error} onRetry=${me.reload} /></main>`;
  }
  const user = me.data;
  const initial = user && user.full_name ? user.full_name.trim()[0].toUpperCase() : "";

  return html`<main class="screen">
    <div class="profile-head">
      ${initial
        ? html`<span class="avatar" aria-hidden="true">${initial}</span>`
        : html`<span class="avatar" aria-hidden="true" dangerouslySetInnerHTML=${svg("user", 24)}></span>`}
      <div class="profile-who">
        ${user ? html`<b>${user.full_name || "Без имени"}</b><span class="muted">${formatPhone(user.phone)}</span>`
          : html`<${Skel} w="60%" h="var(--fs-h3)" /><${Skel} w="45%" />`}
      </div>
      <button class="link-btn profile-edit" type="button" disabled=${!user} onClick=${() => setOpen("name")}>Изменить</button>
    </div>

    <div class="stack-lg">
      <div class="list">
        <button class="list-row" type="button" onClick=${() => bus.emit("goto", "garage")}>
          <span class="strip-ico" dangerouslySetInnerHTML=${svg("car")}></span>
          <span class="list-body"><b>Мои машины</b><span class="muted">Их видит мастер, когда вы приезжаете</span></span>
          ${cars && cars.length > 0 && html`<span class="list-side muted">${cars.length}</span>`}
          <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
        </button>
        <button class="list-row" type="button" onClick=${() => setOpen("points")}>
          <span class="strip-ico" dangerouslySetInnerHTML=${svg("pin")}></span>
          <span class="list-body"><b>Адреса и часы работы</b></span>
          <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
        </button>
        <a class="list-row" href=${telHref(CONFIG.phone)}>
          <span class="strip-ico" dangerouslySetInnerHTML=${svg("phone")}></span>
          <span class="list-body"><b>Позвонить в сервис</b><span class="muted">${CONFIG.phone}</span></span>
        </a>
      </div>
      <div class="list">
        <button class="list-row" type="button" onClick=${() => bus.emit("goto", "bonus")}>
          <span class="strip-ico" dangerouslySetInnerHTML=${svg("wallet")}></span>
          <span class="list-body"><b>Бонусы и приглашения</b></span>
          <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
        </button>
      </div>
      <div class="list">
        <button class="list-row is-danger" type="button" onClick=${signOut}>
          <span class="strip-ico" dangerouslySetInnerHTML=${svg("logout")}></span>
          <span class="list-body"><b>Выйти</b></span>
        </button>
      </div>
      <p class="hint center">${CONFIG.company} · ${CONFIG.siteUrl.replace(/^https?:\/\//, "")}</p>
    </div>

    ${open === "name" && user && html`<${NameSheet} user=${user} onClose=${() => setOpen(null)}
      onSaved=${() => { setOpen(null); me.reload(); }} />`}
    ${open === "points" && html`<${PointsSheet} onClose=${() => setOpen(null)} />`}
  </main>`;
}

function NameSheet({ user, onClose, onSaved }) {
  const [name, setName] = useState(user.full_name || "");
  const [busy, setBusy] = useState(false);
  async function save() {
    if (!name.trim()) { toast("Как к вам обращаться? Имя видит мастер.", "error"); return; }
    setBusy(true);
    const ok = await call(() => api.patch("/auth/me/", { full_name: name.trim() }));
    setBusy(false);
    if (ok) { toast("Имя сохранено", "ok"); onSaved(); }
  }
  return html`<${Sheet} title="Как вас зовут" onClose=${onClose}
    actions=${html`<button class="btn btn-primary btn-lg" type="button" disabled=${busy} onClick=${save}>
      ${busy ? "Сохраняем…" : "Сохранить"}</button>`}>
    <form class="stack" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <div class="field">
        <label for="p-name">Имя</label>
        <input id="p-name" autocomplete="name" value=${name} onInput=${(e) => setName(e.target.value)} />
      </div>
      <p class="hint">Имя видит мастер — так он понимает, что заезжаете именно вы.</p>
    </form>
  </${Sheet}>`;
}

/** Адреса сервиса: часы, маршрут, телефон поста. */
function PointsSheet({ onClose }) {
  const list = useLoad(() => api.get("/service-points/"), [], "points");
  const route = (p) => (p.latitude && p.longitude
    ? "https://yandex.ru/maps/?rtext=~" + p.latitude + "," + p.longitude + "&rtt=auto"
    : "https://yandex.ru/maps/?text=" + encodeURIComponent(p.address));
  return html`<${Sheet} title="Адреса" onClose=${onClose}>
    ${!list.data ? html`<div class="stack-sm"><${Skel} h="var(--space-9)" r="var(--radius-lg)" /><${Skel} h="var(--space-9)" r="var(--radius-lg)" /></div>`
      : html`<div class="stack">${list.data.map((p) => html`<section class="card pad point-card" key=${p.id}>
          <b>${p.name}</b>
          <span class="muted">${p.address}</span>
          <span class="hint">${p.opens_at.slice(0, 5)}–${p.closes_at.slice(0, 5)}${p.workdays && p.workdays.length && p.workdays.length < 7 ? " · по графику" : " · ежедневно"}</span>
          <div class="form-pair">
            <a class="btn" href=${route(p)} target="_blank" rel="noopener">Маршрут</a>
            ${p.phone && html`<a class="btn" href=${telHref(p.phone)}>Позвонить</a>`}
          </div>
        </section>`)}</div>`}
  </${Sheet}>`;
}

/* Бонусы: неоновая карта клиента, «Пригласить друга», остальное — вторым
   уровнем.

   Выбор заказчика при редизайне (октябрь 2026): вместо макета «одна
   цифра» — карта клиента со знаком: баланс крупно, имя, код и QR на ней
   же, чтобы друг рядом сразу отсканировал. Одна главная кнопка —
   «Пригласить друга»; история, друзья, правила и ввод чужого кода —
   строками, каждый открывается окном снизу.

   Слова — человеческие (решение заказчика): «две команды друзей» вместо
   «левой и правой ветки», без «уровней» и «плеч».

   Ни процентов, ни ожидаемой выплаты здесь не считается — всё присылает
   сервер (`left_leg`, `right_leg`, `expected_payout`). Вторая копия
   правил в приложении однажды разошлась бы с первой. */

import {
  CONFIG, LoadError, Sheet, Skel, api, call, canPaste, copyText, errorText, fmt, html, pasteText,
  shareText, toast, useLoad, useState,
} from "app/lib";
import { canScan, inviteFromText, scanInvite } from "app/scan";

const points = (n) => fmt.number(n) + " " + fmt.plural(Math.floor(Number(n)), "балл", "балла", "баллов");
const svg = (name, size) => ({ __html: window.App.icon(name, size || 20) });

// Строки журнала баллов словами клиента, а не названиями из базы.
const ENTRY_TITLE = {
  payout: "Начислено за ночь",
  accrual: "Начислено",
  spend: "Оплата замены баллами",
  adjustment: "Исправление",
};

export function Bonus({ user }) {
  const summary = useLoad(() => api.get("/referral/"), [], "referral");
  const s = summary.data;
  const [open, setOpen] = useState(null); // history | friends | how | code | qr

  let body;
  if (summary.error && !s) {
    body = html`<${LoadError} error=${summary.error} onRetry=${summary.reload} />`;
  } else if (!s) {
    body = html`<div class="stack-lg" aria-busy="true">
      <${Skel} h="calc(var(--space-9) * 3)" r="var(--radius-xl)" />
      <${Skel} h="var(--control-lg)" r="var(--radius)" />
      <${Skel} h="var(--space-9)" r="var(--radius-lg)" />
    </div>`;
  } else if (!s.enabled) {
    body = html`<div class="empty-state"><b>Программа приглашений сейчас недоступна</b></div>`;
  } else {
    body = html`<div class="stack-lg">
      <${ClubCard} s=${s} name=${user && user.full_name} onQr=${() => setOpen("qr")} />
      <${NextPayout} s=${s} />
      <${InviteButton} s=${s} />
      <div class="bonus-stats">
        <div><b>${fmt.number(s.invited_count)}</b><span>${fmt.plural(s.invited_count, "друг", "друга", "друзей")}</span></div>
        <div><b>${fmt.number(Math.floor(Number(s.earned_total)))}</b><span>получено</span></div>
        <div><b>${fmt.number(Math.floor(Number(s.spent_total)))}</b><span>потрачено</span></div>
      </div>
      <div class="list">
        <${Row} icon="list" title="История баллов" onClick=${() => setOpen("history")} />
        <${Row} icon="users" title="Мои друзья" side=${s.invited_count ? String(s.invited_count) : ""} onClick=${() => setOpen("friends")} />
        <${Row} icon="info" title="Как начисляются баллы" onClick=${() => setOpen("how")} />
        ${!s.attached && html`<${Row} icon="gift" title="У меня есть код приглашения" onClick=${() => setOpen("code")} />`}
      </div>
    </div>`;
  }

  const close = () => setOpen(null);
  return html`<main class="screen">
    <div class="screen-head">
      <h1>Бонусы</h1>
      <p>Друг меняет масло — вам приходят баллы. Ими оплачивается часть следующей замены.</p>
    </div>
    ${body}
    ${open === "qr" && s && html`<${Sheet} title="QR-код приглашения" onClose=${close}>
      <div class="stack center">
        <${Qr} text=${s.invite_url} big />
        <p class="muted">Дайте другу навести камеру телефона — откроется страница с вашим кодом.</p>
      </div>
    </${Sheet}>`}
    ${open === "history" && html`<${Sheet} tall title="История баллов" onClose=${close}>
      <${Lazy} path="/referral/points/" pick=${(d) => d.results} render=${PointsRows}
        empty="Здесь появятся начисления за ночь и оплата баллами." />
    </${Sheet}>`}
    ${open === "friends" && html`<${Sheet} tall title="Мои друзья" onClose=${close}>
      <${Lazy} path="/referral/invited/" pick=${(d) => d} render=${InvitedRows}
        empty="Вы ещё никого не пригласили. Отправьте код — это одно сообщение." />
    </${Sheet}>`}
    ${open === "how" && s && html`<${Sheet} title="Как начисляются баллы" onClose=${close}>
      <${HowItWorks} s=${s} />
    </${Sheet}>`}
    ${open === "code" && html`<${Sheet} title="Код приглашения" onClose=${close}>
      <${AttachForm} onAttached=${() => { close(); summary.reload(); }} />
    </${Sheet}>`}
  </main>`;
}

function Row({ icon, title, side, onClick }) {
  return html`<button class="list-row" type="button" onClick=${onClick}>
    <span class="strip-ico" dangerouslySetInnerHTML=${svg(icon)}></span>
    <span class="list-body"><b>${title}</b></span>
    ${side && html`<span class="list-side muted">${side}</span>`}
    <span class="chev" dangerouslySetInnerHTML=${svg("right", 18)}></span>
  </button>`;
}

/** Карта клиента: знак, баланс, имя, код (касание — скопировать) и QR. */
function ClubCard({ s, name, onQr }) {
  async function copy() {
    if (await copyText(s.code)) toast("Код " + s.code + " скопирован", "ok");
    else toast("Не получилось скопировать — перепишите код вручную.", "error");
  }
  return html`<section class="club-card" aria-label="Карта клиента">
    <div class="club-top">
      <img class="club-mark" src=${CONFIG.icon} alt="" />
      <span class="club-brand">${CONFIG.company}</span>
    </div>
    <div class="club-balance">
      <span class="club-label">Можно потратить</span>
      <b>${fmt.number(Math.floor(Number(s.balance)))}</b>
      <span class="club-unit">${fmt.plural(Math.floor(Number(s.balance)), "балл", "балла", "баллов")} · 1 балл = 1 ₽</span>
    </div>
    <div class="club-bottom">
      <button class="club-code" type="button" onClick=${copy} aria-label=${"Ваш код " + s.code + ". Скопировать"}>
        <span>${name || "Ваш код"}</span>
        <b>${s.code}</b>
      </button>
      <button class="club-qr" type="button" onClick=${onQr} aria-label="Показать QR-код крупно">
        <${Qr} text=${s.invite_url} />
      </button>
    </div>
  </section>`;
}

function NextPayout({ s }) {
  const payout = Number(s.expected_payout);
  return html`<p class=${"bonus-next" + (payout > 0 ? " is-coming" : "")}>
    ${payout > 0
      ? html`Ночью, в 00:00 ${s.payout_timezone_label}, придёт ещё <b>${points(payout)}</b>`
      : html`Баллами можно оплатить до ${s.max_discount_percent}% чека — скажите мастеру при расчёте.`}
  </p>`;
}

function InviteButton({ s }) {
  async function share() {
    const message = "Меняю масло по записи, без очереди. Заходи по ссылке, код приглашения "
      + s.code + ": " + s.invite_url;
    const result = await shareText(message);
    if (result === "copied") toast("Приглашение скопировано — отправьте его другу", "ok");
    if (result === "failed") toast("Не получилось поделиться — скопируйте код с карты.", "error");
  }
  return html`<button class="btn btn-primary btn-block btn-lg" type="button" onClick=${share}>
    <span class="btn-ico" dangerouslySetInnerHTML=${svg("share", 18)}></span>Пригласить друга</button>`;
}

function Qr({ text, big }) {
  if (!window.qrcode || !text) return null;
  const qr = window.qrcode(0, "M");
  qr.addData(text);
  qr.make();
  // SVG строит библиотека из нашей же ссылки — чужих данных в нём нет.
  const svgTag = qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
  return html`<div class=${"qr" + (big ? " qr-big" : "")} role="img" aria-label="QR-код приглашения"
    dangerouslySetInnerHTML=${{ __html: svgTag }}></div>`;
}

/* ------------------------------------------------------- второй уровень */

function Lazy({ path, pick, render, empty }) {
  const list = useLoad(() => api.get(path).then(pick));
  if (list.error && !list.data) return html`<p class="muted">${errorText(list.error)}</p>`;
  if (!list.data) return html`<div class="stack-sm">${[0, 1, 2].map(() => html`<${Skel} h="var(--control-lg)" r="var(--radius)" />`)}</div>`;
  if (!list.data.length) return html`<p class="muted">${empty}</p>`;
  return html`<div class="list">${render(list.data)}</div>`;
}

function PointsRows(rows) {
  return rows.map((r) => html`<div class="list-row is-static" key=${r.id}>
    <span class="list-body">
      <b>${ENTRY_TITLE[r.kind] || r.kind_display}${r.booking_code ? " · запись " + r.booking_code : ""}</b>
      <span class="muted">${fmt.dateTime(r.created_at)}${r.comment ? " · " + r.comment : ""}</span>
    </span>
    <b class=${"list-side " + (Number(r.amount) > 0 ? "plus" : "minus")}>${Number(r.amount) > 0 ? "+" : ""}${fmt.number(r.amount)}</b>
  </div>`);
}

function InvitedRows(rows) {
  return rows.map((p, i) => html`<div class="list-row is-static" key=${i}>
    <span class="list-body">
      <b>${p.name}</b>
      <span class="muted">${p.phone_masked} · с ${fmt.date(p.joined_at)}</span>
    </span>
    ${Number(p.earned_from) > 0 && html`<b class="list-side plus">+${fmt.number(p.earned_from)}</b>`}
  </div>`);
}

/** Как устроены выплаты — для тех, кто хочет понять цифры. «Две команды
    друзей» — слова заказчика вместо «левой и правой ветки». */
function HowItWorks({ s }) {
  const left = Number(s.left_leg);
  const right = Number(s.right_leg);
  return html`<div class="stack">
    <p class="muted">Ваши друзья и друзья ваших друзей встают в две команды. Баллы с их замен копятся в каждой
      команде отдельно. Каждую ночь в 00:00 ${s.payout_timezone_label} вам начисляется то, что набрала меньшая
      команда, а если команды равны — обе. Остаток ждёт следующей ночи.</p>
    <div class="legs">
      <div class=${"leg" + (left < right ? " weak" : "")}><span class="hint">Первая команда</span><b>${fmt.number(left)}</b></div>
      <div class=${"leg" + (right < left ? " weak" : "")}><span class="hint">Вторая команда</span><b>${fmt.number(right)}</b></div>
    </div>
    <div class="card pad">
      <div class="summary-row"><span>Получено всего</span><span>${points(s.earned_total)}</span></div>
      <div class="summary-row"><span>Потрачено</span><span>${points(s.spent_total)}</span></div>
    </div>
    <p class="hint">Баллами можно оплатить до ${s.max_discount_percent}% чека — скажите мастеру при расчёте.</p>
  </div>`;
}

function AttachForm({ onAttached }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  async function attach(value) {
    const c = (value || code).trim();
    if (!c) return;
    setBusy(true);
    const ok = await call(() => api.post("/referral/attach/", { code: c }));
    setBusy(false);
    if (ok) { toast("Приглашение принято", "ok"); onAttached(); }
  }

  // Отсканировали или вставили — привязываем сразу, без «Применить».
  async function scan() {
    const found = await scanInvite();
    if (found) { setCode(found); attach(found); }
  }

  async function paste() {
    const found = inviteFromText(await pasteText());
    if (found) { setCode(found); attach(found); } else toast("В буфере нет кода приглашения.", "error");
  }
  return html`<div class="stack">
    <p class="muted">Если вас пригласил знакомый — введите его код. Принять приглашение можно один раз.</p>
    <div class="field">
      <label for="attach-code">Код приглашения</label>
      <input id="attach-code" class="code-field" autocapitalize="characters" placeholder="Например, QWW6SK" value=${code}
        onInput=${(e) => setCode(e.target.value.toUpperCase())} />
    </div>
    <button class="btn btn-primary btn-block" type="button" disabled=${busy || !code.trim()} onClick=${() => attach()}>Принять приглашение</button>
    <div class="form-pair">
      ${canPaste() && html`<button class="btn" type="button" disabled=${busy} onClick=${paste}>Вставить код</button>`}
      ${canScan() && html`<button class="btn" type="button" disabled=${busy} onClick=${scan}>Сканировать QR</button>`}
    </div>
  </div>`;
}

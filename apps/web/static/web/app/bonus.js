/* Бонусы: сколько можно потратить, что придёт ночью, пригласить друга.

   Макет «одна цифра»: наверху крупно — баланс, одной строкой — ближайшая
   выплата, одна главная кнопка. Всё остальное (история, приглашённые, как
   устроены выплаты, ввод чужого кода) — свёрнуто вторым уровнем: экран
   открывают, чтобы узнать «сколько у меня» и отправить приглашение.

   Ни процентов, ни ожидаемой выплаты здесь не считается — всё присылает
   сервер (`left_leg`, `right_leg`, `expected_payout`). Вторая копия
   правил в приложении однажды разошлась бы с первой. */

import {
  LoadError, api, call, canPaste, copyText, errorText, fmt, html, pasteText, shareText, toast, useLoad,
  useState,
} from "app/lib";
import { canScan, inviteFromText, scanInvite } from "app/scan";

const points = (n) => fmt.number(n) + " " + fmt.plural(Math.floor(Number(n)), "балл", "балла", "баллов");

export function Bonus() {
  const summary = useLoad(() => api.get("/referral/"));
  const s = summary.data;

  let body;
  if (summary.error && !s) {
    body = html`<${LoadError} error=${summary.error} onRetry=${summary.reload} />`;
  } else if (!s) {
    body = html`<p class="muted center">Загружаем…</p>`;
  } else if (!s.enabled) {
    body = html`<div class="empty-state"><b>Программа приглашений сейчас недоступна</b></div>`;
  } else {
    body = html`<div class="stack-lg">
      <${Balance} s=${s} />
      <${Invite} s=${s} />
      <${More} s=${s} onAttached=${summary.reload} />
    </div>`;
  }

  return html`<main class="screen">
    <div class="screen-head">
      <h1>Бонусы</h1>
      <p>Друг меняет масло — вам приходят баллы. Ими оплачивается следующая замена.</p>
    </div>
    ${body}
  </main>`;
}

/** Главное: сколько можно потратить и что придёт ближайшей ночью. */
function Balance({ s }) {
  const payout = Number(s.expected_payout);
  return html`<section class="card pad">
    <span class="kicker">Можно потратить</span>
    <div class="big-number">${points(Math.floor(Number(s.balance)))}</div>
    <p class="muted">1 балл = 1 ₽. Баллами можно оплатить до ${s.max_discount_percent}% чека —
      скажите мастеру при расчёте.</p>
    <p class=${"bonus-next" + (payout > 0 ? " is-coming" : "")}>
      ${payout > 0
        ? html`В 00:00 ${s.payout_timezone_label} придёт ещё <b>${points(payout)}</b>`
        : "Пока новых выплат нет — баллы от друзей копятся."}
    </p>
  </section>`;
}

/** Одна главная кнопка и два быстрых действия рядом: код и QR. */
function Invite({ s }) {
  const [qr, setQr] = useState(false);

  async function share() {
    const message = "Меняю масло по записи, без очереди. Заходи по ссылке, код приглашения "
      + s.code + ": " + s.invite_url;
    const result = await shareText(message);
    if (result === "copied") toast("Приглашение скопировано — отправьте его другу", "ok");
    if (result === "failed") toast("Не получилось поделиться — скопируйте код.", "error");
  }

  async function copy() {
    if (await copyText(s.code)) toast("Код " + s.code + " скопирован", "ok");
    else toast("Не получилось скопировать — выделите код вручную.", "error");
  }

  return html`<div class="stack">
    <button class="btn btn-primary btn-block btn-lg" type="button" onClick=${share}>Пригласить друга</button>
    <div class="row" style="flex-wrap:nowrap">
      <button class="btn" style="flex:1" type="button" onClick=${copy} aria-label=${"Скопировать код " + s.code}>
        Код <span class="mono">${s.code}</span>
      </button>
      <button class="btn" style="flex:1" type="button" aria-expanded=${String(qr)} onClick=${() => setQr(!qr)}>
        ${qr ? "Скрыть QR-код" : "Показать QR-код"}
      </button>
    </div>
    ${qr && html`<section class="card pad center">
      <${Qr} text=${s.invite_url} />
      <p class="hint">Дайте другу отсканировать камерой телефона</p>
    </section>`}
  </div>`;
}

function Qr({ text }) {
  if (!window.qrcode || !text) return null;
  const qr = window.qrcode(0, "M");
  qr.addData(text);
  qr.make();
  // SVG строит библиотека из нашей же ссылки — чужих данных в нём нет.
  const svg = qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
  return html`<div class="qr" role="img" aria-label="QR-код приглашения" dangerouslySetInnerHTML=${{ __html: svg }}></div>`;
}

/* ------------------------------------------------------- второй уровень */

/** Свёрнутые разделы. Списки грузятся, когда раздел впервые открыли. */
function More({ s, onAttached }) {
  return html`<div class="card disclosures">
    <${Section} title="История баллов">
      <${Lazy} path="/referral/points/" pick=${(d) => d.results} render=${PointsRows}
        empty="Здесь появятся ночные выплаты и оплата баллами." />
    </${Section}>
    <${Section} title=${"Приглашённые" + (s.invited_count ? " · " + s.invited_count : "")}>
      <${Lazy} path="/referral/invited/" pick=${(d) => d} render=${InvitedRows}
        empty="Вы ещё никого не пригласили. Отправьте код — это одно сообщение." />
    </${Section}>
    <${Section} title="Как начисляются баллы">
      <${HowItWorks} s=${s} />
    </${Section}>
    ${!s.attached && html`<${Section} title="У меня есть код приглашения">
      <${AttachForm} onAttached=${onAttached} />
    </${Section}>`}
  </div>`;
}

function Section({ title, children }) {
  const [open, setOpen] = useState(false);
  return html`<details class="disclosure" onToggle=${(e) => setOpen(e.currentTarget.open)}>
    <summary>${title}</summary>
    <div class="disclosure-body">${open && children}</div>
  </details>`;
}

function Lazy({ path, pick, render, empty }) {
  const list = useLoad(() => api.get(path).then(pick));
  if (list.error && !list.data) return html`<p class="muted">${errorText(list.error)}</p>`;
  if (!list.data) return html`<p class="muted">Загружаем…</p>`;
  if (!list.data.length) return html`<p class="muted">${empty}</p>`;
  return render(list.data);
}

function PointsRows(rows) {
  return rows.map((r) => html`<div class="history-row" key=${r.id}>
    <div>
      <div>${r.kind_display}${r.booking_code ? " · запись " + r.booking_code : ""}</div>
      <div class="hint">${fmt.dateTime(r.created_at)}${r.comment ? " · " + r.comment : ""}</div>
    </div>
    <span class=${Number(r.amount) > 0 ? "plus" : "minus"}>${Number(r.amount) > 0 ? "+" : ""}${fmt.number(r.amount)}</span>
  </div>`);
}

function InvitedRows(rows) {
  return rows.map((p, i) => html`<div class="history-row" key=${i}>
    <div>
      <div>${p.name}</div>
      <div class="hint">${p.phone_masked} · уровень ${p.line} · с ${fmt.date(p.joined_at)}</div>
    </div>
    <span class="plus">${Number(p.earned_from) > 0 ? "+" + fmt.number(p.earned_from) : ""}</span>
  </div>`);
}

/** Как устроены выплаты — для тех, кто хочет понять цифры. */
function HowItWorks({ s }) {
  const left = Number(s.left_leg);
  const right = Number(s.right_leg);
  return html`<div class="stack-sm">
    <p class="muted">Баллы от покупок друзей копятся в двух ветках — левой и правой.
      Каждую ночь в 00:00 ${s.payout_timezone_label} выплачивается меньшая ветка, а если
      ветки равны — обе. Остаток ждёт следующей ночи.</p>
    <div class="legs">
      <div class=${"leg" + (left < right ? " weak" : "")}><span class="hint">Левая ветка</span><b>${fmt.number(left)}</b></div>
      <div class=${"leg" + (right < left ? " weak" : "")}><span class="hint">Правая ветка</span><b>${fmt.number(right)}</b></div>
    </div>
    <div class="summary-row"><span>Получено всего</span><span>${points(s.earned_total)}</span></div>
    <div class="summary-row"><span>Потрачено</span><span>${points(s.spent_total)}</span></div>
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
    <div class="row" style="flex-wrap:nowrap">
      <input style="flex:1" autocapitalize="characters" placeholder="Введите код" value=${code}
        onInput=${(e) => setCode(e.target.value.toUpperCase())} aria-label="Код приглашения" />
      <button class="btn btn-primary" type="button" disabled=${busy || !code.trim()} onClick=${() => attach()}>Применить</button>
    </div>
    <div class="row" style="flex-wrap:nowrap">
      ${canPaste() && html`<button class="btn" style="flex:1" type="button" disabled=${busy} onClick=${paste}>Вставить код</button>`}
      ${canScan() && html`<button class="btn" style="flex:1" type="button" disabled=${busy} onClick=${scan}>Сканировать QR</button>`}
    </div>
  </div>`;
}

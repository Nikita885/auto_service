/* Бонусы: баланс, плечи до ночной выплаты, код приглашения, история.

   Ни процентов, ни ожидаемой выплаты здесь не считается — всё присылает
   сервер (`left_leg`, `right_leg`, `expected_payout`). Вторая копия
   правил в приложении однажды разошлась бы с первой. */

import {
  LoadError, api, call, errorText, fmt, html, money, toast, useEffect, useLoad, useState,
} from "app/lib";

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
      <${InviteCard} s=${s} />
      ${!s.attached && html`<${AttachCard} onAttached=${summary.reload} />`}
      <${History} />
    </div>`;
  }

  return html`<main class="screen">
    <div class="screen-head">
      <h1>Приглашайте друзей</h1>
      <p>Друг меняет масло — вам приходят баллы. Ими оплачивается следующая замена.</p>
    </div>
    ${body}
  </main>`;
}

function Balance({ s }) {
  const left = Number(s.left_leg);
  const right = Number(s.right_leg);
  const payout = Number(s.expected_payout);
  // Слабое плечо подсвечиваем: клиенту сразу видно, какое отстаёт.
  const weak = left === right ? null : left < right ? "left" : "right";
  return html`<section class="card pad">
    <span class="kicker">Баллов на счету</span>
    <div class="big-number">${fmt.number(Math.floor(Number(s.balance)))}</div>
    <p class="muted">Баллами можно закрыть до ${s.max_discount_percent}% чека. 1 балл = 1 ₽.</p>

    <div class="legs">
      <div class=${"leg" + (weak === "left" ? " weak" : "")}>
        <span class="kicker">Левое плечо</span><b>${fmt.number(left)}</b>
      </div>
      <div class=${"leg" + (weak === "right" ? " weak" : "")}>
        <span class="kicker">Правое плечо</span><b>${fmt.number(right)}</b>
      </div>
    </div>
    <p class="payout-line">
      ${payout > 0
        ? html`В 00:00 ${s.payout_timezone_label} придёт <b>${fmt.number(payout)} баллов</b>`
        : "Выплата будет, когда баллы появятся в обоих плечах. Пока они копятся."}
    </p>
    <p class="hint" style="margin-top:6px">Каждую ночь выплачивается меньшее плечо, а если плечи равны — оба. Остаток переносится.</p>

    <div class="row" style="justify-content:space-between;margin-top:12px">
      <span class="muted">Получено ${money(s.earned_total)}</span>
      <span class="muted">Потрачено ${money(s.spent_total)}</span>
    </div>
  </section>`;
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

function InviteCard({ s }) {
  async function share() {
    const message = "Меняю масло по записи, без очереди. Заходи по ссылке, код приглашения "
      + s.code + ": " + s.invite_url;
    // На iPhone — системное меню «Поделиться»; где его нет, копируем текст.
    if (navigator.share) {
      try { await navigator.share({ title: "Приглашение", text: message }); } catch (e) { /* закрыли меню */ }
      return;
    }
    copy(message);
  }

  async function copy(value) {
    try {
      await navigator.clipboard.writeText(value || s.code);
      toast(value ? "Приглашение скопировано" : "Код скопирован", "ok");
    } catch (e) {
      toast("Не получилось скопировать — выделите код вручную.", "error");
    }
  }

  return html`<section class="card pad center">
    <span class="kicker">Ваш код приглашения</span>
    <div class="invite-code" style="margin-top:6px">${s.code}</div>
    <${Qr} text=${s.invite_url} />
    <p class="hint">Дайте отсканировать этот код</p>
    <div class="row" style="margin-top:12px;flex-wrap:nowrap">
      <button class="btn btn-primary" style="flex:1" type="button" onClick=${share}>Поделиться</button>
      <button class="btn" style="flex:1" type="button" onClick=${() => copy()}>Скопировать код</button>
    </div>
    <p class="muted" style="margin-top:12px">Вы пригласили: ${s.invited_count} · В вашей структуре: ${(s.line_counts || []).reduce((a, b) => a + b, 0)}</p>
  </section>`;
}

function AttachCard({ onAttached }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  async function attach() {
    if (!code.trim()) return;
    setBusy(true);
    const ok = await call(() => api.post("/referral/attach/", { code: code.trim() }));
    setBusy(false);
    if (ok) { toast("Приглашение принято", "ok"); onAttached(); }
  }
  return html`<section class="card pad stack">
    <b>У меня есть код приглашения</b>
    <div class="row" style="flex-wrap:nowrap">
      <input style="flex:1" autocapitalize="characters" placeholder="Введите код" value=${code}
        onInput=${(e) => setCode(e.target.value.toUpperCase())} aria-label="Код приглашения" />
      <button class="btn btn-primary" type="button" disabled=${busy || !code.trim()} onClick=${attach}>Применить</button>
    </div>
  </section>`;
}

function History() {
  const [tab, setTab] = useState("points");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setRows(null);
    setError(null);
    const path = tab === "points" ? "/referral/points/" : "/referral/invited/";
    api.get(path)
      .then((data) => setRows(tab === "points" ? data.results : data))
      .catch((err) => setError(err));
  }, [tab]);

  return html`<section class="card pad">
    <div class="seg" role="tablist">
      <button type="button" aria-pressed=${String(tab === "points")} onClick=${() => setTab("points")}>История баллов</button>
      <button type="button" aria-pressed=${String(tab === "invited")} onClick=${() => setTab("invited")}>Приглашённые</button>
    </div>
    ${error ? html`<p class="muted">${errorText(error)}</p>`
      : rows === null ? html`<p class="muted">Загружаем…</p>`
      : !rows.length ? html`<p class="muted">${tab === "points"
        ? "Здесь появятся ночные выплаты и списания баллов."
        : "Вы ещё никого не пригласили. Отправьте код — это одно сообщение."}</p>`
      : tab === "points"
        ? rows.map((r) => html`<div class="history-row" key=${r.id}>
            <div>
              <div>${r.kind_display}${r.booking_code ? " · запись " + r.booking_code : ""}</div>
              <div class="hint">${fmt.dateTime(r.created_at)}${r.comment ? " · " + r.comment : ""}</div>
            </div>
            <span class=${Number(r.amount) > 0 ? "plus" : "minus"}>${Number(r.amount) > 0 ? "+" : ""}${fmt.number(r.amount)}</span>
          </div>`)
        : rows.map((p, i) => html`<div class="history-row" key=${i}>
            <div>
              <div>${p.name}</div>
              <div class="hint">${p.phone_masked} · ${p.line}-я линия · с ${fmt.date(p.joined_at)}</div>
            </div>
            <span class="plus">${Number(p.earned_from) > 0 ? "+" + fmt.number(p.earned_from) : ""}</span>
          </div>`)}
  </section>`;
}

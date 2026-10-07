/* Мастер записи: адрес → масло → время → машина и подтверждение.

   Открывается окном поверх вкладки «Записи» (`BookingWizard` в `Sheet`).
   Черновик живёт на сервере, поэтому закрыть окно или уйти на другую
   вкладку можно в любой момент: вкладка покажет «Продолжить запись», и
   мастер откроется на том же шаге с тем же таймером.

   Шаги ведёт сервер: черновик сообщает `next_action`, и окно рисует ровно
   его. Своего конечного автомата здесь нет — вторая копия правил однажды
   разошлась бы с первой. Таймер тоже серверный: `seconds_left` при каждом
   ответе, локально только тикаем до следующего. */

import { CarPicker, carLabel } from "app/cars";
import {
  CONFIG, api, ask, call, errorText, fmt, html, toast, useEffect, useRef, useState, visitTime,
} from "app/lib";

const GONE = ["draft_expired", "draft_closed"];

/** Весь сценарий записи. `onClose` — закрыть окно (черновик остаётся),
    `onBooked(booking)` — запись создана. */
export function BookingWizard({ onClose, onBooked }) {
  const [draft, setDraft] = useState(undefined); // undefined — грузим, null — не вышло начать
  const [created, setCreated] = useState(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);

  /** Открыли окно — продолжаем живой черновик или начинаем новый. */
  async function begin(restart) {
    setBusy(true);
    try {
      setDraft(await api.post("/bookings/drafts/", { restart: Boolean(restart) }));
      setExpired(false);
      setCreated(null);
    } catch (err) {
      setDraft(null);
      toast(errorText(err), "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { begin(false); }, []);

  async function reload() {
    try {
      const current = await api.get("/bookings/drafts/current/");
      if (current) setDraft(current);
      else setExpired(true);
    } catch (err) {
      toast(errorText(err), "error");
    }
  }

  /** Любой шаг: отправить, принять новое состояние, пережить «время вышло». */
  async function step(path, body) {
    if (busy) return undefined;
    setBusy(true);
    try {
      const next = await api.post("/bookings/drafts/" + draft.id + "/" + path + "/", body || {});
      setDraft(next);
      return next;
    } catch (err) {
      if (GONE.includes(err.code)) {
        setExpired(true);
      } else {
        toast(errorText(err), "error");
        // Слот заняли или масло разобрали — черновик жив, перечитываем его.
        if (err.code === "slot_taken" || err.code === "oil_out_of_stock") reload();
      }
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function confirm(comment, carId) {
    if (busy) return;
    setBusy(true);
    try {
      const booking = await api.post("/bookings/drafts/" + draft.id + "/confirm/", {
        comment, car_id: carId || null,
      });
      setCreated(booking);
      onBooked(booking);
    } catch (err) {
      if (GONE.includes(err.code)) setExpired(true);
      else {
        toast(errorText(err), "error");
        // Машину удалили на другом устройстве — черновик жив, выбор
        // перечитается; остальное (слот, масло) — перечитываем черновик.
        if (err.code !== "car_not_found") reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function drop() {
    const yes = await ask({
      title: "Прервать запись?",
      text: "Выбранное время сразу освободится.",
      confirmLabel: "Прервать", danger: true,
    });
    if (!yes) return;
    await call(() => api.post("/bookings/drafts/" + draft.id + "/cancel/", {}));
    onClose();
  }

  if (created) return html`<${Created} booking=${created} onDone=${onClose} />`;
  if (expired) {
    return html`<div class="card pad center stack">
      <b>Пять минут вышли</b>
      <p class="muted">Запись не сохранилась, выбранное время освободилось. Начните заново — это быстро.</p>
      <button class="btn btn-primary btn-block" type="button" disabled=${busy} onClick=${() => begin(true)}>Начать заново</button>
    </div>`;
  }
  if (draft === undefined) return html`<p class="muted center">Загружаем…</p>`;
  if (draft === null) {
    return html`<div class="card pad center stack">
      <b>Не получилось начать запись</b>
      <p class="muted">Попробуйте ещё раз или запишитесь по телефону ${CONFIG.phone}.</p>
      <button class="btn btn-primary btn-block" type="button" disabled=${busy} onClick=${() => begin(false)}>Повторить</button>
    </div>`;
  }
  return html`<${Wizard} draft=${draft} busy=${busy} step=${step} confirm=${confirm}
    onExpire=${() => setExpired(true)} onDrop=${drop} onRestart=${() => begin(true)} />`;
}

/* ---------------------------------------------------------------- шаги */

function Wizard({ draft, busy, step, confirm, onExpire, onDrop, onRestart }) {
  const done = draft.progress ? draft.progress.completed : 0;
  const total = draft.progress ? draft.progress.total : 4;
  const titles = {
    select_point: "Шаг 1 из 4 · Адрес",
    select_oil: "Шаг 2 из 4 · Масло",
    select_slot: "Шаг 3 из 4 · Время",
    confirm: "Шаг 4 из 4 · Подтверждение",
  };

  let content;
  if (draft.next_action === "select_point") content = html`<${PointStep} busy=${busy} step=${step} />`;
  else if (draft.next_action === "select_oil") content = html`<${OilStep} draft=${draft} busy=${busy} step=${step} />`;
  else if (draft.next_action === "select_slot") {
    const point = draft.service_point;
    content = html`<${SlotPicker} pointId=${point.id} zone=${point.timezone} pointName=${point.name}
      busy=${busy} actionLabel="Дальше" onPick=${(startAt) => step("select-slot", { start_at: startAt })} />`;
  } else content = html`<${ConfirmStep} draft=${draft} busy=${busy} confirm=${confirm} />`;

  return html`<div>
    <div class="row" style="justify-content:space-between">
      <span class="kicker">${titles[draft.next_action] || ""}</span>
      <${Timer} seconds=${draft.seconds_left} stamp=${draft.id + draft.step} onExpire=${onExpire} />
    </div>
    <div class="progress" aria-hidden="true">
      ${Array.from({ length: total }, (_, i) => html`<span class=${i < done ? "done" : ""}></span>`)}
    </div>
    ${content}
    <div class="row" style="margin-top:16px">
      <button class="btn btn-ghost" type="button" onClick=${onDrop}>Прервать</button>
      <span class="spacer"></span>
      <button class="btn btn-ghost" type="button" onClick=${onRestart}>Начать заново</button>
    </div>
  </div>`;
}

export function Timer({ seconds, stamp, onExpire }) {
  const deadline = useRef(Date.now() + seconds * 1000);
  const [left, setLeft] = useState(seconds);

  // Сервер присылает остаток на каждом шаге — сверяем часы по нему.
  useEffect(() => {
    deadline.current = Date.now() + seconds * 1000;
    setLeft(seconds);
  }, [stamp, seconds]);

  useEffect(() => {
    const t = setInterval(() => {
      const s = Math.max(0, Math.round((deadline.current - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) { clearInterval(t); if (onExpire) onExpire(); }
    }, 1000);
    return () => clearInterval(t);
  }, [stamp]);

  return html`<span class=${"timer" + (left <= 60 ? " low" : "")} title="До конца записи">${fmt.clock(left)}</span>`;
}

function PointStep({ busy, step }) {
  const [points, setPoints] = useState(null);
  useEffect(() => { call(() => api.get("/service-points/")).then((p) => setPoints(p || [])); }, []);
  if (!points) return html`<p class="muted">Загружаем адреса…</p>`;
  if (!points.length) return html`<p class="muted">Адресов пока нет. Запишитесь по телефону ${CONFIG.phone}.</p>`;
  return html`<div class="stack-sm">
    ${points.map((p) => html`<button class="choice" type="button" key=${p.id} disabled=${busy}
      onClick=${() => step("select-point", { service_point_id: p.id })}>
      <span class="choice-body">
        <span class="choice-title">${p.name}</span>
        <span class="choice-meta">${p.address} · ${p.opens_at.slice(0, 5)}–${p.closes_at.slice(0, 5)}</span>
      </span>
    </button>`)}
  </div>`;
}

function OilStep({ draft, busy, step }) {
  const [oils, setOils] = useState(null);
  useEffect(() => {
    call(() => api.get("/service-points/" + draft.service_point.id + "/oils/")).then((o) => setOils(o || []));
  }, [draft.service_point.id]);
  if (!oils) return html`<p class="muted">Смотрим, что есть в наличии…</p>`;
  if (!oils.length) {
    return html`<p class="muted">На этом адресе сейчас нет масла в наличии. Начните заново и выберите другой адрес.</p>`;
  }
  return html`<div class="stack-sm">
    ${oils.map((oil) => html`<button class="choice" type="button" key=${oil.id} disabled=${busy}
      onClick=${() => step("select-oil", { oil_id: oil.id })}>
      <span class="choice-body">
        <span class="choice-title">${oil.brand} ${oil.name}</span>
        <span class="choice-meta">${oil.viscosity} · ${oil.oil_type_display} · ${oil.volume_liters} л
          ${oil.available_quantity <= 2 ? " · осталось " + oil.available_quantity : ""}</span>
      </span>
    </button>`)}
    <p class="hint">Не знаете, какое нужно? Позвоните — подберём по марке и году: ${CONFIG.phone}.</p>
  </div>`;
}

const DOW = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

/** Свободное время точки: дни лентой, время сеткой, кнопка с выбором.

    Общий для шага записи и для переноса — у них одна и та же точка, одна
    и та же сетка и одно правило свободного поста. */
export function SlotPicker({ pointId, zone, pointName, busy, actionLabel, onPick }) {
  const [days, setDays] = useState(null);
  const [day, setDay] = useState(null);
  const [slots, setSlots] = useState(null);
  const [picked, setPicked] = useState(null);

  useEffect(() => {
    call(() => api.get("/service-points/" + pointId + "/slots/")).then((data) => {
      const list = (data && data.available_days) || [];
      setDays(list);
      if (list.length) setDay(list[0]);
    });
  }, [pointId]);

  useEffect(() => {
    if (!day) return;
    setSlots(null);
    setPicked(null);
    call(() => api.get("/service-points/" + pointId + "/slots/?date=" + day)).then((data) => {
      setSlots((data && data.slots) || []);
    });
  }, [day]);

  if (!days) return html`<p class="muted">Ищем свободное время…</p>`;
  if (!days.length) return html`<p class="muted">Свободного времени в ближайшие дни нет. Позвоните нам: ${CONFIG.phone}.</p>`;

  return html`<div class="stack">
    <div class="days" role="listbox" aria-label="День">
      ${days.map((d) => {
        const date = new Date(d + "T12:00:00");
        return html`<button class="day" type="button" key=${d} aria-pressed=${String(d === day)} onClick=${() => setDay(d)}>
          <small>${DOW[date.getDay()]}</small><b>${date.getDate()}</b>
        </button>`;
      })}
    </div>
    ${slots === null ? html`<p class="muted">Загружаем время…</p>` : slots.length === 0
      ? html`<p class="muted">На этот день всё занято — выберите другой.</p>`
      : html`<div class="slots">
          ${slots.map((s) => html`<button class="slot-btn" type="button" key=${s.start_at}
            aria-pressed=${String(picked === s.start_at)} onClick=${() => setPicked(s.start_at)}>${s.local_time}</button>`)}
        </div>`}
    <p class="hint">Время указано по адресу: ${pointName}.</p>
    <div class="sticky-actions">
      <button class="btn btn-primary" type="button" disabled=${!picked || busy}
        onClick=${() => onPick(picked)}>
        ${picked ? actionLabel + " · " + visitTime(picked, zone) : "Выберите время"}
      </button>
    </div>
  </div>`;
}

function ConfirmStep({ draft, busy, confirm }) {
  const [comment, setComment] = useState("");
  const [carId, setCarId] = useState(null);
  const oil = draft.oil;
  const point = draft.service_point;
  return html`<div class="stack">
    <div class="card pad">
      <div class="summary-row"><span>Адрес</span><span>${point.name}<br /><small class="muted">${point.address}</small></span></div>
      <div class="summary-row"><span>Когда</span><span>${visitTime(draft.slot_start, point.timezone)}</span></div>
      <div class="summary-row"><span>Масло</span><span>${oil.title}</span></div>
    </div>
    <div class="stack-sm">
      <span class="kicker">Автомобиль</span>
      <${CarPicker} value=${carId} onChange=${setCarId} />
    </div>
    <div class="field">
      <label for="comment">Комментарий мастеру (необязательно)</label>
      <textarea id="comment" rows="2" maxlength="500" placeholder="Например: приеду на 5 минут раньше"
        value=${comment} onInput=${(e) => setComment(e.target.value)}></textarea>
    </div>
    <p class="hint">Баллами можно оплатить до ${CONFIG.maxDiscount}% чека — скажите мастеру при расчёте.</p>
    <div class="sticky-actions">
      <button class="btn btn-primary" type="button" disabled=${busy} onClick=${() => confirm(comment, carId)}>
        ${busy ? "Записываем…" : "Записаться"}
      </button>
    </div>
  </div>`;
}

function Created({ booking, onDone }) {
  return html`<div class="card pad stack center">
    <span class="kicker">Вы записаны</span>
    <div class="invite-code">${booking.code}</div>
    <p class="muted">Код записи назовёте на посту.</p>
    <div style="text-align:left">
      <div class="summary-row"><span>Когда</span><span>${visitTime(booking.start_at, booking.service_point.timezone)}</span></div>
      <div class="summary-row"><span>Адрес</span><span>${booking.service_point.address}</span></div>
      <div class="summary-row"><span>Масло</span><span>${booking.oil_title}</span></div>
      ${booking.car && html`<div class="summary-row"><span>Автомобиль</span><span>${carLabel(booking.car)}</span></div>`}
    </div>
    <button class="btn btn-primary btn-block" type="button" onClick=${onDone}>Готово</button>
  </div>`;
}

/* Мастер записи: адрес → масло → время → машина и подтверждение.

   Открывается окном снизу на «Главной» (`BookingWizard` в `Sheet`).
   Черновик живёт на сервере, поэтому окно можно закрыть в любой момент:
   «Главная» покажет «Продолжить запись», и мастер откроется на том же
   шаге с тем же таймером.

   Шаги — те же четыре, по порядку (выбор заказчика), но сверху видно, что
   уже выбрано, и на любой пройденный шаг можно вернуться касанием: сервер
   это разрешает и сам сбрасывает то, что зависит от изменённого (другой
   адрес — заново масло и время). Вперёд — только по порядку: какой шаг
   следующий, говорит сервер (`next_action`); своего конечного автомата
   здесь нет — вторая копия правил однажды разошлась бы с первой. Таймер
   тоже серверный: `seconds_left` при каждом ответе, локально только
   тикаем до следующего. */

import { CarPicker, carLabel } from "app/cars";
import {
  CONFIG, InfoRow, Skel, api, ask, call, errorText, fmt, html, toast, useEffect, useRef, useState,
  visitTime,
} from "app/lib";

const GONE = ["draft_expired", "draft_closed"];

// Обещание клиенту — слово в слово решение заказчика (октябрь 2026):
// мастер точки перезванивает в течение 30 минут в рабочее время, заявки
// вне рабочих часов — утром.
export const CALLBACK_TEXT = "Мастер позвонит и поможет выбрать: в рабочее время — в течение 30 минут, "
  + "вне рабочих часов — утром";

/** Шаги по порядку: ключ вида, действие сервера и подпись чипа. */
const STEPS = [
  ["point", "select_point", "Адрес"],
  ["oil", "select_oil", "Масло"],
  ["slot", "select_slot", "Время"],
  ["confirm", "confirm", "Машина"],
];
const viewOf = (action) => (STEPS.find((s) => s[1] === action) || STEPS[0])[0];
const indexOf = (view) => STEPS.findIndex((s) => s[0] === view);

/** Весь сценарий записи. `onClose` — закрыть окно (черновик остаётся),
    `onBooked(booking)` — запись создана. */
export function BookingWizard({ onClose, onBooked }) {
  const [draft, setDraft] = useState(undefined); // undefined — грузим, null — не вышло начать
  const [view, setView] = useState(null);
  const [created, setCreated] = useState(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);

  function accept(next) {
    setDraft(next);
    setView(viewOf(next.next_action));
  }

  /** Открыли окно — продолжаем живой черновик или начинаем новый. */
  async function begin(restart) {
    setBusy(true);
    try {
      accept(await api.post("/bookings/drafts/", { restart: Boolean(restart) }));
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
      if (current) accept(current);
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
      accept(next);
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
      confirmLabel: "Прервать", cancelLabel: "Продолжить запись", danger: true,
    });
    if (!yes) return;
    await call(() => api.post("/bookings/drafts/" + draft.id + "/cancel/", {}));
    onClose();
  }

  if (created) return html`<${Created} booking=${created} onDone=${onClose} />`;
  if (expired) {
    return html`<div class="empty-state">
      <span class="empty-ico" dangerouslySetInnerHTML=${{ __html: window.App.icon("clock", 24) }}></span>
      <b>Пять минут вышли</b>
      <p>Выбранное время освободилось. Начните заново — это быстро.</p>
      <button class="btn btn-primary btn-lg" type="button" disabled=${busy} onClick=${() => begin(true)}>Начать заново</button>
    </div>`;
  }
  if (draft === undefined) return html`<${WizardSkeleton} />`;
  if (draft === null) {
    return html`<div class="empty-state">
      <b>Не получилось начать запись</b>
      <p>Попробуйте ещё раз или запишитесь по телефону ${CONFIG.phone}.</p>
      <button class="btn btn-primary" type="button" disabled=${busy} onClick=${() => begin(false)}>Повторить</button>
    </div>`;
  }

  const point = draft.service_point;
  let content;
  if (view === "point") content = html`<${PointStep} draft=${draft} busy=${busy} step=${step} />`;
  else if (view === "oil") content = html`<${OilStep} draft=${draft} busy=${busy} step=${step} />`;
  else if (view === "slot") {
    content = html`<${SlotPicker} pointId=${point.id} zone=${point.timezone} pointName=${point.name}
      initial=${draft.slot_start} busy=${busy} actionLabel="Дальше"
      onPick=${(startAt) => step("select-slot", { start_at: startAt })} />`;
  } else content = html`<${ConfirmStep} draft=${draft} busy=${busy} confirm=${confirm} />`;

  return html`<div class="wizard">
    <${StepChips} draft=${draft} view=${view} onPick=${setView} onExpire=${() => setExpired(true)} />
    ${content}
    <button class="link-btn wizard-drop" type="button" onClick=${drop}>Прервать запись</button>
  </div>`;
}

function WizardSkeleton() {
  return html`<div class="stack" aria-busy="true">
    <div class="row"><${Skel} w="60%" h="var(--control-sm)" r="var(--radius-pill)" /><span class="spacer"></span><${Skel} w="var(--control-lg)" h="var(--control-sm)" r="var(--radius-pill)" /></div>
    <${Skel} w="40%" h="var(--fs-h3)" />
    <${Skel} h="var(--control-lg)" r="var(--radius)" />
    <${Skel} h="var(--control-lg)" r="var(--radius)" />
  </div>`;
}

/** Шаги чипами: пройденный показывает выбранное и открывается касанием,
    текущий подсвечен, будущие недоступны. Справа — таймер. */
function StepChips({ draft, view, onPick, onExpire }) {
  const reached = indexOf(viewOf(draft.next_action));
  const value = {
    point: draft.service_point && draft.service_point.name,
    oil: draft.oil_on_site ? "Подберём на месте" : draft.oil && draft.oil.brand,
    slot: draft.slot_start && visitTime(draft.slot_start, draft.service_point.timezone),
    confirm: null,
  };
  const at = indexOf(view);
  return html`<div class="wizard-top">
    <div class="wizard-head">
      <span class="kicker">Шаг ${at + 1} из ${STEPS.length}</span>
      <${Timer} seconds=${draft.seconds_left} stamp=${draft.id + draft.step} onExpire=${onExpire} />
    </div>
    <nav class="step-chips" aria-label="Шаги записи">
      ${STEPS.map(([key, , label], i) => {
        const current = key === view;
        const done = i < reached || (i <= reached && value[key]);
        return html`<button type="button" key=${key} class=${"step-chip" + (current ? " is-current" : "") + (done ? " is-done" : "")}
          disabled=${i > reached} aria-current=${current ? "step" : null}
          aria-label=${label + (done && value[key] ? ": " + value[key] : "")} onClick=${() => onPick(key)}>
          <small>${label}</small>
          <span>${(done && value[key]) || (current ? "выбираем" : "—")}</span>
        </button>`;
      })}
    </nav>
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

  return html`<span class=${"timer" + (left <= 60 ? " low" : "")} role="timer"
    aria-label=${"На запись осталось " + fmt.clock(left)}>${fmt.clock(left)}</span>`;
}

function Choice({ selected, disabled, onClick, title, meta, side }) {
  return html`<button class="choice" type="button" aria-pressed=${String(Boolean(selected))} disabled=${disabled} onClick=${onClick}>
    <span class="choice-body">
      <span class="choice-title">${title}</span>
      ${meta && html`<span class="choice-meta">${meta}</span>`}
    </span>
    ${side}
    <span class="choice-mark" aria-hidden="true" dangerouslySetInnerHTML=${{ __html: window.App.icon("check", 16) }}></span>
  </button>`;
}

const hours = (p) => p.opens_at.slice(0, 5) + "–" + p.closes_at.slice(0, 5);

function PointStep({ draft, busy, step }) {
  const [points, setPoints] = useState(null);
  useEffect(() => { call(() => api.get("/service-points/")).then((p) => setPoints(p || [])); }, []);
  const chosen = draft.service_point && draft.service_point.id;
  return html`<section class="stack">
    <h3 class="step-title">Куда приедете?</h3>
    ${!points ? html`<${Skel} h="var(--control-lg)" r="var(--radius)" /><${Skel} h="var(--control-lg)" r="var(--radius)" />`
      : !points.length ? html`<p class="muted">Адресов пока нет. Запишитесь по телефону ${CONFIG.phone}.</p>`
      : html`<div class="stack-sm">${points.map((p) => html`<${Choice} key=${p.id} selected=${p.id === chosen} disabled=${busy}
          title=${p.name} meta=${p.address + " · " + hours(p)}
          onClick=${() => step("select-point", { service_point_id: p.id })} />`)}</div>`}
    ${chosen && html`<p class="hint">Другой адрес — масло и время выберете заново: на нём своё наличие и своё расписание.</p>`}
  </section>`;
}

const liters = (v) => String(Number(v)).replace(".", ",") + " л";

function OilStep({ draft, busy, step }) {
  const [oils, setOils] = useState(null);
  useEffect(() => {
    call(() => api.get("/service-points/" + draft.service_point.id + "/oils/")).then((o) => setOils(o || []));
  }, [draft.service_point.id]);
  const chosen = draft.oil && draft.oil.id;
  return html`<section class="stack">
    <h3 class="step-title">Какое масло?</h3>
    ${!oils ? html`<${Skel} h="var(--control-lg)" r="var(--radius)" /><${Skel} h="var(--control-lg)" r="var(--radius)" />`
      : html`<div class="stack-sm">
          ${oils.map((oil) => html`<${Choice} key=${oil.id} selected=${oil.id === chosen} disabled=${busy}
            title=${oil.brand + " " + oil.name} meta=${[oil.viscosity, oil.oil_type_display, liters(oil.volume_liters)].join(" · ")}
            onClick=${() => step("select-oil", { oil_id: oil.id })} />`)}
          <${Choice} selected=${draft.oil_on_site} disabled=${busy} title="Не знаю — подберите на месте"
            meta=${CALLBACK_TEXT}
            onClick=${() => step("select-oil", { on_site: true })} />
        </div>`}
    ${oils && !oils.length && html`<p class="hint">На этом адресе сейчас нет масла в наличии — выберите «Подберите на месте» или другой адрес.</p>`}
  </section>`;
}

const DOW = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
/** Группы времени по часам точки: искать глазами проще, чем по сетке из 24. */
const PARTS = [["Утро", 0, 12], ["День", 12, 17], ["Вечер", 17, 24]];

/** Свободное время точки: дни лентой, время группами, кнопка с выбором.

    Общий для шага записи и для переноса — у них одна и та же точка, одна
    и та же сетка и одно правило свободного поста. `initial` — уже
    выбранное время (вернулись на шаг): открываемся на его дне. */
export function SlotPicker({ pointId, zone, pointName, busy, actionLabel, onPick, initial }) {
  const [days, setDays] = useState(null);
  const [day, setDay] = useState(null);
  const [slots, setSlots] = useState(null);
  const [picked, setPicked] = useState(initial || null);

  useEffect(() => {
    call(() => api.get("/service-points/" + pointId + "/slots/")).then((data) => {
      const list = (data && data.available_days) || [];
      setDays(list);
      const initialDay = initial && localDay(initial, zone);
      setDay(list.includes(initialDay) ? initialDay : list[0] || null);
    });
  }, [pointId]);

  useEffect(() => {
    if (!day) return;
    setSlots(null);
    call(() => api.get("/service-points/" + pointId + "/slots/?date=" + day)).then((data) => {
      setSlots((data && data.slots) || []);
    });
  }, [day]);

  if (!days) {
    return html`<div class="stack" aria-busy="true"><${Skel} h="var(--control-lg)" r="var(--radius)" /><${Skel} h="var(--space-9)" r="var(--radius)" /></div>`;
  }
  if (!days.length) return html`<p class="muted">Свободного времени в ближайшие дни нет. Позвоните нам: ${CONFIG.phone}.</p>`;

  const today = localDay(new Date().toISOString(), zone);
  const dayDate = (d) => new Date(d + "T12:00:00");
  const month = day ? MONTHS[dayDate(day).getMonth()] : "";

  return html`<section class="stack">
    <h3 class="step-title">Когда удобно?</h3>
    <span class="label">${month}</span>
    <div class="days" role="listbox" aria-label="День">
      ${days.map((d) => {
        const date = dayDate(d);
        const label = d === today ? "сег" : DOW[date.getDay()];
        return html`<button class="day" type="button" key=${d} role="option" aria-selected=${String(d === day)}
          aria-pressed=${String(d === day)} onClick=${() => setDay(d)}>
          <small>${label}</small><b>${date.getDate()}</b>
        </button>`;
      })}
    </div>
    ${slots === null ? html`<${Skel} h="var(--space-9)" r="var(--radius)" />` : slots.length === 0
      ? html`<p class="muted">На этот день всё занято — выберите другой.</p>`
      : PARTS.map(([title, from, to]) => {
          const group = slots.filter((s) => { const h = Number(s.local_time.slice(0, 2)); return h >= from && h < to; });
          if (!group.length) return null;
          return html`<div class="slot-group" key=${title}>
            <span class="label">${title} · ${group.length}</span>
            <div class="slots">
              ${group.map((s) => html`<button class="slot-btn" type="button" key=${s.start_at}
                aria-pressed=${String(sameMoment(picked, s.start_at))} onClick=${() => setPicked(s.start_at)}>${s.local_time}</button>`)}
            </div>
          </div>`;
        })}
    <p class="hint">Время — по адресу «${pointName}».</p>
    <div class="sticky-actions">
      <button class="btn btn-primary btn-lg" type="button" disabled=${!picked || busy}
        onClick=${() => onPick(picked)}>
        ${picked ? actionLabel + " · " + visitTime(picked, zone) : "Выберите время"}
      </button>
    </div>
  </section>`;
}

/** День в календаре точки: «2026-10-14». */
function localDay(iso, zone) {
  try { return new Date(iso).toLocaleDateString("en-CA", { timeZone: zone || undefined }); } catch (e) { return iso.slice(0, 10); }
}
const sameMoment = (a, b) => Boolean(a && b) && new Date(a).getTime() === new Date(b).getTime();

function ConfirmStep({ draft, busy, confirm }) {
  const [comment, setComment] = useState("");
  const [carId, setCarId] = useState(null);
  const point = draft.service_point;
  return html`<section class="stack">
    <h3 class="step-title">Проверьте и подтвердите</h3>
    <div class="card pad info-list">
      <${InfoRow} icon="calendar" label="Когда">${visitTime(draft.slot_start, point.timezone)}</${InfoRow}>
      <${InfoRow} icon="pin" label=${point.name}>${point.address}</${InfoRow}>
      <${InfoRow} icon="drop" label="Масло">${draft.oil_on_site ? "Подберём на месте — мастер позвонит" : draft.oil.title}</${InfoRow}>
    </div>
    <span class="label">Какую машину привезёте</span>
    <${CarPicker} value=${carId} onChange=${setCarId} />
    <div class="field">
      <label for="comment">Комментарий мастеру</label>
      <textarea id="comment" rows="2" maxlength="500" placeholder="Необязательно. Например: приеду на 5 минут раньше"
        value=${comment} onInput=${(e) => setComment(e.target.value)}></textarea>
    </div>
    <p class="hint">Баллами можно оплатить до ${CONFIG.maxDiscount}% чека — скажите мастеру при расчёте.</p>
    <div class="sticky-actions">
      <button class="btn btn-primary btn-lg" type="button" disabled=${busy} onClick=${() => confirm(comment, carId)}>
        ${busy ? "Записываем…" : "Записаться"}
      </button>
    </div>
  </section>`;
}

/** Запись создана: знак «получилось» загорается один раз, время крупно,
    код — ниже: «когда ехать» важнее, код понадобится только на посту. */
function Created({ booking, onDone }) {
  const point = booking.service_point;
  return html`<div class="stack-lg">
    <div class="done-head">
      <span class="done-mark" dangerouslySetInnerHTML=${{ __html: window.App.icon("check", 30) }}></span>
      <h2>Вы записаны</h2>
      <p class="done-when">${visitTime(booking.start_at, point.timezone)}</p>
    </div>
    <div class="ticket-stub ticket-stub-solo">
      <span class="muted">Код на посту</span>
      <b class="ticket-code">${booking.code}</b>
    </div>
    <div class="card pad info-list">
      <${InfoRow} icon="pin" label=${point.name}>${point.address}</${InfoRow}>
      <${InfoRow} icon="drop" label="Масло">${booking.oil_title}</${InfoRow}>
      ${booking.car && html`<${InfoRow} icon="car" label="Машина">${carLabel(booking.car)}</${InfoRow}>`}
    </div>
    ${booking.oil_on_site && html`<p class="hint">${CALLBACK_TEXT}.</p>`}
    <button class="btn btn-primary btn-block btn-lg" type="button" onClick=${onDone}>Готово</button>
  </div>`;
}

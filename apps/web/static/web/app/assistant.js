/* Подсказчик в записи: клиент пишет, что с машиной, — получает услугу точки.

   Открывается из шагов «Категория» и «Услуга», если сервер говорит, что
   подсказчик доступен (`GET /assistant/`). Запись он не меняет: под ответом —
   карточка с предложенной услугой, «Выбрать» проводит её обычными шагами
   черновика (это делает мастер записи, `onApply`).

   Текст разговора сервер не хранит — историю держим здесь и шлём с каждым
   сообщением. Лимиты считает сервер: когда разговор или день закончились,
   ответ приходит с `handoff` — показываем «дальше с мастером» и телефон.
   Цен здесь нет и взяться им неоткуда: их нет в каталоге, который видит
   модель, а ответ с рублями сервер заменяет. */

import { api, errorText, html, toast, useEffect, useRef, useState } from "app/lib";

/** Пустой разговор для точки. */
export const freshChat = (pointId) => ({ pointId, chat: null, turns: [], left: null, phone: "", handoff: "" });

/** Что предложено — одной карточкой с кнопкой «Выбрать». */
function Suggestion({ s, busy, onApply, callbackText }) {
  const title = s.service ? s.service.name : s.on_site ? "Мастер подберёт на месте" : s.category.name;
  const meta = s.service ? s.category.name : s.on_site ? callbackText : "Выберите услугу в этой категории";
  return html`<button class="choice" type="button" disabled=${busy} onClick=${() => onApply(s)}>
    <span class="choice-body">
      <span class="choice-title">${title}</span>
      <span class="choice-meta">${meta}</span>
    </span>
    <span class="btn btn-sm btn-primary" aria-hidden="true">Выбрать</span>
  </button>`;
}

export function AssistantChat({ pointId, state, setState, busy, onApply, onBack, callbackText }) {
  const [text, setText] = useState("");
  const [waiting, setWaiting] = useState(false);
  const end = useRef(null);
  const chat = state && state.pointId === pointId ? state : freshChat(pointId);

  useEffect(() => { if (end.current) end.current.scrollIntoView({ block: "end", behavior: "smooth" }); },
    [chat.turns.length, waiting, chat.handoff]);

  async function send(event) {
    event.preventDefault();
    const message = text.trim();
    if (!message || waiting) return;
    const history = chat.turns.map((t) => ({ role: t.role, text: t.text }));
    const asked = { ...chat, turns: [...chat.turns, { role: "user", text: message }] };
    setState(asked);
    setText("");
    setWaiting(true);
    try {
      const answer = await api.post("/assistant/", {
        service_point: pointId, chat: chat.chat, message, history,
      });
      const suggestion = answer.category
        ? { category: answer.category, service: answer.service, on_site: answer.on_site }
        : null;
      setState({
        ...asked,
        chat: answer.chat,
        turns: [...asked.turns, { role: "assistant", text: answer.reply, suggestion }],
        left: answer.messages_left,
        phone: answer.phone,
        handoff: answer.handoff,
      });
    } catch (err) {
      // Сообщение не ушло — возвращаем его в поле, чтобы не набирать заново.
      setState(chat);
      setText(message);
      toast(errorText(err), "error");
    } finally {
      setWaiting(false);
    }
  }

  // «Мастер подберёт на месте» — в последней предложенной категории, где так можно.
  const last = [...chat.turns].reverse().find((t) => t.suggestion);
  const onSite = last && last.suggestion.category.allow_on_site
    ? { category: last.suggestion.category, service: null, on_site: true }
    : null;

  return html`<section class="stack">
    <h3 class="step-title">Подскажем, что выбрать</h3>
    <p class="hint">Опишите своими словами, что с машиной или что хотите сделать. Цену и сроки скажет мастер.</p>
    <div class="chat" aria-live="polite">
      ${chat.turns.map((t, i) => t.role === "user"
        ? html`<div class="bubble bubble-user" key=${i}>${t.text}</div>`
        : html`<div class="bubble bubble-bot" key=${i}>
            <p>${t.text}</p>
            ${t.suggestion && html`<${Suggestion} s=${t.suggestion} busy=${busy} onApply=${onApply} callbackText=${callbackText} />`}
          </div>`)}
      ${waiting && html`<div class="bubble bubble-bot muted">Подбираем…</div>`}
    </div>
    ${chat.handoff
      ? html`<div class="card pad stack-sm">
          <b>Дальше поможет мастер</b>
          <p class="muted">${callbackText}.</p>
          <div class="chat-actions">
            ${chat.phone && html`<a class="btn" href=${"tel:" + chat.phone.replace(/[^\d+]/g, "")}>Позвонить</a>`}
            ${onSite && html`<button class="btn btn-primary" type="button" disabled=${busy} onClick=${() => onApply(onSite)}>Мастер подберёт на месте</button>`}
          </div>
        </div>`
      : html`<form class="chat-form" onSubmit=${send}>
          <label class="visually-hidden" for="assistant-text">Ваш вопрос</label>
          <textarea id="assistant-text" rows="2" maxlength="500" disabled=${waiting}
            placeholder=${chat.turns.length ? "Уточните, если нужно" : "Например: загорелась лампа масла"}
            value=${text} onInput=${(e) => setText(e.target.value)}></textarea>
          <button class="btn btn-primary" type="submit" disabled=${waiting || !text.trim()}>Спросить</button>
        </form>`}
    ${!chat.handoff && chat.left !== null && html`<p class="hint">В этом разговоре осталось вопросов: ${chat.left}</p>`}
    <div ref=${end}></div>
    <button class="link-btn" type="button" onClick=${onBack}>Вернуться к списку</button>
  </section>`;
}

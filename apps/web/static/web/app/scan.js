/* Сканер QR-кода приглашения камерой телефона.

   В Safari на iPhone нет встроенного распознавателя (BarcodeDetector),
   поэтому кадры с камеры разбирает jsQR. Библиотека весит четверть
   мегабайта и нужна раз в жизни клиента — грузим её только при открытии
   сканера, а не вместе с приложением. */

import { CONFIG, html, render, useEffect, useRef, useState } from "app/lib";

let loading = null;

function loadDecoder() {
  if (window.jsQR) return Promise.resolve(window.jsQR);
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = CONFIG.qrDecoderUrl;
      script.onload = () => resolve(window.jsQR);
      script.onerror = () => { loading = null; reject(new Error("decoder")); };
      document.head.append(script);
    });
  }
  return loading;
}

/** Код приглашения из того, что прочитал сканер.

    В QR лежит ссылка `https://<сайт>/i/<код>` — её и разбираем. Голый код
    тоже принимаем: его могут показать и в другом виде. Любой другой QR
    (чужой сайт, Wi-Fi) — не приглашение, и мы честно так и говорим. */
export function inviteFromText(text) {
  const raw = String(text || "").trim();
  const fromLink = raw.match(/\/i\/([A-Za-z0-9]{4,10})\/?(?:[?#].*)?$/);
  if (fromLink) return fromLink[1].toUpperCase();
  const fromQuery = raw.match(/[?&]invite=([A-Za-z0-9]{4,10})/);
  if (fromQuery) return fromQuery[1].toUpperCase();
  if (/^[A-Za-z0-9]{4,10}$/.test(raw)) return raw.toUpperCase();
  return "";
}

function Scanner({ onCode, onClose }) {
  const video = useRef(null);
  const [error, setError] = useState("");
  const [wrong, setWrong] = useState(false);

  useEffect(() => {
    let stream = null;
    let frame = 0;
    let stopped = false;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });

    async function start() {
      try {
        const [decode] = await Promise.all([
          loadDecoder(),
          navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false,
          }).then((s) => { stream = s; }),
        ]);
        if (stopped) return;
        const el = video.current;
        el.srcObject = stream;
        // iPhone играет видео только встроенным и без звука.
        el.setAttribute("playsinline", "");
        el.muted = true;
        await el.play();

        const tick = () => {
          if (stopped) return;
          if (el.readyState === el.HAVE_ENOUGH_DATA) {
            // Уменьшаем кадр: распознаванию хватает 480 px, а телефон не греется.
            const scale = Math.min(1, 480 / el.videoWidth);
            canvas.width = Math.round(el.videoWidth * scale);
            canvas.height = Math.round(el.videoHeight * scale);
            ctx.drawImage(el, 0, 0, canvas.width, canvas.height);
            const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const found = decode(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
            if (found && found.data) {
              const code = inviteFromText(found.data);
              if (code) { onCode(code); return; }
              setWrong(true);
            }
          }
          frame = requestAnimationFrame(tick);
        };
        tick();
      } catch (err) {
        if (err && err.name === "NotAllowedError") {
          setError("Нет доступа к камере. Разрешите его в настройках Safari для этого сайта или введите код вручную.");
        } else if (err && err.message === "decoder") {
          setError("Не удалось загрузить сканер. Проверьте интернет или введите код вручную.");
        } else {
          setError("Камера недоступна. Введите код приглашения вручную.");
        }
      }
    }

    start();
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      if (stream) stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return html`<div class="scanner" role="dialog" aria-modal="true" aria-label="Сканер QR-кода">
    <video ref=${video} class="scanner-video" playsinline muted></video>
    <div class="scanner-frame" aria-hidden="true"></div>
    <div class="scanner-bar">
      <p>${error || (wrong
        ? "Это не QR-код приглашения. Наведите камеру на код в «Бонусах» у друга."
        : "Наведите камеру на QR-код приглашения")}</p>
      <button class="btn btn-block" type="button" onClick=${onClose}>Закрыть</button>
    </div>
  </div>`;
}

/** Открыть сканер поверх приложения. Промис вернёт код или null. */
export function scanInvite() {
  return new Promise((resolve) => {
    const host = document.createElement("div");
    document.body.append(host);
    const close = (code) => {
      render(null, host);
      host.remove();
      resolve(code || null);
    };
    render(html`<${Scanner} onCode=${close} onClose=${() => close(null)} />`, host);
  });
}

export const canScan = () => Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

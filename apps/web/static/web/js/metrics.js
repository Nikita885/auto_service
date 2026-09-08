/* Метрики администратора: один запрос к /api/v1/master/metrics/ и восемь
   блоков на его основе.

   Графики рисуются вручную в SVG — без библиотек: данных немного, а так
   картинка сама подхватывает тему из CSS-переменных и не тянет мегабайт
   стороннего кода ради двух диаграмм. */

(function (global) {
  "use strict";

  const { fmt, $, $$, el, empty, guard } = App;

  let api = null;
  let range = 30;

  /* ------------------------------------------------------------- запрос */

  function params() {
    const query = new URLSearchParams();
    const from = $("#m-from").value;
    const to = $("#m-to").value;
    const point = $("#m-point").value;

    if (from) query.set("date_from", from);
    if (to) query.set("date_to", to);
    if (point) query.set("service_point", point);
    return query;
  }

  async function load() {
    const data = await guard(() => api.get("/master/metrics/?" + params().toString()));
    if (!data) return;

    // Поля дат заполняем ответом: сервер сам решил, какой период показать
    // по умолчанию, и панель должна показывать ровно его.
    $("#m-from").value = data.period.date_from;
    $("#m-to").value = data.period.date_to;
    $("#metrics-caption").textContent =
      fmt.dateFull(data.period.date_from) + " — " + fmt.dateFull(data.period.date_to) +
      " · " + data.period.days + " " + fmt.plural(data.period.days, "день", "дня", "дней") +
      " · часовой пояс " + data.period.timezone;

    renderKpi(data);
    renderDays(data.by_day);
    renderFunnel(data.funnel);
    renderHours(data.by_hour);
    renderPoints(data.by_point);
    renderOils(data.top_oils);
    renderStock(data.stock);
  }

  /* ---------------------------------------------------------------- KPI */

  function renderKpi(data) {
    const t = data.totals;
    const cards = [
      { label: "Выручка", value: fmt.money(t.revenue), accent: true,
        hint: "масло " + fmt.money(t.oil_revenue) + " + работа " + fmt.money(t.work_revenue) },
      { label: "Средний чек", value: fmt.money(t.avg_check), hint: "по выполненным записям" },
      { label: "Записей за период", value: fmt.number(t.total),
        hint: t.completed + " выполнено · " + t.pending + " ждут · " + t.in_progress + " в работе" },
      { label: "Доля выполненных", value: fmt.percent(t.completion_rate),
        hint: "отмены " + fmt.percent(t.cancel_rate) + " · неявки " + fmt.percent(t.no_show_rate) },
      { label: "Конверсия записи", value: fmt.percent(data.funnel.conversion),
        hint: data.funnel.confirmed + " из " + data.funnel.started + " начатых дошли до конца" },
      { label: "Сейчас записываются", value: fmt.number(data.live.drafts_now),
        hint: data.live.upcoming + " предстоящих записей" },
      { label: "Клиенты", value: fmt.number(data.clients.total),
        hint: "+" + data.clients.new + " за период · " + data.clients.returning + " возвращались" },
      { label: "Канистр на складе", value: fmt.number(data.stock.total_quantity),
        hint: data.stock.low_count ? data.stock.low_count + " позиций заканчивается" : "запас в норме" },
    ];

    $("#m-kpi").innerHTML = cards
      .map((card) =>
        '<div class="stat' + (card.accent ? " stat-accent" : "") + '">' +
        '<div class="stat-label">' + card.label + "</div>" +
        '<div class="stat-value">' + card.value + "</div>" +
        '<div class="stat-hint">' + card.hint + "</div></div>"
      )
      .join("");
  }

  /* ------------------------------------------------- динамика по дням */

  function renderDays(days) {
    const box = $("#m-days");
    box.innerHTML = "";

    const hasData = days.some((day) => day.total > 0);
    if (!hasData) {
      box.append(empty("За этот период записей не было.", "chart"));
      return;
    }

    const W = 660, H = 210, padL = 34, padR = 42, padB = 26, padT = 12;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    const maxCount = Math.max(1, ...days.map((d) => d.total));
    const maxMoney = Math.max(1, ...days.map((d) => Number(d.revenue)));

    const step = plotW / days.length;
    const barW = Math.max(2, Math.min(26, step * 0.62));

    const parts = [];

    // Горизонтальная сетка и подписи количества.
    for (let i = 0; i <= 3; i++) {
      const y = padT + (plotH * i) / 3;
      const value = Math.round((maxCount * (3 - i)) / 3);
      parts.push('<line class="chart-grid" x1="' + padL + '" y1="' + y + '" x2="' + (W - padR) + '" y2="' + y + '"/>');
      parts.push('<text class="chart-axis" x="' + (padL - 7) + '" y="' + (y + 3) + '" text-anchor="end">' + value + "</text>");
    }

    days.forEach((day, i) => {
      const x = padL + step * i + (step - barW) / 2;
      const h = (day.total / maxCount) * plotH;
      const y = padT + plotH - h;

      if (day.total) {
        parts.push(
          '<rect class="chart-bar" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) +
          '" width="' + barW.toFixed(1) + '" height="' + Math.max(h, 1.5).toFixed(1) + '" rx="3">' +
          "<title>" + fmt.dateFull(day.date) + ": " + day.total + " записей, выручка " +
          fmt.money(day.revenue) + "</title></rect>"
        );
      }
    });

    // Линия выручки поверх столбцов — вторая шкала справа.
    const points = days.map((day, i) => {
      const x = padL + step * i + step / 2;
      const y = padT + plotH - (Number(day.revenue) / maxMoney) * plotH;
      return [x, y];
    });

    parts.push(
      '<path class="chart-area" d="M' + points[0][0].toFixed(1) + " " + (padT + plotH) +
      points.map((p) => " L" + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("") +
      " L" + points[points.length - 1][0].toFixed(1) + " " + (padT + plotH) + ' Z"/>'
    );
    parts.push(
      '<path class="chart-line" d="M' +
      points.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L") + '"/>'
    );

    parts.push(
      '<text class="chart-axis" x="' + (W - padR + 6) + '" y="' + (padT + 4) + '">' +
      fmt.money(maxMoney) + "</text>"
    );

    // Подписи дат: показываем не больше восьми, иначе они слипаются.
    const every = Math.max(1, Math.ceil(days.length / 8));
    days.forEach((day, i) => {
      if (i % every) return;
      const x = padL + step * i + step / 2;
      parts.push(
        '<text class="chart-axis" x="' + x.toFixed(1) + '" y="' + (H - 8) +
        '" text-anchor="middle">' + fmt.date(day.date) + "</text>"
      );
    });

    box.innerHTML =
      '<svg class="chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Динамика записей и выручки">' +
      parts.join("") + "</svg>" +
      '<div class="legend" style="margin-top:10px">' +
      '<span class="legend-item"><span class="legend-swatch" style="background:var(--accent)"></span>записи</span>' +
      '<span class="legend-item"><span class="legend-swatch" style="background:var(--info)"></span>выручка</span>' +
      "</div>";
  }

  /* ------------------------------------------------------------- воронка */

  function renderFunnel(funnel) {
    const box = $("#m-funnel");
    box.innerHTML = "";

    if (!funnel.started) {
      box.append(empty("За этот период никто не начинал запись.", "list"));
      return;
    }

    const rows = funnel.steps
      .map((step) =>
        '<div class="funnel-row">' +
        '<div class="funnel-label">' + step.label + "</div>" +
        '<div class="funnel-track"><div class="funnel-fill" style="width:' + Math.max(step.share, 1) + '%"></div></div>' +
        '<div class="funnel-value">' + fmt.number(step.count) + " · " + fmt.percent(step.share) + "</div>" +
        "</div>"
      )
      .join("");

    const lost = [
      { label: "Истекли пять минут", value: funnel.expired, kind: "badge-warn" },
      { label: "Прервали сами", value: funnel.cancelled, kind: "badge-danger" },
      { label: "Начали заново", value: funnel.restarted, kind: "badge" },
      { label: "В процессе сейчас", value: funnel.alive, kind: "badge-accent" },
    ]
      .map((item) => '<span class="badge ' + item.kind + '">' + item.label + ": " + item.value + "</span>")
      .join("");

    box.innerHTML =
      '<div class="funnel">' + rows + "</div>" +
      '<div class="divider"></div>' +
      '<div class="row" style="gap:8px">' + lost + "</div>";
  }

  /* --------------------------------------------------------------- часы */

  function renderHours(hours) {
    const box = $("#m-hours");
    box.innerHTML = "";

    const max = Math.max(...hours.map((h) => h.total));
    if (!max) {
      box.append(empty("Нет записей, чтобы построить загрузку.", "clock"));
      return;
    }

    const W = 660, H = 180, padL = 26, padB = 24, padT = 10;
    const plotW = W - padL - 10;
    const plotH = H - padT - padB;
    const step = plotW / 24;
    const barW = step * 0.66;

    const bars = hours
      .map((row) => {
        const x = padL + step * row.hour + (step - barW) / 2;
        const h = (row.total / max) * plotH;
        const y = padT + plotH - h;
        const cls = row.total ? "chart-bar" : "chart-bar-soft";
        return (
          '<rect class="' + cls + '" x="' + x.toFixed(1) + '" y="' + (row.total ? y.toFixed(1) : padT + plotH - 2) +
          '" width="' + barW.toFixed(1) + '" height="' + (row.total ? Math.max(h, 1.5).toFixed(1) : 2) + '" rx="2">' +
          "<title>" + String(row.hour).padStart(2, "0") + ":00 — " + row.total + " записей</title></rect>"
        );
      })
      .join("");

    const labels = hours
      .filter((row) => row.hour % 3 === 0)
      .map((row) => {
        const x = padL + step * row.hour + step / 2;
        return (
          '<text class="chart-axis" x="' + x.toFixed(1) + '" y="' + (H - 7) + '" text-anchor="middle">' +
          String(row.hour).padStart(2, "0") + "</text>"
        );
      })
      .join("");

    box.innerHTML =
      '<svg class="chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Загрузка по часам">' +
      '<line class="chart-grid" x1="' + padL + '" y1="' + (padT + plotH) + '" x2="' + (W - 10) + '" y2="' + (padT + plotH) + '"/>' +
      '<text class="chart-axis" x="' + (padL - 6) + '" y="' + (padT + 8) + '" text-anchor="end">' + max + "</text>" +
      bars + labels + "</svg>";
  }

  /* -------------------------------------------------------------- точки */

  function renderPoints(points) {
    const box = $("#m-points");
    box.innerHTML = "";

    if (!points.length) {
      box.append(empty("Записей по точкам нет.", "pin"));
      return;
    }

    const max = Math.max(...points.map((p) => Number(p.revenue) || 0), 1);
    box.innerHTML =
      '<div class="rank">' +
      points
        .map((point) =>
          '<div class="rank-row">' +
          '<div class="rank-name">' + point.name + "</div>" +
          '<div class="rank-value">' + fmt.money(point.revenue) + " · " + point.total + " " +
          fmt.plural(point.total, "запись", "записи", "записей") + "</div>" +
          '<div class="rank-track"><div class="rank-fill" style="width:' +
          ((Number(point.revenue) / max) * 100).toFixed(1) + '%"></div></div>' +
          "</div>"
        )
        .join("") +
      "</div>";
  }

  /* --------------------------------------------------------------- масла */

  function renderOils(oils) {
    const box = $("#m-oils");
    box.innerHTML = "";

    if (!oils.length) {
      box.append(empty("Пока ничего не заказывали.", "drop"));
      return;
    }

    const max = Math.max(...oils.map((oil) => oil.total), 1);
    box.innerHTML =
      '<div class="rank">' +
      oils
        .map((oil) =>
          '<div class="rank-row">' +
          '<div class="rank-name">' + oil.oil_title + "</div>" +
          '<div class="rank-value">' + oil.total + " " + fmt.plural(oil.total, "запись", "записи", "записей") +
          " · " + fmt.money(oil.revenue) + "</div>" +
          '<div class="rank-track"><div class="rank-fill" style="width:' +
          ((oil.total / max) * 100).toFixed(1) + '%"></div></div>' +
          "</div>"
        )
        .join("") +
      "</div>";
  }

  /* --------------------------------------------------------------- склад */

  function renderStock(stock) {
    const box = $("#m-stock");
    box.innerHTML = "";

    $("#m-stock-sub").textContent =
      "Остатки канистр · порог «заканчивается» — " + stock.threshold;

    if (!stock.items.length) {
      box.append(empty("Остатки не заведены.", "box"));
      return;
    }

    const rows = stock.items
      .map((item) =>
        "<tr><td>" + item.oil + '<div class="cell-sub">' + item.point + "</div></td>" +
        '<td class="num nowrap">' +
        (item.is_low
          ? '<span class="badge badge-danger">' + item.quantity + "</span>"
          : '<span class="badge badge-ok">' + item.quantity + "</span>") +
        "</td></tr>"
      )
      .join("");

    box.innerHTML =
      '<div class="table-wrap" style="box-shadow:none">' +
      "<table><thead><tr><th>Позиция</th><th class=\"num\">Остаток</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div>";
  }

  /* --------------------------------------------------------------- старт */

  function applyRange(days) {
    range = days;
    const to = new Date();
    const from = new Date();
    from.setDate(to.getDate() - (days - 1));
    $("#m-from").value = fmt.isoDate(from);
    $("#m-to").value = fmt.isoDate(to);
  }

  function init(context) {
    api = context.api;

    $$(".tab[data-range]").forEach((tab) => {
      tab.onclick = () => {
        $$(".tab[data-range]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
        applyRange(Number(tab.dataset.range));
        load();
      };
    });

    $("#btn-metrics").onclick = load;
    $("#m-point").onchange = load;

    applyRange(range);
    load();
  }

  global.Metrics = { init, load };
})(window);

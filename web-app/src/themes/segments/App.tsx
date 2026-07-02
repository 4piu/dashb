import { type PointerEvent, useEffect, useRef, useState } from 'react';
import { connectDashb, type ConnectionState, type SampleEntry } from '../../theme-sdk';

type MetricValue = {
  value: unknown;
  unit?: string;
  ts_ms: number;
};

type Rect = {
  x: number;
  y: number;
  w: number;
  h: number;
};

type FormattedValue = {
  digits: string;
  unit?: string;
  unitBank?: string[];
};

type SegmentValueOptions = {
  align?: CanvasTextAlign;
  maxRight?: number;
  // Pins the digit block's right edge directly, bypassing the maxRight/unit-
  // reservation math below. Used to align digits across values whose units
  // differ in width (e.g. "MHz" vs "degC"), where matching maxRight alone
  // would still leave the digits themselves misaligned.
  digitsRight?: number;
  unitLayout?: 'inline' | 'bank' | 'percent';
  unitSize?: number;
};

const LIVE_METRICS = [
  'cpu.utilization',
  'cpu.utilization_percore',
  'cpu.clock_average',
  'cpu.power_package',
  'cpu.temperature_package',
  'gpu.utilization',
  'gpu.core_clock_mhz',
  'gpu.power_draw_w',
  'gpu.temperature_c',
  'gpu.memory_used_bytes',
  'memory.physical.used',
  'memory.physical.percent',
  'memory.swap.used',
  'memory.swap.percent',
  'network.bytes_recv_per_s',
  'network.bytes_sent_per_s',
  'disk.bytes_read_per_s',
  'disk.bytes_written_per_s',
] as const;

const STATIC_METRICS = [
  'gpu.memory_total_bytes',
  'memory.physical.total',
  'memory.swap.total',
] as const;

const SAMPLING_MS: Record<string, number> = {
  'cpu.utilization': 500,
  'cpu.utilization_percore': 500,
  'cpu.clock_average': 500,
  'cpu.power_package': 500,
  'cpu.temperature_package': 500,
  'gpu.utilization': 1000,
  'gpu.core_clock_mhz': 1000,
  'gpu.power_draw_w': 1000,
  'gpu.temperature_c': 1000,
  'gpu.memory_used_bytes': 1000,
  'memory.physical.used': 1000,
  'memory.physical.percent': 1000,
  'memory.swap.used': 1000,
  'memory.swap.percent': 1000,
  'network.bytes_recv_per_s': 1000,
  'network.bytes_sent_per_s': 1000,
  'disk.bytes_read_per_s': 1000,
  'disk.bytes_written_per_s': 1000,
};

const CORE_HISTORY_LIMIT = 36;
const COLORS = {
  black: '#000000',
  white: '#f4f7f2',
  line: 'rgba(244, 247, 242, 0.32)',
  green: '#51ff8a',
  yellow: '#fff56b',
  orange: '#ff9a38',
  red: '#ff4242',
  cyan: '#47e9ff',
};
const GAUGE_BANDS = [COLORS.green, COLORS.yellow, COLORS.orange, COLORS.red];
// Shipped alongside DSEG7 so every glyph on screen comes from a bundled font
// instead of falling back to whatever sans-serif happens to be installed.
const UI_FONT_FAMILY = '"Kode Mono", monospace';

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function arrayValue(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => numberValue(item))
    .filter((item): item is number => item !== null);
}

function clampPercent(value: number | null): number | null {
  if (value === null) {
    return null;
  }
  return Math.max(0, Math.min(100, value));
}

function integerValue(value: number | null, unit = '', minDigits = 0): FormattedValue {
  if (value === null) {
    return { digits: '-'.repeat(Math.max(3, minDigits)), unit };
  }
  return {
    digits: String(Math.round(value)).padStart(minDigits, '0'),
    unit,
  };
}

function bytesValue(value: number | null): FormattedValue {
  if (value === null) {
    return { digits: '---', unitBank: ['MB', 'GB'] };
  }
  const gb = value / 1024 / 1024 / 1024;
  if (gb >= 1) {
    return { digits: gb.toFixed(1), unit: 'GB', unitBank: ['MB', 'GB'] };
  }
  return {
    digits: String(Math.round(value / 1024 / 1024)),
    unit: 'MB',
    unitBank: ['MB', 'GB'],
  };
}

function rateValue(value: number | null): FormattedValue {
  if (value === null) {
    return { digits: '---', unitBank: ['KB/s', 'MB/s', 'GB/s'] };
  }
  const abs = Math.abs(value);
  if (abs >= 1024 * 1024 * 1024) {
    return {
      digits: (value / 1024 / 1024 / 1024).toFixed(1),
      unit: 'GB/s',
      unitBank: ['KB/s', 'MB/s', 'GB/s'],
    };
  }
  if (abs >= 1024 * 1024) {
    return {
      digits: (value / 1024 / 1024).toFixed(1),
      unit: 'MB/s',
      unitBank: ['KB/s', 'MB/s', 'GB/s'],
    };
  }
  return {
    digits: String(Math.round(value / 1024)),
    unit: 'KB/s',
    unitBank: ['KB/s', 'MB/s', 'GB/s'],
  };
}

function useDashbMetrics() {
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');
  const [connectionDetail, setConnectionDetail] = useState('');
  const [supportedMetrics, setSupportedMetrics] = useState<Set<string>>(new Set());
  const [values, setValues] = useState<Record<string, MetricValue>>({});
  const [coreHistory, setCoreHistory] = useState<number[][]>([]);

  useEffect(() => {
    const updateValues = (entries: SampleEntry[], ts_ms: number) => {
      setValues((current) => {
        const next = { ...current };
        for (const entry of entries) {
          next[entry.metric] = {
            value: entry.value,
            unit: entry.unit,
            ts_ms,
          };
        }
        return next;
      });

      const coreEntry = entries.find(
        (entry) => entry.metric === 'cpu.utilization_percore',
      );
      if (coreEntry) {
        const cores = arrayValue(coreEntry.value);
        setCoreHistory((current) =>
          cores.map((coreValue, index) => [
            ...(current[index] ?? []).slice(-(CORE_HISTORY_LIMIT - 1)),
            coreValue,
          ]),
        );
      }
    };

    const client = connectDashb({
      clientName: 'dashb-segments-theme',
      clientVersion: '0.1.0',
      onConnectionChange: (state, detail) => {
        setConnectionState(state);
        setConnectionDetail(detail);
        // 'stale' means the socket is still open but no data has arrived in
        // a while (e.g. the server machine slept) - blank the display same
        // as an outright disconnect, since what's on screen can no longer
        // be trusted.
        if (state === 'disconnected' || state === 'stale') {
          setValues({});
          setCoreHistory([]);
        }
      },
      onServerInfo: (message) => {
        const metricSet = new Set((message.metrics ?? []).map(({ metric }) => metric));
        setSupportedMetrics(metricSet);

        const queryMetrics = STATIC_METRICS.filter((metric) => metricSet.has(metric));
        if (queryMetrics.length > 0) {
          client.query(queryMetrics, 'segments-query-static');
        }

        const subscriptions = LIVE_METRICS.filter((metric) => metricSet.has(metric)).map(
          (metric) => ({
            metric,
            interval_ms: SAMPLING_MS[metric] ?? 1000,
          }),
        );
        if (subscriptions.length > 0) {
          client.subscribe(subscriptions, 'segments-subscribe');
        }
      },
      onQueryResult: (message) => updateValues(message.values ?? [], message.ts_ms),
      onSample: (message) => updateValues(message.values ?? [], message.ts_ms),
      onSubscribed: (message) => {
        const accepted = message.accepted?.length ?? 0;
        const rejected = message.rejected?.length ?? 0;
        setConnectionDetail(`subscribed ${accepted}/${accepted + rejected}`);
      },
    });

    return () => client.close();
  }, []);

  return { connectionState, connectionDetail, supportedMetrics, values, coreHistory };
}

function rgba(hex: string, alpha: number): string {
  const red = parseInt(hex.slice(1, 3), 16);
  const green = parseInt(hex.slice(3, 5), 16);
  const blue = parseInt(hex.slice(5, 7), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function font(size: number, family = UI_FONT_FAMILY, weight = 700): string {
  return `${weight} ${Math.max(1, size)}px ${family}`;
}

function segmentFont(size: number): string {
  return `${Math.max(1, size)}px "DSEG7 Classic", "Courier New", monospace`;
}

function drawText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  size: number,
  align: CanvasTextAlign = 'left',
) {
  ctx.font = font(size);
  ctx.textAlign = align;
  ctx.textBaseline = 'middle';
  ctx.fillStyle = COLORS.white;
  ctx.fillText(text, x, y);
}

function drawPanelLabel(
  ctx: CanvasRenderingContext2D,
  label: string,
  x: number,
  y: number,
  size: number,
) {
  ctx.font = font(size);
  ctx.textAlign = 'left';
  // A single pad on all sides plus a middle baseline keeps the text centered
  // with equal margin left/right/top/bottom, instead of the old top-aligned
  // text with mismatched horizontal/vertical padding.
  const pad = size * 0.3;
  const width = ctx.measureText(label).width + pad * 2;
  const height = size + pad * 2;
  ctx.strokeStyle = COLORS.line;
  ctx.lineWidth = Math.max(1, size * 0.05);
  roundRect(ctx, x, y, width, height, Math.max(1, size * 0.08));
  ctx.stroke();
  ctx.fillStyle = COLORS.white;
  ctx.textBaseline = 'middle';
  ctx.fillText(label, x + pad, y + height / 2);
  return { width, height };
}

function drawSegmentText(
  ctx: CanvasRenderingContext2D,
  text: string,
  mask: string,
  x: number,
  y: number,
  size: number,
  align: CanvasTextAlign = 'left',
  baseline: CanvasTextBaseline = 'middle',
) {
  ctx.font = segmentFont(size);
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
  ctx.fillStyle = rgba(COLORS.white, 0.14);
  ctx.fillText(mask, x, y);
  ctx.fillStyle = COLORS.white;
  ctx.shadowColor = rgba(COLORS.white, 0.35);
  ctx.shadowBlur = size * 0.14;
  ctx.fillText(text, x, y);
  ctx.shadowBlur = 0;
}

function drawSegmentValue(
  ctx: CanvasRenderingContext2D,
  value: FormattedValue,
  mask: string,
  x: number,
  y: number,
  size: number,
  options: SegmentValueOptions = {},
): { digitRight: number } {
  const align = options.align ?? 'right';
  const unitLayout = options.unitLayout ?? (value.unitBank ? 'bank' : 'inline');
  const unitSize =
    options.unitSize ??
    (unitLayout === 'bank' ? size * 0.3 : unitLayout === 'percent' ? size * 0.42 : size * 0.42);
  const unitGap = unitLayout === 'percent' ? size * 0.12 : size * 0.24;
  const units = value.unitBank ?? (value.unit ? [value.unit] : []);

  ctx.font = segmentFont(size);
  const textWidth = ctx.measureText(mask).width;
  ctx.font = font(unitSize, UI_FONT_FAMILY, 800);
  const unitWidth = units.length === 0 ? 0 : Math.max(...units.map((unit) => ctx.measureText(unit).width));
  const unitRight = options.maxRight ?? Number.POSITIVE_INFINITY;
  const reservedUnitWidth = unitWidth > 0 ? unitGap + unitWidth : 0;
  const digitRightLimit = Number.isFinite(unitRight) ? unitRight - reservedUnitWidth : Number.POSITIVE_INFINITY;
  const digitRight =
    options.digitsRight ?? Math.min(align === 'right' ? x : x + textWidth, digitRightLimit);
  const digitX = align === 'right' ? digitRight : digitRight - textWidth;
  const unitX = digitRight + unitGap;
  const bottom = y + size * 0.42;

  drawSegmentText(ctx, value.digits, mask, digitX, bottom, size, align, 'bottom');
  if (value.unitBank) {
    drawUnitBank(ctx, value.unitBank, value.unit, unitX, bottom, unitSize);
  } else if (value.unit) {
    drawUnitText(ctx, value.unit, unitX, bottom, unitSize);
  }
  return { digitRight };
}

// Measures how wide a segment value (digits + reserved unit space) would
// render at a given size, without drawing anything - used to shrink text
// that would otherwise overflow its available width on narrower/squarer
// layouts.
function measureSegmentValueWidth(
  ctx: CanvasRenderingContext2D,
  value: FormattedValue,
  mask: string,
  size: number,
  options: SegmentValueOptions = {},
): number {
  const unitLayout = options.unitLayout ?? (value.unitBank ? 'bank' : 'inline');
  const unitSize =
    options.unitSize ??
    (unitLayout === 'bank' ? size * 0.3 : unitLayout === 'percent' ? size * 0.42 : size * 0.42);
  const unitGap = unitLayout === 'percent' ? size * 0.12 : size * 0.24;
  const units = value.unitBank ?? (value.unit ? [value.unit] : []);

  ctx.font = segmentFont(size);
  const textWidth = ctx.measureText(mask).width;
  ctx.font = font(unitSize, UI_FONT_FAMILY, 800);
  const unitWidth = units.length === 0 ? 0 : Math.max(...units.map((unit) => ctx.measureText(unit).width));
  const reservedUnitWidth = unitWidth > 0 ? unitGap + unitWidth : 0;
  return textWidth + reservedUnitWidth;
}

function fitSegmentValueSize(
  ctx: CanvasRenderingContext2D,
  value: FormattedValue,
  mask: string,
  size: number,
  maxWidth: number,
  options: SegmentValueOptions = {},
  minSize = 9,
): number {
  const width = measureSegmentValueWidth(ctx, value, mask, size, options);
  if (width <= 0 || width <= maxWidth) {
    return size;
  }
  return Math.max(minSize, size * (maxWidth / width));
}

function drawUnitText(
  ctx: CanvasRenderingContext2D,
  unit: string,
  x: number,
  y: number,
  size: number,
) {
  ctx.font = font(size, UI_FONT_FAMILY, 800);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'bottom';
  ctx.fillStyle = COLORS.white;
  ctx.fillText(unit, x, y);
}

function drawUnitBank(
  ctx: CanvasRenderingContext2D,
  units: string[],
  activeUnit: string | undefined,
  x: number,
  y: number,
  size: number,
) {
  ctx.font = font(size, UI_FONT_FAMILY, 800);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'bottom';
  const lineHeight = size * 1.08;
  units.forEach((unit, index) => {
    ctx.fillStyle = unit === activeUnit ? COLORS.white : rgba(COLORS.white, 0.16);
    ctx.fillText(unit, x, y - (units.length - 1 - index) * lineHeight);
  });
}

function drawCenteredPercent(
  ctx: CanvasRenderingContext2D,
  value: number | null,
  cx: number,
  cy: number,
  size: number,
) {
  ctx.font = segmentFont(size);
  const digitBottom = cy + size * 0.42;
  ctx.textBaseline = 'bottom';
  const digitWidth = ctx.measureText('8').width;
  const rounded = value === null ? null : Math.round(Math.max(0, Math.min(100, value)));
  const lowerDigits = rounded === null ? '--' : String(rounded % 100).padStart(2, '0');
  const leadingOneX = cx - digitWidth * 1.06;
  ctx.textAlign = 'right';
  ctx.fillStyle = rgba(COLORS.white, 0.14);
  ctx.fillText('1', leadingOneX, digitBottom);
  ctx.textAlign = 'center';
  ctx.fillText('88', cx, digitBottom);
  ctx.fillStyle = COLORS.white;
  ctx.shadowColor = rgba(COLORS.white, 0.35);
  ctx.shadowBlur = size * 0.14;
  if (rounded === 100) {
    ctx.textAlign = 'right';
    ctx.fillText('1', leadingOneX, digitBottom);
  }
  ctx.textAlign = 'center';
  ctx.fillText(lowerDigits, cx, digitBottom);
  ctx.shadowBlur = 0;
  drawUnitText(ctx, '%', cx + digitWidth * 1.1, digitBottom + size * 0.1, size * 0.52);
}

function drawGauge(
  ctx: CanvasRenderingContext2D,
  rect: Rect,
  value: number | null,
  label: string,
) {
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h * 0.58;
  const radius = Math.min(rect.w * 0.43, rect.h * 0.48);
  const segmentCount = 32;
  const litCount =
    value === null ? 0 : Math.round((Math.max(0, Math.min(100, value)) / 100) * segmentCount);
  const segmentW = Math.max(3, radius * 0.055);
  const segmentH = Math.max(9, radius * 0.18);

  for (let index = 0; index < segmentCount; index += 1) {
    const angle = (-128 + (256 * index) / (segmentCount - 1)) * (Math.PI / 180);
    const bandIndex = Math.min(3, Math.floor((index / segmentCount) * 4));
    const color = GAUGE_BANDS[bandIndex];
    const x = cx + Math.sin(angle) * radius;
    const y = cy - Math.cos(angle) * radius;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.fillStyle = index < litCount ? color : rgba(color, 0.14);
    ctx.shadowColor = index < litCount ? rgba(color, 0.4) : 'transparent';
    ctx.shadowBlur = index < litCount ? radius * 0.08 : 0;
    roundRect(ctx, -segmentW / 2, -segmentH / 2, segmentW, segmentH, segmentW * 0.35);
    ctx.fill();
    ctx.restore();
  }

  drawCenteredPercent(ctx, value, cx, cy, radius * 0.6);
  drawText(ctx, label, cx, rect.y + rect.h - radius * 0.05, Math.max(12, radius * 0.19), 'center');
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  ctx.beginPath();
  ctx.roundRect(x, y, width, height, radius);
}

function panelLayout(width: number, height: number) {
  const pad = Math.max(2, Math.min(width, height) * 0.005);
  const line = 1;
  const grid: Rect = {
    x: pad,
    y: pad,
    w: width - pad * 2,
    h: height - pad * 2,
  };
  const col = (grid.w - line * 2) / 3;
  const row = (grid.h - line) / 2;
  return {
    pad,
    line,
    grid,
    cpu: { x: grid.x, y: grid.y, w: col, h: row },
    cores: { x: grid.x + col + line, y: grid.y, w: col * 2 + line, h: row },
    gpu: { x: grid.x, y: grid.y + row + line, w: col, h: row },
    ram: { x: grid.x + col + line, y: grid.y + row + line, w: col, h: row },
    io: { x: grid.x + (col + line) * 2, y: grid.y + row + line, w: col, h: row },
  };
}

function inset(rect: Rect, amount: number): Rect {
  return {
    x: rect.x + amount,
    y: rect.y + amount,
    w: Math.max(0, rect.w - amount * 2),
    h: Math.max(0, rect.h - amount * 2),
  };
}

function drawPanelHeader(
  ctx: CanvasRenderingContext2D,
  rect: Rect,
  label: string,
  headline?: FormattedValue,
  headlineMask?: string,
  headlineSize?: number,
  outerRect?: Rect,
): { digitRight?: number } {
  const labelSize = Math.max(11, Math.min(rect.w, rect.h) * 0.055);
  const valueSize = headlineSize ?? labelSize * 0.95;
  const labelOrigin = outerRect ?? rect;
  drawPanelLabel(ctx, label, labelOrigin.x, labelOrigin.y, labelSize);
  if (headline) {
    const { digitRight } = drawSegmentValue(
      ctx,
      headline,
      headlineMask ?? headline.digits.replace(/[0-9-]/g, '8'),
      rect.x + rect.w,
      rect.y + valueSize * 0.62,
      valueSize,
      { align: 'right', maxRight: rect.x + rect.w, unitSize: valueSize * 0.46 },
    );
    return { digitRight };
  }
  return {};
}

function drawClockPowerTempRow(
  ctx: CanvasRenderingContext2D,
  r: Rect,
  rect: Rect,
  label: string,
  clock: FormattedValue,
  power: FormattedValue,
  temp: FormattedValue,
) {
  // Text is normally sized off panel height; on a square-ish panel (low
  // aspect ratio) that can produce power/temperature values wider than the
  // half-width each gets, so they collide in the middle. Shrink to whatever
  // actually fits, measured against the segment font at the candidate size.
  let small = Math.max(13, rect.h * 0.11);
  const halfWidth = r.w * 0.46;
  small = Math.min(
    small,
    fitSegmentValueSize(ctx, power, '888', small, halfWidth, { unitSize: small * 0.48 }),
    fitSegmentValueSize(ctx, temp, '888', small, halfWidth, { unitSize: small * 0.48 }),
  );
  const header = drawPanelHeader(ctx, r, label, clock, '8888', small, rect);
  const y = r.y + rect.h * 0.22;
  drawSegmentValue(ctx, power, '888', r.x, y, small, {
    align: 'left',
    maxRight: r.x + r.w * 0.48,
    unitSize: small * 0.48,
  });
  // Align the temperature digits' right edge with the clock header's digits
  // (not just its overall maxRight) - "MHz" and "degC" reserve different unit
  // widths, so matching maxRight alone still leaves the digits misaligned.
  drawSegmentValue(ctx, temp, '888', r.x + r.w, y, small, {
    align: 'right',
    digitsRight: header.digitRight,
    unitSize: small * 0.48,
  });
  return small;
}

function drawCpuPanel(ctx: CanvasRenderingContext2D, rect: Rect, values: Record<string, MetricValue>) {
  const r = inset(rect, Math.max(4, rect.w * 0.02));
  drawClockPowerTempRow(
    ctx,
    r,
    rect,
    'CPU',
    integerValue(numberValue(values['cpu.clock_average']?.value), 'MHz'),
    integerValue(numberValue(values['cpu.power_package']?.value), 'W'),
    integerValue(numberValue(values['cpu.temperature_package']?.value), '°C'),
  );
  drawGauge(ctx, { x: r.x, y: r.y + rect.h * 0.24, w: r.w, h: rect.h * 0.68 }, clampPercent(numberValue(values['cpu.utilization']?.value)), 'UTIL');
}

function drawGpuPanel(ctx: CanvasRenderingContext2D, rect: Rect, values: Record<string, MetricValue>) {
  const r = inset(rect, Math.max(4, rect.w * 0.02));
  drawClockPowerTempRow(
    ctx,
    r,
    rect,
    'GPU',
    integerValue(numberValue(values['gpu.core_clock_mhz']?.value), 'MHz'),
    integerValue(numberValue(values['gpu.power_draw_w']?.value), 'W'),
    integerValue(numberValue(values['gpu.temperature_c']?.value), '°C'),
  );
  const gaugeY = r.y + rect.h * 0.31;
  const gaugeH = rect.h * 0.56;
  const gap = r.w * 0.04;
  drawGauge(ctx, { x: r.x, y: gaugeY, w: (r.w - gap) / 2, h: gaugeH }, clampPercent(numberValue(values['gpu.utilization']?.value)), 'UTIL');
  const used = numberValue(values['gpu.memory_used_bytes']?.value);
  const total = numberValue(values['gpu.memory_total_bytes']?.value);
  const vram = used !== null && total ? clampPercent((used / total) * 100) : null;
  drawGauge(ctx, { x: r.x + (r.w + gap) / 2, y: gaugeY, w: (r.w - gap) / 2, h: gaugeH }, vram, 'VRAM');
}

function drawMemoryPanel(ctx: CanvasRenderingContext2D, rect: Rect, values: Record<string, MetricValue>) {
  const r = inset(rect, Math.max(4, rect.w * 0.02));
  drawPanelHeader(ctx, r, 'RAM', undefined, undefined, undefined, rect);
  const top = { x: r.x, y: r.y + rect.h * 0.1, w: r.w, h: rect.h * 0.42 };
  const bottom = { x: r.x, y: r.y + rect.h * 0.53, w: r.w, h: rect.h * 0.42 };
  drawMemorySection(ctx, top, 'PHYS', numberValue(values['memory.physical.used']?.value), numberValue(values['memory.physical.total']?.value), clampPercent(numberValue(values['memory.physical.percent']?.value)));
  drawMemorySection(ctx, bottom, 'SWAP', numberValue(values['memory.swap.used']?.value), numberValue(values['memory.swap.total']?.value), clampPercent(numberValue(values['memory.swap.percent']?.value)));
}

function drawMemorySection(
  ctx: CanvasRenderingContext2D,
  rect: Rect,
  label: string,
  used: number | null,
  total: number | null,
  percent: number | null,
) {
  const gaugeRect = { x: rect.x, y: rect.y, w: rect.w * 0.42, h: rect.h };
  const textLeft = rect.x + rect.w * 0.45;
  const valueX = rect.x + rect.w;
  const resolvedPercent = percent ?? (used !== null && total ? clampPercent((used / total) * 100) : null);
  drawGauge(ctx, gaugeRect, resolvedPercent, label);
  // Cap the value size to what actually fits between the gauge and the right
  // edge - on a square-ish panel the height-based size can be wide enough to
  // overlap the gauge.
  const usedValue = bytesValue(used);
  const totalValue = bytesValue(total);
  const availableWidth = (valueX - textLeft) * 0.96;
  let size = Math.max(13, rect.h * 0.28);
  size = Math.min(
    size,
    fitSegmentValueSize(ctx, usedValue, '8888.8', size, availableWidth, { unitLayout: 'bank', unitSize: size * 0.4 }),
    fitSegmentValueSize(ctx, totalValue, '8888.8', size, availableWidth, { unitLayout: 'bank', unitSize: size * 0.4 }),
  );
  drawText(ctx, 'USED', textLeft, rect.y + rect.h * 0.08, size * 0.52);
  drawSegmentValue(ctx, usedValue, '8888.8', valueX, rect.y + rect.h * 0.32, size, {
    align: 'right',
    maxRight: valueX,
    unitLayout: 'bank',
    unitSize: size * 0.4,
  });
  drawText(ctx, 'TOTAL', textLeft, rect.y + rect.h * 0.58, size * 0.52);
  drawSegmentValue(ctx, totalValue, '8888.8', valueX, rect.y + rect.h * 0.82, size, {
    align: 'right',
    maxRight: valueX,
    unitLayout: 'bank',
    unitSize: size * 0.4,
  });
}

function drawIoPanel(ctx: CanvasRenderingContext2D, rect: Rect, values: Record<string, MetricValue>) {
  const r = inset(rect, Math.max(4, rect.w * 0.02));
  const sectionH = r.h / 2;
  const midY = r.y + sectionH;
  // Match the labelSize formula drawPanelHeader uses for the CPU/GPU/RAM panels
  // so DISK/NET labels are the same size as every other panel label.
  const labelSize = Math.max(11, Math.min(r.w, r.h) * 0.055);
  ctx.fillStyle = COLORS.line;
  // Span the full outer width (not just the inset content width) so this
  // divider reaches the NET label's left edge below.
  ctx.fillRect(rect.x, midY, rect.w, 1);
  drawIoSection(
    ctx,
    'DISK',
    [
      ['W', rateValue(numberValue(values['disk.bytes_written_per_s']?.value))],
      ['R', rateValue(numberValue(values['disk.bytes_read_per_s']?.value))],
    ],
    r.x,
    r.y,
    r.w,
    sectionH,
    labelSize,
    { x: rect.x, y: rect.y },
  );
  drawIoSection(
    ctx,
    'NET',
    [
      ['TX', rateValue(numberValue(values['network.bytes_sent_per_s']?.value))],
      ['RX', rateValue(numberValue(values['network.bytes_recv_per_s']?.value))],
    ],
    r.x,
    midY,
    r.w,
    sectionH,
    labelSize,
    { x: rect.x, y: midY },
  );
}

function drawIoSection(
  ctx: CanvasRenderingContext2D,
  label: string,
  rows: Array<[string, FormattedValue]>,
  x: number,
  y: number,
  width: number,
  height: number,
  labelSize: number,
  labelOrigin: { x: number; y: number },
) {
  drawPanelLabel(ctx, label, labelOrigin.x, labelOrigin.y, labelSize);
  let size = Math.max(11, height * 0.26);
  // Reserve space for the row label ("W"/"R"/"TX"/"RX") before fitting the
  // value - on a square-ish panel the height-based size can otherwise be wide
  // enough that the right-aligned value runs into the label on the left.
  const labelGap = size * 0.5;
  size = Math.min(
    size,
    ...rows.map(([rowLabel, value]) => {
      ctx.font = font(size * 0.75);
      const labelWidth = ctx.measureText(rowLabel).width;
      const available = (width - labelWidth - labelGap) * 0.96;
      return fitSegmentValueSize(ctx, value, '8888.8', size, available, { unitLayout: 'bank' });
    }),
  );
  drawIoLine(ctx, rows[0][0], rows[0][1], x, y + height * 0.45, width, size);
  drawIoLine(ctx, rows[1][0], rows[1][1], x, y + height * 0.78, width, size);
}

function drawIoLine(
  ctx: CanvasRenderingContext2D,
  label: string,
  value: FormattedValue,
  x: number,
  y: number,
  width: number,
  size: number,
) {
  drawText(ctx, label, x, y, size * 0.75, 'left');
  drawSegmentValue(ctx, value, '8888.8', x + width, y, size, {
    align: 'right',
    maxRight: x + width,
    unitLayout: 'bank',
  });
}

function drawCorePanel(
  ctx: CanvasRenderingContext2D,
  rect: Rect,
  values: Record<string, MetricValue>,
  coreHistory: number[][],
) {
  const r = inset(rect, Math.max(4, rect.h * 0.025));
  const currentCores = arrayValue(values['cpu.utilization_percore']?.value);
  const count = Math.max(currentCores.length, coreHistory.length, 16);
  const columns = Math.max(1, Math.ceil(Math.sqrt(count)));
  const rows = Math.max(1, Math.ceil(count / columns));
  const gridTop = r.y + rect.h * 0.02;
  const colGap = Math.max(2, Math.min(6, rect.h * 0.014));
  const rowGap = Math.max(1, Math.min(4, rect.h * 0.008));
  const cellW = (r.w - colGap * (columns - 1)) / columns;
  const cellH = (r.y + r.h - gridTop - rowGap * (rows - 1)) / rows;
  for (let index = 0; index < count; index += 1) {
    const col = index % columns;
    const row = Math.floor(index / columns);
    const cell = {
      x: r.x + col * (cellW + colGap),
      y: gridTop + row * (cellH + rowGap),
      w: cellW,
      h: cellH,
    };
    drawCoreCell(ctx, cell, index, clampPercent(currentCores[index] ?? null), coreHistory[index] ?? []);
  }
}

function drawCoreCell(
  ctx: CanvasRenderingContext2D,
  rect: Rect,
  index: number,
  value: number | null,
  history: number[],
) {
  const labelSize = Math.max(8, Math.min(rect.h * 0.34, rect.w * 0.09));
  const valueSize = Math.max(9, Math.min(rect.h * 0.34, rect.w * 0.1));
  const chartY = rect.y + rect.h * 0.1;
  const chartH = rect.h * 0.78;
  ctx.font = font(labelSize);
  const labelW = ctx.measureText(`C${index}`).width;
  const valueW = valueSize * 2.75;
  const stackW = Math.max(labelW, valueW);
  const stackGap = Math.max(3, rect.w * 0.025);
  ctx.font = font(labelSize);
  ctx.textAlign = 'right';
  ctx.textBaseline = 'top';
  ctx.fillStyle = COLORS.white;
  ctx.fillText(`C${index}`, rect.x + stackW, chartY);
  drawSegmentValue(ctx, { digits: value === null ? '--' : String(Math.round(value)), unit: '%' }, '188', rect.x + stackW, chartY + chartH - valueSize * 0.42, valueSize, {
    align: 'right',
    maxRight: rect.x + stackW,
    unitLayout: 'percent',
    unitSize: valueSize * 0.52,
  });
  const chart = {
    x: rect.x + stackW + stackGap,
    y: chartY,
    w: Math.max(1, rect.w - stackW - stackGap),
    h: chartH,
  };
  drawCoreHistory(ctx, chart, history);
}

function drawCoreHistory(ctx: CanvasRenderingContext2D, rect: Rect, values: number[]) {
  const gap = 1;
  const maxCols = CORE_HISTORY_LIMIT;
  const dot = Math.max(1, Math.floor(Math.min(rect.h / 4, rect.w / 18)));
  const rows = Math.max(3, Math.floor((rect.h + gap) / (dot + gap)));
  const cols = Math.max(6, Math.min(maxCols, Math.floor((rect.w + gap) / (dot + gap))));
  const gridW = cols * dot + (cols - 1) * gap;
  const gridH = rows * dot + (rows - 1) * gap;
  const startX = rect.x + Math.max(0, rect.w - gridW);
  const startY = rect.y + Math.max(0, (rect.h - gridH) / 2);
  for (let col = 0; col < cols; col += 1) {
    const value = values[col - (cols - values.length)] ?? null;
    const level = value === null ? 0 : Math.max(0, Math.min(rows, Math.ceil((value / 100) * rows)));
    for (let row = 0; row < rows; row += 1) {
      const band = rows - row;
      const color = GAUGE_BANDS[Math.min(3, Math.floor(((band - 1) / rows) * 4))];
      const lit = rows - row <= level;
      ctx.fillStyle = lit ? color : rgba(color, 0.12);
      roundRect(ctx, startX + col * (dot + gap), startY + row * (dot + gap), dot, dot, Math.min(2, dot * 0.3));
      ctx.fill();
    }
  }
}

function drawDashboard(
  canvas: HTMLCanvasElement,
  values: Record<string, MetricValue>,
  coreHistory: number[][],
) {
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = COLORS.black;
  ctx.fillRect(0, 0, width, height);

  const layout = panelLayout(width, height);
  ctx.fillStyle = COLORS.line;
  ctx.fillRect(layout.grid.x + layout.cpu.w, layout.grid.y + layout.cpu.h + layout.line, layout.line, layout.cpu.h);
  ctx.fillRect(layout.grid.x + layout.cpu.w + layout.line + layout.ram.w, layout.grid.y + layout.cpu.h + layout.line, layout.line, layout.cpu.h);
  ctx.fillRect(layout.grid.x + layout.cpu.w, layout.grid.y, layout.line, layout.cpu.h);
  ctx.fillRect(layout.grid.x, layout.grid.y + layout.cpu.h, layout.grid.w, layout.line);

  drawCpuPanel(ctx, layout.cpu, values);
  drawCorePanel(ctx, layout.cores, values, coreHistory);
  drawGpuPanel(ctx, layout.gpu, values);
  drawMemoryPanel(ctx, layout.ram, values);
  drawIoPanel(ctx, layout.io, values);
}

function App() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const longPressTimerRef = useRef<number | null>(null);
  const pointerStartRef = useRef<{ x: number; y: number } | null>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [resizeTick, setResizeTick] = useState(0);
  const { values, coreHistory } = useDashbMetrics();

  useEffect(() => {
    const onResize = () => setResizeTick((current) => current + 1);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const draw = () => {
      if (!cancelled && canvasRef.current) {
        drawDashboard(canvasRef.current, values, coreHistory);
      }
    };
    void document.fonts?.ready.then(draw);
    draw();
    return () => {
      cancelled = true;
    };
  }, [values, coreHistory, resizeTick]);

  const clearLongPress = () => {
    if (longPressTimerRef.current !== null) {
      window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    pointerStartRef.current = null;
  };

  const getLocalPointer = (event: PointerEvent<HTMLElement>) => {
    const nativeEvent = event.nativeEvent;
    if (event.target instanceof HTMLCanvasElement) {
      return { x: nativeEvent.offsetX, y: nativeEvent.offsetY };
    }
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  };

  const handlePointerDown = (event: PointerEvent<HTMLElement>) => {
    if (isMenuOpen) {
      setIsMenuOpen(false);
      return;
    }
    if (event.button !== 0 && event.pointerType === 'mouse') {
      return;
    }
    const position = getLocalPointer(event);
    pointerStartRef.current = position;
    longPressTimerRef.current = window.setTimeout(() => {
      longPressTimerRef.current = null;
      setIsMenuOpen(true);
    }, 550);
  };

  const handlePointerMove = (event: PointerEvent<HTMLElement>) => {
    if (!pointerStartRef.current) {
      return;
    }
    const position = getLocalPointer(event);
    const distance = Math.hypot(position.x - pointerStartRef.current.x, position.y - pointerStartRef.current.y);
    if (distance > 12) {
      clearLongPress();
    }
  };

  const toggleFullscreen = () => {
    const root = document.documentElement;
    setIsMenuOpen(false);
    if (document.fullscreenElement) {
      void document.exitFullscreen();
      return;
    }
    void root.requestFullscreen?.();
  };

  return (
    <main
      className="segments-screen"
      onContextMenu={(event) => event.preventDefault()}
      onPointerCancel={clearLongPress}
      onPointerDown={handlePointerDown}
      onPointerLeave={clearLongPress}
      onPointerMove={handlePointerMove}
      onPointerUp={clearLongPress}
    >
      <canvas ref={canvasRef} className="segments-canvas" />
      {isMenuOpen && (
        <div
          className="segments-menu"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <button className="segments-menu-button" type="button" onClick={toggleFullscreen}>
            {document.fullscreenElement ? 'Exit fullscreen' : 'Enter fullscreen'}
          </button>
        </div>
      )}
    </main>
  );
}

export default App;

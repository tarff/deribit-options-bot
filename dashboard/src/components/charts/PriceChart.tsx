import { useEffect, useRef } from 'react';
import { createChart, ColorType, type IChartApi, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts';
import { colors, chartColors } from '../../styles/theme';

interface ChartDataPoint {
  time: number;
  value?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
}

interface PriceChartProps {
  data: ChartDataPoint[];
  type?: 'line' | 'candlestick';
  height?: number;
  showVolume?: boolean;
  lineColor?: string;
  title?: string;
}

export function PriceChart({
  data,
  type = 'line',
  height = 400,
  lineColor = chartColors.btcLine,
  title,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Line'> | ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: colors.bgCard },
        textColor: colors.textMuted,
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: chartColors.gridLines },
        horzLines: { color: chartColors.gridLines },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: chartColors.crosshair,
          labelBackgroundColor: colors.bgSecondary,
        },
        horzLine: {
          color: chartColors.crosshair,
          labelBackgroundColor: colors.bgSecondary,
        },
      },
      rightPriceScale: {
        borderColor: colors.border,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: colors.border,
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: height,
    });

    chartRef.current = chart;

    if (type === 'line') {
      const series = chart.addLineSeries({
        color: lineColor,
        lineWidth: 2,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 4,
        crosshairMarkerBackgroundColor: lineColor,
        priceFormat: {
          type: 'price',
          precision: 2,
          minMove: 0.01,
        },
      });
      seriesRef.current = series;

      if (data.length > 0) {
        const lineData = data.map((d) => ({
          time: d.time as UTCTimestamp,
          value: d.value ?? d.close ?? 0,
        }));
        series.setData(lineData);
      }
    } else {
      const series = chart.addCandlestickSeries({
        upColor: colors.profitGreen,
        downColor: colors.lossRed,
        borderUpColor: colors.profitGreen,
        borderDownColor: colors.lossRed,
        wickUpColor: colors.profitGreen,
        wickDownColor: colors.lossRed,
      });
      seriesRef.current = series;

      if (data.length > 0) {
        const candleData = data.map((d) => ({
          time: d.time as UTCTimestamp,
          open: d.open ?? 0,
          high: d.high ?? 0,
          low: d.low ?? 0,
          close: d.close ?? 0,
        }));
        series.setData(candleData);
      }
    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [type, height, lineColor]);

  // Update data when it changes
  useEffect(() => {
    if (seriesRef.current && data.length > 0) {
      if (type === 'line') {
        const lineData = data.map((d) => ({
          time: d.time as UTCTimestamp,
          value: d.value ?? d.close ?? 0,
        }));
        (seriesRef.current as ISeriesApi<'Line'>).setData(lineData);
      } else {
        const candleData = data.map((d) => ({
          time: d.time as UTCTimestamp,
          open: d.open ?? 0,
          high: d.high ?? 0,
          low: d.low ?? 0,
          close: d.close ?? 0,
        }));
        (seriesRef.current as ISeriesApi<'Candlestick'>).setData(candleData);
      }
      chartRef.current?.timeScale().fitContent();
    }
  }, [data, type]);

  return (
    <div className="card">
      {title && (
        <h3 className="text-sm font-display uppercase tracking-wider text-text-muted mb-4">
          {title}
        </h3>
      )}
      <div ref={containerRef} className="rounded-lg overflow-hidden" />
    </div>
  );
}

export default PriceChart;

import { useEffect, useRef } from 'react';
import { createChart, ColorType, type IChartApi, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts';
import { colors, chartColors } from '../../styles/theme';

interface DvolDataPoint {
  time: UTCTimestamp;
  value: number;
}

interface DvolChartProps {
  data: DvolDataPoint[];
  height?: number;
  showThresholds?: boolean;
}

export function DvolChart({
  data,
  height = 300,
  showThresholds = true,
}: DvolChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null);

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

    // Main DVOL line
    const series = chart.addLineSeries({
      color: chartColors.dvolLine,
      lineWidth: 2,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
      crosshairMarkerBackgroundColor: chartColors.dvolLine,
      priceFormat: {
        type: 'price',
        precision: 1,
        minMove: 0.1,
      },
    });
    seriesRef.current = series;

    if (data.length > 0) {
      series.setData(data);
    }

    // Add threshold lines
    if (showThresholds) {
      // High stress threshold (60)
      const highStressLine = chart.addLineSeries({
        color: colors.warningAmber,
        lineWidth: 1,
        lineStyle: 2, // Dashed
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });

      // Extreme fear threshold (80)
      const extremeFearLine = chart.addLineSeries({
        color: colors.lossRed,
        lineWidth: 1,
        lineStyle: 2, // Dashed
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });

      if (data.length > 0) {
        const firstTime = data[0].time;
        const lastTime = data[data.length - 1].time;

        highStressLine.setData([
          { time: firstTime, value: 60 },
          { time: lastTime, value: 60 },
        ]);

        extremeFearLine.setData([
          { time: firstTime, value: 80 },
          { time: lastTime, value: 80 },
        ]);
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
  }, [height, showThresholds]);

  // Update data
  useEffect(() => {
    if (seriesRef.current && data.length > 0) {
      seriesRef.current.setData(data);
      chartRef.current?.timeScale().fitContent();
    }
  }, [data]);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-display uppercase tracking-wider text-text-muted">
          DVOL Index
        </h3>
        {showThresholds && (
          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-1">
              <div className="w-3 h-0.5 bg-warning" />
              <span className="text-text-muted">60 High Stress</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-0.5 bg-loss" />
              <span className="text-text-muted">80 Extreme Fear</span>
            </div>
          </div>
        )}
      </div>
      <div ref={containerRef} className="rounded-lg overflow-hidden" />
    </div>
  );
}

export default DvolChart;

/**
 * ConfidenceGauge — Animated circular gauge for impact score.
 */
export default function ConfidenceGauge({ score = 0, size = 64, strokeWidth = 4 }) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(1, score));
  const offset = circumference * (1 - pct);

  // Color based on score
  const color = pct >= 0.7 ? '#22c55e' : pct >= 0.4 ? '#f59e0b' : '#8b95ad';

  return (
    <div className="gauge-container">
      <div className="gauge-ring" style={{ width: size, height: size }}>
        <svg width={size} height={size}>
          <circle
            className="gauge-ring__bg"
            cx={size / 2}
            cy={size / 2}
            r={radius}
            strokeWidth={strokeWidth}
          />
          <circle
            className="gauge-ring__fill"
            cx={size / 2}
            cy={size / 2}
            r={radius}
            strokeWidth={strokeWidth}
            stroke={color}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
          />
        </svg>
        <div className="gauge-ring__value" style={{ color }}>
          {(pct * 100).toFixed(0)}
        </div>
      </div>
    </div>
  );
}

/**
 * SentimentBadge — Color-coded pill showing sentiment and confidence.
 */
export default function SentimentBadge({ sentiment, confidence }) {
  const type = (sentiment || 'NEUTRAL').toUpperCase();
  const label = type.charAt(0) + type.slice(1).toLowerCase();
  const modifier = type === 'POSITIVE' ? 'positive' : type === 'NEGATIVE' ? 'negative' : 'neutral';

  return (
    <span className={`sentiment-badge sentiment-badge--${modifier}`}>
      <span className={`sentiment-dot sentiment-dot--${modifier}`} />
      {label}
      {confidence != null && (
        <span style={{ opacity: 0.7, marginLeft: 4, fontSize: '0.688rem' }}>
          {(confidence * 100).toFixed(0)}%
        </span>
      )}
    </span>
  );
}

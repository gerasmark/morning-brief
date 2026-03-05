import { useEffect, useMemo, useState } from 'react';
import { sourceIconUrl } from '../sourceIcon';

type Props = {
  source: string;
  size?: number;
};

export default function SourceIcon({ source, size = 14 }: Props) {
  const [failed, setFailed] = useState(false);
  const iconUrl = useMemo(() => sourceIconUrl(source), [source]);

  useEffect(() => {
    setFailed(false);
  }, [source]);

  if (!iconUrl || failed) {
    return (
      <span
        className="source-icon-fallback"
        style={{ width: size, height: size, minWidth: size, minHeight: size }}
        aria-hidden="true"
      >
        📰
      </span>
    );
  }

  return (
    <img
      className="source-icon-img"
      src={iconUrl}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

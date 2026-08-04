import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { whatsappAPI } from '../../services/api';

/** Load CRM-proxied WATI media with auth (img/audio can't send Bearer headers). */
export function WaAuthenticatedMedia({ mediaUrl, kind, alt }) {
  const [src, setSrc] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let objectUrl = null;
    let cancelled = false;

    const run = async () => {
      setError(false);
      setSrc(null);
      if (!mediaUrl) {
        setError(true);
        return;
      }
      // Public HTTPS (e.g. our brochure CDN) — use directly
      if (/^https?:\/\//i.test(mediaUrl) && !mediaUrl.includes('/whatsapp/media')) {
        if (!cancelled) setSrc(mediaUrl);
        return;
      }
      try {
        let fileName = '';
        try {
          const u = new URL(mediaUrl, window.location.origin);
          fileName = u.searchParams.get('fileName') || '';
        } catch {
          const m = /fileName=([^&]+)/.exec(mediaUrl);
          fileName = m ? decodeURIComponent(m[1]) : '';
        }
        if (!fileName && mediaUrl.startsWith('data/')) {
          fileName = mediaUrl;
        }
        if (!fileName) {
          if (!cancelled) setError(true);
          return;
        }
        const res = await whatsappAPI.getMediaBlob(fileName);
        objectUrl = URL.createObjectURL(res.data);
        if (!cancelled) setSrc(objectUrl);
      } catch (e) {
        console.warn('WhatsApp media load failed', e);
        if (!cancelled) setError(true);
      }
    };

    run();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [mediaUrl]);

  if (error) {
    return <p className="text-xs opacity-80">Could not load media</p>;
  }
  if (!src) {
    return (
      <div className="flex items-center gap-2 text-xs opacity-80 py-2">
        <Loader2 size={14} className="animate-spin" />
        Loading…
      </div>
    );
  }
  if (kind === 'image') {
    return (
      <a href={src} target="_blank" rel="noopener noreferrer" className="block">
        <img
          src={src}
          alt={alt || 'Image'}
          className="max-w-full max-h-64 rounded-lg object-contain bg-black/20"
        />
      </a>
    );
  }
  if (kind === 'audio') {
    return <audio controls src={src} className="w-full max-w-[260px]" preload="metadata" />;
  }
  if (kind === 'video') {
    return (
      <video controls src={src} className="max-w-full max-h-64 rounded-lg" preload="metadata" />
    );
  }
  return (
    <a href={src} target="_blank" rel="noopener noreferrer" className="text-xs underline opacity-90">
      Open file
    </a>
  );
}

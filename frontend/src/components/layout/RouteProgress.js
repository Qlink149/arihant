import React, { useEffect, useState, useRef } from 'react';
import { useLocation } from 'react-router-dom';

/** Top bar on client-side route changes (works with BrowserRouter; not data-router-only). */
const RouteProgress = () => {
  const location = useLocation();
  const [visible, setVisible] = useState(false);
  const skipNext = useRef(true);

  useEffect(() => {
    if (skipNext.current) {
      skipNext.current = false;
      return;
    }
    setVisible(true);
    const done = setTimeout(() => setVisible(false), 320);
    return () => clearTimeout(done);
  }, [location.pathname, location.search, location.key]);

  if (!visible) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-[100] h-0.5 overflow-hidden pointer-events-none">
      <div
        className="h-full w-1/3 bg-gradient-to-r from-transparent via-[#C5A059] to-transparent animate-pulse"
        style={{ animation: 'vcRouteShimmer 1.1s ease-in-out infinite' }}
      />
      <style>{`
        @keyframes vcRouteShimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(400%); }
        }
      `}</style>
    </div>
  );
};

export default RouteProgress;

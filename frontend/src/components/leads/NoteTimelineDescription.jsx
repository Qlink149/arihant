import React from 'react';
import { missingMentionNames, splitMentionSegments } from '../../utils/noteMentions';

/**
 * Timeline note body: highlight @mentions; show legacy chips when names were only in metadata.
 */
export default function NoteTimelineDescription({
  description = '',
  mentionedNames = [],
  className = 'text-crm-fg',
  'data-testid': testId = 'timeline-note-description',
}) {
  const segments = splitMentionSegments(description);
  const legacy = missingMentionNames(description, mentionedNames);

  return (
    <div data-testid={testId}>
      {description ? (
        <p className={`${className} whitespace-pre-wrap break-words`}>
          {segments.map((seg, i) =>
            seg.type === 'mention' ? (
              <span
                key={`m-${i}`}
                className="text-[#C5A059] font-medium"
                data-testid="timeline-mention-token"
              >
                {seg.value}
              </span>
            ) : (
              <span key={`t-${i}`}>{seg.value}</span>
            )
          )}
        </p>
      ) : null}
      {legacy.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2" data-testid="timeline-legacy-mentions">
          {legacy.map((name) => (
            <span
              key={name}
              className="inline-flex items-center rounded-full border border-[#C5A059]/40 bg-[#C5A059]/10 px-2 py-0.5 text-xs text-[#C5A059]"
            >
              @{name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

import React from 'react';
import { Check, CheckCheck, File, Headphones, Image as ImageIcon } from 'lucide-react';
import { formatTimeIST } from '../../utils/datetime';
import { WaAuthenticatedMedia } from './WaAuthenticatedMedia';

export function MessageStatus({ status }) {
  if (!status) return null;
  if (status === 'submitted') return <Check size={11} className="opacity-50 text-green-200" />;
  if (status === 'sent') return <Check size={11} className="text-green-200" />;
  if (status === 'delivered') return <CheckCheck size={11} className="text-green-200" />;
  if (status === 'read') return <CheckCheck size={11} className="text-blue-300" />;
  if (status === 'failed') return <span className="text-red-400 text-xs leading-none">✗</span>;
  return null;
}

/** Typed WhatsApp bubble — text / image / audio / document / template. */
export function ChatMessageBubble({ msg }) {
  const outbound = msg.direction === 'outbound';
  const type = String(msg.message_type || '').toLowerCase();
  const fileHint = `${msg.media_filename || ''} ${msg.media_url || ''} ${msg.content || ''}`.toLowerCase();
  const isImage =
    type === 'image' ||
    /\.(jpe?g|png|webp|gif|bmp)(\?|$)/i.test(fileHint) ||
    /\/images\//i.test(fileHint);
  const isAudio =
    type === 'audio' ||
    type === 'voice' ||
    /\.(ogg|mp3|m4a|aac|opus|amr|wav)(\?|$)/i.test(fileHint) ||
    /\/audio\//i.test(fileHint);
  const isVideo =
    type === 'video' ||
    /\.(mp4|3gp|mov|webm)(\?|$)/i.test(fileHint) ||
    /\/video\//i.test(fileHint);
  const isDocument =
    !isImage &&
    !isAudio &&
    !isVideo &&
    (type === 'document' ||
      Boolean(msg.media_filename) ||
      Boolean(msg.media_url) ||
      /\.pdf(\?|$)/i.test(fileHint));
  const isTemplate = type === 'template' || Boolean(msg.template_name);
  const displayName =
    msg.media_display_name ||
    (msg.media_filename || '').split(/[/\\]/).pop() ||
    msg.content ||
    'File';

  let body;
  if (isImage) {
    body = (
      <div className="wa-bubble-text text-sm space-y-1">
        <div className="flex items-center gap-1.5 text-xs opacity-80 mb-1">
          <ImageIcon size={12} />
          <span>Image</span>
        </div>
        <WaAuthenticatedMedia
          mediaUrl={msg.media_url || msg.media_filename}
          kind="image"
          alt={displayName}
        />
      </div>
    );
  } else if (isAudio) {
    body = (
      <div className="wa-bubble-text text-sm space-y-1">
        <div className="flex items-center gap-1.5 text-xs opacity-80 mb-1">
          <Headphones size={12} />
          <span>Audio</span>
        </div>
        <WaAuthenticatedMedia mediaUrl={msg.media_url || msg.media_filename} kind="audio" />
      </div>
    );
  } else if (isVideo) {
    body = (
      <div className="wa-bubble-text text-sm space-y-1">
        <WaAuthenticatedMedia mediaUrl={msg.media_url || msg.media_filename} kind="video" />
      </div>
    );
  } else if (isDocument) {
    body = (
      <div className="wa-bubble-text text-sm space-y-1">
        <div className="flex items-start gap-2">
          <File size={16} className="mt-0.5 shrink-0 opacity-90" />
          <div className="min-w-0">
            <p className="font-medium truncate">{displayName}</p>
            <p className="text-xs opacity-80">
              {/\.pdf/i.test(displayName) ? 'PDF document' : 'Document'}
            </p>
            {msg.media_url || msg.media_filename ? (
              <div className="mt-1">
                <WaAuthenticatedMedia
                  mediaUrl={msg.media_url || msg.media_filename}
                  kind="document"
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    );
  } else if (isTemplate && !msg.reply_label) {
    body = (
      <div className="wa-bubble-text text-sm space-y-0.5">
        <p className="text-xs uppercase tracking-wide opacity-70">Template</p>
        <p className="whitespace-pre-wrap">{msg.content}</p>
      </div>
    );
  } else {
    body = (
      <p className="wa-bubble-text text-sm whitespace-pre-wrap">
        {msg.reply_label || msg.content}
      </p>
    );
  }

  return (
    <div className={`flex ${outbound ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] px-4 py-3 rounded-2xl ${
          outbound
            ? 'wa-bubble-out bg-green-600 text-white text-on-brand rounded-br-md'
            : 'wa-bubble-in bg-[#262626] text-white rounded-bl-md'
        }`}
      >
        {body}
        <div
          className={`wa-bubble-meta flex items-center gap-2 mt-1 text-xs ${
            outbound ? 'text-green-200' : 'text-crm-fg-muted'
          }`}
        >
          <span>{formatTimeIST(msg.created_at) || '—'}</span>
          {outbound ? <MessageStatus status={msg.status} /> : null}
        </div>
      </div>
    </div>
  );
}

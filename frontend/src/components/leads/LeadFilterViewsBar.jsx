import React, { useMemo, useState, memo } from 'react';
import { Bookmark, BookmarkPlus, ChevronDown, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '../ui/button';
import { CrmBadge } from '../ui/CrmBadge';
import { Input } from '../ui/input';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import { filtersMatchView } from '../../utils/leadFilters';

export const LeadFilterViewsBar = memo(function LeadFilterViewsBar({
  views = [],
  loading = false,
  currentFilters,
  currentSearch,
  activeViewId,
  onApplyView,
  onSaveView,
  onUpdateView,
  onDeleteView,
  onClearActiveView,
}) {
  const [listOpen, setListOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameView, setRenameView] = useState(null);
  const [renameName, setRenameName] = useState('');
  const [renaming, setRenaming] = useState(false);

  const matchedView = useMemo(
    () => views.find((v) => filtersMatchView(currentFilters, currentSearch, v.filters)),
    [views, currentFilters, currentSearch]
  );

  const effectiveActiveId = useMemo(() => {
    if (activeViewId) {
      const view = views.find((v) => v.id === activeViewId);
      if (view && filtersMatchView(currentFilters, currentSearch, view.filters)) {
        return activeViewId;
      }
    }
    return matchedView?.id || null;
  }, [activeViewId, views, currentFilters, currentSearch, matchedView]);

  const activeView = useMemo(
    () => views.find((v) => v.id === effectiveActiveId) || null,
    [views, effectiveActiveId]
  );

  const pinnedView = activeViewId ? views.find((v) => v.id === activeViewId) || null : null;
  const filtersChangedFromActive = useMemo(
    () => pinnedView && !filtersMatchView(currentFilters, currentSearch, pinnedView.filters),
    [pinnedView, currentFilters, currentSearch],
  );

  const handleSave = async () => {
    const name = saveName.trim();
    if (!name) {
      toast.error('Enter a name for this view');
      return;
    }
    setSaving(true);
    try {
      await onSaveView(name);
      setSaveOpen(false);
      setSaveName('');
      toast.success('Filter view saved');
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Failed to save view';
      toast.error(typeof msg === 'string' ? msg : 'Failed to save view');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    if (!pinnedView) return;
    setSaving(true);
    try {
      await onUpdateView(pinnedView.id);
      toast.success('Filter view updated');
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Failed to update view';
      toast.error(typeof msg === 'string' ? msg : 'Failed to update view');
    } finally {
      setSaving(false);
    }
  };

  const openRename = (view) => {
    setRenameView(view);
    setRenameName(view?.name || '');
    setRenameOpen(true);
  };

  const handleRename = async () => {
    const name = renameName.trim();
    if (!renameView?.id || !name) return;
    setRenaming(true);
    try {
      await onUpdateView(renameView.id, { name });
      setRenameOpen(false);
      setRenameView(null);
      toast.success('View renamed');
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Failed to rename view';
      toast.error(typeof msg === 'string' ? msg : 'Failed to rename view');
    } finally {
      setRenaming(false);
    }
  };

  const handleDelete = async (view) => {
    if (!view?.id) return;
    const ok = window.confirm(`Delete saved view "${view.name}"?`);
    if (!ok) return;
    try {
      await onDeleteView(view.id);
      if (effectiveActiveId === view.id && onClearActiveView) onClearActiveView();
      toast.success('Filter view deleted');
    } catch {
      toast.error('Failed to delete view');
    }
  };

  const handleApplyView = (view) => {
    onApplyView(view);
    setListOpen(false);
  };

  const viewsButtonLabel = loading
    ? 'Views'
    : activeView
      ? `Views · ${activeView.name}`
      : views.length > 0
        ? `Views (${views.length})`
        : 'Views';

  return (
    <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-white/5" data-testid="filter-views-bar">
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => setListOpen(true)}
        className="h-8 text-xs bg-crm-elevated border-crm-border text-white hover:bg-white/5"
        data-testid="open-filter-views-btn"
      >
        <Bookmark size={12} className="mr-1.5 text-[#C5A059]" />
        {viewsButtonLabel}
        <ChevronDown size={12} className="ml-1.5 opacity-60" />
      </Button>

      {activeView ? (
        <CrmBadge chip variant="gold" data-testid="active-filter-view-chip">
          {activeView.name}
        </CrmBadge>
      ) : null}

      {pinnedView && filtersChangedFromActive ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleUpdate}
          disabled={saving}
          className="h-8 text-xs bg-crm-elevated border-[#C5A059]/50 text-[#C5A059] hover:bg-[#C5A059]/10"
          data-testid="update-filter-view-btn"
        >
          Update &quot;{pinnedView.name}&quot;
        </Button>
      ) : null}

      <div className="flex items-center gap-2 ml-auto">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setSaveOpen(true)}
          className="h-8 text-xs bg-crm-elevated border-crm-border text-white hover:bg-white/5"
          data-testid="save-filter-view-btn"
        >
          <BookmarkPlus size={12} className="mr-1" />
          Save view
        </Button>
      </div>

      <Dialog open={listOpen} onOpenChange={setListOpen}>
        <DialogContent
          className="bg-crm-elevated border-crm-border text-white sm:max-w-md"
          aria-describedby={undefined}
        >
          <DialogHeader>
            <DialogTitle className="font-serif text-xl">Saved filter views</DialogTitle>
          </DialogHeader>
          <p className="text-crm-fg-secondary text-sm -mt-2">
            Apply a saved combination of filters, date range, and search.
          </p>

          <div className="max-h-[min(50vh,320px)] overflow-y-auto -mx-1 px-1" data-testid="filter-views-list">
            {loading ? (
              <p className="text-crm-fg-muted text-sm py-6 text-center">Loading views…</p>
            ) : views.length === 0 ? (
              <div className="py-8 text-center border border-dashed border-crm-border rounded-lg">
                <Bookmark className="mx-auto text-crm-fg-muted mb-2" size={24} />
                <p className="text-crm-fg-secondary text-sm">No saved views yet</p>
                <p className="text-crm-fg-muted text-xs mt-1">Save your current filters to reuse them later.</p>
              </div>
            ) : (
              <ul className="space-y-2">
                {views.map((view) => {
                  const isActive = view.id === effectiveActiveId;
                  return (
                    <li
                      key={view.id}
                      className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 transition-colors ${
                        isActive
                          ? 'border-[#C5A059]/50 bg-[#C5A059]/10'
                          : 'border-crm-border bg-black/20 hover:border-white/20'
                      }`}
                      data-testid={`filter-view-row-${view.id}`}
                    >
                      <button
                        type="button"
                        onClick={() => handleApplyView(view)}
                        className="flex-1 min-w-0 text-left"
                        data-testid={`filter-view-${view.id}`}
                      >
                        <span className={`text-sm font-medium truncate block ${isActive ? 'text-[#C5A059]' : 'text-white'}`}>
                          {view.name}
                        </span>
                        {isActive ? (
                          <span className="text-[10px] uppercase tracking-wider text-[#C5A059]/80 mt-0.5 block">
                            Active
                          </span>
                        ) : null}
                      </button>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 text-crm-fg-muted hover:text-white shrink-0"
                        onClick={() => openRename(view)}
                        aria-label={`Rename ${view.name}`}
                      >
                        <Pencil size={14} />
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 text-crm-fg-muted hover:text-red-400 shrink-0"
                        onClick={() => handleDelete(view)}
                        aria-label={`Delete ${view.name}`}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <DialogFooter className="gap-2 sm:justify-between">
            <Button
              variant="ghost"
              onClick={() => setListOpen(false)}
              className="text-crm-fg-secondary hover:text-white"
            >
              Close
            </Button>
            <Button
              onClick={() => {
                setListOpen(false);
                setSaveOpen(true);
              }}
              className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90"
            >
              <BookmarkPlus size={14} className="mr-1.5" />
              Save current view
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent className="bg-crm-elevated border-crm-border text-white sm:max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Save filter view</DialogTitle>
          </DialogHeader>
          <p className="text-crm-fg-secondary text-sm">
            Save your current filters, date range, and search as a reusable view.
          </p>
          <Input
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            placeholder="e.g. South Chennai 2-5Cr"
            className="bg-crm-muted border-crm-border text-white"
            maxLength={60}
            data-testid="filter-view-name-input"
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave();
            }}
          />
          <DialogFooter className="gap-2">
            <Button variant="ghost" onClick={() => setSaveOpen(false)} className="text-crm-fg-secondary">
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving} className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90">
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent className="bg-crm-elevated border-crm-border text-white sm:max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Rename view</DialogTitle>
          </DialogHeader>
          <Input
            value={renameName}
            onChange={(e) => setRenameName(e.target.value)}
            className="bg-crm-muted border-crm-border text-white"
            maxLength={60}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleRename();
            }}
          />
          <DialogFooter className="gap-2">
            <Button variant="ghost" onClick={() => setRenameOpen(false)} className="text-crm-fg-secondary">
              Cancel
            </Button>
            <Button onClick={handleRename} disabled={renaming} className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90">
              {renaming ? 'Saving…' : 'Rename'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
});

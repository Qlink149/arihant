import React, { useEffect, useState } from 'react';
import { Pencil } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Button } from '../ui/button';

export function TaskEditModal({ open, onOpenChange, task, onSave, saving }) {
  const [form, setForm] = useState({
    description: '',
    due_date: '',
    priority: 'medium',
  });

  useEffect(() => {
    if (!task) return;
    setForm({
      description: task.description || '',
      due_date: task.due_date || '',
      priority: task.priority || 'medium',
    });
  }, [task, open]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!form.description.trim() || !form.due_date) return;
    onSave?.(task?.id, {
      description: form.description.trim(),
      due_date: form.due_date,
      priority: form.priority,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-lg" data-testid="task-edit-modal">
        <DialogHeader>
          <DialogTitle className="font-serif text-xl flex items-center gap-2">
            <Pencil className="text-[#C5A059]" size={20} />
            Edit Task
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-[#A1A1AA] text-xs mb-1.5 block">Description *</label>
            <input
              type="text"
              value={form.description}
              onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
              className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
              data-testid="edit-task-description"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[#A1A1AA] text-xs mb-1.5 block">Due Date *</label>
              <input
                type="date"
                value={form.due_date}
                onChange={(e) => setForm((p) => ({ ...p, due_date: e.target.value }))}
                className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                data-testid="edit-task-due-date"
              />
            </div>
            <div>
              <label className="text-[#A1A1AA] text-xs mb-1.5 block">Priority</label>
              <select
                value={form.priority}
                onChange={(e) => setForm((p) => ({ ...p, priority: e.target.value }))}
                className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                data-testid="edit-task-priority"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              className="border-white/10 text-white hover:bg-white/5"
              onClick={() => onOpenChange?.(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={saving || !form.description.trim() || !form.due_date}
              className="bg-[#C5A059] text-black hover:bg-[#E5C079] disabled:opacity-50"
              data-testid="save-edit-task-btn"
            >
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default TaskEditModal;

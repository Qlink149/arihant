/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { SelectWithOther } from './SelectWithOther';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './dialog';
import { UI_LEAD_STATUSES as LEAD_STATUSES } from '../../constants/leadStatus';

let container;
let root;

afterEach(() => {
  if (root) {
    act(() => root.unmount());
    root = null;
  }
  if (container) {
    container.remove();
    container = null;
  }
});

function render(ui) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(ui);
  });
}

function AddCustomerFormFixture() {
  const leadSources = ['Facebook Lead Form', 'google', 'management reference'];
  const budgetRanges = ['Under 1Cr', '1-2 Cr', '2-5 Cr', '5 Cr+'];

  return (
    <Dialog open>
      <DialogContent className="bg-[#1A1A1A] text-white" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Add New Customer</DialogTitle>
        </DialogHeader>
        <SelectWithOther value="" options={['Project A']} onChange={() => {}} />
        <SelectWithOther value="" options={budgetRanges} onChange={() => {}} />
        <Select value={undefined} onValueChange={() => {}}>
          <SelectTrigger>
            <SelectValue placeholder="Select Intent" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="Investor">Investor</SelectItem>
            <SelectItem value="Self-Occupation">Self-Occupation</SelectItem>
          </SelectContent>
        </Select>
        <Select value={undefined} onValueChange={() => {}}>
          <SelectTrigger>
            <SelectValue placeholder="Select Source" />
          </SelectTrigger>
          <SelectContent>
            {leadSources.map((source) => (
              <SelectItem key={source} value={source}>{source}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value="__unassigned__" onValueChange={() => {}}>
          <SelectTrigger>
            <SelectValue placeholder="Manager" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__unassigned__">Unassigned</SelectItem>
            <SelectItem value="1">Alice (manager)</SelectItem>
          </SelectContent>
        </Select>
        <div>
          {LEAD_STATUSES.map((status) => (
            <button key={status} type="button">{status}</button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

describe('addCustomerForm', () => {
  it('renders add customer form fixture without throwing', () => {
    expect(() => render(<AddCustomerFormFixture />)).not.toThrow();
    expect(document.body.textContent).toContain('Add New Customer');
  });

  it('renders SelectWithOther with empty value', () => {
    expect(() =>
      render(<SelectWithOther value="" options={['A', 'B']} onChange={() => {}} />)
    ).not.toThrow();
  });

  it('does not loop when options array reference changes with same values', () => {
    const onModeChange = vi.fn();
    function Wrapper() {
      const [tick, setTick] = React.useState(0);
      const options = ['Under 1Cr', '1-2 Cr'];
      React.useEffect(() => {
        if (tick < 3) {
          const id = requestAnimationFrame(() => setTick((n) => n + 1));
          return () => cancelAnimationFrame(id);
        }
        return undefined;
      }, [tick]);
      return (
        <SelectWithOther
          value=""
          options={options}
          onChange={() => {}}
          onModeChange={onModeChange}
        />
      );
    }
    render(<Wrapper />);
    expect(onModeChange.mock.calls.length).toBeLessThan(5);
  });
});

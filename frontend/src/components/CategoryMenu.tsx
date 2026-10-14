import { CaretDown, MagnifyingGlass } from '@phosphor-icons/react';
import * as Popover from '@radix-ui/react-popover';
import { useMemo, useRef, useState, type KeyboardEvent } from 'react';

import { categoryColors } from '../format/category';
import { CategoryPill } from './Badge';
import { cx } from './cx';

export interface CategoryOption {
  id: string;
  name: string;
}

/** Searchable category picker: type to filter, arrows to move, Enter to choose. */
export function CategoryMenu({
  categories,
  value,
  valueName,
  onChange,
  disabled,
  searchLabel,
  onCreate,
  createLabel,
}: {
  categories: CategoryOption[];
  value: string | null;
  valueName: string | null;
  onChange: (categoryId: string) => void;
  disabled?: boolean;
  searchLabel: string;
  /** When given, typing a name that does not exist offers to create it. */
  onCreate?: (name: string) => void;
  createLabel?: (name: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? categories.filter((c) => c.name.toLowerCase().includes(q)) : categories;
  }, [categories, query]);

  const typed = query.trim();
  const canCreate =
    !!onCreate &&
    typed.length > 0 &&
    !categories.some((c) => c.name.toLowerCase() === typed.toLowerCase());
  const create = () => {
    if (!onCreate || !typed) return;
    onCreate(typed);
    setOpen(false);
    setQuery('');
  };

  const choose = (id: string) => {
    onChange(id);
    setOpen(false);
    setQuery('');
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, filtered.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter' && filtered[active]) {
      event.preventDefault();
      choose(filtered[active].id);
    } else if (event.key === 'Enter' && canCreate) {
      event.preventDefault();
      create();
    }
  };

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        setActive(0);
        setQuery('');
      }}
    >
      <Popover.Trigger
        data-testid="category-trigger"
        disabled={disabled}
        className="group inline-flex items-center gap-1.5 rounded-chip disabled:opacity-60"
      >
        <CategoryPill categoryId={value} name={valueName} />
        <CaretDown size={12} aria-hidden className="text-ink-3 group-hover:text-ink" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-64 rounded-control border border-hairline bg-surface p-1.5 shadow-popover"
        >
          <div className="mb-1 flex items-center gap-2 rounded-[6px] bg-surface-sunken px-2.5">
            <MagnifyingGlass size={14} aria-hidden className="text-ink-3" />
            <input
              autoFocus
              aria-label={searchLabel}
              placeholder={searchLabel}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              className="h-8 w-full bg-transparent text-small text-ink outline-none placeholder:text-ink-3"
            />
          </div>
          <ul
            ref={listRef}
            role="listbox"
            aria-label={searchLabel}
            className="max-h-64 overflow-y-auto"
          >
            {filtered.map((c, i) => {
              const { index } = categoryColors(c.id);
              return (
                <li
                  key={c.id}
                  role="option"
                  aria-selected={c.id === value}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(c.id)}
                  className={cx(
                    'flex cursor-pointer items-center gap-2 rounded-[6px] px-2.5 py-1.5 text-small',
                    i === active ? 'bg-surface-selected text-ink' : 'text-ink-2',
                  )}
                >
                  <span
                    aria-hidden
                    className="size-2 rounded-full"
                    style={{ backgroundColor: `var(--color-cat-${index}-mark)` }}
                  />
                  {c.name}
                </li>
              );
            })}
          </ul>
          {canCreate ? (
            <button
              type="button"
              onClick={create}
              className="mt-1 w-full rounded-[6px] border-t border-hairline px-2.5 py-2 text-left text-small text-agent hover:bg-surface-hover"
            >
              {createLabel ? createLabel(typed) : `Create "${typed}"`}
            </button>
          ) : null}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

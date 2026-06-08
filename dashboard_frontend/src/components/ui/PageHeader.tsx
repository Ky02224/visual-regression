import React from 'react';

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: React.ReactNode }) {
  return (
    <header className="mb-8 border-b border-[var(--outline)] pb-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--on-surface)]">{title}</h1>
          {description && <p className="text-sm text-[var(--on-surface-variant)] mt-1">{description}</p>}
        </div>
        {action}
      </div>
    </header>
  );
}

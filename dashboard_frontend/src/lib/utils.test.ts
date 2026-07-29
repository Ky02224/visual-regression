import { describe, expect, it } from 'vitest';
import { cn, statusBadgeClass, parseAspectRatio, formatChangeType, getRunChangeLabel, changeTypeBadgeClass } from './utils';

describe('cn', () => {
  it('merges class names and resolves tailwind conflicts', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4');
  });

  it('drops falsy values', () => {
    expect(cn('a', false, undefined, null, 'b')).toBe('a b');
  });
});

describe('statusBadgeClass', () => {
  it('groups passed/approved/no_changes into the same green style', () => {
    const passed = statusBadgeClass('passed');
    expect(statusBadgeClass('approved')).toBe(passed);
    expect(statusBadgeClass('no_changes')).toBe(passed);
    expect(passed).toContain('green');
  });

  it('groups failed/rejected into red', () => {
    expect(statusBadgeClass('failed')).toContain('red');
    expect(statusBadgeClass('rejected')).toContain('red');
  });

  it('falls back to a neutral style for unknown status', () => {
    expect(statusBadgeClass('unknown')).toContain('stone');
  });
});

describe('parseAspectRatio', () => {
  it('parses a W/H ratio string', () => {
    expect(parseAspectRatio('16/9')).toBeCloseTo(16 / 9);
  });

  it('falls back to 16/10 for a malformed ratio', () => {
    expect(parseAspectRatio('not-a-ratio')).toBeCloseTo(16 / 10);
  });

  it('falls back to 16/10 when either side is zero', () => {
    expect(parseAspectRatio('0/9')).toBeCloseTo(16 / 10);
  });
});

describe('formatChangeType', () => {
  it('returns null for empty input', () => {
    expect(formatChangeType(null)).toBeNull();
    expect(formatChangeType(undefined)).toBeNull();
    expect(formatChangeType('')).toBeNull();
  });

  it('treats insignificant/meaningful-change as no label', () => {
    expect(formatChangeType('insignificant-change')).toBeNull();
    expect(formatChangeType('meaningful-change')).toBeNull();
  });

  it('maps known raw AI labels to their consolidated user-facing category', () => {
    expect(formatChangeType('color-regression')).toBe('Color mismatch');
    expect(formatChangeType('broken-image')).toBe('Missing element');
    expect(formatChangeType('unreadable-text')).toBe('Font substitution');
    expect(formatChangeType('overlay-obstruction')).toBe('Dynamic content');
    expect(formatChangeType('misaligned-fields')).toBe('Layout shift');
  });

  it('title-cases an unrecognized label as a fallback', () => {
    expect(formatChangeType('some_new_defect')).toBe('Some New Defect');
  });

  it('is case-insensitive and normalizes underscores', () => {
    expect(formatChangeType('COLOR_REGRESSION')).toBe('Color mismatch');
  });
});

describe('getRunChangeLabel', () => {
  it('reads ai_label first, falling back to aiLabel', () => {
    expect(getRunChangeLabel({ ai_label: 'color-regression' })).toBe('Color mismatch');
    expect(getRunChangeLabel({ aiLabel: 'broken-image' })).toBe('Missing element');
  });

  it('returns null when neither field is a string', () => {
    expect(getRunChangeLabel({})).toBeNull();
    expect(getRunChangeLabel({ ai_label: 42 })).toBeNull();
  });
});

describe('changeTypeBadgeClass', () => {
  it('gives distinct styles to distinct consolidated categories', () => {
    const layoutClass = changeTypeBadgeClass('layout-shift');
    const colorClass = changeTypeBadgeClass('color-mismatch');
    expect(layoutClass).not.toBe(colorClass);
  });

  it('maps a raw (unconsolidated) label to the same style as its consolidated category', () => {
    expect(changeTypeBadgeClass('color-regression')).toBe(changeTypeBadgeClass('color-mismatch'));
    expect(changeTypeBadgeClass('misaligned-fields')).toBe(changeTypeBadgeClass('layout-shift'));
  });

  it('falls back to the default indigo style for unknown categories', () => {
    expect(changeTypeBadgeClass('totally-unknown')).toContain('indigo');
  });
});

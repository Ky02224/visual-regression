import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ComparisonToolbar } from './ComparisonToolbar';

/**
 * Comment pins are rendered only by the overlay view. In Side by side and
 * Slider they simply do not exist, with nothing on screen saying so — a
 * reviewer working in those two could not tell a run had been commented on.
 * The toolbar is the one control strip present in all three.
 */
function renderToolbar(props: Partial<React.ComponentProps<typeof ComparisonToolbar>> = {}) {
  const onJumpToComments = vi.fn();
  const onViewModeChange = vi.fn();
  render(
    <ComparisonToolbar
      viewMode="side-by-side"
      onViewModeChange={onViewModeChange}
      showDiff={false}
      onShowDiffChange={vi.fn()}
      zoom="fit"
      onZoomChange={vi.fn()}
      commentCount={0}
      onJumpToComments={onJumpToComments}
      {...props}
    />,
  );
  return { onJumpToComments, onViewModeChange };
}

describe('ComparisonToolbar comment control', () => {
  it('shows the comment count', () => {
    renderToolbar({ commentCount: 2 });

    expect(screen.getByRole('button', { name: /2 comments/i })).toBeInTheDocument();
  });

  it('is absent when there are no comments', () => {
    renderToolbar({ commentCount: 0 });

    expect(screen.queryByRole('button', { name: /comment/i })).not.toBeInTheDocument();
  });

  it('is absent when the prop is not passed at all', () => {
    render(
      <ComparisonToolbar
        viewMode="overlay"
        onViewModeChange={vi.fn()}
        showDiff={false}
        onShowDiffChange={vi.fn()}
        zoom="fit"
        onZoomChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole('button', { name: /comment/i })).not.toBeInTheDocument();
  });

  it('says where the pins are when they are not on screen', () => {
    renderToolbar({ commentCount: 1, viewMode: 'slider' });

    expect(screen.getByText(/pinned in overlay/i)).toBeInTheDocument();
  });

  it('drops that note in the view that does render pins', () => {
    renderToolbar({ commentCount: 1, viewMode: 'overlay' });

    expect(screen.queryByText(/pinned in overlay/i)).not.toBeInTheDocument();
  });

  it('asks the page to jump to the first comment when clicked', async () => {
    const { onJumpToComments } = renderToolbar({ commentCount: 3 });

    await userEvent.click(screen.getByRole('button', { name: /3 comments/i }));

    expect(onJumpToComments).toHaveBeenCalledTimes(1);
  });

  it('uses the singular for a single comment', () => {
    renderToolbar({ commentCount: 1 });

    expect(screen.getByRole('button', { name: /1 comment(?!s)/i })).toBeInTheDocument();
  });
});
